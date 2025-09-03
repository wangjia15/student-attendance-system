"""
Database models for class sessions and attendance tracking.
"""
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class SessionStatus(str, Enum):
    """Class session status enumeration."""
    ACTIVE = "active"
    EXPIRED = "expired"
    ENDED = "ended"


class ClassSession(BaseModel):
    """Class session model with security and tracking features."""
    
    id: str = Field(..., description="Unique session identifier")
    teacher_id: str = Field(..., description="ID of the teacher who created the session")
    class_name: str = Field(..., description="Name of the class")
    subject: Optional[str] = Field(None, description="Subject being taught")
    
    # Session timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Session expiration time")
    ended_at: Optional[datetime] = Field(None, description="When session was manually ended")
    
    # Security tokens
    jwt_token: str = Field(..., description="JWT token for session authentication")
    verification_code: str = Field(..., description="6-digit verification code")
    
    # Sharing and access
    share_link: str = Field(..., description="Shareable deep link")
    qr_code_data: str = Field(..., description="QR code data (JWT token)")
    
    # Status and settings
    status: SessionStatus = Field(default=SessionStatus.ACTIVE)
    max_students: Optional[int] = Field(None, description="Maximum number of students")
    allow_late_join: bool = Field(default=True, description="Allow students to join after start")
    
    # Tracking
    total_joins: int = Field(default=0, description="Total number of student joins")
    unique_students: List[str] = Field(default=[], description="List of unique student IDs who joined")


class ClassSessionCreate(BaseModel):
    """Request model for creating a new class session."""
    
    class_name: str = Field(..., min_length=1, max_length=100, description="Name of the class")
    subject: Optional[str] = Field(None, max_length=50, description="Subject being taught")
    expiration_minutes: int = Field(default=30, ge=5, le=180, description="Session duration in minutes")
    max_students: Optional[int] = Field(None, ge=1, le=500, description="Maximum students allowed")
    allow_late_join: bool = Field(default=True, description="Allow late joins")