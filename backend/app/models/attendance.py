from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    EXCUSED = "excused"


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False)
    
    # Attendance details
    status = Column(SQLEnum(AttendanceStatus), default=AttendanceStatus.ABSENT)
    check_in_time = Column(DateTime(timezone=True), nullable=True)
    check_out_time = Column(DateTime(timezone=True), nullable=True)
    
    # State management
    is_manual_override = Column(Boolean, default=False)
    override_by_teacher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    override_reason = Column(String(500), nullable=True)
    
    # Additional info
    verification_method = Column(String(50), nullable=True)  # "qr_code", "manual", "verification_code", "teacher_override"
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    notes = Column(String(500), nullable=True)
    
    # Late detection
    is_late = Column(Boolean, default=False)
    late_minutes = Column(Integer, default=0)
    grace_period_used = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    student = relationship("User", back_populates="attendance_records", foreign_keys=[student_id], overlaps="override_teacher")
    class_session = relationship("ClassSession", back_populates="attendance_records")
    override_teacher = relationship("User", foreign_keys=[override_by_teacher_id], overlaps="student")


class AttendanceAuditLog(Base):
    __tablename__ = "attendance_audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Who made the change
    
    # Audit details
    action = Column(String(50), nullable=False)  # "create", "update_status", "override", "bulk_update"
    old_status = Column(SQLEnum(AttendanceStatus), nullable=True)
    new_status = Column(SQLEnum(AttendanceStatus), nullable=False)
    reason = Column(String(500), nullable=True)
    
    # Additional context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    audit_metadata = Column(Text, nullable=True)  # JSON string for additional data
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    attendance_record = relationship("AttendanceRecord")
    user = relationship("User")