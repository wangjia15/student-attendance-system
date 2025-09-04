from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List
from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"
    EXPIRED = "expired"


class ClassSessionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    subject: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    duration_minutes: Optional[int] = Field(None, ge=1, le=480)
    allow_late_join: bool = True
    require_verification: bool = True
    auto_end_minutes: int = Field(120, ge=1, le=480)


class ClassSessionCreate(ClassSessionBase):
    pass


class ClassSessionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    subject: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    status: Optional[SessionStatus] = None
    allow_late_join: Optional[bool] = None
    require_verification: Optional[bool] = None
    end_time: Optional[datetime] = None


class ClassSession(ClassSessionBase):
    id: int
    teacher_id: int
    status: SessionStatus
    jwt_token: str
    verification_code: str
    qr_data: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ClassSessionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    subject: Optional[str] = None
    location: Optional[str] = None
    status: SessionStatus
    verification_code: str
    qr_data: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    allow_late_join: bool
    require_verification: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# WebSocket models for real-time updates
class StudentJoin(BaseModel):
    student_id: int
    student_name: str
    join_time: datetime
    verification_method: str = "qr_code"


class LiveSessionStats(BaseModel):
    class_session_id: int
    total_students: int
    present_students: int
    late_students: int
    absent_students: int
    last_updated: datetime


class WebSocketMessage(BaseModel):
    type: str  # "student_joined", "session_stats", "session_ended"
    data: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class QRCodeResponse(BaseModel):
    qr_code_data: str
    verification_code: str
    deep_link: str
    expires_at: datetime