#!/usr/bin/env python3
"""
添加测试数据到各个表格
"""
import asyncio
import sys
sys.path.append('.')

from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.class_session import ClassSession, Class, StudentEnrollment
from app.models.attendance import AttendanceRecord, AttendanceStatus
from sqlalchemy import select
from datetime import datetime, timedelta
import random
import string

async def add_test_data():
    """添加测试数据到各个表格"""
    async for db in get_db():
        print("=== 添加测试数据 ===")
        
        # 1. 添加更多学生用户
        print("1. 添加学生用户...")
        students_data = [
            {"email": "alice@student.com", "username": "alice", "full_name": "Alice Johnson"},
            {"email": "bob@student.com", "username": "bob", "full_name": "Bob Smith"}, 
            {"email": "charlie@student.com", "username": "charlie", "full_name": "Charlie Brown"},
            {"email": "diana@student.com", "username": "diana", "full_name": "Diana Prince"},
            {"email": "eve@student.com", "username": "eve", "full_name": "Eve Wilson"},
        ]
        
        for student_data in students_data:
            # 检查是否已存在
            result = await db.execute(select(User).where(User.email == student_data["email"]))
            if not result.scalar_one_or_none():
                new_student = User(
                    email=student_data["email"],
                    username=student_data["username"],
                    full_name=student_data["full_name"],
                    hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",  # "Student123"
                    role=UserRole.STUDENT,
                    is_active=True
                )
                db.add(new_student)
                print(f"  添加学生: {student_data['full_name']}")
        
        # 2. 添加更多教师用户
        print("2. 添加教师用户...")
        teachers_data = [
            {"email": "prof.smith@teacher.com", "username": "prof_smith", "full_name": "Prof. John Smith"},
            {"email": "dr.jones@teacher.com", "username": "dr_jones", "full_name": "Dr. Sarah Jones"},
            {"email": "mr.wilson@teacher.com", "username": "mr_wilson", "full_name": "Mr. David Wilson"},
        ]
        
        for teacher_data in teachers_data:
            result = await db.execute(select(User).where(User.email == teacher_data["email"]))
            if not result.scalar_one_or_none():
                new_teacher = User(
                    email=teacher_data["email"],
                    username=teacher_data["username"],
                    full_name=teacher_data["full_name"],
                    hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",  # "Teacher123"
                    role=UserRole.TEACHER,
                    is_active=True
                )
                db.add(new_teacher)
                print(f"  添加教师: {teacher_data['full_name']}")
        
        await db.commit()
        
        # 3. 获取所有用户用于后续操作
        all_students = await db.execute(select(User).where(User.role == UserRole.STUDENT))
        students = all_students.scalars().all()
        
        all_teachers = await db.execute(select(User).where(User.role == UserRole.TEACHER))
        teachers = all_teachers.scalars().all()
        
        print(f"  总共学生数量: {len(students)}")
        print(f"  总共教师数量: {len(teachers)}")
        
        # 4. 添加课程类别
        print("3. 添加课程类别...")
        classes_data = [
            {"name": "Advanced Mathematics", "subject": "Mathematics", "description": "Calculus and Linear Algebra"},
            {"name": "Physics Lab", "subject": "Physics", "description": "Experimental Physics"},
            {"name": "Computer Science 101", "subject": "Computer Science", "description": "Introduction to Programming"},
            {"name": "English Literature", "subject": "English", "description": "Modern Literature Analysis"},
            {"name": "Chemistry Basics", "subject": "Chemistry", "description": "Fundamental Chemistry Concepts"},
        ]
        
        for i, class_data in enumerate(classes_data):
            if i < len(teachers):
                teacher = teachers[i]
                new_class = Class(
                    name=class_data["name"],
                    description=class_data["description"],
                    subject=class_data["subject"],
                    teacher_id=teacher.id
                )
                db.add(new_class)
                print(f"  添加课程: {class_data['name']} (教师: {teacher.full_name})")
        
        await db.commit()
        
        # 5. 添加学生选课记录
        print("4. 添加学生选课记录...")
        all_classes = await db.execute(select(Class))
        classes = all_classes.scalars().all()
        
        enrollment_count = 0
        for class_obj in classes:
            # 每个课程随机选择3-5个学生
            selected_students = random.sample(students, min(random.randint(3, 5), len(students)))
            for student in selected_students:
                # 检查是否已经选过课
                existing = await db.execute(
                    select(StudentEnrollment).where(
                        StudentEnrollment.student_id == student.id,
                        StudentEnrollment.class_id == class_obj.id
                    )
                )
                if not existing.scalar_one_or_none():
                    enrollment = StudentEnrollment(
                        student_id=student.id,
                        class_id=class_obj.id,
                        is_active=True
                    )
                    db.add(enrollment)
                    enrollment_count += 1
        
        await db.commit()
        print(f"  添加选课记录: {enrollment_count} 条")
        
        # 6. 添加历史班级会话
        print("5. 添加历史班级会话...")
        session_count = 0
        for class_obj in classes:
            # 为每个课程添加2-4个历史会话
            session_num = random.randint(2, 4)
            for i in range(session_num):
                # 生成过去几天的会话
                days_ago = random.randint(1, 14)
                start_time = datetime.utcnow() - timedelta(days=days_ago, hours=random.randint(8, 16))
                
                verification_code = ''.join(random.choices(string.digits, k=6))
                
                status_choice = random.choice(["ended", "ended", "ended", "active"])  # 大部分是结束状态
                
                session = ClassSession(
                    name=f"{class_obj.name} - Session {i+1}",
                    description=f"Regular session for {class_obj.name}",
                    subject=class_obj.subject,
                    teacher_id=class_obj.teacher_id,
                    class_id=class_obj.id,
                    status=status_choice,
                    jwt_token="test_token_" + verification_code,
                    verification_code=verification_code,
                    start_time=start_time,
                    end_time=start_time + timedelta(minutes=90) if status_choice == "ended" else None,
                    duration_minutes=90,
                    allow_late_join=True,
                    require_verification=True
                )
                db.add(session)
                session_count += 1
        
        await db.commit()
        print(f"  添加班级会话: {session_count} 个")
        
        # 7. 添加出勤记录
        print("6. 添加出勤记录...")
        all_sessions = await db.execute(select(ClassSession))
        sessions = all_sessions.scalars().all()
        
        attendance_count = 0
        for session in sessions:
            # 获取选了这门课的学生
            enrollments = await db.execute(
                select(StudentEnrollment).where(
                    StudentEnrollment.class_id == session.class_id,
                    StudentEnrollment.is_active == True
                )
            )
            enrolled_students = enrollments.scalars().all()
            
            # 为每个学生随机生成出勤记录
            for enrollment in enrolled_students:
                if random.random() < 0.8:  # 80%的概率有出勤记录
                    attendance_status = random.choices(
                        [AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT],
                        weights=[70, 20, 10]  # 70%出席, 20%迟到, 10%缺席
                    )[0]
                    
                    is_late = attendance_status == AttendanceStatus.LATE
                    late_minutes = random.randint(5, 30) if is_late else 0
                    
                    check_in_time = session.start_time + timedelta(minutes=late_minutes) if attendance_status != AttendanceStatus.ABSENT else None
                    
                    attendance = AttendanceRecord(
                        student_id=enrollment.student_id,
                        class_session_id=session.id,
                        status=attendance_status,
                        check_in_time=check_in_time,
                        verification_method="verification_code" if attendance_status != AttendanceStatus.ABSENT else None,
                        is_late=is_late,
                        late_minutes=late_minutes,
                        is_manual_override=False
                    )
                    db.add(attendance)
                    attendance_count += 1
        
        await db.commit()
        print(f"  添加出勤记录: {attendance_count} 条")
        
        print("\n=== 数据添加完成 ===")
        print("现在系统中有丰富的测试数据供测试使用！")
        break

if __name__ == "__main__":
    asyncio.run(add_test_data())