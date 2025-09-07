#!/usr/bin/env python3
"""
简化的验证码功能测试脚本
"""
import asyncio
import sys
import requests
from datetime import datetime

def test_login():
    """测试登录功能"""
    print("1. 测试用户登录...")
    response = requests.post('http://localhost:8000/api/v1/auth/login', 
        headers={'Content-Type': 'application/json'},
        json={'email': 'student@example.com', 'password': 'Student123'})
    
    if response.status_code == 200:
        token = response.json()['access_token']
        print("Login successful")
        return token
    else:
        print(f"Login failed: {response.status_code} - {response.text}")
        return None

def test_verification_code(token, code):
    """测试验证码功能"""
    print(f"2. 测试验证码: {code}")
    response = requests.post('http://localhost:8000/api/v1/attendance/check-in/code',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        json={'verification_code': code})
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")
    
    return response.status_code == 200

def get_active_sessions():
    """获取所有活跃的课程会话"""
    print("3. 检查活跃的课程会话...")
    import sqlite3
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, verification_code, status, start_time, allow_late_join 
        FROM class_sessions 
        WHERE status = "active"
        ORDER BY id DESC 
        LIMIT 5
    ''')
    sessions = cursor.fetchall()
    
    print(f"找到 {len(sessions)} 个活跃会话:")
    for session in sessions:
        print(f"  ID: {session[0]}, 名称: {session[1]}, 验证码: {session[2]}")
        print(f"    状态: {session[3]}, 开始时间: {session[4]}, 允许迟到: {session[5]}")
    
    conn.close()
    return sessions

if __name__ == "__main__":
    print("=== 验证码功能测试 ===")
    
    # 获取活跃会话
    sessions = get_active_sessions()
    
    # 登录
    token = test_login()
    if not token:
        sys.exit(1)
    
    # 测试每个验证码
    success_count = 0
    for session in sessions:
        verification_code = session[2]
        print(f"\n--- 测试会话 ID {session[0]} (验证码: {verification_code}) ---")
        
        if test_verification_code(token, verification_code):
            print("SUCCESS! Verification code works!")
            success_count += 1
        else:
            print("FAILED: Verification code test failed")
    
    print(f"\n=== 测试完成: {success_count}/{len(sessions)} 成功 ===")