from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from app.models.attendance import AttendanceStatus


# Student Check-in Schemas
class StudentJoinRequest(BaseModel):
    jwt_token: str = Field(..., description="JWT token from QR code")


class VerificationCodeJoinRequest(BaseModel):
    verification_code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")


class StudentCheckInRequest(BaseModel):
    class_session_id: int
    verification_method: str = Field(..., description="qr_code, verification_code, manual")
    notes: Optional[str] = Field(None, max_length=500)


class StudentJoinResponse(BaseModel):
    success: bool
    message: str
    class_session_id: int
    class_name: str
    join_time: Optional[datetime] = None
    attendance_status: AttendanceStatus
    is_late: bool = False
    late_minutes: int = 0


# Enhanced Attendance Response
class AttendanceResponse(BaseModel):
    id: int
    class_session_id: int
    class_name: str
    subject: Optional[str] = None
    teacher_name: str
    student_name: str
    status: AttendanceStatus
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    verification_method: Optional[str] = None
    is_late: bool = False
    late_minutes: int = 0
    is_manual_override: bool = False
    override_reason: Optional[str] = None
    override_teacher_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# Teacher Override Schemas
class TeacherOverrideRequest(BaseModel):
    student_id: int
    new_status: AttendanceStatus
    reason: str = Field(..., min_length=1, max_length=500)
    notes: Optional[str] = Field(None, max_length=500)


class BulkAttendanceOperation(str, Enum):
    MARK_PRESENT = "mark_present"
    MARK_ABSENT = "mark_absent" 
    MARK_LATE = "mark_late"
    MARK_EXCUSED = "mark_excused"


class BulkAttendanceRequest(BaseModel):
    class_session_id: int
    operation: BulkAttendanceOperation
    student_ids: Optional[List[int]] = None  # If None, apply to all students
    reason: str = Field(..., min_length=1, max_length=500)
    notes: Optional[str] = Field(None, max_length=500)


class BulkAttendanceResponse(BaseModel):
    success: bool
    message: str
    processed_count: int
    failed_count: int
    failed_students: List[Dict[str, Any]] = []


# Audit Trail Schemas
class AttendanceAuditLogResponse(BaseModel):
    id: int
    attendance_record_id: int
    user_name: str
    action: str
    old_status: Optional[AttendanceStatus] = None
    new_status: AttendanceStatus
    reason: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# Statistics and Analytics
class AttendanceStats(BaseModel):
    total_students: int
    present_count: int
    late_count: int
    absent_count: int
    excused_count: int
    attendance_rate: float
    late_rate: float


class StudentAttendancePattern(BaseModel):
    student_id: int
    student_name: str
    total_sessions: int
    present_count: int
    late_count: int
    absent_count: int
    excused_count: int
    consecutive_absences: int
    attendance_rate: float
    is_at_risk: bool = False
    risk_factors: List[str] = []


class ClassAttendanceReport(BaseModel):
    class_session_id: int
    class_name: str
    subject: Optional[str] = None
    teacher_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    stats: AttendanceStats
    records: List[AttendanceResponse]
    patterns: List[StudentAttendancePattern] = []


# Real-time Status Schemas
class AttendanceStatusUpdate(BaseModel):
    class_session_id: int
    student_id: int
    old_status: AttendanceStatus
    new_status: AttendanceStatus
    timestamp: datetime
    updated_by: str  # username
    reason: Optional[str] = None


class ClassAttendanceStatus(BaseModel):
    class_session_id: int
    class_name: str
    total_enrolled: int
    checked_in_count: int
    present_count: int
    late_count: int
    absent_count: int
    excused_count: int
    last_updated: datetime


# Advanced Schemas for Pattern Detection
class AttendancePatternRequest(BaseModel):
    class_session_id: Optional[int] = None
    student_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_sessions: int = Field(default=5, ge=1)


class AttendanceAlert(BaseModel):
    type: str  # "consecutive_absence", "low_attendance", "irregular_pattern"
    severity: str  # "low", "medium", "high"
    student_id: int
    student_name: str
    message: str
    data: Dict[str, Any]
    created_at: datetime


# Creation and Update Schemas
class AttendanceRecordCreate(BaseModel):
    student_id: int
    class_session_id: int
    status: AttendanceStatus = AttendanceStatus.ABSENT
    verification_method: Optional[str] = None
    notes: Optional[str] = None


class AttendanceRecordUpdate(BaseModel):
    status: Optional[AttendanceStatus] = None
    check_out_time: Optional[datetime] = None
    notes: Optional[str] = None