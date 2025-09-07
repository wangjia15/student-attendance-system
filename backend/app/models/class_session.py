from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class Class(Base):
    """Model for classes/courses."""
    __tablename__ = "classes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    subject = Column(String(100), nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # SIS integration
    sis_class_id = Column(String(100), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    teacher = relationship("User", foreign_keys=[teacher_id])


class StudentEnrollment(Base):
    """Model for student enrollment in classes."""
    __tablename__ = "student_enrollments"
    
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    
    # Enrollment details
    enrollment_date = Column(DateTime(timezone=True), server_default=func.now())
    withdrawal_date = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    
    # SIS integration
    sis_enrollment_id = Column(String(100), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    student = relationship("User", foreign_keys=[student_id])
    class_ = relationship("Class", foreign_keys=[class_id])


# Removed SessionStatus enum - using string literals instead


class ClassSession(Base):
    __tablename__ = "class_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    subject = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    
    # Class and teacher relationships
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_ = relationship("Class", foreign_keys=[class_id])
    teacher = relationship("User", back_populates="classes_teaching")
    
    # Session status and tokens
    status = Column(String(10), default="active")
    jwt_token = Column(Text, nullable=False)
    verification_code = Column(String(6), nullable=False, index=True)
    qr_data = Column(Text, nullable=True)
    
    # Session timing
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    
    # Configuration
    allow_late_join = Column(Boolean, default=True)
    require_verification = Column(Boolean, default=True)
    auto_end_minutes = Column(Integer, default=120)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    attendance_records = relationship("AttendanceRecord", back_populates="class_session", cascade="all, delete-orphan")
    attendance_alerts = relationship("AttendanceAlert", back_populates="class_session")
    
    @property
    def class_name(self) -> str:
        """Get class name for analytics compatibility."""
        return self.name