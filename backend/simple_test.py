"""
Simple test to verify backend components work
"""
import sys
import sqlite3
import os

print("Student Attendance System - Backend Component Test")
print("=" * 50)

# Test 1: Database connectivity
print("\n1. Testing Database...")
try:
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print(f"SUCCESS: Found {len(tables)} database tables")
    if tables:
        print(f"Tables: {[table[0] for table in tables]}")
    conn.close()
except Exception as e:
    print(f"FAILED: Database error - {e}")

# Test 2: Core imports
print("\n2. Testing Core Imports...")
try:
    from app.core.config import settings
    print("SUCCESS: Configuration loaded")
    print(f"Database URL: {settings.DATABASE_URL[:30]}...")
except Exception as e:
    print(f"FAILED: Config import - {e}")

try:
    from app.models.user import User, UserRole
    print("SUCCESS: User models imported")
except Exception as e:
    print(f"FAILED: User models - {e}")

try:
    from app.models.attendance import AttendanceRecord
    print("SUCCESS: Attendance models imported")  
except Exception as e:
    print(f"FAILED: Attendance models - {e}")

try:
    from app.models.class_session import ClassSession
    print("SUCCESS: Class session models imported")
except Exception as e:
    print(f"FAILED: Class session models - {e}")

# Test 3: API endpoints
print("\n3. Testing API Modules...")
try:
    from app.api.v1 import auth, classes, attendance
    print("SUCCESS: API modules imported")
except Exception as e:
    print(f"FAILED: API modules - {e}")

# Test 4: Services
print("\n4. Testing Services...")
services_found = 0
services_tested = [
    ('app.services.attendance_engine', 'AttendanceEngine'),
    ('app.services.qr_generator', 'QRCodeGenerator'), 
    ('app.services.privacy_service', 'PrivacyService'),
]

for module_name, class_name in services_tested:
    try:
        module = __import__(module_name, fromlist=[class_name])
        getattr(module, class_name)
        services_found += 1
        print(f"SUCCESS: {class_name} service available")
    except Exception as e:
        print(f"FAILED: {class_name} service - {e}")

print(f"\nFound {services_found}/{len(services_tested)} services working")

# Test 5: FERPA Compliance
print("\n5. Testing FERPA Compliance...")
try:
    from app.compliance.audit_service import ComplianceAuditService
    from app.compliance.anonymizer import DataAnonymizer
    print("SUCCESS: FERPA compliance modules imported")
except Exception as e:
    print(f"FAILED: FERPA compliance - {e}")

# Test 6: Check if main.py can be imported
print("\n6. Testing Main Application...")
try:
    import main
    print("SUCCESS: Main application module imported")
    if hasattr(main, 'app'):
        print("SUCCESS: FastAPI app instance found")
    else:
        print("WARNING: FastAPI app instance not found")
except Exception as e:
    print(f"FAILED: Main application - {e}")

print("\n" + "=" * 50)
print("Backend Component Test Complete")

# Simple functionality test
print("\n7. Testing Basic Functionality...")
try:
    # Test database query
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Check if we have any data
    try:
        cursor.execute("SELECT COUNT(*) FROM users;")
        user_count = cursor.fetchone()[0]
        print(f"Users in database: {user_count}")
    except:
        print("No users table yet (normal for fresh setup)")
        
    try:
        cursor.execute("SELECT COUNT(*) FROM class_sessions;")  
        class_count = cursor.fetchone()[0]
        print(f"Classes in database: {class_count}")
    except:
        print("No classes table yet (normal for fresh setup)")
        
    conn.close()
    print("SUCCESS: Database queries working")
    
except Exception as e:
    print(f"FAILED: Database functionality - {e}")

print("\nTest completed!")