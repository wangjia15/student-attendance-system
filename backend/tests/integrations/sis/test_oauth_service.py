"""
Tests for SIS OAuth service.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import aiohttp
from aioresponses import aioresponses

from app.integrations.sis.oauth_service import (
    SISOAuthService, OAuthError, TokenExpiredError, AuthenticationFailedError
)
from app.models.sis_integration import SISIntegration, SISOAuthToken, SISIntegrationStatus
from app.core.sis_config import SISProviderType, OAuthConfig


@pytest.fixture
def oauth_config():
    """Create a test OAuth configuration."""
    return OAuthConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
        authorization_url="https://example.com/oauth/authorize",
        token_url="https://example.com/oauth/token",
        redirect_uri="https://attendance.school.edu/oauth/callback",
        scope=["read", "write"]
    )


@pytest.fixture
def sis_integration():
    """Create a test SIS integration."""
    integration = Mock(spec=SISIntegration)
    integration.id = 1
    integration.provider_id = "test_provider"
    integration.provider_type = SISProviderType.POWERSCHOOL
    integration.update_auth_success = Mock()
    integration.update_auth_failure = Mock()
    return integration


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()
    db.delete = AsyncMock()
    return db


class TestSISOAuthService:
    """Test SIS OAuth service functionality."""
    
    @pytest.mark.asyncio
    async def test_context_manager(self, mock_db):
        """Test OAuth service as async context manager."""
        async with SISOAuthService(mock_db) as service:
            assert service._http_session is not None
            assert isinstance(service._http_session, aiohttp.ClientSession)
            
        # Session should be closed after exiting context
        assert service._http_session is None
        
    @pytest.mark.asyncio
    async def test_generate_authorization_url(self, mock_db, sis_integration, oauth_config):
        """Test generating OAuth authorization URL."""
        async with SISOAuthService(mock_db) as service:
            auth_url, state = await service.generate_authorization_url(
                sis_integration,
                oauth_config,
                state="custom_state"
            )
            
            assert "custom_state" == state
            assert "https://example.com/oauth/authorize" in auth_url
            assert "client_id=test_client_id" in auth_url
            assert "redirect_uri=" in auth_url
            assert "scope=read+write" in auth_url
            assert "state=custom_state" in auth_url
            
    @pytest.mark.asyncio
    async def test_generate_authorization_url_auto_state(self, mock_db, sis_integration, oauth_config):
        """Test generating authorization URL with auto-generated state."""
        async with SISOAuthService(mock_db) as service:
            auth_url, state = await service.generate_authorization_url(
                sis_integration,
                oauth_config
            )
            
            assert state is not None
            assert len(state) > 20  # Should be a reasonably long random string
            assert f"state={state}" in auth_url
            
    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self, mock_db, sis_integration, oauth_config):
        """Test successful token exchange."""
        # Mock token response
        token_response = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "read write"
        }
        
        with aioresponses() as m:
            m.post(
                oauth_config.token_url,
                payload=token_response,
                status=200
            )
            
            # Mock database operations
            mock_existing_token = Mock()
            mock_db.execute.return_value.scalars.return_value = [mock_existing_token]
            
            async with SISOAuthService(mock_db) as service:
                token = await service.exchange_code_for_token(
                    sis_integration,
                    oauth_config,
                    "test_auth_code",
                    "test_state"
                )
                
                # Verify token was created
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called()
                sis_integration.update_auth_success.assert_called_once()
                
    @pytest.mark.asyncio
    async def test_exchange_code_for_token_failure(self, mock_db, sis_integration, oauth_config):
        """Test failed token exchange."""
        error_response = {
            "error": "invalid_grant",
            "error_description": "Authorization code is invalid"
        }
        
        with aioresponses() as m:
            m.post(
                oauth_config.token_url,
                payload=error_response,
                status=400
            )
            
            async with SISOAuthService(mock_db) as service:
                with pytest.raises(AuthenticationFailedError) as exc_info:
                    await service.exchange_code_for_token(
                        sis_integration,
                        oauth_config,
                        "invalid_code",
                        "test_state"
                    )
                    
                assert "Token exchange failed" in str(exc_info.value)
                
    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, mock_db, sis_integration, oauth_config):
        """Test successful token refresh."""
        # Create mock token
        token = Mock(spec=SISOAuthToken)
        token.refresh_token = "test_refresh_token"
        token.set_expiry_from_seconds = Mock()
        token.updated_at = None
        
        # Mock refresh response
        refresh_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "token_type": "bearer",
            "expires_in": 3600
        }
        
        with aioresponses() as m:
            m.post(
                oauth_config.token_url,
                payload=refresh_response,
                status=200
            )
            
            async with SISOAuthService(mock_db) as service:
                refreshed_token = await service.refresh_access_token(
                    sis_integration,
                    oauth_config,
                    token
                )
                
                # Verify token was updated
                assert refreshed_token == token
                token.set_expiry_from_seconds.assert_called_with(3600)
                mock_db.commit.assert_called()
                sis_integration.update_auth_success.assert_called_once()
                
    @pytest.mark.asyncio
    async def test_refresh_access_token_no_refresh_token(self, mock_db, sis_integration, oauth_config):
        """Test token refresh without refresh token."""
        token = Mock(spec=SISOAuthToken)
        token.refresh_token = None
        
        async with SISOAuthService(mock_db) as service:
            with pytest.raises(AuthenticationFailedError, match="No refresh token available"):
                await service.refresh_access_token(
                    sis_integration,
                    oauth_config,
                    token
                )
                
    @pytest.mark.asyncio
    async def test_refresh_access_token_failure(self, mock_db, sis_integration, oauth_config):
        """Test failed token refresh."""
        token = Mock(spec=SISOAuthToken)
        token.refresh_token = "invalid_refresh_token"
        
        error_response = {
            "error": "invalid_grant",
            "error_description": "Refresh token is invalid"
        }
        
        with aioresponses() as m:
            m.post(
                oauth_config.token_url,
                payload=error_response,
                status=400
            )
            
            async with SISOAuthService(mock_db) as service:
                with pytest.raises(AuthenticationFailedError) as exc_info:
                    await service.refresh_access_token(
                        sis_integration,
                        oauth_config,
                        token
                    )
                    
                assert "Token refresh failed" in str(exc_info.value)
                sis_integration.update_auth_failure.assert_called_once()
                
    @pytest.mark.asyncio
    async def test_get_valid_token_not_expired(self, mock_db, sis_integration, oauth_config):
        """Test getting valid token that hasn't expired."""
        # Mock non-expired token
        token = Mock(spec=SISOAuthToken)
        token.is_expired = False
        token.refresh_token = "test_refresh_token"
        
        # Mock database query
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = token
        mock_db.execute.return_value = mock_result
        
        async with SISOAuthService(mock_db) as service:
            result_token = await service.get_valid_token(sis_integration, oauth_config)
            
            assert result_token == token
            
    @pytest.mark.asyncio
    async def test_get_valid_token_expired_with_refresh(self, mock_db, sis_integration, oauth_config):
        """Test getting valid token when current token is expired but can be refreshed."""
        # Mock expired token
        token = Mock(spec=SISOAuthToken)
        token.is_expired = True
        token.refresh_token = "test_refresh_token"
        token.set_expiry_from_seconds = Mock()
        token.updated_at = None
        
        # Mock database query
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = token
        mock_db.execute.return_value = mock_result
        
        # Mock refresh response
        refresh_response = {
            "access_token": "refreshed_access_token",
            "token_type": "bearer",
            "expires_in": 3600
        }
        
        with aioresponses() as m:
            m.post(
                oauth_config.token_url,
                payload=refresh_response,
                status=200
            )
            
            async with SISOAuthService(mock_db) as service:
                result_token = await service.get_valid_token(sis_integration, oauth_config)
                
                assert result_token == token
                sis_integration.update_auth_success.assert_called_once()
                
    @pytest.mark.asyncio
    async def test_get_valid_token_no_token(self, mock_db, sis_integration, oauth_config):
        """Test getting valid token when no token exists."""
        # Mock no token found
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        async with SISOAuthService(mock_db) as service:
            result_token = await service.get_valid_token(sis_integration, oauth_config)
            
            assert result_token is None
            
    @pytest.mark.asyncio
    async def test_revoke_token_success(self, mock_db, sis_integration, oauth_config):
        """Test successful token revocation."""
        token = Mock(spec=SISOAuthToken)
        token.access_token = "test_access_token"
        
        # Add revoke URL to OAuth config
        oauth_config.custom_fields = {"revoke_url": "https://example.com/oauth/revoke"}
        
        with aioresponses() as m:
            m.post(
                "https://example.com/oauth/revoke",
                status=200
            )
            
            async with SISOAuthService(mock_db) as service:
                result = await service.revoke_token(
                    sis_integration,
                    oauth_config,
                    token
                )
                
                assert result is True
                mock_db.delete.assert_called_with(token)
                mock_db.commit.assert_called()
                
    @pytest.mark.asyncio
    async def test_revoke_token_no_revoke_url(self, mock_db, sis_integration, oauth_config):
        """Test token revocation without revoke URL."""
        token = Mock(spec=SISOAuthToken)
        token.access_token = "test_access_token"
        
        async with SISOAuthService(mock_db) as service:
            result = await service.revoke_token(
                sis_integration,
                oauth_config,
                token
            )
            
            assert result is True
            mock_db.delete.assert_called_with(token)
            mock_db.commit.assert_called()
            
    @pytest.mark.asyncio
    async def test_get_decrypted_token(self, mock_db):
        """Test getting decrypted token."""
        token = Mock(spec=SISOAuthToken)
        token.access_token = "encrypted_token"
        
        async with SISOAuthService(mock_db) as service:
            decrypted = await service.get_decrypted_token(token)
            
            # Currently returns as-is since encryption not implemented
            assert decrypted == "encrypted_token"


