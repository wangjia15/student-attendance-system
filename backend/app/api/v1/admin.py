"""
Admin API endpoints for system management and statistics.
"""
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.models.user import User, UserRole
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord, AttendanceStatus

router = APIRouter()


@router.get("/stats")
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get system statistics for admin dashboard."""
    try:
        # Total users count
        total_users_result = await db.execute(select(func.count(User.id)))
        total_users = total_users_result.scalar() or 0
        
        # Teachers count
        teachers_result = await db.execute(
            select(func.count(User.id)).where(User.role == UserRole.TEACHER)
        )
        total_teachers = teachers_result.scalar() or 0
        
        # Students count
        students_result = await db.execute(
            select(func.count(User.id)).where(User.role == UserRole.STUDENT)
        )
        total_students = students_result.scalar() or 0
        
        # Active classes count
        active_classes_result = await db.execute(
            select(func.count(ClassSession.id)).where(ClassSession.status == "active")
        )
        active_classes = active_classes_result.scalar() or 0
        
        # Total attendance records
        attendance_records_result = await db.execute(select(func.count(AttendanceRecord.id)))
        total_attendance_records = attendance_records_result.scalar() or 0
        
        # Attendance rate calculation
        present_count_result = await db.execute(
            select(func.count(AttendanceRecord.id)).where(
                AttendanceRecord.status == AttendanceStatus.PRESENT
            )
        )
        present_count = present_count_result.scalar() or 0
        
        attendance_rate = round((present_count / total_attendance_records * 100) if total_attendance_records > 0 else 0, 1)
        
        return {
            "total_users": total_users,
            "total_teachers": total_teachers,
            "total_students": total_students,
            "active_classes": active_classes,
            "total_attendance_records": total_attendance_records,
            "attendance_rate": attendance_rate
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system stats: {str(e)}"
        )


@router.get("/recent-users")
async def get_recent_users(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get recently created users for admin dashboard."""
    try:
        result = await db.execute(
            select(User)
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        users = result.scalars().all()
        
        return [
            {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "last_login": user.last_login
            }
            for user in users
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get recent users: {str(e)}"
        )


@router.get("/active-classes")
async def get_active_classes(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get currently active classes for admin dashboard."""
    try:
        # Join with User table to get teacher name
        result = await db.execute(
            select(ClassSession, User.full_name.label('teacher_name'))
            .join(User, ClassSession.teacher_id == User.id)
            .where(ClassSession.status == "active")
            .order_by(ClassSession.created_at.desc())
            .limit(limit)
        )
        
        class_data = result.all()
        
        classes_list = []
        for session, teacher_name in class_data:
            # Get student count for this class
            student_count_result = await db.execute(
                select(func.count(AttendanceRecord.id.distinct())).where(
                    AttendanceRecord.class_session_id == session.id
                )
            )
            student_count = student_count_result.scalar() or 0
            
            classes_list.append({
                "id": session.id,
                "name": session.name,
                "teacher_name": teacher_name,
                "status": session.status,
                "present_count": student_count,
                "start_time": session.start_time.isoformat() if session.start_time else None,
                "created_at": session.created_at.isoformat() if session.created_at else None
            })
        
        return classes_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active classes: {str(e)}"
        )


@router.get("/all-users")
async def get_all_users(
    role: str = None,
    is_active: bool = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get all users with optional filtering for admin management."""
    try:
        query = select(User)
        
        # Apply filters
        if role:
            if role == 'teacher':
                query = query.where(User.role == UserRole.TEACHER)
            elif role == 'student':
                query = query.where(User.role == UserRole.STUDENT)
            elif role == 'admin':
                query = query.where(User.role == UserRole.ADMIN)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        users = result.scalars().all()
        
        return [
            {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "last_login": user.last_login
            }
            for user in users
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get users: {str(e)}"
        )


@router.get("/all-classes")
async def get_all_classes(
    status_filter: str = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Get all classes with optional status filtering for admin management."""
    try:
        query = select(ClassSession, User.full_name.label('teacher_name')).join(
            User, ClassSession.teacher_id == User.id
        )
        
        if status_filter:
            query = query.where(ClassSession.status == status_filter)
        
        query = query.order_by(ClassSession.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        class_data = result.all()
        
        classes_list = []
        for session, teacher_name in class_data:
            # Get attendance statistics
            attendance_stats_result = await db.execute(
                select(
                    func.count(AttendanceRecord.id).label('total_records'),
                    func.count(AttendanceRecord.id).filter(AttendanceRecord.status == AttendanceStatus.PRESENT).label('present_count')
                ).where(AttendanceRecord.class_session_id == session.id)
            )
            stats = attendance_stats_result.first()
            total_records = stats.total_records if stats and stats.total_records else 0
            present_count = stats.present_count if stats and stats.present_count else 0
            
            classes_list.append({
                "id": session.id,
                "name": session.name,
                "description": session.description,
                "subject": session.subject,
                "location": session.location,
                "teacher_name": teacher_name,
                "status": session.status,
                "start_time": session.start_time,
                "end_time": session.end_time,
                "total_attendance_records": total_records,
                "present_count": present_count,
                "attendance_rate": round((present_count / total_records * 100) if total_records > 0 else 0, 1),
                "created_at": session.created_at
            })
        
        return classes_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get classes: {str(e)}"
        )


@router.post("/users")
async def create_user(
    user_data: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Create a new user."""
    try:
        from app.core.auth import get_password_hash
        
        # Check if user already exists
        existing_user = await db.execute(
            select(User).where(
                (User.email == user_data.get('email')) | 
                (User.username == user_data.get('username'))
            )
        )
        if existing_user.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email or username already exists"
            )
        
        # Create new user
        new_user = User(
            email=user_data['email'],
            username=user_data['username'],
            full_name=user_data['full_name'],
            hashed_password=get_password_hash(user_data['password']),
            role=UserRole(user_data['role']),
            is_active=user_data.get('is_active', True)
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        return {
            "id": new_user.id,
            "email": new_user.email,
            "username": new_user.username,
            "full_name": new_user.full_name,
            "role": new_user.role.value,
            "is_active": new_user.is_active,
            "created_at": new_user.created_at
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    user_data: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Update an existing user."""
    try:
        # Get the user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update user fields
        if 'full_name' in user_data:
            user.full_name = user_data['full_name']
        if 'email' in user_data:
            user.email = user_data['email']
        if 'username' in user_data:
            user.username = user_data['username']
        if 'role' in user_data:
            user.role = UserRole(user_data['role'])
        if 'is_active' in user_data:
            user.is_active = user_data['is_active']
        if 'password' in user_data:
            from app.core.auth import get_password_hash
            user.hashed_password = get_password_hash(user_data['password'])
        
        await db.commit()
        await db.refresh(user)
        
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_login": user.last_login
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(e)}"
        )


@router.patch("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Toggle user active status."""
    try:
        # Get the user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Toggle status
        user.is_active = not user.is_active
        await db.commit()
        await db.refresh(user)
        
        return {
            "id": user.id,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "message": f"User {'activated' if user.is_active else 'deactivated'} successfully"
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle user status: {str(e)}"
        )


@router.get("/users/search")
async def search_users(
    q: str = "",
    role: str = None,
    is_active: bool = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Search users with text query and filters."""
    try:
        query = select(User)
        
        # Text search
        if q:
            search_filter = (
                User.full_name.ilike(f"%{q}%") |
                User.email.ilike(f"%{q}%") |
                User.username.ilike(f"%{q}%")
            )
            query = query.where(search_filter)
        
        # Role filter
        if role:
            if role == 'teacher':
                query = query.where(User.role == UserRole.TEACHER)
            elif role == 'student':
                query = query.where(User.role == UserRole.STUDENT)
            elif role == 'admin':
                query = query.where(User.role == UserRole.ADMIN)
        
        # Status filter
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        users = result.scalars().all()
        
        return [
            {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "last_login": user.last_login
            }
            for user in users
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search users: {str(e)}"
        )


@router.get("/users/export")
async def export_users(
    format: str = "csv",
    role: str = None,
    is_active: bool = None,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """Export users data in CSV format."""
    try:
        query = select(User)
        
        # Apply filters
        if role:
            if role == 'teacher':
                query = query.where(User.role == UserRole.TEACHER)
            elif role == 'student':
                query = query.where(User.role == UserRole.STUDENT)
            elif role == 'admin':
                query = query.where(User.role == UserRole.ADMIN)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        query = query.order_by(User.created_at.desc())
        
        result = await db.execute(query)
        users = result.scalars().all()
        
        if format.lower() == "csv":
            import io
            import csv
            from datetime import datetime
            from fastapi.responses import StreamingResponse
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'ID', 'Full Name', 'Username', 'Email', 'Role', 
                'Status', 'Created At', 'Last Login'
            ])
            
            # Write data
            for user in users:
                writer.writerow([
                    user.id,
                    user.full_name,
                    user.username,
                    user.email,
                    user.role.value,
                    'Active' if user.is_active else 'Inactive',
                    user.created_at.isoformat() if user.created_at else '',
                    user.last_login.isoformat() if user.last_login else 'Never'
                ])
            
            output.seek(0)
            
            # Return CSV as download
            filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
        else:
            # Return JSON format
            return [
                {
                    "id": user.id,
                    "full_name": user.full_name,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role.value,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
                for user in users
            ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export users: {str(e)}"
        )