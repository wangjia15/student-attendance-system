"""
Pydantic schemas for SIS integration API endpoints.
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from app.core.sis_config import SISProviderType
from app.models.sis_integration import SISIntegrationStatus


class SISProviderConfig(BaseModel):
    """Configuration for SIS provider setup."""
    provider_type: SISProviderType
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    base_url: str = Field(..., min_length=1, max_length=500)
    api_version: str = "v1"
    timeout: int = Field(default=30, ge=5, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    rate_limit: int = Field(default=100, ge=1, le=10000)
    config: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class SISIntegrationCreate(SISProviderConfig):
    """Schema for creating new SIS integration."""
    provider_id: str = Field(..., min_length=1, max_length=50)
    enabled: bool = True


class SISIntegrationUpdate(BaseModel):
    """Schema for updating SIS integration."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    base_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_version: Optional[str] = None
    timeout: Optional[int] = Field(None, ge=5, le=300)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    rate_limit: Optional[int] = Field(None, ge=1, le=10000)
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class SISIntegrationResponse(BaseModel):
    """Schema for SIS integration response."""
    id: int
    provider_id: str
    provider_type: SISProviderType
    name: str
    description: Optional[str]
    base_url: str
    api_version: str
    timeout: int
    max_retries: int
    rate_limit: int
    status: SISIntegrationStatus
    enabled: bool
    config: Dict[str, Any] = Field(default_factory=dict)
    
    # Authentication tracking
    last_auth_success: Optional[datetime]
    last_auth_failure: Optional[datetime]
    auth_failure_count: int
    
    # Sync tracking
    last_sync_start: Optional[datetime]
    last_sync_success: Optional[datetime]
    last_sync_failure: Optional[datetime]
    sync_failure_count: int
    
    # Statistics
    total_students_synced: int
    total_enrollments_synced: int
    total_api_calls: int
    
    # Health status
    is_healthy: bool
    
    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SISIntegrationSummary(BaseModel):
    """Simplified schema for listing SIS integrations."""
    id: int
    provider_id: str
    provider_type: SISProviderType
    name: str
    status: SISIntegrationStatus
    enabled: bool
    is_healthy: bool
    last_sync_success: Optional[datetime]
    total_students_synced: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SISOAuthTokenResponse(BaseModel):
    """Schema for OAuth token information (without sensitive data)."""
    id: int
    token_type: str
    scope: Optional[str]
    expires_at: Optional[datetime]
    is_expired: bool
    expires_soon: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SISAuthorizationURL(BaseModel):
    """Schema for OAuth authorization URL response."""
    authorization_url: str
    state: str


class SISOAuthCallback(BaseModel):
    """Schema for OAuth callback data."""
    code: str
    state: str
    integration_id: int


class SISSyncOperationResponse(BaseModel):
    """Schema for sync operation status."""
    id: int
    operation_type: str
    status: str
    total_records: int
    processed_records: int
    successful_records: int
    failed_records: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    progress_percentage: float
    error_message: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SISSyncRequest(BaseModel):
    """Schema for requesting sync operation."""
    operation_type: str = Field(..., pattern="^(students|enrollments|full)$")
    force_sync: bool = False


class SISStudentMappingResponse(BaseModel):
    """Schema for student mapping information."""
    id: int
    local_student_id: int
    sis_student_id: str
    sis_student_number: Optional[str]
    sis_email: Optional[str]
    sis_state_id: Optional[str]
    last_synced_at: Optional[datetime]
    sync_conflicts: Optional[List[Dict[str, Any]]]
    is_active: bool
    needs_sync: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SISConflictResolution(BaseModel):
    """Schema for resolving sync conflicts."""
    mapping_id: int
    resolutions: Dict[str, str] = Field(..., description="field -> 'local' or 'sis'")


class SISHealthCheck(BaseModel):
    """Schema for SIS integration health check."""
    integration_id: int
    provider_type: SISProviderType
    is_healthy: bool
    status: SISIntegrationStatus
    connectivity: bool
    authentication: bool
    last_check: datetime
    issues: List[str] = Field(default_factory=list)


class SISMetrics(BaseModel):
    """Schema for SIS integration metrics."""
    total_integrations: int
    active_integrations: int
    healthy_integrations: int
    total_students_synced: int
    total_sync_operations: int
    failed_sync_operations: int
    average_sync_time: float
    last_sync_times: Dict[str, Optional[datetime]]