class TestSISOAuthToken:
    """Test SIS OAuth token model functionality."""
    
    def test_token_expiry_properties(self):
        """Test token expiry-related properties."""
        token = SISOAuthToken(
            integration_id=1,
            access_token="test_token",
            token_type="bearer"
        )
        
        # Test without expiry
        assert token.is_expired is False
        assert token.expires_soon is False
        
        # Test with future expiry
        token.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert token.is_expired is False
        assert token.expires_soon is False
        
        # Test with near expiry (within 5 minutes)
        token.expires_at = datetime.utcnow() + timedelta(minutes=2)
        assert token.is_expired is False
        assert token.expires_soon is True
        
        # Test with past expiry
        token.expires_at = datetime.utcnow() - timedelta(minutes=1)
        assert token.is_expired is True
        assert token.expires_soon is True
        
    def test_set_expiry_from_seconds(self):
        """Test setting expiry from seconds."""
        token = SISOAuthToken(
            integration_id=1,
            access_token="test_token",
            token_type="bearer"
        )
        
        before_time = datetime.utcnow()
        token.set_expiry_from_seconds(3600)  # 1 hour
        after_time = datetime.utcnow()
        
        expected_expiry = before_time + timedelta(seconds=3600)
        
        # Should be within a reasonable range
        assert token.expires_at >= expected_expiry - timedelta(seconds=1)
        assert token.expires_at <= after_time + timedelta(seconds=3600)