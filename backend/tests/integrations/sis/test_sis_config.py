"""
Tests for SIS configuration system.
"""

import pytest
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock

from app.core.sis_config import (
    SISProviderType, SISProviderConfig, OAuthConfig, SyncScheduleConfig,
    BaseSISProvider, SISConfigManager, sis_config_manager
)


class TestOAuthConfig:
    """Test OAuth configuration validation."""
    
    def test_valid_oauth_config(self):
        """Test creating valid OAuth configuration."""
        config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback",
            scope=["read", "write"]
        )
        
        assert config.client_id == "test_client"
        assert config.client_secret == "test_secret"
        assert config.scope == ["read", "write"]
        
    def test_oauth_config_with_extra_fields(self):
        """Test OAuth config with custom fields."""
        config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback",
            revoke_url="https://example.com/oauth/revoke"  # Extra field
        )
        
        assert hasattr(config, 'revoke_url')
        assert config.revoke_url == "https://example.com/oauth/revoke"


class TestSISProviderConfig:
    """Test SIS provider configuration validation."""
    
    def test_valid_provider_config(self):
        """Test creating valid provider configuration."""
        oauth_config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://powerschool.com/oauth/authorize",
            token_url="https://powerschool.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback"
        )
        
        config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com",
            oauth_config=oauth_config,
            rate_limit=60
        )
        
        assert config.provider_type == SISProviderType.POWERSCHOOL
        assert config.name == "Test PowerSchool"
        assert config.base_url == "https://district.powerschool.com"
        assert config.rate_limit == 60
        
    def test_invalid_base_url(self):
        """Test validation of invalid base URL."""
        with pytest.raises(ValueError, match="Base URL must start with http"):
            SISProviderConfig(
                provider_type=SISProviderType.POWERSCHOOL,
                name="Test PowerSchool",
                base_url="invalid-url",  # Invalid URL
                rate_limit=60
            )
            
    def test_base_url_trailing_slash_removal(self):
        """Test base URL trailing slash removal."""
        config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com/",  # Has trailing slash
            rate_limit=60
        )
        
        assert config.base_url == "https://district.powerschool.com"  # Should be removed


class TestSyncScheduleConfig:
    """Test sync schedule configuration."""
    
    def test_valid_sync_config(self):
        """Test creating valid sync configuration."""
        config = SyncScheduleConfig(
            real_time=True,
            hourly=False,
            daily=True,
            daily_time="02:30",
            sync_students=True,
            sync_enrollments=True,
            batch_size=150
        )
        
        assert config.real_time is True
        assert config.daily_time == "02:30"
        assert config.batch_size == 150
        
    def test_invalid_daily_time(self):
        """Test validation of invalid daily time format."""
        with pytest.raises(ValueError, match="daily_time must be in HH:MM format"):
            SyncScheduleConfig(daily_time="25:00")  # Invalid hour
            
        with pytest.raises(ValueError, match="daily_time must be in HH:MM format"):
            SyncScheduleConfig(daily_time="2:30")  # Should be 02:30


class TestBaseSISProvider:
    """Test base SIS provider functionality."""
    
    def test_provider_initialization(self):
        """Test provider initialization."""
        config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test Provider",
            base_url="https://example.com"
        )
        
        class TestProvider(BaseSISProvider):
            async def authenticate(self) -> bool:
                return True
                
            async def get_students(self, **kwargs):
                return []
                
            async def get_enrollments(self, **kwargs):
                return []
                
            async def sync_student(self, student_data: Dict[str, Any]) -> bool:
                return True
                
        provider = TestProvider(config)
        
        assert provider.config == config
        assert provider.is_authenticated is False
        assert provider._token_expires_at is None
        
    @pytest.mark.asyncio
    async def test_provider_health_check_default(self):
        """Test default health check implementation."""
        config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test Provider",
            base_url="https://example.com"
        )
        
        class TestProvider(BaseSISProvider):
            async def authenticate(self) -> bool:
                self._authenticated = True
                return True
                
            async def get_students(self, **kwargs):
                return []
                
            async def get_enrollments(self, **kwargs):
                return []
                
            async def sync_student(self, student_data: Dict[str, Any]) -> bool:
                return True
                
        provider = TestProvider(config)
        result = await provider.health_check()
        
        assert result is True
        assert provider.is_authenticated is True


