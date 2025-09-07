"""
Verify test data was added correctly to the database.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord


async def verify_test_data():
    """Verify test data exists in the database."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        try:
            # Check students
            result = await session.execute(
                select(User).where(User.role == UserRole.STUDENT)
            )
            students = result.scalars().all()
            print(f"Total students in database: {len(students)}")
            
            # Show test students
            test_students = [s for s in students if s.username.endswith("_2025")]
            print(f"Test students created: {len(test_students)}")
            for student in test_students:
                print(f"  - {student.full_name} ({student.username}, {student.email})")
            
            # Check class sessions
            result = await session.execute(select(ClassSession))
            classes = result.scalars().all()
            print(f"\nTotal class sessions: {len(classes)}")
            
            # Check attendance records
            result = await session.execute(select(AttendanceRecord))
            attendance_records = result.scalars().all()
            print(f"Total attendance records: {len(attendance_records)}")
            
            # Show attendance by class with student count
            print("\nClass sessions with student counts:")
            for class_session in classes[:5]:  # Show first 5 classes
                result = await session.execute(
                    select(func.count(func.distinct(AttendanceRecord.student_id))).where(
                        AttendanceRecord.class_session_id == class_session.id
                    )
                )
                student_count = result.scalar() or 0
                
                result = await session.execute(
                    select(AttendanceRecord).where(
                        AttendanceRecord.class_session_id == class_session.id
                    )
                )
                records = result.scalars().all()
                
                print(f"  - {class_session.name}: {student_count} unique students, {len(records)} records")
                for record in records[:3]:  # Show first 3 records
                    result = await session.execute(
                        select(User).where(User.id == record.student_id)
                    )
                    student = result.scalar_one_or_none()
                    if student:
                        print(f"    * {student.full_name}: {record.status}")
                if len(records) > 3:
                    print(f"    ... and {len(records) - 3} more records")
            
            print("\n✅ Test data verification complete!")
            
        except Exception as e:
            print(f"Error verifying test data: {e}")
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify_test_data())