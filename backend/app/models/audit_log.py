"""
Security Audit Log Model

Immutable audit trail storage with integrity verification for security events.
Works alongside FERPA compliance audit logging.
"""

import hashlib
import json
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import validates
import uuid

from app.core.database import Base


class SecurityAuditLog(Base):
    """
    Immutable security audit log entries with integrity verification.
    
    This model stores all security-related events and user actions with
    cryptographic integrity verification to ensure tamper-proof logging.
    """
    __tablename__ = "security_audit_logs"
    
    # Primary identification
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    sequence_number = Column(Integer, nullable=False, index=True)  # Sequential numbering
    
    # Event classification
    event_type = Column(String(50), nullable=False, index=True)  # LOGIN, LOGOUT, DATA_ACCESS, etc.
    event_category = Column(String(30), nullable=False, index=True)  # AUTHENTICATION, AUTHORIZATION, DATA, SYSTEM
    severity = Column(String(20), nullable=False, default="INFO")  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    
    # User and session information
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(255), nullable=True)
    session_id = Column(String(255), nullable=True, index=True)
    
    # Request details
    ip_address = Column(String(45), nullable=True, index=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    endpoint = Column(String(255), nullable=True)
    method = Column(String(10), nullable=True)
    
    # Event data
    event_data = Column(JSONB, nullable=True)  # Structured event data
    message = Column(Text, nullable=False)  # Human-readable message
    
    # Timing
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Security and integrity
    is_suspicious = Column(Boolean, default=False, index=True)
    risk_score = Column(Integer, default=0)  # 0-100 risk assessment
    integrity_hash = Column(String(64), nullable=False)  # SHA-256 hash
    previous_hash = Column(String(64), nullable=True)  # Chain integrity
    
    # System metadata
    source_system = Column(String(50), default="attendance_system")
    correlation_id = Column(String(255), nullable=True, index=True)  # Link related events
    
    # Create indexes for common queries
    __table_args__ = (
        Index('idx_security_audit_timestamp_user', 'timestamp', 'user_id'),
        Index('idx_security_audit_event_severity', 'event_type', 'severity'),
        Index('idx_security_audit_suspicious', 'is_suspicious', 'timestamp'),
        Index('idx_security_audit_ip_time', 'ip_address', 'timestamp'),
    )
    
    @validates('event_type', 'event_category', 'severity')
    def validate_enum_fields(self, key, value):
        """Validate enum-like fields."""
        if key == 'event_type':
            valid_types = {
                'LOGIN_SUCCESS', 'LOGIN_FAILURE', 'LOGOUT', 'PASSWORD_CHANGE',
                'MFA_SUCCESS', 'MFA_FAILURE', 'ACCOUNT_LOCKED', 'ACCOUNT_UNLOCKED',
                'DATA_ACCESS', 'DATA_EXPORT', 'DATA_IMPORT', 'DATA_DELETE',
                'PERMISSION_GRANTED', 'PERMISSION_DENIED', 'ROLE_CHANGE',
                'SYSTEM_ERROR', 'SECURITY_VIOLATION', 'ANOMALY_DETECTED',
                'INCIDENT_CREATED', 'INCIDENT_RESOLVED'
            }
            if value not in valid_types:
                raise ValueError(f"Invalid event_type: {value}")
                
        elif key == 'event_category':
            valid_categories = {
                'AUTHENTICATION', 'AUTHORIZATION', 'DATA', 'SYSTEM', 
                'SECURITY', 'COMPLIANCE', 'INCIDENT'
            }
            if value not in valid_categories:
                raise ValueError(f"Invalid event_category: {value}")
                
        elif key == 'severity':
            valid_severities = {'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'}
            if value not in valid_severities:
                raise ValueError(f"Invalid severity: {value}")
                
        return value
    
    def calculate_integrity_hash(self) -> str:
        """
        Calculate SHA-256 integrity hash for this log entry.
        Includes all critical fields to detect tampering.
        """
        # Create deterministic string representation
        hash_data = {
            'sequence_number': self.sequence_number,
            'event_type': self.event_type,
            'event_category': self.event_category,
            'severity': self.severity,
            'user_id': self.user_id,
            'username': self.username,
            'ip_address': self.ip_address,
            'endpoint': self.endpoint,
            'method': self.method,
            'event_data': self.event_data,
            'message': self.message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'previous_hash': self.previous_hash
        }
        
        # Convert to JSON string with sorted keys for consistency
        hash_string = json.dumps(hash_data, sort_keys=True, default=str)
        
        # Return SHA-256 hash
        return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()
    
    def verify_integrity(self) -> bool:
        """Verify the integrity hash of this log entry."""
        expected_hash = self.calculate_integrity_hash()
        return expected_hash == self.integrity_hash
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': str(self.id),
            'sequence_number': self.sequence_number,
            'event_type': self.event_type,
            'event_category': self.event_category,
            'severity': self.severity,
            'user_id': self.user_id,
            'username': self.username,
            'session_id': self.session_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'endpoint': self.endpoint,
            'method': self.method,
            'event_data': self.event_data,
            'message': self.message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'is_suspicious': self.is_suspicious,
            'risk_score': self.risk_score,
            'source_system': self.source_system,
            'correlation_id': self.correlation_id
        }


