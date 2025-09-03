"""
API endpoints for class session management.
"""
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse

from ...core.security import jwt_manager, verification_code_manager
from ...models.class_session import (
    ClassSession, ClassSessionCreate, ClassSessionResponse, SessionStatus
)

router = APIRouter()

# In-memory storage for demo (use proper database in production)
sessions_db: dict = {}


def get_current_teacher_id() -> str:
    """Get current teacher ID from authentication context."""
    # TODO: Implement proper authentication
    return "teacher_123"


@router.post("/create", response_model=ClassSessionResponse)
async def create_class_session(
    session_data: ClassSessionCreate,
    teacher_id: str = Depends(get_current_teacher_id)
):
    """
    Create a new class attendance session.
    
    Creates a secure class session with JWT tokens, QR codes, 
    verification codes, and shareable links.
    """
    # Generate unique class ID
    class_id = f"class_{secrets.token_urlsafe(8)}"
    
    # Calculate expiration time
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=session_data.expiration_minutes)
    
    # Generate JWT token
    jwt_token = jwt_manager.create_class_session_token(
        class_id=class_id,
        teacher_id=teacher_id,
        expiration_minutes=session_data.expiration_minutes
    )
    
    # Generate 6-digit verification code
    verification_code = verification_code_manager.generate_verification_code(
        class_id=class_id,
        expiration_minutes=session_data.expiration_minutes
    )
    
    # Generate shareable link
    base_url = "https://attendance.school.edu"  # Configure based on environment
    share_link = f"{base_url}/join/{class_id}?code={verification_code}"
    
    # Generate QR code data (simplified for now)
    qr_code_data = f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    
    # Create session object
    session = ClassSession(
        id=class_id,
        teacher_id=teacher_id,
        class_name=session_data.class_name,
        subject=session_data.subject,
        expires_at=expires_at,
        jwt_token=jwt_token,
        verification_code=verification_code,
        share_link=share_link,
        qr_code_data=qr_code_data,
        max_students=session_data.max_students,
        allow_late_join=session_data.allow_late_join
    )
    
    # Store session
    sessions_db[class_id] = session
    
    # Return response
    return ClassSessionResponse(
        id=session.id,
        class_name=session.class_name,
        subject=session.subject,
        teacher_id=session.teacher_id,
        status=session.status,
        created_at=session.created_at,
        expires_at=session.expires_at,
        ended_at=session.ended_at,
        verification_code=session.verification_code,
        share_link=session.share_link,
        qr_code_data=session.qr_code_data,
        total_joins=session.total_joins,
        unique_student_count=len(session.unique_students)
    )


@router.post("/{class_id}/qr-code/regenerate")
async def regenerate_qr_code(
    class_id: str,
    teacher_id: str = Depends(get_current_teacher_id)
):
    """
    Regenerate QR code with new JWT token for security.
    """
    if class_id not in sessions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Class session not found"
        )
    
    session = sessions_db[class_id]
    
    # Verify teacher ownership
    if session.teacher_id != teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this session"
        )
    
    # Calculate remaining time
    now = datetime.now(timezone.utc)
    remaining_time = session.expires_at - now
    remaining_minutes = max(int(remaining_time.total_seconds() / 60), 5)
    
    # Generate new JWT token
    new_jwt_token = jwt_manager.create_class_session_token(
        class_id=class_id,
        teacher_id=teacher_id,
        expiration_minutes=remaining_minutes
    )
    
    # Update session
    session.jwt_token = new_jwt_token
    sessions_db[class_id] = session
    
    return {
        "class_id": class_id,
        "jwt_token": new_jwt_token,
        "regenerated_at": now.isoformat(),
        "expires_at": session.expires_at.isoformat()
    }


@router.get("/{class_id}/share-link")
async def get_share_link(
    class_id: str,
    teacher_id: str = Depends(get_current_teacher_id)
):
    """
    Get shareable link for the class session.
    """
    if class_id not in sessions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Class session not found"
        )
    
    session = sessions_db[class_id]
    
    # Verify teacher ownership
    if session.teacher_id != teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this session"
        )
    
    return {
        "class_id": class_id,
        "class_name": session.class_name,
        "share_link": session.share_link,
        "verification_code": session.verification_code,
        "deep_link": f"attendance://join/{class_id}?code={session.verification_code}",
        "qr_code_data": session.qr_code_data
    }