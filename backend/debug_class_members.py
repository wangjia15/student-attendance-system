"""
Debug script to check class members issue
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord


async def debug_class_members():
    """Debug the class members issue."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        try:
            # Get a specific Mathematics class
            result = await session.execute(
                select(ClassSession).where(ClassSession.name == "Mathematics").limit(1)
            )
            math_class = result.scalar_one_or_none()
            
            if not math_class:
                print("No Mathematics class found!")
                return
                
            print(f"Found class: {math_class.name} (ID: {math_class.id})")
            print(f"Teacher ID: {math_class.teacher_id}")
            print(f"Status: {math_class.status}")
            
            # Check attendance records for this class
            result = await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.class_session_id == math_class.id
                )
            )
            attendance_records = result.scalars().all()
            print(f"\nAttendance records for this class: {len(attendance_records)}")
            
            for record in attendance_records:
                # Get student info
                result = await session.execute(
                    select(User).where(User.id == record.student_id)
                )
                student = result.scalar_one_or_none()
                if student:
                    print(f"  - Student: {student.full_name} (ID: {student.id}, Status: {record.status})")
            
            # Count unique students using the same logic as API
            count_result = await session.execute(
                select(func.count(func.distinct(AttendanceRecord.student_id))).where(
                    AttendanceRecord.class_session_id == math_class.id
                )
            )
            student_count = count_result.scalar() or 0
            print(f"\nUnique student count: {student_count}")
            
            # Test the members query (same as API)
            subquery = select(AttendanceRecord.student_id).where(
                AttendanceRecord.class_session_id == math_class.id
            ).distinct()
            
            result = await session.execute(
                select(User).where(User.id.in_(subquery))
            )
            students = result.scalars().all()
            print(f"Members query result: {len(students)} students")
            
            for student in students:
                print(f"  - {student.full_name} ({student.username}, {student.email})")
            
            # Check all classes with student counts
            print(f"\n=== All classes with student counts ===")
            result = await session.execute(select(ClassSession))
            all_classes = result.scalars().all()
            
            for cls in all_classes[:10]:  # First 10 classes
                count_result = await session.execute(
                    select(func.count(func.distinct(AttendanceRecord.student_id))).where(
                        AttendanceRecord.class_session_id == cls.id
                    )
                )
                student_count = count_result.scalar() or 0
                print(f"  {cls.name} (ID: {cls.id}): {student_count} students")
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(debug_class_members())