"""
API endpoints for student attendance and check-in with advanced state management.
"""
from fastapi import APIRouter, HTTPException, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import joinedload
from datetime import datetime
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.auth import get_current_user, decode_token
from app.core.security import verify_verification_code
from app.models.user import User, UserRole
from app.models.class_session import ClassSession, StudentEnrollment
from app.models.attendance import AttendanceRecord, AttendanceStatus, AttendanceAuditLog
from app.services.attendance_engine import AttendanceEngine
from app.schemas.attendance import (
    StudentJoinRequest, AttendanceResponse, StudentJoinResponse,
    VerificationCodeJoinRequest, StudentCheckInRequest,
    TeacherOverrideRequest, BulkAttendanceRequest, BulkAttendanceResponse,
    ClassAttendanceReport, AttendanceStats, StudentAttendancePattern,
    AttendanceAlert, ClassAttendanceStatus, AttendanceAuditLogResponse,
    AttendancePatternRequest
)

router = APIRouter()


@router.post("/check-in/qr", response_model=StudentJoinResponse)
async def student_check_in_qr(
    join_data: StudentJoinRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Student self-check-in using QR code (JWT token) with late detection."""
    try:
        # Decode and verify JWT token from QR code
        try:
            payload = decode_token(join_data.jwt_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired QR code"
            )
        
        # Extract session information from token
        teacher_id = payload.get("teacher_id")
        session_id = payload.get("session_id")
        
        if not teacher_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid QR code format"
            )
        
        # Find the class session
        if session_id:
            result = await db.execute(
                select(ClassSession).where(
                    ClassSession.id == session_id,
                    ClassSession.status == "active"
                )
            )
        else:
            result = await db.execute(
                select(ClassSession).where(
                    ClassSession.teacher_id == teacher_id,
                    ClassSession.status == "active"
                ).order_by(ClassSession.created_at.desc())
            )
        
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Class session not found or has ended"
            )
        
        # Check if student already has attendance record
        existing_record = await db.execute(
            select(AttendanceRecord).where(
                and_(
                    AttendanceRecord.student_id == current_user.id,
                    AttendanceRecord.class_session_id == session.id
                )
            )
        )
        existing = existing_record.scalar_one_or_none()
        
        if existing and existing.check_in_time:
            return StudentJoinResponse(
                success=True,
                message="Already checked in to this class",
                class_session_id=session.id,
                class_name=session.name,
                join_time=existing.check_in_time,
                attendance_status=existing.status,
                is_late=existing.is_late,
                late_minutes=existing.late_minutes
            )
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Determine attendance status based on timing
        check_in_time = datetime.utcnow()
        attendance_status = await engine.determine_attendance_status(session, check_in_time)
        
        if existing:
            # Update existing record
            attendance_record = await engine.update_attendance_status(
                existing,
                attendance_status,
                current_user.id,
                f"Student self-check-in via QR code",
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent")
            )
            attendance_record.check_in_time = check_in_time
            attendance_record.verification_method = "qr_code"
            
            # Calculate late status
            is_late, late_minutes, grace_period_used = await engine.calculate_late_status(
                session, check_in_time
            )
            attendance_record.is_late = is_late
            attendance_record.late_minutes = late_minutes
            attendance_record.grace_period_used = grace_period_used
        else:
            # Create new attendance record
            attendance_record = await engine.create_attendance_record(
                current_user.id,
                session.id,
                attendance_status,
                "qr_code",
                current_user.id,
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent"),
                check_in_time=check_in_time
            )
        
        # Ensure student is enrolled in the class if class_id exists
        if session.class_id:
            # Check if student enrollment already exists
            enrollment_result = await db.execute(
                select(StudentEnrollment).where(
                    and_(
                        StudentEnrollment.student_id == current_user.id,
                        StudentEnrollment.class_id == session.class_id,
                        StudentEnrollment.is_active == True
                    )
                )
            )
            existing_enrollment = enrollment_result.scalar_one_or_none()
            
            if not existing_enrollment:
                # Create new student enrollment
                enrollment = StudentEnrollment(
                    student_id=current_user.id,
                    class_id=session.class_id,
                    is_active=True
                )
                db.add(enrollment)
        
        await db.commit()
        await db.refresh(attendance_record)
        
        status_message = "Successfully checked in"
        if attendance_record.is_late:
            status_message = f"Checked in late ({attendance_record.late_minutes} minutes)"
        elif attendance_record.grace_period_used:
            status_message = "Checked in (within grace period)"
        
        return StudentJoinResponse(
            success=True,
            message=f"{status_message} to {session.name}",
            class_session_id=session.id,
            class_name=session.name,
            join_time=attendance_record.check_in_time,
            attendance_status=attendance_record.status,
            is_late=attendance_record.is_late,
            late_minutes=attendance_record.late_minutes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check in: {str(e)}"
        )


@router.post("/check-in/code", response_model=StudentJoinResponse)
async def student_check_in_code(
    join_data: VerificationCodeJoinRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Student self-check-in using 6-digit verification code with late detection."""
    try:
        
        # Find the class session with this verification code
        result = await db.execute(
            select(ClassSession).where(
                ClassSession.verification_code == join_data.verification_code,
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
        
        # Check if student already has attendance record
        existing_record = await db.execute(
            select(AttendanceRecord).where(
                and_(
                    AttendanceRecord.student_id == current_user.id,
                    AttendanceRecord.class_session_id == session.id
                )
            )
        )
        existing = existing_record.scalar_one_or_none()
        
        if existing and existing.check_in_time:
            return StudentJoinResponse(
                success=True,
                message="Already checked in to this class",
                class_session_id=session.id,
                class_name=session.name,
                join_time=existing.check_in_time,
                attendance_status=existing.status,
                is_late=existing.is_late,
                late_minutes=existing.late_minutes
            )
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Determine attendance status based on timing
        check_in_time = datetime.utcnow()
        attendance_status = await engine.determine_attendance_status(session, check_in_time)
        
        if existing:
            # Update existing record
            attendance_record = await engine.update_attendance_status(
                existing,
                attendance_status,
                current_user.id,
                "Student self-check-in via verification code",
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent")
            )
            attendance_record.check_in_time = check_in_time
            attendance_record.verification_method = "verification_code"
            
            # Calculate late status
            is_late, late_minutes, grace_period_used = await engine.calculate_late_status(
                session, check_in_time
            )
            attendance_record.is_late = is_late
            attendance_record.late_minutes = late_minutes
            attendance_record.grace_period_used = grace_period_used
        else:
            # Create new attendance record
            attendance_record = await engine.create_attendance_record(
                current_user.id,
                session.id,
                attendance_status,
                "verification_code",
                current_user.id,
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent"),
                check_in_time=check_in_time
            )
        
        # Ensure student is enrolled in the class if class_id exists
        if session.class_id:
            # Check if student enrollment already exists
            enrollment_result = await db.execute(
                select(StudentEnrollment).where(
                    and_(
                        StudentEnrollment.student_id == current_user.id,
                        StudentEnrollment.class_id == session.class_id,
                        StudentEnrollment.is_active == True
                    )
                )
            )
            existing_enrollment = enrollment_result.scalar_one_or_none()
            
            if not existing_enrollment:
                # Create new student enrollment
                enrollment = StudentEnrollment(
                    student_id=current_user.id,
                    class_id=session.class_id,
                    is_active=True
                )
                db.add(enrollment)
        
        await db.commit()
        await db.refresh(attendance_record)
        
        status_message = "Successfully checked in"
        if attendance_record.is_late:
            status_message = f"Checked in late ({attendance_record.late_minutes} minutes)"
        elif attendance_record.grace_period_used:
            status_message = "Checked in (within grace period)"
        
        return StudentJoinResponse(
            success=True,
            message=f"{status_message} to {session.name}",
            class_session_id=session.id,
            class_name=session.name,
            join_time=attendance_record.check_in_time,
            attendance_status=attendance_record.status,
            is_late=attendance_record.is_late,
            late_minutes=attendance_record.late_minutes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check in: {str(e)}"
        )


@router.get("/my-attendance", response_model=list[AttendanceResponse])
async def get_my_attendance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0
):
    """Get current user's attendance history."""
    try:
        # Join with teacher user table to get teacher name
        result = await db.execute(
            select(AttendanceRecord, ClassSession, User)
            .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
            .join(User, ClassSession.teacher_id == User.id)
            .where(AttendanceRecord.student_id == current_user.id)
            .order_by(AttendanceRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        records = result.all()
        
        attendance_list = []
        for attendance, session, teacher in records:
            attendance_list.append(AttendanceResponse(
                id=attendance.id,
                class_session_id=attendance.class_session_id,
                class_name=session.name,
                subject=session.subject,
                teacher_name=teacher.full_name or teacher.username,
                student_name=current_user.full_name or current_user.username,
                status=attendance.status,
                check_in_time=attendance.check_in_time,
                check_out_time=attendance.check_out_time,
                verification_method=attendance.verification_method,
                is_late=attendance.is_late or False,
                late_minutes=attendance.late_minutes or 0,
                is_manual_override=attendance.is_manual_override or False,
                override_reason=attendance.override_reason,
                override_teacher_name=teacher.full_name or teacher.username if attendance.is_manual_override else None,
                notes=attendance.notes,
                created_at=attendance.created_at,
                updated_at=attendance.updated_at
            ))
        
        return attendance_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get attendance history: {str(e)}"
        )


@router.post("/checkout/{session_id}")
async def checkout_from_class(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check out from a class session."""
    try:
        # Find attendance record
        result = await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.student_id == current_user.id,
                AttendanceRecord.class_session_id == session_id,
                AttendanceRecord.check_out_time.is_(None)
            )
        )
        attendance = result.scalar_one_or_none()
        
        if not attendance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active attendance record found for this class"
            )
        
        # Update checkout time
        attendance.check_out_time = datetime.utcnow()
        attendance.updated_at = datetime.utcnow()
        
        await db.commit()
        
        return {
            "message": "Successfully checked out",
            "check_out_time": attendance.check_out_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check out: {str(e)}"
        )


# Teacher Override Endpoints
@router.put("/override/{class_session_id}")
async def teacher_override_attendance(
    class_session_id: int,
    override_data: TeacherOverrideRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Teacher override for individual student attendance with audit trail."""
    try:
        # Verify teacher permissions
        if current_user.role != UserRole.TEACHER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only teachers can override attendance"
            )
        
        # Verify teacher has access to this class session
        result = await db.execute(
            select(ClassSession).where(
                and_(
                    ClassSession.id == class_session_id,
                    ClassSession.teacher_id == current_user.id
                )
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Class session not found or access denied"
            )
        
        # Find or create attendance record
        result = await db.execute(
            select(AttendanceRecord).where(
                and_(
                    AttendanceRecord.student_id == override_data.student_id,
                    AttendanceRecord.class_session_id == class_session_id
                )
            )
        )
        attendance_record = result.scalar_one_or_none()
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        if attendance_record:
            # Update existing record
            await engine.update_attendance_status(
                attendance_record,
                override_data.new_status,
                current_user.id,
                override_data.reason,
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent"),
                override_data.notes
            )
        else:
            # Create new record with override
            check_in_time = datetime.utcnow() if override_data.new_status != AttendanceStatus.ABSENT else None
            attendance_record = await engine.create_attendance_record(
                override_data.student_id,
                class_session_id,
                override_data.new_status,
                "teacher_override",
                current_user.id,
                str(request.client.host) if request.client else None,
                request.headers.get("user-agent"),
                override_data.notes,
                check_in_time,
                override_data.reason
            )
        
        await db.commit()
        await db.refresh(attendance_record)
        
        return {
            "success": True,
            "message": f"Attendance overridden to {override_data.new_status.value}",
            "attendance_record": attendance_record
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to override attendance: {str(e)}"
        )


@router.post("/bulk-operations", response_model=BulkAttendanceResponse)
async def bulk_attendance_operations(
    bulk_data: BulkAttendanceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk attendance operations for class-wide management."""
    try:
        # Verify teacher permissions
        if current_user.role != UserRole.TEACHER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only teachers can perform bulk operations"
            )
        
        # Verify teacher has access to this class session
        result = await db.execute(
            select(ClassSession).where(
                and_(
                    ClassSession.id == bulk_data.class_session_id,
                    ClassSession.teacher_id == current_user.id
                )
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Class session not found or access denied"
            )
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Perform bulk operation
        result = await engine.bulk_update_attendance(
            bulk_data.class_session_id,
            bulk_data.operation,
            bulk_data.student_ids,
            current_user.id,
            bulk_data.reason,
            bulk_data.notes,
            str(request.client.host) if request.client else None,
            request.headers.get("user-agent")
        )
        
        await db.commit()
        
        return BulkAttendanceResponse(
            success=result["failed_count"] == 0,
            message=f"Processed {result['processed_count']} students, {result['failed_count']} failed",
            processed_count=result["processed_count"],
            failed_count=result["failed_count"],
            failed_students=result["failed_students"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform bulk operation: {str(e)}"
        )


# Analytics and Reporting Endpoints
@router.get("/class/{class_session_id}/status", response_model=ClassAttendanceStatus)
async def get_class_attendance_status(
    class_session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get real-time attendance status for a class session."""
    try:
        # Get class session
        result = await db.execute(
            select(ClassSession).where(ClassSession.id == class_session_id)
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Class session not found"
            )
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Get attendance statistics
        stats = await engine.calculate_attendance_stats(class_session_id)
        
        # Get enrolled student count
        enrolled_count = len(session.enrolled_students) if session.enrolled_students else 0
        
        # Count checked-in students (those with check_in_time)
        result = await db.execute(
            select(func.count(AttendanceRecord.id))
            .where(
                and_(
                    AttendanceRecord.class_session_id == class_session_id,
                    AttendanceRecord.check_in_time.is_not(None)
                )
            )
        )
        checked_in_count = result.scalar()
        
        return ClassAttendanceStatus(
            class_session_id=class_session_id,
            class_name=session.name,
            total_enrolled=enrolled_count,
            checked_in_count=checked_in_count,
            present_count=stats.present_count,
            late_count=stats.late_count,
            absent_count=stats.absent_count,
            excused_count=stats.excused_count,
            last_updated=datetime.utcnow()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get attendance status: {str(e)}"
        )


@router.get("/class/{class_session_id}/report", response_model=ClassAttendanceReport)
async def get_class_attendance_report(
    class_session_id: int,
    include_patterns: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get comprehensive attendance report for a class session."""
    try:
        # Get class session with teacher info
        result = await db.execute(
            select(ClassSession, User.full_name)
            .join(User, ClassSession.teacher_id == User.id)
            .where(ClassSession.id == class_session_id)
        )
        session_data = result.first()
        
        if not session_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Class session not found"
            )
        
        session, teacher_name = session_data
        
        # Get attendance records with student info
        result = await db.execute(
            select(AttendanceRecord, User.full_name)
            .join(User, AttendanceRecord.student_id == User.id)
            .where(AttendanceRecord.class_session_id == class_session_id)
            .order_by(User.full_name)
        )
        attendance_data = result.all()
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Get statistics
        stats = await engine.calculate_attendance_stats(class_session_id)
        
        # Build attendance records
        records = []
        for attendance, student_name in attendance_data:
            # Get override teacher name if applicable
            override_teacher_name = None
            if attendance.override_by_teacher_id:
                result = await db.execute(
                    select(User.full_name).where(User.id == attendance.override_by_teacher_id)
                )
                override_teacher_name = result.scalar()
            
            records.append(AttendanceResponse(
                id=attendance.id,
                class_session_id=attendance.class_session_id,
                class_name=session.name,
                subject=session.subject,
                teacher_name=teacher_name,
                student_name=student_name,
                status=attendance.status,
                check_in_time=attendance.check_in_time,
                check_out_time=attendance.check_out_time,
                verification_method=attendance.verification_method,
                is_late=attendance.is_late,
                late_minutes=attendance.late_minutes,
                is_manual_override=attendance.is_manual_override,
                override_reason=attendance.override_reason,
                override_teacher_name=override_teacher_name,
                notes=attendance.notes,
                created_at=attendance.created_at,
                updated_at=attendance.updated_at
            ))
        
        # Calculate duration
        duration_minutes = None
        if session.end_time:
            duration = session.end_time - session.start_time
            duration_minutes = int(duration.total_seconds() / 60)
        
        # Get attendance patterns if requested
        patterns = []
        if include_patterns:
            student_ids = [record.student_id for record, _ in attendance_data]
            for student_id in student_ids:
                pattern = await engine.analyze_student_attendance_pattern(student_id)
                patterns.append(pattern)
        
        return ClassAttendanceReport(
            class_session_id=class_session_id,
            class_name=session.name,
            subject=session.subject,
            teacher_name=teacher_name,
            start_time=session.start_time,
            end_time=session.end_time,
            duration_minutes=duration_minutes,
            stats=stats,
            records=records,
            patterns=patterns
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate attendance report: {str(e)}"
        )


@router.get("/patterns/analyze", response_model=List[AttendanceAlert])
async def analyze_attendance_patterns(
    pattern_request: AttendancePatternRequest = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Analyze attendance patterns and generate alerts for at-risk students."""
    try:
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Generate attendance alerts
        alerts = await engine.generate_attendance_alerts(
            pattern_request.class_session_id,
            pattern_request.student_id
        )
        
        return alerts
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze patterns: {str(e)}"
        )


@router.get("/audit/{attendance_record_id}", response_model=List[AttendanceAuditLogResponse])
async def get_attendance_audit_trail(
    attendance_record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get audit trail for an attendance record."""
    try:
        # Verify user has access to this attendance record
        result = await db.execute(
            select(AttendanceRecord).where(AttendanceRecord.id == attendance_record_id)
        )
        attendance_record = result.scalar_one_or_none()
        
        if not attendance_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attendance record not found"
            )
        
        # Check permissions - student can see their own, teachers can see their class records
        if current_user.role == UserRole.STUDENT and attendance_record.student_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        elif current_user.role == UserRole.TEACHER:
            # Verify teacher owns the class session
            result = await db.execute(
                select(ClassSession).where(
                    and_(
                        ClassSession.id == attendance_record.class_session_id,
                        ClassSession.teacher_id == current_user.id
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied"
                )
        
        # Initialize attendance engine
        engine = AttendanceEngine(db)
        
        # Get audit trail
        audit_logs = await engine.get_audit_trail(attendance_record_id)
        
        # Convert to response format
        audit_responses = []
        for log in audit_logs:
            # Get user name
            result = await db.execute(
                select(User.full_name).where(User.id == log.user_id)
            )
            user_name = result.scalar() or "Unknown"
            
            audit_responses.append(AttendanceAuditLogResponse(
                id=log.id,
                attendance_record_id=log.attendance_record_id,
                user_name=user_name,
                action=log.action,
                old_status=log.old_status,
                new_status=log.new_status,
                reason=log.reason,
                created_at=log.created_at
            ))
        
        return audit_responses
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get audit trail: {str(e)}"
        )


@router.get("/test-route")
async def test_route():
    """Test endpoint to verify routing works."""
    return {"status": "success", "message": "Route is working"}


@router.get("/my-classes")
async def get_my_enrolled_classes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """Get classes that the current student has attended or is enrolled in."""
    try:
        # Build base query to get classes where student has attendance records
        query = (
            select(ClassSession, User.full_name.label('teacher_name'))
            .join(AttendanceRecord, ClassSession.id == AttendanceRecord.class_session_id)
            .join(User, ClassSession.teacher_id == User.id)
            .where(AttendanceRecord.student_id == current_user.id)
        )
        
        # Apply status filter if provided
        if status_filter:
            query = query.where(ClassSession.status == status_filter)
        
        # Add ordering and pagination
        query = query.order_by(ClassSession.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        classes_data = result.all()
        
        enrolled_classes = []
        for session, teacher_name in classes_data:
            # Get the student's latest attendance record for this class
            attendance_result = await db.execute(
                select(AttendanceRecord)
                .where(
                    and_(
                        AttendanceRecord.student_id == current_user.id,
                        AttendanceRecord.class_session_id == session.id
                    )
                )
                .order_by(AttendanceRecord.created_at.desc())
                .limit(1)
            )
            latest_attendance = attendance_result.scalar_one_or_none()
            
            # Determine if there's an active session requiring check-in
            is_active_session = session.status == "active"
            requires_checkin = is_active_session and (not latest_attendance or not latest_attendance.check_in_time)
            
            enrolled_classes.append({
                "id": session.id,
                "name": session.name,
                "subject": session.subject,
                "teacher_name": teacher_name,
                "status": session.status,
                "start_time": session.start_time,
                "end_time": session.end_time,
                "verification_code": session.verification_code if is_active_session else None,
                "is_active_session": is_active_session,
                "requires_checkin": requires_checkin,
                "last_attendance_status": latest_attendance.status if latest_attendance else None,
                "last_check_in_time": latest_attendance.check_in_time if latest_attendance else None,
                "created_at": session.created_at,
                "location": getattr(session, 'location', None),
                "description": getattr(session, 'description', None)
            })
        
        return enrolled_classes
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get enrolled classes: {str(e)}"
        )


@router.get("/active-sessions")
async def get_active_sessions_for_student(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get active class sessions that require check-in from student."""
    try:
        # Get all active sessions where student has an attendance record (i.e., is enrolled)
        # but hasn't checked in yet
        query = (
            select(ClassSession, User.full_name.label('teacher_name'), AttendanceRecord)
            .join(AttendanceRecord, ClassSession.id == AttendanceRecord.class_session_id)
            .join(User, ClassSession.teacher_id == User.id)
            .where(
                and_(
                    AttendanceRecord.student_id == current_user.id,
                    ClassSession.status == "active",
                    AttendanceRecord.check_in_time.is_(None)
                )
            )
            .order_by(ClassSession.start_time.desc())
        )
        
        result = await db.execute(query)
        active_sessions_data = result.all()
        
        active_sessions = []
        for session, teacher_name, attendance_record in active_sessions_data:
            # Check if session just started (within last 30 minutes)
            session_age = datetime.utcnow() - session.start_time
            is_newly_started = session_age.total_seconds() <= 1800  # 30 minutes
            
            active_sessions.append({
                "id": session.id,
                "name": session.name,
                "subject": session.subject,
                "teacher_name": teacher_name,
                "start_time": session.start_time,
                "end_time": session.end_time,
                "verification_code": session.verification_code,
                "is_newly_started": is_newly_started,
                "session_age_minutes": int(session_age.total_seconds() / 60),
                "location": getattr(session, 'location', None),
                "allow_late_join": session.allow_late_join,
                "attendance_record_id": attendance_record.id
            })
        
        return active_sessions
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active sessions: {str(e)}"
        )
