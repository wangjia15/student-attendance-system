"""
Tests for main SIS service.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from app.services.sis_service import (
    SISService, SISServiceError, IntegrationNotFoundError, IntegrationDisabledError
)
from app.models.sis_integration import SISIntegration, SISIntegrationStatus, SISOAuthToken
from app.core.sis_config import SISProviderType, SISProviderConfig, OAuthConfig
from app.integrations.sis.roster_sync import ConflictResolutionStrategy


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


@pytest.fixture
def sis_service(mock_db):
    """Create SIS service instance with mocked dependencies."""
    service = SISService(mock_db)
    
    # Mock the dependent services
    service.token_manager = AsyncMock()
    service.roster_sync = AsyncMock()
    service.enrollment_handler = AsyncMock()
    
    return service


@pytest.fixture
def sample_integration():
    """Create a sample SIS integration."""
    return SISIntegration(
        id=1,
        provider_id="test_powerschool",
        provider_type=SISProviderType.POWERSCHOOL,
        name="Test PowerSchool",
        base_url="https://district.powerschool.com",
        status=SISIntegrationStatus.ACTIVE,
        enabled=True
    )


@pytest.fixture
def sample_provider_config():
    """Create a sample provider configuration."""
    oauth_config = OAuthConfig(
        client_id="test_client",
        client_secret="test_secret",
        authorization_url="https://powerschool.com/oauth/authorize",
        token_url="https://powerschool.com/oauth/token",
        redirect_uri="https://attendance.school.edu/oauth/callback"
    )
    
    return SISProviderConfig(
        provider_type=SISProviderType.POWERSCHOOL,
        name="Test PowerSchool",
        base_url="https://district.powerschool.com",
        oauth_config=oauth_config,
        enabled=True
    )


class TestSISService:
    """Test main SIS service functionality."""
    
    @pytest.mark.asyncio
    async def test_start_service(self, sis_service):
        """Test starting the SIS service."""
        sis_service.token_manager.start_token_monitoring = AsyncMock()
        
        with patch('asyncio.create_task') as mock_create_task:
            await sis_service.start_service()
            
            sis_service.token_manager.start_token_monitoring.assert_called_once()
            mock_create_task.assert_called_once()
            
    @pytest.mark.asyncio
    async def test_stop_service(self, sis_service):
        """Test stopping the SIS service."""
        # Mock a background task
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        mock_task.cancel = Mock()
        sis_service._background_tasks['test_task'] = mock_task
        
        sis_service.token_manager.stop_token_monitoring = AsyncMock()
        
        await sis_service.stop_service()
        
        sis_service.token_manager.stop_token_monitoring.assert_called_once()
        mock_task.cancel.assert_called_once()
        assert len(sis_service._background_tasks) == 0
        
    @pytest.mark.asyncio
    async def test_create_integration_success(self, sis_service, sample_provider_config):
        """Test successful integration creation."""
        # Mock configuration validation
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.validate_provider_config.return_value = []  # No errors
            mock_config_manager.register_provider = Mock()
            
            # Mock database operations
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = None  # No existing integration
            sis_service.db.execute.return_value = mock_result
            
            integration = await sis_service.create_integration(
                provider_type=SISProviderType.POWERSCHOOL,
                provider_id="test_powerschool",
                name="Test PowerSchool",
                config=sample_provider_config
            )
            
            # Verify database operations
            sis_service.db.add.assert_called_once()
            sis_service.db.commit.assert_called_once()
            sis_service.db.refresh.assert_called_once()
            
            # Verify configuration registration
            mock_config_manager.register_provider.assert_called_once_with(
                "test_powerschool", sample_provider_config
            )
            
    @pytest.mark.asyncio
    async def test_create_integration_validation_error(self, sis_service, sample_provider_config):
        """Test integration creation with validation errors."""
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.validate_provider_config.return_value = ["OAuth client_id is required"]
            
            with pytest.raises(SISServiceError, match="Configuration validation failed"):
                await sis_service.create_integration(
                    provider_type=SISProviderType.POWERSCHOOL,
                    provider_id="test_powerschool",
                    name="Test PowerSchool",
                    config=sample_provider_config
                )
                
    @pytest.mark.asyncio
    async def test_create_integration_duplicate(self, sis_service, sample_provider_config, sample_integration):
        """Test creating integration with duplicate provider_id."""
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.validate_provider_config.return_value = []
            
            # Mock existing integration
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = sample_integration
            sis_service.db.execute.return_value = mock_result
            
            with pytest.raises(SISServiceError, match="Integration with provider_id.*already exists"):
                await sis_service.create_integration(
                    provider_type=SISProviderType.POWERSCHOOL,
                    provider_id="test_powerschool",
                    name="Test PowerSchool",
                    config=sample_provider_config
                )
                
    @pytest.mark.asyncio
    async def test_get_integration(self, sis_service, sample_integration):
        """Test getting integration by ID."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = sample_integration
        sis_service.db.execute.return_value = mock_result
        
        result = await sis_service.get_integration(1)
        
        assert result == sample_integration
        sis_service.db.execute.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_get_integration_not_found(self, sis_service):
        """Test getting non-existent integration."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        sis_service.db.execute.return_value = mock_result
        
        result = await sis_service.get_integration(999)
        
        assert result is None
        
    @pytest.mark.asyncio
    async def test_list_integrations(self, sis_service):
        """Test listing integrations."""
        integrations = [
            Mock(enabled=True),
            Mock(enabled=False),
            Mock(enabled=True)
        ]
        
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = integrations
        sis_service.db.execute.return_value = mock_result
        
        # Test listing all integrations
        result = await sis_service.list_integrations(enabled_only=False)
        assert len(result) == 3
        
        # Test listing only enabled integrations
        enabled_integrations = [i for i in integrations if i.enabled]
        mock_result.scalars.return_value.all.return_value = enabled_integrations
        result = await sis_service.list_integrations(enabled_only=True)
        assert len(result) == 2
        
    @pytest.mark.asyncio
    async def test_update_integration(self, sis_service, sample_integration):
        """Test updating integration."""
        # Mock get_integration
        sis_service.get_integration = AsyncMock(return_value=sample_integration)
        
        updates = {"name": "Updated Name", "enabled": False}
        result = await sis_service.update_integration(1, updates)
        
        assert result == sample_integration
        assert sample_integration.name == "Updated Name"
        assert sample_integration.enabled is False
        sis_service.db.commit.assert_called_once()
        sis_service.db.refresh.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_delete_integration(self, sis_service, sample_integration):
        """Test deleting integration."""
        # Mock dependencies
        sis_service.get_integration = AsyncMock(return_value=sample_integration)
        sis_service.token_manager.revoke_all_tokens_for_integration = AsyncMock(return_value=True)
        
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.remove_provider = Mock(return_value=True)
            
            result = await sis_service.delete_integration(1)
            
            assert result is True
            sis_service.token_manager.revoke_all_tokens_for_integration.assert_called_once_with(1)
            sis_service.db.delete.assert_called_with(sample_integration)
            sis_service.db.commit.assert_called_once()
            mock_config_manager.remove_provider.assert_called_once()
            
    @pytest.mark.asyncio
    async def test_initiate_oauth_flow(self, sis_service, sample_integration):
        """Test initiating OAuth flow."""
        # Mock dependencies
        sis_service.get_integration = AsyncMock(return_value=sample_integration)
        
        oauth_config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback"
        )
        
        provider_config = Mock()
        provider_config.oauth_config = oauth_config
        
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.get_provider_config.return_value = provider_config
            
            with patch('app.integrations.sis.oauth_service.SISOAuthService') as mock_oauth_service:
                mock_service_instance = AsyncMock()
                mock_service_instance.generate_authorization_url.return_value = ("https://auth.url", "state123")
                mock_oauth_service.return_value.__aenter__.return_value = mock_service_instance
                
                result = await sis_service.initiate_oauth_flow(1, "custom_state")
                
                assert result["authorization_url"] == "https://auth.url"
                assert result["state"] == "state123"
                
    @pytest.mark.asyncio
    async def test_complete_oauth_flow_success(self, sis_service, sample_integration):
        """Test successful OAuth flow completion."""
        # Mock dependencies
        sis_service.get_integration = AsyncMock(return_value=sample_integration)
        
        oauth_config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback"
        )
        
        provider_config = Mock()
        provider_config.oauth_config = oauth_config
        
        with patch('app.core.sis_config.sis_config_manager') as mock_config_manager:
            mock_config_manager.get_provider_config.return_value = provider_config
            
            with patch('app.integrations.sis.oauth_service.SISOAuthService') as mock_oauth_service:
                mock_service_instance = AsyncMock()
                mock_service_instance.exchange_code_for_token.return_value = Mock()
                mock_oauth_service.return_value.__aenter__.return_value = mock_service_instance
                
                result = await sis_service.complete_oauth_flow(1, "auth_code", "state123")
                
                assert result is True
                assert sample_integration.status == SISIntegrationStatus.ACTIVE
                sis_service.db.commit.assert_called()
                
    @pytest.mark.asyncio
    async def test_sync_all_rosters(self, sis_service):
        """Test syncing all rosters."""
        expected_result = {
            'total_integrations': 2,
            'successful_syncs': 1,
            'failed_syncs': 1,
            'students_processed': 100
        }
        
        sis_service.roster_sync.sync_all_integrations.return_value = expected_result
        
        result = await sis_service.sync_all_rosters(ConflictResolutionStrategy.SIS_WINS)
        
        assert result == expected_result
        sis_service.roster_sync.sync_all_integrations.assert_called_once_with(
            ConflictResolutionStrategy.SIS_WINS
        )
        
    @pytest.mark.asyncio
    async def test_sync_integration_roster(self, sis_service):
        """Test syncing roster for specific integration."""
        expected_result = {
            'integration_id': 1,
            'success': True,
            'students_processed': 50
        }
        
        sis_service.roster_sync.sync_integration_roster.return_value = expected_result
        
        result = await sis_service.sync_integration_roster(1)
        
        assert result == expected_result
        sis_service.roster_sync.sync_integration_roster.assert_called_once_with(
            1, ConflictResolutionStrategy.NEWEST_WINS
        )
        
    @pytest.mark.asyncio
    async def test_check_integration_health(self, sis_service, sample_integration):
        """Test checking integration health."""
        # Mock dependencies
        sis_service.get_integration = AsyncMock(return_value=sample_integration)
        sis_service.token_manager.get_token_status = AsyncMock(return_value={
            'token_id': 1,
            'expires_at': datetime.utcnow() + timedelta(hours=1),
            'is_expired': False
        })
        
        # Mock provider health check
        mock_provider = AsyncMock()
        mock_provider.health_check.return_value = True
        
        with patch.object(sis_service, '_get_provider_instance', return_value=mock_provider):
            # Mock recent sync operations
            mock_sync_ops = [
                Mock(
                    id=1,
                    operation_type='roster_sync',
                    status='completed',
                    started_at=datetime.utcnow() - timedelta(hours=1),
                    completed_at=datetime.utcnow() - timedelta(minutes=50),
                    processed_records=100,
                    successful_records=95,
                    failed_records=5
                )
            ]
            
            mock_result = Mock()
            mock_result.scalars.return_value.all.return_value = mock_sync_ops
            sis_service.db.execute.return_value = mock_result
            
            result = await sis_service.check_integration_health(1)
            
            assert result['healthy'] is True
            assert result['integration_status'] == sample_integration.status
            assert result['is_enabled'] is True
            assert 'token_status' in result
            assert 'recent_syncs' in result
            assert 'statistics' in result
            
    @pytest.mark.asyncio
    async def test_check_integration_health_not_found(self, sis_service):
        """Test health check for non-existent integration."""
        sis_service.get_integration = AsyncMock(return_value=None)
        
        result = await sis_service.check_integration_health(999)
        
        assert result['healthy'] is False
        assert result['error'] == 'Integration not found'
        
    @pytest.mark.asyncio
    async def test_check_integration_health_disabled(self, sis_service):
        """Test health check for disabled integration."""
        disabled_integration = Mock()
        disabled_integration.enabled = False
        
        sis_service.get_integration = AsyncMock(return_value=disabled_integration)
        
        result = await sis_service.check_integration_health(1)
        
        assert result['healthy'] is False
        assert result['error'] == 'Integration disabled'
        
    @pytest.mark.asyncio
    async def test_get_system_status(self, sis_service):
        """Test getting overall system status."""
        # Mock integrations
        integrations = [
            Mock(
                id=1, provider_id='ps1', name='PowerSchool 1', 
                provider_type=SISProviderType.POWERSCHOOL,
                status=SISIntegrationStatus.ACTIVE, enabled=True,
                last_sync_success=datetime.utcnow()
            ),
            Mock(
                id=2, provider_id='ic1', name='Infinite Campus 1',
                provider_type=SISProviderType.INFINITE_CAMPUS,
                status=SISIntegrationStatus.ERROR, enabled=True,
                last_sync_success=None
            )
        ]
        
        sis_service.list_integrations = AsyncMock(return_value=integrations)
        sis_service.check_integration_health = AsyncMock(side_effect=[
            {'healthy': True},
            {'healthy': False}
        ])
        
        result = await sis_service.get_system_status()
        
        assert result['total_integrations'] == 2
        assert result['active_integrations'] == 1
        assert result['error_integrations'] == 1
        assert result['disabled_integrations'] == 0
        assert result['pending_integrations'] == 0
        assert len(result['integrations']) == 2
        
    @pytest.mark.asyncio
    async def test_get_pending_conflicts(self, sis_service):
        """Test getting pending conflicts."""
        expected_conflicts = [
            {'mapping_id': 1, 'conflicts': ['email_mismatch']},
            {'mapping_id': 2, 'conflicts': ['name_mismatch']}
        ]
        
        sis_service.roster_sync.get_pending_conflicts.return_value = expected_conflicts
        
        result = await sis_service.get_pending_conflicts()
        
        assert result == expected_conflicts
        sis_service.roster_sync.get_pending_conflicts.assert_called_once_with(None)
        
        # Test with integration filter
        result = await sis_service.get_pending_conflicts(integration_id=1)
        sis_service.roster_sync.get_pending_conflicts.assert_called_with(1)
        
    @pytest.mark.asyncio
    async def test_resolve_conflicts(self, sis_service):
        """Test resolving conflicts."""
        resolutions = {'email': 'student@school.edu', 'full_name': 'John Doe'}
        
        sis_service.roster_sync.resolve_student_conflicts.return_value = True
        
        result = await sis_service.resolve_conflicts(1, resolutions)
        
        assert result is True
        sis_service.roster_sync.resolve_student_conflicts.assert_called_once_with(1, resolutions)