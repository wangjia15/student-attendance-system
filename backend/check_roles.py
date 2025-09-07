"""
Check role values in the database
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.core.config import settings


async def check_roles():
    """Check the role values in the database."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        try:
            # Check role values and class 69
            sql = """
            SELECT DISTINCT role FROM users;
            """
            result = await session.execute(text(sql))
            roles = result.fetchall()
            print("All roles in database:")
            for role in roles:
                print(f"  - '{role[0]}'")
            
            # Check if class 69 has any students
            sql = """
            SELECT COUNT(*) FROM attendance_records WHERE class_session_id = 69;
            """
            result = await session.execute(text(sql))
            count = result.scalar()
            print(f"\nClass 69 attendance records: {count}")
            
            # Check which students are in class 69
            if count > 0:
                sql = """
                SELECT u.full_name, u.role 
                FROM users u 
                JOIN attendance_records ar ON u.id = ar.student_id 
                WHERE ar.class_session_id = 69;
                """
                result = await session.execute(text(sql))
                students = result.fetchall()
                print(f"Students in class 69:")
                for student in students:
                    print(f"  - {student[0]} ({student[1]})")
                    
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_roles())