#!/usr/bin/env python3
"""
Final test of verification code functionality
"""
import requests
import json

def test_verification_functionality():
    """Test the complete verification code flow"""
    
    print("=== Final Verification Code Test ===")
    
    # Step 1: Login as student
    print("1. Logging in as student...")
    login_response = requests.post('http://localhost:8000/api/v1/auth/login', 
        headers={'Content-Type': 'application/json'},
        json={'email': 'student@example.com', 'password': 'Student123'})
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code} - {login_response.text}")
        return False
    
    token = login_response.json()['access_token']
    print("OK Login successful")
    
    # Step 2: Test verification code
    test_code = "348788"
    print(f"2. Testing verification code: {test_code}")
    
    response = requests.post('http://localhost:8000/api/v1/attendance/check-in/code',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        json={'verification_code': test_code})
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        print("SUCCESS: Verification code worked!")
        result = response.json()
        print(f"Joined class: {result.get('class_name')}")
        print(f"Attendance status: {result.get('attendance_status')}")
        return True
    else:
        print("FAILED: Verification code still not working")
        return False

if __name__ == "__main__":
    success = test_verification_functionality()
    print(f"\n=== Test Result: {'PASSED' if success else 'FAILED'} ===")