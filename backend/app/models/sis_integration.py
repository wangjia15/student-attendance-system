"""
SQLAlchemy models for SIS integration metadata and credentials.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON, 
    ForeignKey, Index, UniqueConstraint, Enum as SQLEnum
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
import enum
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.core.database import Base
from app.core.sis_config import SISProviderType


class SISIntegrationStatus(str, enum.Enum):
    """Status of SIS integration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"
    DISABLED = "disabled"


class SISIntegration(Base):
    """Model for SIS integration configurations and metadata."""
    
    __tablename__ = "sis_integrations"
    
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(String(50), unique=True, index=True, nullable=False)
    provider_type = Column(SQLEnum(SISProviderType), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Provider configuration
    base_url = Column(String(500), nullable=False)
    api_version = Column(String(20), default="v1")
    timeout = Column(Integer, default=30)
    max_retries = Column(Integer, default=3)
    rate_limit = Column(Integer, default=100)  # requests per minute
    
    # Status and configuration
    status = Column(SQLEnum(SISIntegrationStatus), default=SISIntegrationStatus.PENDING)
    enabled = Column(Boolean, default=True)
    config_json = Column(JSON, nullable=True)  # Provider-specific configuration
    
    # Authentication tracking
    last_auth_success = Column(DateTime(timezone=True), nullable=True)
    last_auth_failure = Column(DateTime(timezone=True), nullable=True)
    auth_failure_count = Column(Integer, default=0)
    
    # Sync tracking
    last_sync_start = Column(DateTime(timezone=True), nullable=True)
    last_sync_success = Column(DateTime(timezone=True), nullable=True)
    last_sync_failure = Column(DateTime(timezone=True), nullable=True)
    sync_failure_count = Column(Integer, default=0)
    
    # Statistics
    total_students_synced = Column(Integer, default=0)
    total_enrollments_synced = Column(Integer, default=0)
    total_api_calls = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    oauth_tokens = relationship("SISOAuthToken", back_populates="integration", cascade="all, delete-orphan")
    sync_operations = relationship("SISSyncOperation", back_populates="integration", cascade="all, delete-orphan")
    student_mappings = relationship("SISStudentMapping", back_populates="integration", cascade="all, delete-orphan")
    
    @hybrid_property
    def is_healthy(self) -> bool:
        """Check if integration is healthy."""
        return (
            self.enabled and
            self.status == SISIntegrationStatus.ACTIVE and
            self.auth_failure_count < 3 and
            self.sync_failure_count < 5
        )
    
    @hybrid_property
    def config(self) -> Dict[str, Any]:
        """Get configuration as dictionary."""
        return self.config_json or {}
    
    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        """Set configuration from dictionary."""
        self.config_json = value
        
    def update_auth_success(self) -> None:
        """Update authentication success tracking."""
        self.last_auth_success = func.now()
        self.auth_failure_count = 0
        if self.status == SISIntegrationStatus.ERROR:
            self.status = SISIntegrationStatus.ACTIVE
            
    def update_auth_failure(self) -> None:
        """Update authentication failure tracking."""
        self.last_auth_failure = func.now()
        self.auth_failure_count += 1
        if self.auth_failure_count >= 3:
            self.status = SISIntegrationStatus.ERROR
            
    def update_sync_success(self, students_count: int = 0, enrollments_count: int = 0) -> None:
        """Update sync success tracking."""
        self.last_sync_success = func.now()
        self.sync_failure_count = 0
        self.total_students_synced += students_count
        self.total_enrollments_synced += enrollments_count
        if self.status == SISIntegrationStatus.ERROR:
            self.status = SISIntegrationStatus.ACTIVE
            
    def update_sync_failure(self) -> None:
        """Update sync failure tracking."""
        self.last_sync_failure = func.now()
        self.sync_failure_count += 1
        if self.sync_failure_count >= 5:
            self.status = SISIntegrationStatus.ERROR


class SISOAuthToken(Base):
    """Model for storing SIS OAuth tokens securely."""
    
    __tablename__ = "sis_oauth_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    
    # OAuth token data (encrypted in production)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    token_type = Column(String(50), default="bearer")
    scope = Column(String(500), nullable=True)
    
    # Token lifecycle
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", back_populates="oauth_tokens")
    
    @hybrid_property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() >= self.expires_at
        
    @hybrid_property
    def expires_soon(self) -> bool:
        """Check if token expires within 5 minutes."""
        if not self.expires_at:
            return False
        return datetime.utcnow() >= (self.expires_at - timedelta(minutes=5))
        
    def set_expiry_from_seconds(self, expires_in: int) -> None:
        """Set expiry time from seconds from now."""
        self.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)


class SISSyncOperation(Base):
    """Model for tracking SIS sync operations."""
    
    __tablename__ = "sis_sync_operations"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    
    # Operation details
    operation_type = Column(String(50), nullable=False)  # 'students', 'enrollments', 'full'
    status = Column(String(20), nullable=False)  # 'pending', 'running', 'completed', 'failed'
    
    # Progress tracking
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    successful_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)
    
    # Metadata
    operation_metadata = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", back_populates="sync_operations")
    
    @hybrid_property
    def duration_seconds(self) -> Optional[int]:
        """Get operation duration in seconds."""
        if not self.started_at or not self.completed_at:
            return None
        return int((self.completed_at - self.started_at).total_seconds())
        
    @hybrid_property
    def progress_percentage(self) -> float:
        """Get operation progress as percentage."""
        if self.total_records == 0:
            return 0.0
        return (self.processed_records / self.total_records) * 100


class SISStudentMapping(Base):
    """Model for mapping local students to SIS student records."""
    
    __tablename__ = "sis_student_mappings"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    local_student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # SIS identifiers
    sis_student_id = Column(String(100), nullable=False)
    sis_student_number = Column(String(50), nullable=True)
    sis_email = Column(String(255), nullable=True)
    sis_state_id = Column(String(50), nullable=True)
    
    # Sync metadata
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_conflicts = Column(JSON, nullable=True)  # Track data conflicts
    
    # Status tracking
    is_active = Column(Boolean, default=True)
    needs_sync = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", back_populates="student_mappings")
    local_student = relationship("User", foreign_keys=[local_student_id])
    
    __table_args__ = (
        UniqueConstraint('integration_id', 'local_student_id', name='_integration_student_uc'),
        UniqueConstraint('integration_id', 'sis_student_id', name='_integration_sis_student_uc'),
        Index('idx_sis_mapping_lookup', integration_id, sis_student_id),
        Index('idx_sis_mapping_sync', integration_id, needs_sync),
    )
    
    def add_conflict(self, field: str, local_value: Any, sis_value: Any) -> None:
        """Add a sync conflict to track data differences."""
        if not self.sync_conflicts:
            self.sync_conflicts = []
            
        conflict = {
            "field": field,
            "local_value": str(local_value),
            "sis_value": str(sis_value),
            "detected_at": datetime.utcnow().isoformat()
        }
        
        # Remove existing conflict for this field
        self.sync_conflicts = [c for c in self.sync_conflicts if c["field"] != field]
        self.sync_conflicts.append(conflict)
        
    def clear_conflicts(self) -> None:
        """Clear all sync conflicts."""
        self.sync_conflicts = None