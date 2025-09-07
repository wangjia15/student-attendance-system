#!/usr/bin/env python3
"""
直接测试API端点
"""
import requests
import json

def test_api_endpoint():
    """直接测试API端点"""
    
    # 1. 登录获取token
    print("1. 登录...")
    login_response = requests.post('http://localhost:8000/api/v1/auth/login', 
        headers={'Content-Type': 'application/json'},
        json={'email': 'student@example.com', 'password': 'Student123'})
    
    print(f"Login status: {login_response.status_code}")
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.text}")
        return
    
    token = login_response.json()['access_token']
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    # 2. 测试获取sessions列表，确认API端点工作
    print("2. 测试获取sessions...")
    sessions_response = requests.get('http://localhost:8000/api/v1/class-sessions/', 
        headers=headers)
    print(f"Sessions status: {sessions_response.status_code}")
    if sessions_response.status_code == 200:
        sessions = sessions_response.json()
        print(f"Found {len(sessions)} sessions")
        for session in sessions[:3]:  # Show first 3
            print(f"  ID: {session['id']}, Name: {session['name']}, Code: {session['verification_code']}")
    
    # 3. 直接测试verification endpoint
    test_code = "348788"
    print(f"3. 测试验证码端点: {test_code}")
    
    # 确认端点存在
    endpoint_url = 'http://localhost:8000/api/v1/attendance/check-in/code'
    verification_response = requests.post(endpoint_url,
        headers=headers,
        json={'verification_code': test_code})
    
    print(f"Verification status: {verification_response.status_code}")
    print(f"Response: {verification_response.text}")
    
    # 4. 测试是否端点路由问题
    print("4. 测试API路由...")
    routes_response = requests.get('http://localhost:8000/docs')
    print(f"API docs accessible: {routes_response.status_code == 200}")

if __name__ == "__main__":
    test_api_endpoint()