#!/usr/bin/env python3
"""
直接测试SQLAlchemy查询
"""
import asyncio
import sys
sys.path.append('.')

from app.core.database import get_db
from app.models.class_session import ClassSession, SessionStatus
from sqlalchemy import select, and_

async def test_sqlalchemy_query():
    """直接测试SQLAlchemy查询是否工作"""
    async for db in get_db():
        print("=== 测试SQLAlchemy查询 ===")
        
        # 测试简单查询
        print("1. 查询所有class sessions...")
        result = await db.execute(select(ClassSession))
        all_sessions = result.scalars().all()
        print(f"找到 {len(all_sessions)} 个sessions")
        
        # 测试状态枚举
        print(f"2. SessionStatus.ACTIVE = {SessionStatus.ACTIVE}")
        print(f"   类型: {type(SessionStatus.ACTIVE)}")
        print(f"   值: {SessionStatus.ACTIVE.value}")
        
        # 测试带条件的查询
        print("3. 查询active状态的sessions...")
        result = await db.execute(
            select(ClassSession).where(ClassSession.status == SessionStatus.ACTIVE)
        )
        active_sessions = result.scalars().all()
        print(f"找到 {len(active_sessions)} 个active sessions")
        
        for session in active_sessions:
            print(f"  ID: {session.id}, 验证码: {session.verification_code}, 状态: {session.status}")
        
        # 测试具体验证码查询
        test_code = "348788"
        print(f"4. 查询验证码 {test_code}...")
        result = await db.execute(
            select(ClassSession).where(
                and_(
                    ClassSession.verification_code == test_code,
                    ClassSession.status == SessionStatus.ACTIVE
                )
            )
        )
        target_session = result.scalar_one_or_none()
        
        if target_session:
            print(f"SUCCESS: 找到会话 ID {target_session.id}")
            print(f"  名称: {target_session.name}")
            print(f"  状态: {target_session.status}")
            print(f"  类型: {type(target_session.status)}")
        else:
            print(f"FAILED: 未找到验证码为 {test_code} 的active会话")
            
            # 尝试不带状态查询
            result2 = await db.execute(
                select(ClassSession).where(ClassSession.verification_code == test_code)
            )
            any_session = result2.scalar_one_or_none()
            if any_session:
                print(f"  但找到该验证码的会话 ID {any_session.id}, 状态: {any_session.status}")
            else:
                print(f"  完全未找到该验证码的会话")
        
        break

if __name__ == "__main__":
    asyncio.run(test_sqlalchemy_query())