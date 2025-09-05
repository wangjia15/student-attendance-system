"""
FERPA Compliance Data Models

This module defines SQLAlchemy models for FERPA compliance including:
- Student consent management
- Data access logging
- Data retention policies
- Compliance audit trails
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from datetime import datetime, timedelta

from app.core.database import Base


class ConsentType(str, enum.Enum):
    """Types of consent for data sharing"""
    DIRECTORY_INFORMATION = "directory_information"
    ACADEMIC_RECORDS = "academic_records"
    ATTENDANCE_RECORDS = "attendance_records"
    DISCIPLINARY_RECORDS = "disciplinary_records"
    HEALTH_RECORDS = "health_records"
    THIRD_PARTY_SHARING = "third_party_sharing"
    RESEARCH_PARTICIPATION = "research_participation"
    MARKETING_COMMUNICATIONS = "marketing_communications"


class ConsentStatus(str, enum.Enum):
    """Status of consent"""
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    PENDING = "pending"


class DataAccessReason(str, enum.Enum):
    """Legitimate educational interests for data access"""
    EDUCATIONAL_INSTRUCTION = "educational_instruction"
    STUDENT_SUPPORT = "student_support"
    ACADEMIC_ADVISING = "academic_advising"
    DISCIPLINARY_ACTION = "disciplinary_action"
    SAFETY_EMERGENCY = "safety_emergency"
    COMPLIANCE_AUDIT = "compliance_audit"
    LEGITIMATE_RESEARCH = "legitimate_research"
    COURT_ORDER = "court_order"
    DIRECTORY_REQUEST = "directory_request"
    PARENT_REQUEST = "parent_request"


class DataRetentionCategory(str, enum.Enum):
    """Categories for data retention policies"""
    ATTENDANCE_RECORDS = "attendance_records"
    ACADEMIC_RECORDS = "academic_records"
    DISCIPLINARY_RECORDS = "disciplinary_records"
    COMMUNICATION_LOGS = "communication_logs"
    AUDIT_LOGS = "audit_logs"
    CONSENT_RECORDS = "consent_records"
    EMERGENCY_CONTACTS = "emergency_contacts"
    HEALTH_INFORMATION = "health_information"


class StudentConsent(Base):
    """Model for tracking student/parent consent for data sharing"""
    __tablename__ = "student_consents"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # For minors
    granted_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Who granted consent
    
    # Consent details
    consent_type = Column(SQLEnum(ConsentType), nullable=False)
    status = Column(SQLEnum(ConsentStatus), default=ConsentStatus.PENDING)
    
    # Consent scope and limitations
    purpose_description = Column(Text, nullable=False)
    data_categories = Column(Text, nullable=True)  # JSON array of data types
    recipient_organizations = Column(Text, nullable=True)  # JSON array
    
    # Time constraints
    effective_date = Column(DateTime(timezone=True), nullable=False)
    expiration_date = Column(DateTime(timezone=True), nullable=True)
    
    # Legal basis
    legal_basis = Column(String(200), nullable=True)
    is_required_by_law = Column(Boolean, default=False)
    
    # Metadata
    consent_method = Column(String(50), nullable=True)  # "digital_signature", "written_form", "verbal"
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    consent_document_path = Column(String(500), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    student = relationship("User", foreign_keys=[student_id])
    parent = relationship("User", foreign_keys=[parent_id])
    granted_by = relationship("User", foreign_keys=[granted_by_id])


class DataAccessLog(Base):
    """Model for logging all access to student educational records"""
    __tablename__ = "data_access_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Access details
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # What was accessed
    data_type = Column(String(100), nullable=False)  # e.g., "attendance_record", "grade"
    record_id = Column(Integer, nullable=True)  # ID of specific record accessed
    table_name = Column(String(100), nullable=True)
    
    # Access context
    access_reason = Column(SQLEnum(DataAccessReason), nullable=False)
    purpose_description = Column(Text, nullable=False)
    
    # Technical details
    action = Column(String(50), nullable=False)  # "view", "create", "update", "delete", "export"
    endpoint = Column(String(200), nullable=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500), nullable=True)
    session_id = Column(String(255), nullable=True)
    
    # Privacy protections
    data_anonymized = Column(Boolean, default=False)
    consent_verified = Column(Boolean, default=False)
    legitimate_interest_basis = Column(Text, nullable=True)
    
    # Timestamps
    access_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    accessing_user = relationship("User", foreign_keys=[user_id])
    student = relationship("User", foreign_keys=[student_id])


class DataRetentionPolicy(Base):
    """Model for defining data retention policies"""
    __tablename__ = "data_retention_policies"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Policy identification
    policy_name = Column(String(200), nullable=False, unique=True)
    category = Column(SQLEnum(DataRetentionCategory), nullable=False)
    
    # Retention rules
    retention_period_years = Column(Integer, nullable=False)
    retention_period_months = Column(Integer, default=0)
    retention_period_days = Column(Integer, default=0)
    
    # Policy details
    description = Column(Text, nullable=False)
    legal_basis = Column(Text, nullable=False)
    exceptions = Column(Text, nullable=True)  # JSON array of exception conditions
    
    # Automated processing
    auto_purge_enabled = Column(Boolean, default=True)
    warning_period_days = Column(Integer, default=30)  # Warn before purging
    
    # Policy status
    is_active = Column(Boolean, default=True)
    requires_manual_review = Column(Boolean, default=False)
    
    # Timestamps
    effective_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships with data purge schedules
    purge_schedules = relationship("DataPurgeSchedule", back_populates="policy")


class DataPurgeSchedule(Base):
    """Model for tracking scheduled data purges"""
    __tablename__ = "data_purge_schedules"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Policy reference
    policy_id = Column(Integer, ForeignKey("data_retention_policies.id"), nullable=False)
    
    # Record identification
    table_name = Column(String(100), nullable=False)
    record_id = Column(Integer, nullable=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Purge scheduling
    scheduled_purge_date = Column(DateTime(timezone=True), nullable=False)
    warning_sent_date = Column(DateTime(timezone=True), nullable=True)
    actual_purge_date = Column(DateTime(timezone=True), nullable=True)
    
    # Status and metadata
    status = Column(String(50), default="scheduled")  # scheduled, warned, purged, exempted
    exemption_reason = Column(Text, nullable=True)
    exemption_granted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    exemption_expires = Column(DateTime(timezone=True), nullable=True)
    
    # Audit trail
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    policy = relationship("DataRetentionPolicy", back_populates="purge_schedules")
    student = relationship("User", foreign_keys=[student_id])
    exemption_grantor = relationship("User", foreign_keys=[exemption_granted_by])


class ComplianceAuditLog(Base):
    """Model for comprehensive compliance audit logging"""
    __tablename__ = "compliance_audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Audit event identification
    event_type = Column(String(100), nullable=False)  # "consent_granted", "data_accessed", "policy_violation"
    event_category = Column(String(50), nullable=False)  # "privacy", "consent", "retention", "access"
    severity_level = Column(String(20), default="info")  # "info", "warning", "error", "critical"
    
    # Context
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    affected_student_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Event details
    description = Column(Text, nullable=False)
    technical_details = Column(Text, nullable=True)  # JSON object
    compliance_impact = Column(Text, nullable=True)
    
    # Resolution tracking
    requires_action = Column(Boolean, default=False)
    action_taken = Column(Text, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    affected_student = relationship("User", foreign_keys=[affected_student_id])
    resolver = relationship("User", foreign_keys=[resolved_by])


class PrivacySettings(Base):
    """Model for student privacy settings and preferences"""
    __tablename__ = "privacy_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Student reference
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Directory information settings
    directory_info_public = Column(Boolean, default=False)
    allow_name_disclosure = Column(Boolean, default=False)
    allow_photo_disclosure = Column(Boolean, default=False)
    allow_contact_disclosure = Column(Boolean, default=False)
    allow_academic_info_disclosure = Column(Boolean, default=False)
    
    # Communication preferences
    allow_progress_notifications = Column(Boolean, default=True)
    allow_attendance_notifications = Column(Boolean, default=True)
    allow_emergency_contact = Column(Boolean, default=True)
    
    # Data sharing preferences
    opt_in_research = Column(Boolean, default=False)
    opt_in_analytics = Column(Boolean, default=False)
    opt_in_third_party_services = Column(Boolean, default=False)
    
    # Parental controls (for minors)
    parental_approval_required = Column(Boolean, default=False)
    parent_email_cc = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    student = relationship("User", foreign_keys=[student_id])