class TestSISConfigManager:
    """Test SIS configuration manager."""
    
    def test_register_and_get_provider(self):
        """Test registering and retrieving provider configuration."""
        manager = SISConfigManager()
        
        config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com"
        )
        
        # Register provider
        manager.register_provider("test_ps", config)
        
        # Retrieve provider
        retrieved_config = manager.get_provider_config("test_ps")
        assert retrieved_config == config
        
        # Test non-existent provider
        assert manager.get_provider_config("nonexistent") is None
        
    def test_list_providers(self):
        """Test listing providers with filtering."""
        manager = SISConfigManager()
        
        # Register enabled provider
        config1 = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Enabled Provider",
            base_url="https://district1.powerschool.com",
            enabled=True
        )
        manager.register_provider("enabled_provider", config1)
        
        # Register disabled provider
        config2 = SISProviderConfig(
            provider_type=SISProviderType.INFINITE_CAMPUS,
            name="Disabled Provider",
            base_url="https://district2.infinitecampus.com",
            enabled=False
        )
        manager.register_provider("disabled_provider", config2)
        
        # Test listing all providers
        all_providers = manager.list_providers(enabled_only=False)
        assert len(all_providers) == 2
        
        # Test listing only enabled providers
        enabled_providers = manager.list_providers(enabled_only=True)
        assert len(enabled_providers) == 1
        assert "enabled_provider" in enabled_providers
        assert "disabled_provider" not in enabled_providers
        
    def test_remove_provider(self):
        """Test removing provider configuration."""
        manager = SISConfigManager()
        
        config = SISProviderConfig(
            provider_type=SISProviderType.SKYWARD,
            name="Test Skyward",
            base_url="https://district.skyward.com"
        )
        
        # Register provider
        manager.register_provider("test_skyward", config)
        assert manager.get_provider_config("test_skyward") is not None
        
        # Remove provider
        result = manager.remove_provider("test_skyward")
        assert result is True
        assert manager.get_provider_config("test_skyward") is None
        
        # Test removing non-existent provider
        result = manager.remove_provider("nonexistent")
        assert result is False
        
    def test_sync_config_management(self):
        """Test sync configuration management."""
        manager = SISConfigManager()
        
        sync_config = SyncScheduleConfig(
            real_time=True,
            daily=True,
            daily_time="03:00",
            batch_size=200
        )
        
        # Set sync config
        manager.set_sync_config(sync_config)
        
        # Get sync config
        retrieved_config = manager.get_sync_config()
        assert retrieved_config == sync_config
        assert retrieved_config.daily_time == "03:00"
        
    def test_validate_provider_config(self):
        """Test provider configuration validation."""
        manager = SISConfigManager()
        
        # Test valid configuration
        oauth_config = OAuthConfig(
            client_id="test_client",
            client_secret="test_secret",
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback"
        )
        
        valid_config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com",
            oauth_config=oauth_config
        )
        
        errors = manager.validate_provider_config(valid_config)
        assert len(errors) == 0
        
        # Test configuration without OAuth (for standard provider)
        invalid_config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com"
            # Missing oauth_config
        )
        
        errors = manager.validate_provider_config(invalid_config)
        assert len(errors) > 0
        assert any("OAuth configuration is required" in error for error in errors)
        
        # Test OAuth config with missing fields
        incomplete_oauth = OAuthConfig(
            client_id="test_client",
            # Missing client_secret
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            redirect_uri="https://attendance.school.edu/oauth/callback"
        )
        
        incomplete_config = SISProviderConfig(
            provider_type=SISProviderType.POWERSCHOOL,
            name="Test PowerSchool",
            base_url="https://district.powerschool.com",
            oauth_config=incomplete_oauth
        )
        
        # This would fail at Pydantic validation level before reaching our validator
        with pytest.raises(ValueError):
            incomplete_oauth.client_secret  # This should raise since it's required


class TestGlobalConfigManager:
    """Test global configuration manager instance."""
    
    def test_global_instance(self):
        """Test that global config manager instance works."""
        # Clear any existing configuration
        sis_config_manager._providers.clear()
        
        config = SISProviderConfig(
            provider_type=SISProviderType.CUSTOM,
            name="Global Test Provider",
            base_url="https://example.com"
        )
        
        # Register with global manager
        sis_config_manager.register_provider("global_test", config)
        
        # Retrieve from global manager
        retrieved = sis_config_manager.get_provider_config("global_test")
        assert retrieved is not None
        assert retrieved.name == "Global Test Provider"
        
        # Clean up
        sis_config_manager.remove_provider("global_test")