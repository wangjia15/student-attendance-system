"""
API endpoints for class session management.
"""
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.auth import get_current_teacher
from app.core.security import create_class_token, create_verification_code
from app.core.config import settings
from app.services.qr_generator import generate_class_qr_code
from app.models.user import User
from app.models.class_session import ClassSession, SessionStatus
from app.schemas.class_session import (
    ClassSessionCreate, ClassSessionResponse, ClassSessionUpdate,
    QRCodeResponse
)

router = APIRouter()


@router.post("/create", response_model=ClassSessionResponse)
async def create_class_session(
    session_data: ClassSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Create a new class attendance session."""
    try:
        # Create JWT token for the class
        token_data = {
            "teacher_id": current_teacher.id,
            "class_name": session_data.name,
            "created_at": datetime.utcnow().isoformat()
        }
        jwt_token = create_class_token(token_data)
        
        # Generate 6-digit verification code
        verification_code = create_verification_code()
        
        # Generate QR code with real data
        deep_link = f"attendance://join/{verification_code}"
        qr_data = generate_class_qr_code(deep_link, session_data.name)
        
        # Create session in database
        session = ClassSession(
            name=session_data.name,
            description=session_data.description,
            subject=session_data.subject,
            location=session_data.location,
            teacher_id=current_teacher.id,
            jwt_token=jwt_token,
            verification_code=verification_code,
            qr_data=qr_data,
            duration_minutes=session_data.duration_minutes,
            allow_late_join=session_data.allow_late_join,
            require_verification=session_data.require_verification,
            auto_end_minutes=session_data.auto_end_minutes,
            status=SessionStatus.ACTIVE
        )
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        return ClassSessionResponse.from_orm(session)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}"
        )


@router.get("/", response_model=List[ClassSessionResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher),
    status_filter: SessionStatus = None,
    limit: int = 50,
    offset: int = 0
):
    """List class sessions for the current teacher."""
    try:
        query = select(ClassSession).where(ClassSession.teacher_id == current_teacher.id)
        
        if status_filter:
            query = query.where(ClassSession.status == status_filter)
        
        query = query.order_by(ClassSession.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        sessions = result.scalars().all()
        
        return [ClassSessionResponse.from_orm(session) for session in sessions]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list sessions: {str(e)}"
        )


@router.get("/{session_id}", response_model=ClassSessionResponse)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Get a specific class session."""
    try:
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.teacher_id == current_teacher.id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied"
            )
        
        return ClassSessionResponse.from_orm(session)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session: {str(e)}"
        )


@router.patch("/{session_id}", response_model=ClassSessionResponse)
async def update_session(
    session_id: int,
    session_update: ClassSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Update a class session."""
    try:
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.teacher_id == current_teacher.id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied"
            )
        
        # Update fields if provided
        update_data = session_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(session, field, value)
        
        session.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(session)
        
        return ClassSessionResponse.from_orm(session)
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update session: {str(e)}"
        )


@router.post("/{session_id}/regenerate-qr", response_model=QRCodeResponse)
async def regenerate_qr_code(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Regenerate QR code for security purposes."""
    try:
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.teacher_id == current_teacher.id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied"
            )
        
        # Generate new JWT token
        token_data = {
            "session_id": session_id,
            "teacher_id": current_teacher.id,
            "class_name": session.name,
            "created_at": datetime.utcnow().isoformat(),
            "regenerated": True
        }
        new_jwt_token = create_class_token(token_data)
        
        # Generate new QR code
        deep_link = f"attendance://join/{session.verification_code}"
        new_qr_data = generate_class_qr_code(deep_link, session.name)
        
        # Update session
        session.jwt_token = new_jwt_token
        session.qr_data = new_qr_data
        session.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(session)
        
        return QRCodeResponse(
            qr_code_data=new_qr_data,
            verification_code=session.verification_code,
            deep_link=deep_link,
            expires_at=datetime.utcnow() + timedelta(hours=2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate QR code: {str(e)}"
        )


@router.get("/{session_id}/share-link")
async def get_share_link(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Get shareable link for the class session."""
    try:
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.teacher_id == current_teacher.id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied"
            )
        
        verification_code = session.verification_code
        
        return {
            "session_id": session_id,
            "verification_code": verification_code,
            "deep_link": f"attendance://join/{verification_code}",
            "web_link": f"{settings.FRONTEND_URL}/join/{verification_code}",
            "sms_text": f"Join class '{session.name}' with code: {verification_code} or visit: {settings.FRONTEND_URL}/join/{verification_code}",
            "email_subject": f"Join Class: {session.name}",
            "email_body": f"You're invited to join the class '{session.name}'.\\n\\nUse verification code: {verification_code}\\nOr click: {settings.FRONTEND_URL}/join/{verification_code}\\n\\nClass Details:\\nLocation: {session.location or 'Not specified'}\\nSubject: {session.subject or 'Not specified'}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get share link: {str(e)}"
        )


@router.post("/{session_id}/end")
async def end_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """End a class session."""
    try:
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.teacher_id == current_teacher.id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied"
            )
        
        session.status = SessionStatus.ENDED
        session.end_time = datetime.utcnow()
        session.updated_at = datetime.utcnow()
        
        await db.commit()
        
        return {"message": "Session ended successfully", "ended_at": session.end_time}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to end session: {str(e)}"
        )