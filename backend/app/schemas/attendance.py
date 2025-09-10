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


# WebSocket Message Schemas
class WebSocketMessageBase(BaseModel):
    """Base schema for all WebSocket messages."""
    type: str = Field(..., description="Message type identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    class_id: str = Field(..., description="Class session ID for message routing")


class AttendanceCreatedMessage(WebSocketMessageBase):
    """Message sent when a new attendance record is created."""
    type: str = Field(default="attendance_created", const=True)
    data: Dict[str, Any] = Field(..., description="Attendance record data")
    student_id: int = Field(..., description="Student ID for authorization")
    student_name: str = Field(..., description="Student name for display")
    status: AttendanceStatus = Field(..., description="New attendance status")
    verification_method: Optional[str] = Field(None, description="How attendance was recorded")
    is_late: bool = Field(default=False, description="Whether student was late")
    late_minutes: int = Field(default=0, description="Minutes late if applicable")


class AttendanceUpdatedMessage(WebSocketMessageBase):
    """Message sent when an attendance record is updated."""
    type: str = Field(default="attendance_updated", const=True)
    data: Dict[str, Any] = Field(..., description="Updated attendance record data")
    attendance_id: int = Field(..., description="Attendance record ID")
    student_id: int = Field(..., description="Student ID for authorization")
    student_name: str = Field(..., description="Student name for display")
    old_status: AttendanceStatus = Field(..., description="Previous attendance status")
    new_status: AttendanceStatus = Field(..., description="New attendance status")
    updated_by: str = Field(..., description="User who made the update")
    reason: Optional[str] = Field(None, description="Reason for the update")
    is_manual_override: bool = Field(default=False, description="Whether this was a manual override")


class StudentJoinedClassMessage(WebSocketMessageBase):
    """Message sent when a student successfully joins a class."""
    type: str = Field(default="student_joined_class", const=True)
    data: Dict[str, Any] = Field(..., description="Join event data")
    student_id: int = Field(..., description="Student ID for authorization")
    student_name: str = Field(..., description="Student name for display")
    join_time: datetime = Field(..., description="When the student joined")
    verification_method: str = Field(..., description="How the student joined (qr_code, verification_code, manual)")
    attendance_status: AttendanceStatus = Field(..., description="Initial attendance status")
    is_late: bool = Field(default=False, description="Whether student was late")
    late_minutes: int = Field(default=0, description="Minutes late if applicable")


class AttendanceStateChangedMessage(WebSocketMessageBase):
    """General message for any attendance state changes."""
    type: str = Field(default="attendance_state_changed", const=True)
    data: Dict[str, Any] = Field(..., description="State change data")
    change_type: str = Field(..., description="Type of change (created, updated, bulk_update, etc.)")
    affected_students: List[int] = Field(..., description="List of affected student IDs")
    stats: Optional[Dict[str, int]] = Field(None, description="Updated class attendance statistics")
    updated_by: str = Field(..., description="User who triggered the change")


class BulkAttendanceUpdateMessage(WebSocketMessageBase):
    """Message sent when bulk attendance operations are performed."""
    type: str = Field(default="bulk_attendance_update", const=True)
    data: Dict[str, Any] = Field(..., description="Bulk update data")
    operation: str = Field(..., description="Type of bulk operation performed")
    affected_students: List[Dict[str, Any]] = Field(..., description="List of affected students with their new status")
    processed_count: int = Field(..., description="Number of records processed")
    updated_by: str = Field(..., description="Teacher who performed the bulk update")
    reason: str = Field(..., description="Reason for the bulk update")


class AttendanceStatsUpdateMessage(WebSocketMessageBase):
    """Message sent when attendance statistics need to be updated."""
    type: str = Field(default="attendance_stats_update", const=True)
    data: Dict[str, Any] = Field(..., description="Updated statistics data")
    stats: AttendanceStats = Field(..., description="Current attendance statistics")
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


# WebSocket Authorization Helpers
class WebSocketAuthContext(BaseModel):
    """Context for WebSocket message authorization."""
    user_id: str = Field(..., description="User making the request")
    user_type: str = Field(..., description="Type of user (teacher, student, admin)")
    class_id: str = Field(..., description="Class session ID")
    is_teacher: bool = Field(default=False, description="Whether user is a teacher for this class")
    is_student_in_class: bool = Field(default=False, description="Whether user is a student in this class")
    can_view_all_students: bool = Field(default=False, description="Whether user can view all student data")


def authorize_attendance_message(message: WebSocketMessageBase, auth_context: WebSocketAuthContext) -> bool:
    """
    Authorize WebSocket attendance messages based on user permissions.
    
    Args:
        message: The WebSocket message to authorize
        auth_context: The authorization context for the user
    
    Returns:
        bool: True if user is authorized to receive this message
    """
    # Teachers can see all attendance updates for their classes
    if auth_context.is_teacher and auth_context.class_id == message.class_id:
        return True
    
    # Students can only see their own attendance updates
    if auth_context.user_type == "student" and auth_context.is_student_in_class:
        # For student-specific messages, check if it's about them
        if hasattr(message, 'student_id'):
            return str(message.student_id) == auth_context.user_id
        
        # For general messages, students can see class-level stats but not individual student data
        if message.type in ["attendance_stats_update", "attendance_state_changed"]:
            return True
    
    # Admins can see all messages
    if auth_context.user_type == "admin":
        return True
    
    return False