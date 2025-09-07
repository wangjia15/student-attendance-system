#!/usr/bin/env python3
"""
Test class persistence after re-login
"""
import requests
import json

def test_class_persistence():
    """Test that created classes persist after re-login"""
    
    print("=== Class Persistence Test ===")
    
    # Step 1: Login as teacher
    print("1. Logging in as teacher...")
    login_response = requests.post('http://localhost:8000/api/v1/auth/login', 
        headers={'Content-Type': 'application/json'},
        json={'email': 'teacher@example.com', 'password': 'Teacher123'})
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code} - {login_response.text}")
        return False
    
    token = login_response.json()['access_token']
    print("OK Teacher login successful")
    
    # Step 2: Create a test class
    print("2. Creating a test class...")
    class_data = {
        "name": "Test Class - Persistence Check",
        "description": "Testing class persistence after re-login",
        "subject": "Computer Science",
        "location": "Room 101",
        "duration_minutes": 60,
        "allow_late_join": True,
        "require_verification": True,
        "auto_end_minutes": 120
    }
    
    create_response = requests.post('http://localhost:8000/api/v1/classes/create',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        json=class_data)
    
    print(f"Create response status: {create_response.status_code}")
    if create_response.status_code != 200:
        print(f"Class creation failed: {create_response.text}")
        return False
    
    created_class = create_response.json()
    class_id = created_class['id']
    print(f"OK Class created successfully with ID: {class_id}")
    
    # Step 3: List classes before re-login
    print("3. Listing classes before re-login...")
    list_response = requests.get('http://localhost:8000/api/v1/classes/',
        headers={'Authorization': f'Bearer {token}'})
    
    print(f"List response status: {list_response.status_code}")
    if list_response.status_code != 200:
        print(f"Class listing failed: {list_response.text}")
        return False
    
    classes_before = list_response.json()
    print(f"OK Found {len(classes_before)} classes before re-login")
    
    # Step 4: Re-login (simulate fresh session)
    print("4. Re-logging in as teacher...")
    login_response2 = requests.post('http://localhost:8000/api/v1/auth/login', 
        headers={'Content-Type': 'application/json'},
        json={'email': 'teacher@example.com', 'password': 'Teacher123'})
    
    if login_response2.status_code != 200:
        print(f"Re-login failed: {login_response2.status_code} - {login_response2.text}")
        return False
    
    token2 = login_response2.json()['access_token']
    print("OK Teacher re-login successful")
    
    # Step 5: List classes after re-login
    print("5. Listing classes after re-login...")
    list_response2 = requests.get('http://localhost:8000/api/v1/classes/',
        headers={'Authorization': f'Bearer {token2}'})
    
    print(f"List response status: {list_response2.status_code}")
    if list_response2.status_code != 200:
        print(f"Class listing failed after re-login: {list_response2.text}")
        return False
    
    classes_after = list_response2.json()
    print(f"OK Found {len(classes_after)} classes after re-login")
    
    # Step 6: Verify our created class is still there
    found_class = None
    for cls in classes_after:
        if cls['id'] == class_id:
            found_class = cls
            break
    
    if found_class:
        print(f"SUCCESS: Created class '{found_class['name']}' persists after re-login!")
        print(f"  Class ID: {found_class['id']}")
        print(f"  Status: {found_class['status']}")
        return True
    else:
        print(f"FAILED: Created class with ID {class_id} not found after re-login")
        print("Classes found after re-login:")
        for cls in classes_after:
            print(f"  - ID: {cls['id']}, Name: {cls['name']}, Status: {cls['status']}")
        return False

if __name__ == "__main__":
    success = test_class_persistence()
    print(f"\n=== Test Result: {'PASSED' if success else 'FAILED'} ===")