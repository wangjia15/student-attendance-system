#!/usr/bin/env python3
"""
直接测试不使用枚举的查询
"""
import asyncio
import sys
sys.path.append('.')

from app.core.database import get_db
from sqlalchemy import text

async def test_direct_query():
    """直接测试SQL查询，避开枚举问题"""
    async for db in get_db():
        print("=== 直接SQL查询测试 ===")
        
        # 1. 查询所有active状态的sessions
        print("1. 查询所有active状态的sessions...")
        result = await db.execute(text("""
            SELECT id, name, verification_code, status, start_time, allow_late_join 
            FROM class_sessions 
            WHERE status = 'active'
            ORDER BY id DESC 
            LIMIT 5
        """))
        
        rows = result.fetchall()
        print(f"找到 {len(rows)} 个active sessions:")
        for row in rows:
            print(f"  ID: {row.id}, 名称: {row.name}, 验证码: {row.verification_code}")
            print(f"    状态: {row.status}, 开始时间: {row.start_time}")
        
        # 2. 测试具体验证码查询
        test_code = "348788"
        print(f"\n2. 查询验证码 {test_code}...")
        result = await db.execute(text("""
            SELECT id, name, verification_code, status, start_time, teacher_id
            FROM class_sessions 
            WHERE verification_code = :code AND status = 'active'
        """), {"code": test_code})
        
        target_row = result.fetchone()
        
        if target_row:
            print(f"SUCCESS: 找到会话 ID {target_row.id}")
            print(f"  名称: {target_row.name}")
            print(f"  状态: {target_row.status}")
            print(f"  教师ID: {target_row.teacher_id}")
        else:
            print(f"FAILED: 未找到验证码为 {test_code} 的active会话")
            
            # 查看是否存在该验证码（不考虑状态）
            result2 = await db.execute(text("""
                SELECT id, name, verification_code, status
                FROM class_sessions 
                WHERE verification_code = :code
            """), {"code": test_code})
            
            any_row = result2.fetchone()
            if any_row:
                print(f"  但找到该验证码的会话 ID {any_row.id}, 状态: {any_row.status}")
            else:
                print(f"  完全未找到该验证码的会话")
        
        # 3. 测试其他验证码
        print(f"\n3. 测试前5个验证码...")
        for row in rows:
            code = row.verification_code
            result = await db.execute(text("""
                SELECT id, name 
                FROM class_sessions 
                WHERE verification_code = :code AND status = 'active'
            """), {"code": code})
            
            found = result.fetchone()
            status = "✓" if found else "✗"
            print(f"  {status} 验证码 {code}: {'找到' if found else '未找到'}")
        
        break

if __name__ == "__main__":
    asyncio.run(test_direct_query())