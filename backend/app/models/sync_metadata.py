"""
SQLAlchemy models for sync metadata and bidirectional synchronization tracking.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON, 
    ForeignKey, Index, UniqueConstraint, Enum as SQLEnum, Float
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
import enum
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.core.database import Base


class SyncDirection(str, enum.Enum):
    """Direction of synchronization."""
    TO_SIS = "to_sis"
    FROM_SIS = "from_sis"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, enum.Enum):
    """Status of sync operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class SyncType(str, enum.Enum):
    """Type of synchronization."""
    REAL_TIME = "real_time"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    INITIAL = "initial"


class DataType(str, enum.Enum):
    """Type of data being synchronized."""
    STUDENT_DEMOGRAPHICS = "student_demographics"
    ENROLLMENT = "enrollment"
    GRADES = "grades"
    ATTENDANCE = "attendance"
    PARTICIPATION = "participation"
    COURSE_INFO = "course_info"


class SyncSchedule(Base):
    """Model for managing sync schedules."""
    
    __tablename__ = "sync_schedules"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    
    # Schedule configuration
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    data_types = Column(JSON, nullable=False)  # List of DataType values
    sync_direction = Column(SQLEnum(SyncDirection), nullable=False)
    
    # Schedule timing
    is_enabled = Column(Boolean, default=True)
    schedule_type = Column(String(50), nullable=False)  # 'real_time', 'hourly', 'daily', 'weekly'
    cron_expression = Column(String(100), nullable=True)  # For complex schedules
    
    # Real-time settings
    real_time_enabled = Column(Boolean, default=False)
    webhook_url = Column(String(500), nullable=True)
    
    # Schedule times
    hourly_at_minute = Column(Integer, nullable=True)  # 0-59
    daily_at_time = Column(String(5), nullable=True)  # "HH:MM"
    weekly_days = Column(JSON, nullable=True)  # List of weekday numbers (0=Monday)
    
    # Configuration
    batch_size = Column(Integer, default=100)
    timeout_minutes = Column(Integer, default=30)
    retry_attempts = Column(Integer, default=3)
    retry_delay_minutes = Column(Integer, default=5)
    
    # Status
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", foreign_keys=[integration_id])
    sync_operations = relationship("SyncOperation", back_populates="schedule")
    
    @hybrid_property
    def is_healthy(self) -> bool:
        """Check if schedule is healthy."""
        return self.is_enabled and self.consecutive_failures < 3


class SyncOperation(Base):
    """Model for tracking individual sync operations."""
    
    __tablename__ = "sync_operations"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("sync_schedules.id"), nullable=True)
    
    # Operation details
    operation_id = Column(String(50), unique=True, index=True, nullable=False)  # UUID
    data_type = Column(SQLEnum(DataType), nullable=False)
    sync_direction = Column(SQLEnum(SyncDirection), nullable=False)
    sync_type = Column(SQLEnum(SyncType), nullable=False)
    
    # Status and progress
    status = Column(SQLEnum(SyncStatus), default=SyncStatus.PENDING)
    progress_percentage = Column(Float, default=0.0)
    
    # Record counts
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    successful_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    skipped_records = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Metadata
    sync_metadata = Column(JSON, nullable=True)
    last_sync_token = Column(String(500), nullable=True)  # For incremental sync
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", foreign_keys=[integration_id])
    schedule = relationship("SyncSchedule", back_populates="sync_operations")
    record_changes = relationship("SyncRecordChange", back_populates="sync_operation", cascade="all, delete-orphan")
    conflicts = relationship("SyncConflict", back_populates="sync_operation", cascade="all, delete-orphan")
    
    @hybrid_property
    def duration_seconds(self) -> Optional[int]:
        """Get operation duration in seconds."""
        if not self.started_at or not self.completed_at:
            return None
        return int((self.completed_at - self.started_at).total_seconds())
    
    @hybrid_property
    def is_running(self) -> bool:
        """Check if operation is currently running."""
        return self.status == SyncStatus.RUNNING
    
    @hybrid_property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.processed_records == 0:
            return 0.0
        return (self.successful_records / self.processed_records) * 100
    
    def update_progress(self, processed: int, successful: int, failed: int, skipped: int = 0) -> None:
        """Update operation progress."""
        self.processed_records = processed
        self.successful_records = successful
        self.failed_records = failed
        self.skipped_records = skipped
        
        if self.total_records and self.total_records > 0:
            self.progress_percentage = (processed / self.total_records) * 100
    
    def mark_completed(self, success: bool = True) -> None:
        """Mark operation as completed."""
        self.completed_at = func.now()
        if success and self.failed_records == 0:
            self.status = SyncStatus.COMPLETED
        elif self.successful_records > 0:
            self.status = SyncStatus.PARTIAL
        else:
            self.status = SyncStatus.FAILED
        self.progress_percentage = 100.0


class SyncRecordChange(Base):
    """Model for tracking individual record changes during sync."""
    
    __tablename__ = "sync_record_changes"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_operation_id = Column(Integer, ForeignKey("sync_operations.id"), nullable=False)
    
    # Record identification
    record_type = Column(String(50), nullable=False)  # 'student', 'enrollment', etc.
    local_record_id = Column(String(100), nullable=True)  # Local system ID
    external_record_id = Column(String(100), nullable=False)  # SIS system ID
    
    # Change details
    change_type = Column(String(20), nullable=False)  # 'create', 'update', 'delete', 'skip'
    field_changes = Column(JSON, nullable=True)  # Detailed field-level changes
    
    # Before and after data (for rollback/audit)
    before_data = Column(JSON, nullable=True)
    after_data = Column(JSON, nullable=True)
    
    # Status
    was_successful = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    sync_operation = relationship("SyncOperation", back_populates="record_changes")
    
    __table_args__ = (
        Index('idx_sync_record_change_lookup', sync_operation_id, record_type, external_record_id),
    )


