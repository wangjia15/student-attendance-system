"""
API endpoints for class session management.
"""
from fastapi import APIRouter, HTTPException, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from typing import List
from datetime import datetime, timedelta
import logging

from app.core.database import get_db
from app.core.auth import get_current_teacher
from app.core.security import create_class_token, create_verification_code
from app.core.config import settings
from app.core.websocket import websocket_server, MessageType
from app.services.qr_generator import generate_class_qr_code
from app.models.user import User
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord
from app.schemas.class_session import (
    ClassSessionCreate, ClassSessionResponse, ClassSessionUpdate,
    QRCodeResponse
)
from app.schemas.auth import UserResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def session_to_response(session: ClassSession, include_student_count: bool = False) -> ClassSessionResponse:
    """Convert ClassSession model to response schema to avoid enum validation issues."""
    response_data = {
        "id": session.id,
        "name": session.name,
        "description": session.description,
        "subject": session.subject,
        "location": session.location,
        "status": session.status,
        "verification_code": session.verification_code,
        "qr_data": session.qr_data,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "duration_minutes": session.duration_minutes,
        "allow_late_join": session.allow_late_join,
        "require_verification": session.require_verification,
        "created_at": session.created_at
    }
    
    if include_student_count:
        # Get unique student count using direct query to avoid relationship join issues
        from app.models.attendance import AttendanceRecord
        from sqlalchemy import func, select
        # This needs to be called with a database session, so we'll handle it in the endpoint
    
    return ClassSessionResponse(**response_data)


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
            status="active"
        )
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        return session_to_response(session)
        
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
    status_filter: str = None,
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
        
        # Build responses with student counts
        session_responses = []
        for session in sessions:
            # Calculate student count manually to avoid join issues
            count_result = await db.execute(
                select(func.count(func.distinct(AttendanceRecord.student_id))).where(
                    AttendanceRecord.class_session_id == session.id
                )
            )
            student_count = count_result.scalar() or 0
            
            # Create response with student count
            response_data = {
                "id": session.id,
                "name": session.name,
                "description": session.description,
                "subject": session.subject,
                "location": session.location,
                "status": session.status,
                "verification_code": session.verification_code,
                "qr_data": session.qr_data,
                "start_time": session.start_time,
                "end_time": session.end_time,
                "duration_minutes": session.duration_minutes,
                "allow_late_join": session.allow_late_join,
                "require_verification": session.require_verification,
                "created_at": session.created_at,
                "student_count": student_count
            }
            
            response = ClassSessionResponse(**response_data)
            session_responses.append(response)
        
        return session_responses
        
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
        
        return session_to_response(session)
        
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
        
        return session_to_response(session)
        
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


@router.post("/{session_id}/regenerate-code")
async def regenerate_verification_code(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Regenerate verification code for security purposes."""
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
        
        # Generate new verification code
        new_verification_code = create_verification_code()
        
        # Update session with new verification code
        session.verification_code = new_verification_code
        session.updated_at = datetime.utcnow()
        
        # Generate new QR code with updated verification code
        deep_link = f"attendance://join/{new_verification_code}"
        new_qr_data = generate_class_qr_code(deep_link, session.name)
        session.qr_data = new_qr_data
        
        await db.commit()
        await db.refresh(session)
        
        # Broadcast verification code update to connected clients
        try:
            await websocket_server.broadcast_to_class(
                str(session_id),
                MessageType.SESSION_UPDATE,
                {
                    "session_id": session_id,
                    "event": "verification_code_regenerated",
                    "verification_code": new_verification_code,
                    "qr_data": new_qr_data,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            logger.info(f"Broadcasted verification code update for session {session_id}")
        except Exception as ws_error:
            logger.warning(f"Failed to broadcast verification code update: {ws_error}")
        
        # Generate new share link
        share_link = f"{request.base_url}join/{new_verification_code}"
        
        return {
            "verification_code": new_verification_code,
            "share_link": share_link
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate verification code: {str(e)}"
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
        
        session.status = "ended"
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


@router.get("/{session_id}/members", response_model=List[UserResponse])
async def get_session_members(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Get all students who have joined this class session."""
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
        
        # Use raw SQL to completely bypass relationship issues
        sql = """
        SELECT DISTINCT u.id, u.username, u.email, u.full_name, u.role, u.is_active, u.is_verified, u.created_at, u.last_login
        FROM users u 
        INNER JOIN attendance_records ar ON u.id = ar.student_id 
        WHERE ar.class_session_id = :session_id
        """
        result = await db.execute(text(sql), {"session_id": session_id})
        students_data = result.fetchall()
        
        students = []
        for row in students_data:
            students.append(type('Student', (), {
                'id': row[0],
                'username': row[1], 
                'email': row[2],
                'full_name': row[3],
                'role': row[4].lower() if row[4] else 'student',  # Convert to lowercase for enum validation
                'is_active': row[5],
                'is_verified': row[6],
                'created_at': row[7],
                'last_login': row[8]
            })())
        
        return [
            UserResponse(
                id=student.id,
                username=student.username,
                email=student.email,
                full_name=student.full_name,
                role=student.role,
                is_active=student.is_active,
                is_verified=student.is_verified,
                created_at=student.created_at,
                last_login=student.last_login
            ) for student in students
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session members: {str(e)}"
        )


@router.get("/{session_id}/enrollment-stats")
async def get_enrollment_stats(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: User = Depends(get_current_teacher)
):
    """Get enrollment statistics for this class session."""
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
        
        # Count unique students who joined
        result = await db.execute(
            select(User).where(
                User.id.in_(
                    select(AttendanceRecord.student_id).where(
                        AttendanceRecord.class_session_id == session_id
                    )
                )
            )
        )
        enrolled_count = len(result.scalars().all())
        
        # Count attendance records (may be more than enrolled if students checked in/out multiple times)
        result = await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.class_session_id == session_id
            )
        )
        total_records = len(result.scalars().all())
        
        return {
            "session_id": session_id,
            "session_name": session.name,
            "enrolled_students": enrolled_count,
            "total_attendance_records": total_records,
            "session_status": session.status,
            "created_at": session.created_at,
            "start_time": session.start_time,
            "end_time": session.end_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get enrollment stats: {str(e)}"
        )

