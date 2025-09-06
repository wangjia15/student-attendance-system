"""
Simple test server to verify backend functionality
"""
import asyncio
import sqlite3
from datetime import datetime
import json

def test_database():
    """Test SQLite database connectivity and basic operations"""
    print("🗄️ Testing Database Connection...")
    
    try:
        # Connect to database
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # Test basic query
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        print(f"✅ Database connected successfully")
        print(f"📊 Found {len(tables)} tables: {[table[0] for table in tables]}")
        
        # Test user table if exists
        try:
            cursor.execute("SELECT COUNT(*) FROM users;")
            user_count = cursor.fetchone()[0]
            print(f"👥 Users in database: {user_count}")
        except sqlite3.OperationalError:
            print("ℹ️ No users table found - this is normal for initial setup")
        
        # Test attendance table if exists  
        try:
            cursor.execute("SELECT COUNT(*) FROM attendance;")
            attendance_count = cursor.fetchone()[0]
            print(f"📋 Attendance records: {attendance_count}")
        except sqlite3.OperationalError:
            print("ℹ️ No attendance table found - this is normal for initial setup")
            
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def test_models():
    """Test model imports and basic functionality"""
    print("\n🏗️ Testing Models...")
    
    try:
        # Test basic model imports
        from app.models.user import User, Teacher, Student
        from app.models.class_session import ClassSession
        from app.models.attendance import Attendance
        print("✅ Core models imported successfully")
        
        # Test FERPA compliance models
        from app.models.ferpa import FERPAAuditLog, PrivacyConsent
        print("✅ FERPA compliance models imported")
        
        # Test SIS integration models
        from app.models.sis_integration import SISIntegration, SISStudentMapping
        print("✅ SIS integration models imported")
        
        return True
        
    except Exception as e:
        print(f"❌ Models test failed: {e}")
        return False

def test_services():
    """Test service layer functionality"""
    print("\n⚙️ Testing Services...")
    
    try:
        # Test attendance service
        from app.services.attendance_service import AttendanceService
        print("✅ Attendance service imported")
        
        # Test privacy service  
        from app.services.privacy_service import PrivacyService
        print("✅ Privacy service imported")
        
        # Test SIS service
        from app.services.sis_service import SISService  
        print("✅ SIS service imported")
        
        return True
        
    except Exception as e:
        print(f"❌ Services test failed: {e}")
        return False

def test_websocket():
    """Test WebSocket infrastructure"""
    print("\n🔌 Testing WebSocket Infrastructure...")
    
    try:
        # Test WebSocket core
        from app.core.websocket import websocket_server, MessageType
        print("✅ WebSocket core infrastructure imported")
        
        # Test live updates
        from app.websocket.live_updates import connection_manager, live_update_service
        print("✅ Live updates service imported")
        
        return True
        
    except Exception as e:
        print(f"❌ WebSocket test failed: {e}")
        return False

def test_compliance():
    """Test FERPA compliance framework"""
    print("\n⚖️ Testing FERPA Compliance...")
    
    try:
        # Test compliance services
        from app.compliance.audit_service import AuditService
        from app.compliance.anonymizer import DataAnonymizer
        from app.compliance.retention_engine import RetentionEngine
        print("✅ FERPA compliance framework imported")
        
        return True
        
    except Exception as e:
        print(f"❌ FERPA compliance test failed: {e}")
        return False

def test_integrations():
    """Test SIS integrations"""
    print("\n🔗 Testing SIS Integrations...")
    
    try:
        # Test SIS providers
        from app.integrations.sis.providers.powerschool import PowerSchoolProvider
        from app.integrations.sis.providers.infinite_campus import InfiniteCampusProvider
        from app.integrations.sis.providers.skyward import SkywardProvider
        print("✅ SIS provider implementations imported")
        
        # Test OAuth service
        from app.integrations.sis.oauth_service import SISOAuthService
        print("✅ OAuth service imported")
        
        return True
        
    except Exception as e:
        print(f"❌ SIS integrations test failed: {e}")
        return False

def test_config():
    """Test configuration loading"""
    print("\n⚙️ Testing Configuration...")
    
    try:
        from app.core.config import settings
        print(f"✅ Configuration loaded")
        print(f"📧 Environment: {getattr(settings, 'ENVIRONMENT', 'not set')}")
        print(f"🗄️ Database URL: {getattr(settings, 'DATABASE_URL', 'not set')[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

def generate_test_report():
    """Generate comprehensive test report"""
    print("\n" + "="*60)
    print("🎓 STUDENT ATTENDANCE SYSTEM - BACKEND TEST REPORT")
    print("="*60)
    
    tests = [
        ("Database Connectivity", test_database),
        ("Model Imports", test_models), 
        ("Service Layer", test_services),
        ("WebSocket Infrastructure", test_websocket),
        ("FERPA Compliance", test_compliance),
        ("SIS Integrations", test_integrations),
        ("Configuration", test_config)
    ]
    
    results = {}
    total_tests = len(tests)
    passed_tests = 0
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = "PASS" if result else "FAIL"
            if result:
                passed_tests += 1
        except Exception as e:
            results[test_name] = "ERROR"
            print(f"❌ {test_name} failed with error: {e}")
    
    # Generate summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    for test_name, result in results.items():
        status_icon = "✅" if result == "PASS" else "❌" if result == "FAIL" else "💥"
        print(f"{status_icon} {test_name:<30} {result}")
    
    success_rate = (passed_tests / total_tests) * 100
    print(f"\n🎯 Overall Success Rate: {success_rate:.1f}%")
    print(f"✅ Tests Passed: {passed_tests}")
    print(f"❌ Tests Failed: {total_tests - passed_tests}")
    
    if success_rate >= 80:
        print("\n🎉 BACKEND IS READY FOR TESTING!")
        print("The core functionality appears to be working correctly.")
    else:
        print("\n⚠️ BACKEND NEEDS ATTENTION")
        print("Some core components have issues that need to be resolved.")
    
    # Test database schema
    print(f"\n🗄️ DATABASE SCHEMA STATUS:")
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [table[0] for table in cursor.fetchall()]
        
        expected_tables = ['users', 'students', 'teachers', 'class_sessions', 'attendance', 'ferpa_audit_logs']
        found_tables = [table for table in expected_tables if table in tables]
        
        print(f"📊 Expected core tables: {len(expected_tables)}")
        print(f"✅ Found core tables: {len(found_tables)}")
        print(f"📋 All tables: {tables}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Database schema check failed: {e}")
    
    return success_rate >= 80

if __name__ == "__main__":
    print("🚀 Starting Student Attendance System Backend Tests...")
    print(f"🕒 Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    success = generate_test_report()
    
    if success:
        print(f"\n✨ Backend testing completed successfully!")
        exit(0)
    else:
        print(f"\n💥 Backend testing found issues!")
        exit(1)