class SecurityIncident(Base):
    """
    Security incident tracking for automated response.
    """
    __tablename__ = "security_incidents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Incident classification
    incident_type = Column(String(50), nullable=False, index=True)  # BRUTE_FORCE, ANOMALY, etc.
    severity = Column(String(20), nullable=False, index=True)  # CRITICAL, HIGH, MEDIUM, LOW
    status = Column(String(20), nullable=False, default="OPEN", index=True)  # OPEN, INVESTIGATING, RESOLVED
    
    # Incident details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Affected entities
    affected_user_id = Column(Integer, nullable=True, index=True)
    affected_ip_address = Column(String(45), nullable=True, index=True)
    affected_resource = Column(String(255), nullable=True)
    
    # Response tracking
    auto_response_actions = Column(JSONB, nullable=True)  # Automated actions taken
    manual_response_notes = Column(Text, nullable=True)
    
    # Timing
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    first_event_at = Column(DateTime, nullable=True)
    last_event_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    
    # Metrics
    event_count = Column(Integer, default=1)
    risk_score = Column(Integer, default=0)  # 0-100
    
    # System metadata
    correlation_id = Column(String(255), nullable=False, index=True)
    created_by = Column(String(50), default="system")
    
    __table_args__ = (
        Index('idx_security_incidents_status_severity', 'status', 'severity'),
        Index('idx_security_incidents_detected_resolved', 'detected_at', 'resolved_at'),
    )
    
    @validates('incident_type', 'severity', 'status')
    def validate_enum_fields(self, key, value):
        """Validate enum-like fields."""
        if key == 'incident_type':
            valid_types = {
                'BRUTE_FORCE_LOGIN', 'ACCOUNT_TAKEOVER', 'SUSPICIOUS_ACCESS_PATTERN',
                'DATA_EXFILTRATION_ATTEMPT', 'PRIVILEGE_ESCALATION', 'SYSTEM_INTRUSION',
                'MALWARE_DETECTION', 'PHISHING_ATTEMPT', 'ANOMALY_DETECTION',
                'POLICY_VIOLATION', 'COMPLIANCE_BREACH', 'UNAUTHORIZED_ACCESS'
            }
            if value not in valid_types:
                raise ValueError(f"Invalid incident_type: {value}")
                
        elif key == 'severity':
            valid_severities = {'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'}
            if value not in valid_severities:
                raise ValueError(f"Invalid severity: {value}")
                
        elif key == 'status':
            valid_statuses = {'OPEN', 'INVESTIGATING', 'RESOLVED', 'FALSE_POSITIVE'}
            if value not in valid_statuses:
                raise ValueError(f"Invalid status: {value}")
                
        return value


class LoginAttempt(Base):
    """
    Track login attempts for security analysis and lockout mechanisms.
    """
    __tablename__ = "login_attempts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Attempt details
    username = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    user_agent = Column(Text, nullable=True)
    
    # Result
    success = Column(Boolean, nullable=False, index=True)
    failure_reason = Column(String(100), nullable=True)  # INVALID_CREDENTIALS, ACCOUNT_LOCKED, etc.
    
    # Timing
    attempted_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Security analysis
    is_suspicious = Column(Boolean, default=False, index=True)
    risk_factors = Column(JSONB, nullable=True)  # Geographic, timing, pattern analysis
    
    # Session tracking
    session_id = Column(String(255), nullable=True)
    correlation_id = Column(String(255), nullable=True, index=True)
    
    __table_args__ = (
        Index('idx_login_attempts_username_time', 'username', 'attempted_at'),
        Index('idx_login_attempts_ip_time', 'ip_address', 'attempted_at'),
        Index('idx_login_attempts_success_time', 'success', 'attempted_at'),
    )
    
    @validates('failure_reason')
    def validate_failure_reason(self, key, value):
        """Validate failure reason."""
        if value is not None:
            valid_reasons = {
                'INVALID_CREDENTIALS', 'ACCOUNT_LOCKED', 'ACCOUNT_DISABLED',
                'MFA_REQUIRED', 'MFA_FAILED', 'RATE_LIMITED', 'IP_BLOCKED',
                'SUSPICIOUS_ACTIVITY', 'SYSTEM_ERROR'
            }
            if value not in valid_reasons:
                raise ValueError(f"Invalid failure_reason: {value}")
        return value


class UserSession(Base):
    """
    Track active user sessions for security monitoring.
    """
    __tablename__ = "user_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    session_id = Column(String(255), nullable=False, unique=True, index=True)
    
    # User information
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(255), nullable=False)
    
    # Session details
    ip_address = Column(String(45), nullable=False, index=True)
    user_agent = Column(Text, nullable=True)
    
    # Timing
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_activity = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, index=True)
    end_reason = Column(String(50), nullable=True)  # LOGOUT, TIMEOUT, FORCED, etc.
    
    # Security flags
    is_suspicious = Column(Boolean, default=False, index=True)
    requires_mfa = Column(Boolean, default=False)
    mfa_verified = Column(Boolean, default=False)
    
    __table_args__ = (
        Index('idx_user_sessions_user_active', 'user_id', 'is_active'),
        Index('idx_user_sessions_expires', 'expires_at', 'is_active'),
    )