@router.post("/join/{verification_code}")
async def student_join_class(
    verification_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enhanced student class joining with real-time WebSocket feedback."""
    try:
        # Enhanced verification code validation
        if not verification_code or len(verification_code) != 6 or not verification_code.isdigit():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code format. Must be 6 digits."
            )
        
        # Find the class session with this verification code
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.verification_code == verification_code,
                ClassSession.status == "active"
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid verification code or class has ended"
            )
        
        # Check if late join is allowed
        if not session.allow_late_join:
            session_duration = datetime.utcnow() - session.start_time
            if session_duration.total_seconds() > 900:  # 15 minutes
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Late join not allowed for this class"
                )
        
        # Check if student already joined
        existing_record = await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.student_id == current_user.id,
                AttendanceRecord.class_session_id == session.id
            )
        )
        existing = existing_record.scalar_one_or_none()
        
        if existing and existing.check_in_time:
            # Broadcast student already in class
            try:
                await websocket_server.broadcast_to_class(
                    str(session.id),
                    MessageType.STUDENT_JOINED,
                    {
                        "student_id": current_user.id,
                        "student_name": current_user.full_name or current_user.username,
                        "session_id": session.id,
                        "event": "student_already_joined",
                        "join_time": existing.check_in_time.isoformat(),
                        "is_late": existing.is_late or False,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
            except Exception as ws_error:
                logger.warning(f"Failed to broadcast student already joined: {ws_error}")
            
            return {
                "success": True,
                "message": "Already joined this class",
                "class_session_id": session.id,
                "class_name": session.name,
                "join_time": existing.check_in_time,
                "already_joined": True
            }
        
        # Create new attendance record (simplified - this would integrate with attendance.py logic)
        check_in_time = datetime.utcnow()
        is_late = check_in_time > session.start_time + timedelta(minutes=10)
        late_minutes = max(0, int((check_in_time - session.start_time).total_seconds() / 60) - 10) if is_late else 0
        
        if existing:
            existing.check_in_time = check_in_time
            existing.is_late = is_late
            existing.late_minutes = late_minutes
            existing.verification_method = "verification_code"
            attendance_record = existing
        else:
            # This should use the AttendanceEngine from attendance.py
            attendance_record = AttendanceRecord(
                student_id=current_user.id,
                class_session_id=session.id,
                check_in_time=check_in_time,
                verification_method="verification_code",
                is_late=is_late,
                late_minutes=late_minutes,
                status="present"
            )
            db.add(attendance_record)
        
        await db.commit()
        await db.refresh(attendance_record)
        
        # Broadcast student_joined_class message
        try:
            await websocket_server.broadcast_to_class(
                str(session.id),
                MessageType.STUDENT_JOINED,
                {
                    "student_id": current_user.id,
                    "student_name": current_user.full_name or current_user.username,
                    "session_id": session.id,
                    "event": "student_joined_class",
                    "join_time": check_in_time.isoformat(),
                    "is_late": is_late,
                    "late_minutes": late_minutes,
                    "verification_method": "verification_code",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            logger.info(f"Broadcasted student_joined_class for student {current_user.id} in session {session.id}")
        except Exception as ws_error:
            logger.warning(f"Failed to broadcast student_joined_class: {ws_error}")
        
        status_message = "Successfully joined class"
        if is_late:
            status_message = f"Joined class late ({late_minutes} minutes)"
        
        return {
            "success": True,
            "message": f"{status_message}: {session.name}",
            "class_session_id": session.id,
            "class_name": session.name,
            "join_time": check_in_time,
            "is_late": is_late,
            "late_minutes": late_minutes,
            "already_joined": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in student_join_class: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join class: {str(e)}"
        )