"""
Add test student data to the database for testing purposes.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.auth import get_password_hash
from app.models.user import User, UserRole
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord


async def add_test_data():
    """Add test students and attendance records."""
    # Create async engine
    engine = create_async_engine(settings.DATABASE_URL)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        try:
            # Test students data
            test_students = [
                {
                    "username": "alice_chen_2025",
                    "email": "alice.chen@student.edu",
                    "full_name": "Alice Chen",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "bob_wang_2025", 
                    "email": "bob.wang@student.edu",
                    "full_name": "Bob Wang",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "carol_li_2025",
                    "email": "carol.li@student.edu", 
                    "full_name": "Carol Li",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "david_zhang_2025",
                    "email": "david.zhang@student.edu",
                    "full_name": "David Zhang", 
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "emma_liu_2025",
                    "email": "emma.liu@student.edu",
                    "full_name": "Emma Liu",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "frank_wu_2025",
                    "email": "frank.wu@student.edu",
                    "full_name": "Frank Wu",
                    "password": "Student123!", 
                    "role": UserRole.STUDENT
                },
                {
                    "username": "grace_huang_2025",
                    "email": "grace.huang@student.edu",
                    "full_name": "Grace Huang",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                },
                {
                    "username": "henry_zhou_2025",
                    "email": "henry.zhou@student.edu",
                    "full_name": "Henry Zhou",
                    "password": "Student123!",
                    "role": UserRole.STUDENT
                }
            ]
            
            print("Adding test students...")
            created_students = []
            
            for student_data in test_students:
                # Check if student already exists by email or username
                from sqlalchemy import select, or_
                result = await session.execute(
                    select(User).where(
                        or_(
                            User.email == student_data["email"],
                            User.username == student_data["username"]
                        )
                    )
                )
                existing_user = result.scalar_one_or_none()
                
                if existing_user:
                    print(f"Student {student_data['full_name']} already exists, skipping...")
                    created_students.append(existing_user)
                    continue
                
                # Create new student
                hashed_password = get_password_hash(student_data["password"])
                student = User(
                    username=student_data["username"],
                    email=student_data["email"],
                    full_name=student_data["full_name"],
                    hashed_password=hashed_password,
                    role=student_data["role"],
                    is_active=True,
                    is_verified=True,
                    created_at=datetime.utcnow()
                )
                
                session.add(student)
                created_students.append(student)
                print(f"Added student: {student_data['full_name']}")
            
            await session.commit()
            
            # Get existing class sessions to add attendance records
            from sqlalchemy import select
            result = await session.execute(select(ClassSession))
            class_sessions = result.scalars().all()
            
            if class_sessions:
                print(f"\nFound {len(class_sessions)} class sessions, adding attendance records...")
                
                # Add some attendance records for testing
                for i, class_session in enumerate(class_sessions[:3]):  # Only first 3 classes
                    # Add 3-5 students to each class with different statuses
                    students_to_add = created_students[i*2:(i*2)+4]  # Different students for each class
                    
                    for j, student in enumerate(students_to_add):
                        # Vary the attendance status and timing
                        if j == 0:
                            status = "present"
                            check_in_time = class_session.start_time + timedelta(minutes=2)
                            is_late = False
                            late_minutes = 0
                        elif j == 1:
                            status = "late"  
                            check_in_time = class_session.start_time + timedelta(minutes=15)
                            is_late = True
                            late_minutes = 15
                        elif j == 2:
                            status = "present"
                            check_in_time = class_session.start_time + timedelta(minutes=1)
                            is_late = False
                            late_minutes = 0
                        else:
                            status = "late"
                            check_in_time = class_session.start_time + timedelta(minutes=10)
                            is_late = True
                            late_minutes = 10
                        
                        # Check if attendance record already exists
                        result = await session.execute(
                            select(AttendanceRecord).where(
                                AttendanceRecord.class_session_id == class_session.id,
                                AttendanceRecord.student_id == student.id
                            )
                        )
                        existing_record = result.scalar_one_or_none()
                        
                        if existing_record:
                            print(f"Attendance record for {student.full_name} in {class_session.name} already exists, skipping...")
                            continue
                        
                        attendance_record = AttendanceRecord(
                            class_session_id=class_session.id,
                            student_id=student.id,
                            status=status,
                            check_in_time=check_in_time,
                            is_late=is_late,
                            late_minutes=late_minutes,
                            verification_method="verification_code",
                            created_at=check_in_time
                        )
                        
                        session.add(attendance_record)
                        print(f"Added attendance record: {student.full_name} -> {class_session.name} ({status})")
                
                await session.commit()
                print("\nTest attendance records added successfully!")
            else:
                print("\nNo class sessions found. Please create a class first to see student attendance.")
            
            print(f"\nTest data setup complete!")
            print(f"Created {len(created_students)} students")
            print(f"Login credentials for all test students: password = 'Student123!'")
            
        except Exception as e:
            await session.rollback()
            print(f"Error adding test data: {e}")
            raise
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_test_data())