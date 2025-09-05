"""
Secure token management and rotation service for SIS integrations.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
import secrets
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.sis_integration import SISIntegration, SISOAuthToken
from app.integrations.sis.oauth_service import SISOAuthService, AuthenticationFailedError
from app.core.sis_config import sis_config_manager


logger = logging.getLogger(__name__)


class TokenRotationError(Exception):
    """Exception raised during token rotation."""
    pass


class SISTokenManager:
    """Service for managing SIS OAuth tokens and automatic rotation."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._rotation_tasks: Dict[int, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        
    async def start_token_monitoring(self) -> None:
        """Start background token monitoring and rotation."""
        logger.info("Starting SIS token monitoring service")
        
        # Create background task for monitoring
        asyncio.create_task(self._monitor_tokens())
        
    async def stop_token_monitoring(self) -> None:
        """Stop token monitoring and cancel all rotation tasks."""
        logger.info("Stopping SIS token monitoring service")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel all rotation tasks
        for integration_id, task in self._rotation_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        self._rotation_tasks.clear()
        
    async def rotate_token_for_integration(self, integration_id: int) -> bool:
        """
        Manually trigger token rotation for a specific integration.
        
        Args:
            integration_id: ID of the SIS integration
            
        Returns:
            True if rotation successful
        """
        try:
            # Get integration with token
            result = await self.db.execute(
                select(SISIntegration)
                .options(selectinload(SISIntegration.oauth_tokens))
                .where(SISIntegration.id == integration_id)
            )
            integration = result.scalar_one_or_none()
            
            if not integration:
                logger.error(f"Integration {integration_id} not found")
                return False
                
            if not integration.enabled:
                logger.warning(f"Integration {integration.provider_id} is disabled, skipping rotation")
                return False
                
            # Get provider configuration
            provider_config = sis_config_manager.get_provider_config(integration.provider_id)
            if not provider_config or not provider_config.oauth_config:
                logger.error(f"OAuth configuration not found for integration {integration.provider_id}")
                return False
                
            # Perform token rotation
            async with SISOAuthService(self.db) as oauth_service:
                return await self._rotate_integration_token(
                    integration,
                    provider_config.oauth_config,
                    oauth_service
                )
                
        except Exception as e:
            logger.error(f"Error rotating token for integration {integration_id}: {e}")
            return False
            
    async def get_token_status(self, integration_id: int) -> Optional[Dict[str, Any]]:
        """
        Get token status for a specific integration.
        
        Args:
            integration_id: ID of the SIS integration
            
        Returns:
            Token status information
        """
        try:
            result = await self.db.execute(
                select(SISOAuthToken)
                .where(SISOAuthToken.integration_id == integration_id)
                .order_by(SISOAuthToken.created_at.desc())
            )
            token = result.scalar_one_or_none()
            
            if not token:
                return None
                
            status = {
                'token_id': token.id,
                'token_type': token.token_type,
                'created_at': token.created_at,
                'updated_at': token.updated_at,
                'expires_at': token.expires_at,
                'is_expired': token.is_expired,
                'expires_soon': token.expires_soon,
                'has_refresh_token': token.refresh_token is not None,
                'scope': token.scope
            }
            
            if token.expires_at:
                remaining_seconds = (token.expires_at - datetime.utcnow()).total_seconds()
                status['seconds_until_expiry'] = max(0, int(remaining_seconds))
                
            return status
            
        except Exception as e:
            logger.error(f"Error getting token status for integration {integration_id}: {e}")
            return None
            
    async def revoke_all_tokens_for_integration(self, integration_id: int) -> bool:
        """
        Revoke all tokens for a specific integration.
        
        Args:
            integration_id: ID of the SIS integration
            
        Returns:
            True if successful
        """
        try:
            # Get integration with tokens
            result = await self.db.execute(
                select(SISIntegration)
                .options(selectinload(SISIntegration.oauth_tokens))
                .where(SISIntegration.id == integration_id)
            )
            integration = result.scalar_one_or_none()
            
            if not integration:
                logger.error(f"Integration {integration_id} not found")
                return False
                
            # Get provider configuration
            provider_config = sis_config_manager.get_provider_config(integration.provider_id)
            if not provider_config or not provider_config.oauth_config:
                logger.error(f"OAuth configuration not found for integration {integration.provider_id}")
                return False
                
            # Revoke all tokens
            async with SISOAuthService(self.db) as oauth_service:
                success = True
                for token in integration.oauth_tokens:
                    try:
                        await oauth_service.revoke_token(
                            integration,
                            provider_config.oauth_config,
                            token
                        )
                    except Exception as e:
                        logger.error(f"Error revoking token {token.id}: {e}")
                        success = False
                        
                return success
                
        except Exception as e:
            logger.error(f"Error revoking tokens for integration {integration_id}: {e}")
            return False
            
    async def cleanup_expired_tokens(self, days_old: int = 7) -> int:
        """
        Clean up expired tokens older than specified days.
        
        Args:
            days_old: Number of days old for token cleanup
            
        Returns:
            Number of tokens cleaned up
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            # Find expired tokens older than cutoff
            result = await self.db.execute(
                select(SISOAuthToken)
                .where(
                    and_(
                        SISOAuthToken.expires_at < datetime.utcnow(),
                        SISOAuthToken.created_at < cutoff_date
                    )
                )
            )
            expired_tokens = result.scalars().all()
            
            # Delete expired tokens
            count = 0
            for token in expired_tokens:
                await self.db.delete(token)
                count += 1
                
            await self.db.commit()
            
            logger.info(f"Cleaned up {count} expired tokens older than {days_old} days")
            return count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}")
            await self.db.rollback()
            return 0
            
    async def _monitor_tokens(self) -> None:
        """Background task to monitor tokens and trigger rotation."""
        logger.info("Token monitoring task started")
        
        while not self._shutdown_event.is_set():
            try:
                await self._check_and_rotate_tokens()
                
                # Wait for next check (every 5 minutes)
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=300  # 5 minutes
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    pass  # Continue monitoring
                    
            except Exception as e:
                logger.error(f"Error in token monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
                
        logger.info("Token monitoring task stopped")
        
    async def _check_and_rotate_tokens(self) -> None:
        """Check for tokens that need rotation and schedule rotation tasks."""
        try:
            # Find tokens that expire soon (within 10 minutes)
            soon_expiry_time = datetime.utcnow() + timedelta(minutes=10)
            
            result = await self.db.execute(
                select(SISOAuthToken)
                .join(SISIntegration)
                .where(
                    and_(
                        SISOAuthToken.expires_at <= soon_expiry_time,
                        SISOAuthToken.expires_at > datetime.utcnow(),
                        SISOAuthToken.refresh_token.isnot(None),
                        SISIntegration.enabled == True
                    )
                )
                .options(selectinload(SISOAuthToken.integration))
            )
            tokens_to_rotate = result.scalars().all()
            
            logger.debug(f"Found {len(tokens_to_rotate)} tokens that need rotation")
            
            # Schedule rotation tasks
            for token in tokens_to_rotate:
                integration = token.integration
                if integration.id not in self._rotation_tasks or self._rotation_tasks[integration.id].done():
                    # Create new rotation task
                    task = asyncio.create_task(
                        self._schedule_token_rotation(integration.id)
                    )
                    self._rotation_tasks[integration.id] = task
                    
        except Exception as e:
            logger.error(f"Error checking tokens for rotation: {e}")
            
    async def _schedule_token_rotation(self, integration_id: int) -> None:
        """Schedule and perform token rotation for an integration."""
        try:
            logger.info(f"Scheduling token rotation for integration {integration_id}")
            
            # Add some jitter to avoid thundering herd
            delay = secrets.randbelow(30)  # 0-29 seconds
            await asyncio.sleep(delay)
            
            success = await self.rotate_token_for_integration(integration_id)
            
            if success:
                logger.info(f"Successfully rotated token for integration {integration_id}")
            else:
                logger.error(f"Failed to rotate token for integration {integration_id}")
                
        except Exception as e:
            logger.error(f"Error in scheduled token rotation for integration {integration_id}: {e}")
        finally:
            # Clean up completed task
            self._rotation_tasks.pop(integration_id, None)
            
    async def _rotate_integration_token(
        self,
        integration: SISIntegration,
        oauth_config,
        oauth_service: SISOAuthService
    ) -> bool:
        """Perform token rotation for an integration."""
        try:
            # Get current token
            if not integration.oauth_tokens:
                logger.warning(f"No tokens found for integration {integration.provider_id}")
                return False
                
            current_token = integration.oauth_tokens[0]  # Most recent token
            
            if not current_token.refresh_token:
                logger.warning(f"No refresh token available for integration {integration.provider_id}")
                return False
                
            # Attempt to refresh the token
            try:
                await oauth_service.refresh_access_token(
                    integration,
                    oauth_config,
                    current_token
                )
                
                logger.info(f"Successfully refreshed token for integration {integration.provider_id}")
                return True
                
            except AuthenticationFailedError as e:
                logger.error(f"Token refresh failed for integration {integration.provider_id}: {e}")
                
                # Mark integration as having auth issues
                integration.update_auth_failure()
                await self.db.commit()
                
                return False
                
        except Exception as e:
            logger.error(f"Error rotating token for integration {integration.provider_id}: {e}")
            return False