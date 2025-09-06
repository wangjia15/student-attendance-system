"""
OAuth 2.0 authentication service for SIS integrations.
"""

import asyncio
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    class MockAiohttp:
        class ClientSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def get(self, *args, **kwargs): raise NotImplementedError("aiohttp not available")
            async def post(self, *args, **kwargs): raise NotImplementedError("aiohttp not available")
    aiohttp = MockAiohttp()
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse
import secrets
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.sis_integration import SISIntegration, SISOAuthToken
from app.core.sis_config import OAuthConfig, SISProviderConfig
from app.core.security import encrypt_data, decrypt_data


logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Base exception for OAuth errors."""
    pass


class TokenExpiredError(OAuthError):
    """Exception raised when OAuth token is expired."""
    pass


class AuthenticationFailedError(OAuthError):
    """Exception raised when OAuth authentication fails."""
    pass


class SISOAuthService:
    """Service for handling SIS OAuth 2.0 authentication."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._http_session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        self._http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'Student-Attendance-System/1.0'}
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
            
    async def generate_authorization_url(
        self,
        integration: SISIntegration,
        oauth_config: OAuthConfig,
        state: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Generate OAuth authorization URL.
        
        Args:
            integration: SIS integration instance
            oauth_config: OAuth configuration
            state: Optional state parameter for security
            
        Returns:
            Tuple of (authorization_url, state)
        """
        if not state:
            state = secrets.token_urlsafe(32)
            
        params = {
            'response_type': 'code',
            'client_id': oauth_config.client_id,
            'redirect_uri': oauth_config.redirect_uri,
            'state': state,
        }
        
        if oauth_config.scope:
            params['scope'] = ' '.join(oauth_config.scope)
            
        auth_url = f"{oauth_config.authorization_url}?{urlencode(params)}"
        
        logger.info(f"Generated authorization URL for integration {integration.provider_id}")
        return auth_url, state
        
    async def exchange_code_for_token(
        self,
        integration: SISIntegration,
        oauth_config: OAuthConfig,
        authorization_code: str,
        state: str
    ) -> SISOAuthToken:
        """
        Exchange authorization code for access token.
        
        Args:
            integration: SIS integration instance
            oauth_config: OAuth configuration
            authorization_code: Authorization code from callback
            state: State parameter for verification
            
        Returns:
            OAuth token instance
        """
        if not self._http_session:
            raise RuntimeError("OAuth service must be used as async context manager")
            
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': oauth_config.client_id,
            'client_secret': oauth_config.client_secret,
            'code': authorization_code,
            'redirect_uri': oauth_config.redirect_uri,
        }
        
        try:
            async with self._http_session.post(
                oauth_config.token_url,
                data=token_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"Token exchange failed for {integration.provider_id}: "
                        f"Status {response.status}, Error: {error_text}"
                    )
                    raise AuthenticationFailedError(f"Token exchange failed: {error_text}")
                    
                token_response = await response.json()
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error during token exchange for {integration.provider_id}: {e}")
            raise AuthenticationFailedError(f"HTTP error: {e}")
            
        # Create or update token
        token = await self._store_token(integration, token_response)
        
        # Update integration auth success
        integration.update_auth_success()
        await self.db.commit()
        
        logger.info(f"Successfully exchanged code for token for integration {integration.provider_id}")
        return token
        
    async def refresh_access_token(
        self,
        integration: SISIntegration,
        oauth_config: OAuthConfig,
        token: SISOAuthToken
    ) -> SISOAuthToken:
        """
        Refresh access token using refresh token.
        
        Args:
            integration: SIS integration instance
            oauth_config: OAuth configuration
            token: Current OAuth token
            
        Returns:
            Updated OAuth token instance
        """
        if not token.refresh_token:
            raise AuthenticationFailedError("No refresh token available")
            
        if not self._http_session:
            raise RuntimeError("OAuth service must be used as async context manager")
            
        refresh_data = {
            'grant_type': 'refresh_token',
            'client_id': oauth_config.client_id,
            'client_secret': oauth_config.client_secret,
            'refresh_token': token.refresh_token,
        }
        
        try:
            async with self._http_session.post(
                oauth_config.token_url,
                data=refresh_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"Token refresh failed for {integration.provider_id}: "
                        f"Status {response.status}, Error: {error_text}"
                    )
                    # Mark authentication failure
                    integration.update_auth_failure()
                    await self.db.commit()
                    raise AuthenticationFailedError(f"Token refresh failed: {error_text}")
                    
                token_response = await response.json()
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error during token refresh for {integration.provider_id}: {e}")
            integration.update_auth_failure()
            await self.db.commit()
            raise AuthenticationFailedError(f"HTTP error: {e}")
            
        # Update token with new values
        await self._update_token(token, token_response)
        
        # Update integration auth success
        integration.update_auth_success()
        await self.db.commit()
        
        logger.info(f"Successfully refreshed token for integration {integration.provider_id}")
        return token
        
    async def get_valid_token(
        self,
        integration: SISIntegration,
        oauth_config: OAuthConfig
    ) -> Optional[SISOAuthToken]:
        """
        Get a valid access token, refreshing if necessary.
        
        Args:
            integration: SIS integration instance
            oauth_config: OAuth configuration
            
        Returns:
            Valid OAuth token or None if authentication required
        """
        # Get current token
        result = await self.db.execute(
            select(SISOAuthToken)
            .where(SISOAuthToken.integration_id == integration.id)
            .order_by(SISOAuthToken.created_at.desc())
        )
        token = result.scalar_one_or_none()
        
        if not token:
            logger.warning(f"No token found for integration {integration.provider_id}")
            return None
            
        # Check if token is still valid
        if not token.is_expired:
            return token
            
        # Try to refresh if refresh token available
        if token.refresh_token:
            try:
                return await self.refresh_access_token(integration, oauth_config, token)
            except AuthenticationFailedError:
                logger.warning(f"Token refresh failed for integration {integration.provider_id}")
                return None
                
        logger.warning(f"Token expired and no refresh token for integration {integration.provider_id}")
        return None
        
    async def revoke_token(
        self,
        integration: SISIntegration,
        oauth_config: OAuthConfig,
        token: SISOAuthToken
    ) -> bool:
        """
        Revoke OAuth token.
        
        Args:
            integration: SIS integration instance
            oauth_config: OAuth configuration
            token: OAuth token to revoke
            
        Returns:
            True if successful
        """
        if not self._http_session:
            raise RuntimeError("OAuth service must be used as async context manager")
            
        # Some providers support token revocation
        revoke_url = oauth_config.custom_fields.get('revoke_url')
        if not revoke_url:
            # Just delete from database if no revoke endpoint
            await self.db.delete(token)
            await self.db.commit()
            return True
            
        revoke_data = {
            'token': token.access_token,
            'client_id': oauth_config.client_id,
            'client_secret': oauth_config.client_secret,
        }
        
        try:
            async with self._http_session.post(
                revoke_url,
                data=revoke_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            ) as response:
                
                if response.status not in (200, 204):
                    logger.warning(
                        f"Token revocation returned status {response.status} "
                        f"for integration {integration.provider_id}"
                    )
                    
        except aiohttp.ClientError as e:
            logger.warning(f"HTTP error during token revocation: {e}")
            
        # Delete token from database regardless of revocation result
        await self.db.delete(token)
        await self.db.commit()
        
        logger.info(f"Revoked token for integration {integration.provider_id}")
        return True
        
    async def _store_token(
        self,
        integration: SISIntegration,
        token_response: Dict[str, Any]
    ) -> SISOAuthToken:
        """Store OAuth token in database."""
        # Delete existing tokens
        existing_tokens = await self.db.execute(
            select(SISOAuthToken).where(SISOAuthToken.integration_id == integration.id)
        )
        for existing_token in existing_tokens.scalars():
            await self.db.delete(existing_token)
            
        # Create new token
        token = SISOAuthToken(
            integration_id=integration.id,
            access_token=self._encrypt_token(token_response['access_token']),
            refresh_token=self._encrypt_token(token_response.get('refresh_token')) if token_response.get('refresh_token') else None,
            token_type=token_response.get('token_type', 'bearer'),
            scope=token_response.get('scope'),
        )
        
        # Set expiry if provided
        if 'expires_in' in token_response:
            token.set_expiry_from_seconds(int(token_response['expires_in']))
            
        self.db.add(token)
        await self.db.commit()
        await self.db.refresh(token)
        
        return token
        
    async def _update_token(
        self,
        token: SISOAuthToken,
        token_response: Dict[str, Any]
    ) -> None:
        """Update existing OAuth token with new values."""
        token.access_token = self._encrypt_token(token_response['access_token'])
        
        if 'refresh_token' in token_response:
            token.refresh_token = self._encrypt_token(token_response['refresh_token'])
            
        if 'token_type' in token_response:
            token.token_type = token_response['token_type']
            
        if 'scope' in token_response:
            token.scope = token_response['scope']
            
        if 'expires_in' in token_response:
            token.set_expiry_from_seconds(int(token_response['expires_in']))
            
        token.updated_at = datetime.utcnow()
        await self.db.commit()
        
    def _encrypt_token(self, token: str) -> str:
        """Encrypt token for secure storage."""
        from app.core.security import encrypt_data
        return encrypt_data(token)
        
    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt token for use."""
        from app.core.security import decrypt_data
        return decrypt_data(encrypted_token)
        
    async def get_decrypted_token(self, token: SISOAuthToken) -> str:
        """Get decrypted access token for API calls."""
        return self._decrypt_token(token.access_token)