class SyncConflict(Base):
    """Model for tracking and resolving sync conflicts."""
    
    __tablename__ = "sync_conflicts"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_operation_id = Column(Integer, ForeignKey("sync_operations.id"), nullable=False)
    
    # Conflict identification
    record_type = Column(String(50), nullable=False)
    local_record_id = Column(String(100), nullable=True)
    external_record_id = Column(String(100), nullable=False)
    conflict_type = Column(String(50), nullable=False)  # 'data_mismatch', 'timestamp', 'deleted', etc.
    
    # Conflict data
    local_data = Column(JSON, nullable=False)  # Local system data
    external_data = Column(JSON, nullable=False)  # SIS system data
    conflicting_fields = Column(JSON, nullable=False)  # List of conflicting field names
    
    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolution_strategy = Column(String(50), nullable=True)  # 'local_wins', 'external_wins', 'merge', 'manual'
    resolved_data = Column(JSON, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Administrative override
    requires_admin_review = Column(Boolean, default=False)
    admin_notes = Column(Text, nullable=True)
    
    # Timestamps
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    sync_operation = relationship("SyncOperation", back_populates="conflicts")
    resolver = relationship("User", foreign_keys=[resolved_by])
    
    __table_args__ = (
        Index('idx_sync_conflict_unresolved', sync_operation_id, is_resolved),
        Index('idx_sync_conflict_admin_review', requires_admin_review, is_resolved),
    )
    
    def resolve(self, strategy: str, resolved_data: Dict[str, Any], user_id: int, admin_override: bool = False) -> None:
        """Resolve the conflict."""
        self.resolution_strategy = strategy
        self.resolved_data = resolved_data
        self.resolved_by = user_id
        self.resolved_at = func.now()
        self.is_resolved = True
        
        if admin_override:
            self.requires_admin_review = False


class DataValidationRule(Base):
    """Model for data validation rules applied during sync."""
    
    __tablename__ = "data_validation_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("sis_integrations.id"), nullable=False)
    
    # Rule configuration
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    data_type = Column(SQLEnum(DataType), nullable=False)
    field_name = Column(String(100), nullable=False)
    
    # Validation logic
    rule_type = Column(String(50), nullable=False)  # 'required', 'format', 'range', 'custom'
    rule_config = Column(JSON, nullable=False)  # Rule-specific configuration
    
    # Actions on validation failure
    on_failure_action = Column(String(50), default="skip")  # 'skip', 'fail', 'warn', 'fix'
    fix_strategy = Column(String(50), nullable=True)  # How to fix if possible
    
    # Status
    is_enabled = Column(Boolean, default=True)
    failure_count = Column(Integer, default=0)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    integration = relationship("SISIntegration", foreign_keys=[integration_id])
    validation_results = relationship("ValidationResult", back_populates="validation_rule", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('integration_id', 'name', name='_integration_rule_name_uc'),
        Index('idx_validation_rule_lookup', integration_id, data_type, field_name),
    )


class ValidationResult(Base):
    """Model for tracking validation results."""
    
    __tablename__ = "validation_results"
    
    id = Column(Integer, primary_key=True, index=True)
    validation_rule_id = Column(Integer, ForeignKey("data_validation_rules.id"), nullable=False)
    sync_operation_id = Column(Integer, ForeignKey("sync_operations.id"), nullable=False)
    
    # Record identification
    record_type = Column(String(50), nullable=False)
    record_id = Column(String(100), nullable=False)
    
    # Validation result
    is_valid = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    field_value = Column(Text, nullable=True)  # The value that was validated
    
    # Actions taken
    action_taken = Column(String(50), nullable=True)  # What action was taken
    fixed_value = Column(Text, nullable=True)  # Value after fixing
    
    # Timestamps
    validated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    validation_rule = relationship("DataValidationRule", back_populates="validation_results")
    sync_operation = relationship("SyncOperation", foreign_keys=[sync_operation_id])
    
    __table_args__ = (
        Index('idx_validation_result_lookup', sync_operation_id, validation_rule_id),
        Index('idx_validation_result_failed', is_valid, validated_at),
    )


class HistoricalData(Base):
    """Model for preserving historical data during sync operations."""
    
    __tablename__ = "historical_data"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_operation_id = Column(Integer, ForeignKey("sync_operations.id"), nullable=False)
    
    # Record identification
    record_type = Column(String(50), nullable=False)
    record_id = Column(String(100), nullable=False)
    
    # Historical data
    data_snapshot = Column(JSON, nullable=False)  # Complete record at time of change
    change_type = Column(String(20), nullable=False)  # 'before_update', 'before_delete'
    
    # Metadata
    sync_direction = Column(SQLEnum(SyncDirection), nullable=False)
    source_system = Column(String(50), nullable=False)  # 'local', 'sis'
    
    # Retention
    retention_days = Column(Integer, default=365)  # How long to keep this data
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    archived_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    sync_operation = relationship("SyncOperation", foreign_keys=[sync_operation_id])
    
    __table_args__ = (
        Index('idx_historical_data_lookup', record_type, record_id, archived_at),
        Index('idx_historical_data_expiry', expires_at),
    )
    
    def set_expiry(self, retention_days: int = None) -> None:
        """Set expiry date based on retention policy."""
        days = retention_days or self.retention_days
        self.expires_at = datetime.utcnow() + timedelta(days=days)