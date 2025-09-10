from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum, Index
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
    
    # Database indexes for optimized queries
    __table_args__ = (
        # Teacher's classes - common query pattern
        Index('idx_class_teacher_created', 'teacher_id', 'created_at'),
        # SIS integration lookups
        Index('idx_class_sis_id', 'sis_class_id'),
    )


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
    
    # Database indexes for optimized queries
    __table_args__ = (
        # Student's enrollments - common query pattern
        Index('idx_enrollment_student_active', 'student_id', 'is_active'),
        # Class enrollments - finding all students in a class
        Index('idx_enrollment_class_active', 'class_id', 'is_active'),
        # Unique enrollment constraint
        Index('idx_enrollment_unique_student_class', 'student_id', 'class_id', unique=True),
        # SIS integration lookups
        Index('idx_enrollment_sis_id', 'sis_enrollment_id'),
    )


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
    
    # Enrolled students - join through attendance records to get unique students who joined this session
    def get_enrolled_students(self, db_session):
        """Get unique students who have joined this class session."""
        from app.models.user import User
        from app.models.attendance import AttendanceRecord
        from sqlalchemy import select, distinct
        
        # Use direct query to avoid relationship join ambiguity
        result = db_session.execute(
            select(User).where(
                User.id.in_(
                    select(distinct(AttendanceRecord.student_id)).where(
                        AttendanceRecord.class_session_id == self.id
                    )
                )
            )
        )
        return result.scalars().all()
    
    @property
    def class_name(self) -> str:
        """Get class name for analytics compatibility."""
        return self.name
    
    # Database indexes for optimized queries
    __table_args__ = (
        # Teacher's active sessions - most common query pattern
        Index('idx_class_session_teacher_status', 'teacher_id', 'status'),
        # Time-based queries for session management
        Index('idx_class_session_start_time', 'start_time'),
        # Class-based session history
        Index('idx_class_session_class_created', 'class_id', 'created_at'),
        # Active sessions within time range
        Index('idx_class_session_status_time', 'status', 'start_time', 'end_time'),
    )