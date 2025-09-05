"""
Core SIS configuration system with plugin architecture support.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Protocol, TypedDict, runtime_checkable
from pydantic import BaseModel, Field, validator
from enum import Enum
import secrets


class SISProviderType(str, Enum):
    """Supported SIS provider types."""
    POWERSCHOOL = "powerschool"
    INFINITE_CAMPUS = "infinite_campus"
    SKYWARD = "skyward"
    CUSTOM = "custom"


class OAuthConfig(BaseModel):
    """OAuth 2.0 configuration for SIS providers."""
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    redirect_uri: str
    scope: List[str] = []
    
    class Config:
        extra = "allow"


class SISProviderConfig(BaseModel):
    """Configuration for a SIS provider."""
    provider_type: SISProviderType
    name: str
    base_url: str
    oauth_config: Optional[OAuthConfig] = None
    api_version: str = "v1"
    timeout: int = 30
    max_retries: int = 3
    rate_limit: int = 100  # requests per minute
    enabled: bool = True
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('base_url')
    def validate_base_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Base URL must start with http:// or https://')
        return v.rstrip('/')


class SyncScheduleConfig(BaseModel):
    """Configuration for sync schedules."""
    real_time: bool = True
    hourly: bool = False
    daily: bool = False
    daily_time: str = "02:00"  # 2 AM UTC
    sync_students: bool = True
    sync_enrollments: bool = True
    sync_grades: bool = False
    batch_size: int = 100
    
    @validator('daily_time')
    def validate_daily_time(cls, v):
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            raise ValueError('daily_time must be in HH:MM format')


@runtime_checkable
class SISProviderProtocol(Protocol):
    """Protocol that all SIS provider implementations must follow."""
    
    async def authenticate(self) -> bool:
        """Authenticate with the SIS provider."""
        ...
    
    async def get_students(self, **kwargs) -> List[Dict[str, Any]]:
        """Get student data from the SIS."""
        ...
    
    async def get_enrollments(self, **kwargs) -> List[Dict[str, Any]]:
        """Get enrollment data from the SIS."""
        ...
    
    async def sync_student(self, student_data: Dict[str, Any]) -> bool:
        """Sync a single student to the SIS."""
        ...
    
    async def health_check(self) -> bool:
        """Check if the SIS provider is available."""
        ...


class BaseSISProvider(ABC):
    """Base class for all SIS provider implementations."""
    
    def __init__(self, config: SISProviderConfig):
        self.config = config
        self._authenticated = False
        self._token_expires_at: Optional[datetime] = None
        
    @property
    def is_authenticated(self) -> bool:
        """Check if provider is authenticated."""
        if not self._authenticated:
            return False
        if self._token_expires_at and datetime.utcnow() >= self._token_expires_at:
            self._authenticated = False
            return False
        return True
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the SIS provider."""
        pass
    
    @abstractmethod
    async def get_students(self, **kwargs) -> List[Dict[str, Any]]:
        """Get student data from the SIS."""
        pass
    
    @abstractmethod
    async def get_enrollments(self, **kwargs) -> List[Dict[str, Any]]:
        """Get enrollment data from the SIS."""
        pass
    
    @abstractmethod
    async def sync_student(self, student_data: Dict[str, Any]) -> bool:
        """Sync a single student to the SIS."""
        pass
    
    async def health_check(self) -> bool:
        """Default health check implementation."""
        try:
            if not self.is_authenticated:
                return await self.authenticate()
            return True
        except Exception:
            return False


class SISConfigManager:
    """Manager for SIS provider configurations."""
    
    def __init__(self):
        self._providers: Dict[str, SISProviderConfig] = {}
        self._sync_config: Optional[SyncScheduleConfig] = None
        
    def register_provider(self, provider_id: str, config: SISProviderConfig) -> None:
        """Register a SIS provider configuration."""
        self._providers[provider_id] = config
        
    def get_provider_config(self, provider_id: str) -> Optional[SISProviderConfig]:
        """Get configuration for a specific provider."""
        return self._providers.get(provider_id)
        
    def list_providers(self, enabled_only: bool = False) -> Dict[str, SISProviderConfig]:
        """List all registered providers."""
        if enabled_only:
            return {k: v for k, v in self._providers.items() if v.enabled}
        return self._providers.copy()
        
    def remove_provider(self, provider_id: str) -> bool:
        """Remove a provider configuration."""
        return self._providers.pop(provider_id, None) is not None
        
    def set_sync_config(self, config: SyncScheduleConfig) -> None:
        """Set sync schedule configuration."""
        self._sync_config = config
        
    def get_sync_config(self) -> Optional[SyncScheduleConfig]:
        """Get sync schedule configuration."""
        return self._sync_config
        
    def validate_provider_config(self, config: SISProviderConfig) -> List[str]:
        """Validate a provider configuration and return any errors."""
        errors = []
        
        # Check required OAuth config for known providers
        if config.provider_type != SISProviderType.CUSTOM and not config.oauth_config:
            errors.append("OAuth configuration is required for standard SIS providers")
            
        # Validate OAuth config if present
        if config.oauth_config:
            required_oauth_fields = ['client_id', 'client_secret', 'authorization_url', 'token_url']
            for field in required_oauth_fields:
                if not getattr(config.oauth_config, field, None):
                    errors.append(f"OAuth {field} is required")
                    
        return errors


# Global configuration manager instance
sis_config_manager = SISConfigManager()


# Default configurations for known providers
DEFAULT_POWERSCHOOL_CONFIG = {
    "provider_type": SISProviderType.POWERSCHOOL,
    "name": "PowerSchool",
    "base_url": "https://district.powerschool.com",
    "api_version": "v3",
    "rate_limit": 60,  # PowerSchool has stricter rate limits
}

DEFAULT_INFINITE_CAMPUS_CONFIG = {
    "provider_type": SISProviderType.INFINITE_CAMPUS,
    "name": "Infinite Campus",
    "base_url": "https://district.infinitecampus.org",
    "api_version": "v1",
    "rate_limit": 100,
}

DEFAULT_SKYWARD_CONFIG = {
    "provider_type": SISProviderType.SKYWARD,
    "name": "Skyward",
    "base_url": "https://district.skyward.com",
    "api_version": "v1",
    "rate_limit": 80,
}