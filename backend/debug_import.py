#!/usr/bin/env python3
"""
Debug import to find source of SessionStatus enum error
"""
import sys
sys.path.append('.')

print("1. Testing imports...")

try:
    from app.models.class_session import ClassSession
    print("OK ClassSession imported successfully")
    
    # Check if the model has the string field
    print(f"OK ClassSession.status type: {ClassSession.status.type}")
    
except Exception as e:
    print(f"ERROR ClassSession import failed: {e}")

try:
    from app.schemas.class_session import ClassSessionResponse
    print("OK ClassSessionResponse imported successfully")
    
except Exception as e:
    print(f"ERROR ClassSessionResponse import failed: {e}")

print("2. Testing manual creation...")

try:
    from app.core.database import get_db
    from sqlalchemy import select
    import asyncio
    
    async def test_query():
        async for db in get_db():
            query = select(ClassSession).limit(1)
            result = await db.execute(query)
            session = result.scalar_one_or_none()
            
            if session:
                print(f"OK Found session: ID={session.id}, status={session.status}, type={type(session.status)}")
                
                # Try to convert to Pydantic
                try:
                    response = ClassSessionResponse.from_orm(session)
                    print("OK Pydantic conversion successful")
                except Exception as e:
                    print(f"ERROR Pydantic conversion failed: {e}")
            else:
                print("No sessions found in database")
            break
    
    asyncio.run(test_query())
    
except Exception as e:
    print(f"ERROR Database test failed: {e}")
    import traceback
    traceback.print_exc()