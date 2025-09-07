"""
List all teachers in the database
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User, UserRole


async def list_teachers():
    """List all teachers in the database."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_maker() as session:
        try:
            # Get all teachers
            result = await session.execute(
                select(User).where(User.role == UserRole.TEACHER)
            )
            teachers = result.scalars().all()
            
            print(f"Found {len(teachers)} teachers:")
            for teacher in teachers:
                print(f"  - {teacher.full_name}")
                print(f"    Email: {teacher.email}")
                print(f"    Username: {teacher.username}")
                print(f"    Active: {teacher.is_active}")
                print(f"    ID: {teacher.id}")
                print()
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(list_teachers())