"""
Main SIS service layer to coordinate all integrations and provide unified interface.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Type, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import selectinload

from app.models.sis_integration import (
    SISIntegration, SISIntegrationStatus, SISOAuthToken, 
    SISSyncOperation, SISStudentMapping
)
from app.models.user import User
from app.core.sis_config import (
    SISProviderType, SISProviderConfig, OAuthConfig, SyncScheduleConfig,
    sis_config_manager
)
from app.integrations.sis.oauth_service import SISOAuthService
from app.integrations.sis.token_manager import SISTokenManager
from app.integrations.sis.roster_sync import RosterSyncService, ConflictResolutionStrategy
from app.integrations.sis.enrollment_handler import StudentEnrollmentHandler
from app.integrations.sis.providers.powerschool import PowerSchoolProvider
from app.integrations.sis.providers.infinite_campus import InfiniteCampusProvider
from app.integrations.sis.providers.skyward import SkywardProvider


logger = logging.getLogger(__name__)


class SISServiceError(Exception):
    """Base exception for SIS service errors."""
    pass


class IntegrationNotFoundError(SISServiceError):
    """Exception raised when SIS integration is not found."""
    pass


class IntegrationDisabledError(SISServiceError):
    """Exception raised when trying to use a disabled integration."""
    pass


class SISService:
    """
    Main service for coordinating SIS integrations.
    
    This service provides a unified interface for:
    - Managing SIS integrations
    - Orchestrating sync operations
    - Handling authentication
    - Providing status and monitoring
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.token_manager = SISTokenManager(db)
        self.roster_sync = RosterSyncService(db)
        self.enrollment_handler = StudentEnrollmentHandler(db)
        
        self._provider_classes = {
            SISProviderType.POWERSCHOOL: PowerSchoolProvider,
            SISProviderType.INFINITE_CAMPUS: InfiniteCampusProvider,
            SISProviderType.SKYWARD: SkywardProvider,
        }
        
        # Background task management
        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        
    async def start_service(self) -> None:
        """Start the SIS service and background tasks."""
        logger.info("Starting SIS service")
        
        # Start token monitoring
        await self.token_manager.start_token_monitoring()
        
        # Start scheduled sync tasks
        self._background_tasks['sync_scheduler'] = asyncio.create_task(
            self._scheduled_sync_task()
        )
        
        logger.info("SIS service started successfully")
        
    async def stop_service(self) -> None:
        """Stop the SIS service and all background tasks."""
        logger.info("Stopping SIS service")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Stop token monitoring
        await self.token_manager.stop_token_monitoring()
        
        # Cancel background tasks
        for task_name, task in self._background_tasks.items():
            if not task.done():
                logger.info(f"Cancelling background task: {task_name}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        self._background_tasks.clear()
        logger.info("SIS service stopped")
        
    # Integration Management
    
    async def create_integration(
        self,
        provider_type: SISProviderType,
        provider_id: str,
        name: str,
        config: SISProviderConfig
    ) -> SISIntegration:
        """
        Create a new SIS integration.
        
        Args:
            provider_type: Type of SIS provider
            provider_id: Unique identifier for the provider
            name: Human-readable name
            config: Provider configuration
            
        Returns:
            Created integration instance
        """
        # Validate configuration
        errors = sis_config_manager.validate_provider_config(config)
        if errors:
            raise SISServiceError(f"Configuration validation failed: {'; '.join(errors)}")
            
        # Check for existing integration
        result = await self.db.execute(
            select(SISIntegration).where(SISIntegration.provider_id == provider_id)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise SISServiceError(f"Integration with provider_id '{provider_id}' already exists")
            
        # Create integration
        integration = SISIntegration(
            provider_id=provider_id,
            provider_type=provider_type,
            name=name,
            base_url=config.base_url,
            api_version=config.api_version,
            timeout=config.timeout,
            max_retries=config.max_retries,
            rate_limit=config.rate_limit,
            status=SISIntegrationStatus.PENDING,
            enabled=config.enabled,
            config_json=config.custom_fields
        )
        
        self.db.add(integration)
        await self.db.commit()
        await self.db.refresh(integration)
        
        # Register configuration
        sis_config_manager.register_provider(provider_id, config)
        
        logger.info(f"Created SIS integration: {provider_id} ({name})")
        return integration
        
    async def get_integration(self, integration_id: int) -> Optional[SISIntegration]:
        """Get integration by ID."""
        result = await self.db.execute(
            select(SISIntegration).where(SISIntegration.id == integration_id)
        )
        return result.scalar_one_or_none()
        
    async def get_integration_by_provider_id(self, provider_id: str) -> Optional[SISIntegration]:
        """Get integration by provider ID."""
        result = await self.db.execute(
            select(SISIntegration).where(SISIntegration.provider_id == provider_id)
        )
        return result.scalar_one_or_none()
        
    async def list_integrations(
        self,
        enabled_only: bool = False
    ) -> List[SISIntegration]:
        """List all integrations."""
        query = select(SISIntegration)
        
        if enabled_only:
            query = query.where(SISIntegration.enabled == True)
            
        result = await self.db.execute(query)
        return list(result.scalars().all())
        
    async def update_integration(
        self,
        integration_id: int,
        updates: Dict[str, Any]
    ) -> Optional[SISIntegration]:
        """Update integration settings."""
        integration = await self.get_integration(integration_id)
        if not integration:
            return None
            
        # Update fields
        for field, value in updates.items():
            if hasattr(integration, field):
                setattr(integration, field, value)
                
        await self.db.commit()
        await self.db.refresh(integration)
        
        logger.info(f"Updated integration {integration.provider_id}")
        return integration
        
    async def delete_integration(self, integration_id: int) -> bool:
        """Delete an integration and all related data."""
        integration = await self.get_integration(integration_id)
        if not integration:
            return False
            
        # Revoke all tokens first
        await self.token_manager.revoke_all_tokens_for_integration(integration_id)
        
        # Delete integration (cascade will handle related records)
        await self.db.delete(integration)
        await self.db.commit()
        
        # Remove from configuration manager
        sis_config_manager.remove_provider(integration.provider_id)
        
        logger.info(f"Deleted integration {integration.provider_id}")
        return True
        
    # Authentication Management
    
    async def initiate_oauth_flow(
        self,
        integration_id: int,
        state: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Initiate OAuth flow for an integration.
        
        Args:
            integration_id: ID of the integration
            state: Optional state parameter for security
            
        Returns:
            Dictionary with authorization_url and state
        """
        integration = await self.get_integration(integration_id)
        if not integration:
            raise IntegrationNotFoundError(f"Integration {integration_id} not found")
            
        config = sis_config_manager.get_provider_config(integration.provider_id)
        if not config or not config.oauth_config:
            raise SISServiceError("OAuth configuration not found")
            
        async with SISOAuthService(self.db) as oauth_service:
            auth_url, state = await oauth_service.generate_authorization_url(
                integration,
                config.oauth_config,
                state
            )
            
        return {
            'authorization_url': auth_url,
            'state': state
        }
        
    async def complete_oauth_flow(
        self,
        integration_id: int,
        authorization_code: str,
        state: str
    ) -> bool:
        """
        Complete OAuth flow with authorization code.
        
        Args:
            integration_id: ID of the integration
            authorization_code: Authorization code from callback
            state: State parameter for verification
            
        Returns:
            True if successful
        """
        integration = await self.get_integration(integration_id)
        if not integration:
            raise IntegrationNotFoundError(f"Integration {integration_id} not found")
            
        config = sis_config_manager.get_provider_config(integration.provider_id)
        if not config or not config.oauth_config:
            raise SISServiceError("OAuth configuration not found")
            
        try:
            async with SISOAuthService(self.db) as oauth_service:
                await oauth_service.exchange_code_for_token(
                    integration,
                    config.oauth_config,
                    authorization_code,
                    state
                )
                
            # Update integration status to active
            integration.status = SISIntegrationStatus.ACTIVE
            await self.db.commit()
            
            logger.info(f"OAuth flow completed for integration {integration.provider_id}")
            return True
            
        except Exception as e:
            logger.error(f"OAuth flow failed for integration {integration.provider_id}: {e}")
            integration.status = SISIntegrationStatus.ERROR
            await self.db.commit()
            return False
            
    async def refresh_integration_token(self, integration_id: int) -> bool:
        """Refresh OAuth token for an integration."""
        return await self.token_manager.rotate_token_for_integration(integration_id)
        
    # Sync Operations
    
    async def sync_all_rosters(
        self,
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS
    ) -> Dict[str, Any]:
        """Sync rosters for all active integrations."""
        return await self.roster_sync.sync_all_integrations(conflict_strategy)
        
    async def sync_integration_roster(
        self,
        integration_id: int,
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS
    ) -> Dict[str, Any]:
        """Sync roster for a specific integration."""
        return await self.roster_sync.sync_integration_roster(
            integration_id,
            conflict_strategy
        )
        
    async def sync_enrollments(self, integration_id: int) -> Dict[str, Any]:
        """Sync enrollments for an integration."""
        return await self.enrollment_handler.process_enrollment_updates(integration_id)
        
    async def sync_class_enrollments(
        self,
        integration_id: int,
        class_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Sync class enrollments."""
        return await self.enrollment_handler.sync_class_enrollments(
            integration_id,
            class_id
        )
        
    # Health and Monitoring
    
    async def check_integration_health(self, integration_id: int) -> Dict[str, Any]:
        """Check health of a specific integration."""
        integration = await self.get_integration(integration_id)
        if not integration:
            return {'healthy': False, 'error': 'Integration not found'}
            
        if not integration.enabled:
            return {'healthy': False, 'error': 'Integration disabled'}
            
        try:
            # Get provider and check health
            provider = await self._get_provider_instance(integration)
            
            async with provider:
                healthy = await provider.health_check()
                
            # Get token status
            token_status = await self.token_manager.get_token_status(integration_id)
            
            # Get recent sync operations
            result = await self.db.execute(
                select(SISSyncOperation)
                .where(SISSyncOperation.integration_id == integration_id)
                .order_by(desc(SISSyncOperation.created_at))
                .limit(5)
            )
            recent_syncs = result.scalars().all()
            
            return {
                'healthy': healthy,
                'integration_status': integration.status,
                'is_enabled': integration.enabled,
                'last_auth_success': integration.last_auth_success,
                'last_auth_failure': integration.last_auth_failure,
                'auth_failure_count': integration.auth_failure_count,
                'last_sync_success': integration.last_sync_success,
                'last_sync_failure': integration.last_sync_failure,
                'sync_failure_count': integration.sync_failure_count,
                'token_status': token_status,
                'recent_syncs': [
                    {
                        'id': sync.id,
                        'operation_type': sync.operation_type,
                        'status': sync.status,
                        'started_at': sync.started_at,
                        'completed_at': sync.completed_at,
                        'processed_records': sync.processed_records,
                        'successful_records': sync.successful_records,
                        'failed_records': sync.failed_records
                    }
                    for sync in recent_syncs
                ],
                'statistics': {
                    'total_students_synced': integration.total_students_synced,
                    'total_enrollments_synced': integration.total_enrollments_synced,
                    'total_api_calls': integration.total_api_calls
                }
            }
            
        except Exception as e:
            logger.error(f"Error checking health for integration {integration.provider_id}: {e}")
            return {'healthy': False, 'error': str(e)}
            
    async def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        integrations = await self.list_integrations()
        
        status = {
            'total_integrations': len(integrations),
            'active_integrations': 0,
            'error_integrations': 0,
            'disabled_integrations': 0,
            'pending_integrations': 0,
            'integrations': []
        }
        
        for integration in integrations:
            health = await self.check_integration_health(integration.id)
            
            integration_status = {
                'id': integration.id,
                'provider_id': integration.provider_id,
                'name': integration.name,
                'provider_type': integration.provider_type,
                'status': integration.status,
                'enabled': integration.enabled,
                'healthy': health.get('healthy', False),
                'last_sync': integration.last_sync_success
            }
            
            status['integrations'].append(integration_status)
            
            if integration.status == SISIntegrationStatus.ACTIVE:
                status['active_integrations'] += 1
            elif integration.status == SISIntegrationStatus.ERROR:
                status['error_integrations'] += 1
            elif integration.status == SISIntegrationStatus.DISABLED:
                status['disabled_integrations'] += 1
            elif integration.status == SISIntegrationStatus.PENDING:
                status['pending_integrations'] += 1
                
        return status
        
    # Conflict Resolution
    
    async def get_pending_conflicts(
        self,
        integration_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get pending conflicts that require manual resolution."""
        return await self.roster_sync.get_pending_conflicts(integration_id)
        
    async def resolve_conflicts(
        self,
        mapping_id: int,
        resolutions: Dict[str, Any]
    ) -> bool:
        """Resolve conflicts for a student mapping."""
        return await self.roster_sync.resolve_student_conflicts(mapping_id, resolutions)
        
    # Utility Methods
    
    async def _get_provider_instance(self, integration: SISIntegration):
        """Get provider instance for an integration."""
        provider_config = sis_config_manager.get_provider_config(integration.provider_id)
        if not provider_config:
            raise SISServiceError(f"Configuration not found for provider {integration.provider_id}")
            
        provider_class = self._provider_classes.get(integration.provider_type)
        if not provider_class:
            raise SISServiceError(f"Provider class not found for type {integration.provider_type}")
            
        oauth_service = SISOAuthService(self.db)
        return provider_class(provider_config, integration, oauth_service)
        
    async def _scheduled_sync_task(self) -> None:
        """Background task for scheduled synchronization."""
        logger.info("Started scheduled sync task")
        
        while not self._shutdown_event.is_set():
            try:
                # Check for scheduled syncs every 5 minutes
                await self._check_scheduled_syncs()
                
                # Wait for next check
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=300  # 5 minutes
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    pass  # Continue with next check
                    
            except Exception as e:
                logger.error(f"Error in scheduled sync task: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
                
        logger.info("Scheduled sync task stopped")
        
    async def _check_scheduled_syncs(self) -> None:
        """Check for and execute scheduled synchronization operations."""
        # Get sync configuration
        sync_config = sis_config_manager.get_sync_config()
        if not sync_config:
            return
            
        current_time = datetime.utcnow()
        
        # Check for daily syncs
        if sync_config.daily:
            daily_time = datetime.strptime(sync_config.daily_time, "%H:%M").time()
            daily_datetime = datetime.combine(current_time.date(), daily_time)
            
            # Check if we should run daily sync (within 5-minute window)
            if abs((current_time - daily_datetime).total_seconds()) < 300:
                logger.info("Executing scheduled daily sync")
                try:
                    await self.sync_all_rosters()
                except Exception as e:
                    logger.error(f"Daily sync failed: {e}")
                    
        # Hourly syncs would be handled similarly
        # Real-time syncs would be handled by webhooks or frequent polling