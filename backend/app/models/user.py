from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    TEACHER = "teacher"
    STUDENT = "student"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.STUDENT)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    classes_teaching = relationship("ClassSession", back_populates="teacher")
    attendance_records = relationship("AttendanceRecord", back_populates="student", foreign_keys="[AttendanceRecord.student_id]")
    
    # Pattern analysis relationships
    pattern_analyses = relationship("AttendancePatternAnalysis", back_populates="student")
    student_alerts = relationship("AttendanceAlert", foreign_keys="[AttendanceAlert.student_id]")
    acknowledged_alerts = relationship("AttendanceAlert", foreign_keys="[AttendanceAlert.acknowledged_by]")
    resolved_alerts = relationship("AttendanceAlert", foreign_keys="[AttendanceAlert.resolved_by]")
    assigned_followups = relationship("AttendanceAlert", foreign_keys="[AttendanceAlert.followup_assigned_to]")
    implemented_insights = relationship("AttendanceInsight", foreign_keys="[AttendanceInsight.implemented_by]")