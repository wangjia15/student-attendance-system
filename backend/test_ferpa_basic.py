#!/usr/bin/env python3
"""
Basic FERPA Compliance System Validation
Tests the core FERPA compliance functionality to ensure Stream A requirements are met.
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from datetime import datetime, timedelta
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import FERPA components
from app.models.ferpa import (
    StudentConsent, DataAccessLog, DataRetentionPolicy, 
    ConsentType, ConsentStatus, DataAccessReason, DataRetentionCategory
)
from app.models.user import User, UserRole
from app.core.database import Base
from app.services.privacy_service import PrivacyService
from app.compliance.consent_manager import ConsentManager
from app.compliance.data_controller import DataController
from app.compliance.access_logger import AccessLogger
from app.compliance.anonymizer import DataAnonymizer
from app.compliance.dashboard import ComplianceDashboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_test_database():
    """Create in-memory test database"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal(), engine

def create_test_users(db):
    """Create test users for validation"""
    # Create test student
    student = User(
        username="test_student",
        email="student@test.edu", 
        full_name="Test Student",
        hashed_password="hashed_password",
        role=UserRole.STUDENT,
        is_active=True,
        is_verified=True
    )
    db.add(student)
    
    # Create test teacher
    teacher = User(
        username="test_teacher",
        email="teacher@test.edu",
        full_name="Test Teacher", 
        hashed_password="hashed_password",
        role=UserRole.TEACHER,
        is_active=True,
        is_verified=True
    )
    db.add(teacher)
    
    # Create test admin
    admin = User(
        username="test_admin",
        email="admin@test.edu",
        full_name="Test Admin",
        hashed_password="hashed_password", 
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True
    )
    db.add(admin)
    
    db.commit()
    db.refresh(student)
    db.refresh(teacher)
    db.refresh(admin)
    
    return student, teacher, admin

def test_privacy_service_basic(db, student, teacher):
    """Test basic privacy service functionality"""
    logger.info("Testing Privacy Service...")
    
    privacy_service = PrivacyService(db)
    
    # Test consent request
    consent = privacy_service.request_consent(
        student_id=student.id,
        consent_type=ConsentType.ATTENDANCE_RECORDS,
        purpose_description="Academic progress tracking",
        requested_by_id=teacher.id
    )
    
    assert consent is not None
    assert consent.student_id == student.id
    assert consent.status == ConsentStatus.PENDING
    logger.info("✓ Consent request successful")
    
    # Test consent granting
    granted_consent = privacy_service.grant_consent(
        consent_id=consent.id,
        granted_by_id=student.id,
        consent_method="digital_signature"
    )
    
    assert granted_consent.status == ConsentStatus.GRANTED
    logger.info("✓ Consent granting successful")
    
    # Test access logging
    access_log = privacy_service.log_data_access(
        user_id=teacher.id,
        student_id=student.id,
        data_type="attendance_records",
        action="view",
        access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
        purpose_description="Reviewing attendance for academic support"
    )
    
    assert access_log is not None
    assert access_log.consent_verified == True
    logger.info("✓ Data access logging successful")
    
    return True

def test_consent_manager(db, student, teacher):
    """Test consent manager functionality"""
    logger.info("Testing Consent Manager...")
    
    consent_manager = ConsentManager(db)
    
    # Test consent workflow
    consent = consent_manager.create_consent_request(
        student_id=student.id,
        consent_type=ConsentType.ACADEMIC_RECORDS,
        purpose="Grade reporting and academic planning",
        requested_by=teacher.id
    )
    
    assert consent is not None
    logger.info("✓ Consent manager creation successful")
    
    # Test consent approval
    approved = consent_manager.approve_consent(
        consent_id=consent.id,
        approver_id=student.id,
        approval_method="digital_signature"
    )
    
    assert approved == True
    logger.info("✓ Consent approval successful")
    
    return True

def test_data_controller(db, student, teacher, admin):
    """Test data controller functionality"""
    logger.info("Testing Data Controller...")
    
    data_controller = DataController(db)
    
    # Test access permission checking
    can_access = data_controller.check_data_access_permission(
        user_id=teacher.id,
        student_id=student.id,
        data_type="attendance_records",
        access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION
    )
    
    assert can_access["access_granted"] == True
    logger.info("✓ Access permission checking successful")
    
    # Test data access with logging
    access_result = data_controller.access_student_data(
        user_id=teacher.id,
        student_id=student.id,
        data_type="attendance_records",
        action="view",
        purpose="Academic monitoring",
        ip_address="192.168.1.100"
    )
    
    assert access_result["access_logged"] == True
    logger.info("✓ Data access with logging successful")
    
    return True

def test_access_logger(db, student, teacher):
    """Test access logger functionality"""
    logger.info("Testing Access Logger...")
    
    access_logger = AccessLogger(db)
    
    # Test detailed access logging
    log_entry = access_logger.log_access(
        user_id=teacher.id,
        student_id=student.id,
        data_type="academic_records",
        action="export",
        access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
        purpose_description="Generating academic progress report",
        endpoint="/api/v1/students/academic-records",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0 Test Browser",
        consent_verified=True
    )
    
    assert log_entry is not None
    logger.info("✓ Detailed access logging successful")
    
    return True

def test_data_anonymizer(db, student):
    """Test data anonymization functionality"""
    logger.info("Testing Data Anonymizer...")
    
    anonymizer = DataAnonymizer(db)
    
    # Test student data anonymization
    test_data = [
        {
            "id": student.id,
            "username": student.username,
            "full_name": student.full_name,
            "email": student.email,
            "created_at": student.created_at.isoformat() if student.created_at else None
        }
    ]
    
    anonymized_result = anonymizer.anonymize_student_data(test_data)
    
    assert anonymized_result["anonymization_metadata"]["record_count"] == 1
    assert len(anonymized_result["data"]) == 1
    logger.info("✓ Student data anonymization successful")
    
    return True

def test_compliance_dashboard(db, student, teacher, admin):
    """Test compliance dashboard functionality"""
    logger.info("Testing Compliance Dashboard...")
    
    dashboard = ComplianceDashboard(db)
    
    # Test dashboard overview
    overview = dashboard.get_dashboard_overview(admin.id, admin.role)
    
    assert "timestamp" in overview
    assert "overview_metrics" in overview
    assert "compliance_status" in overview
    logger.info("✓ Dashboard overview generation successful")
    
    # Test compliance metrics
    metrics = dashboard.get_compliance_metrics()
    
    assert "period" in metrics
    assert "metrics" in metrics
    logger.info("✓ Compliance metrics generation successful")
    
    return True

def test_data_retention_basic(db):
    """Test basic data retention functionality"""
    logger.info("Testing Data Retention...")
    
    privacy_service = PrivacyService(db)
    
    # Create a retention policy
    policy = privacy_service.create_retention_policy(
        policy_name="Student Attendance Records Retention",
        category=DataRetentionCategory.ATTENDANCE_RECORDS,
        retention_years=7,
        retention_months=0,
        retention_days=0,
        description="FERPA compliant retention for attendance records",
        legal_basis="Family Educational Rights and Privacy Act (FERPA)"
    )
    
    assert policy is not None
    assert policy.retention_period_years == 7
    logger.info("✓ Data retention policy creation successful")
    
    return True

def main():
    """Main test execution"""
    logger.info("Starting FERPA Compliance System Validation...")
    
    try:
        # Create test database and users
        db, engine = create_test_database()
        student, teacher, admin = create_test_users(db)
        
        logger.info(f"Test users created: Student ID {student.id}, Teacher ID {teacher.id}, Admin ID {admin.id}")
        
        # Run validation tests
        tests = [
            (test_privacy_service_basic, "Privacy Service"),
            (test_consent_manager, "Consent Manager"),
            (test_data_controller, "Data Controller"), 
            (test_access_logger, "Access Logger"),
            (test_data_anonymizer, "Data Anonymizer"),
            (test_compliance_dashboard, "Compliance Dashboard"),
            (test_data_retention_basic, "Data Retention")
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test_func, test_name in tests:
            try:
                if test_name in ["Consent Manager", "Data Controller"]:
                    # These tests need all three user types
                    test_func(db, student, teacher, admin)
                elif test_name in ["Data Anonymizer", "Data Retention"]:
                    # These tests need fewer parameters
                    if test_name == "Data Anonymizer":
                        test_func(db, student)
                    else:
                        test_func(db)
                else:
                    # Standard tests need student and teacher
                    test_func(db, student, teacher)
                
                passed_tests += 1
                logger.info(f"✓ {test_name} validation PASSED")
                
            except Exception as e:
                logger.error(f"✗ {test_name} validation FAILED: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # Summary
        logger.info(f"\nFERPA Compliance Validation Summary:")
        logger.info(f"Passed: {passed_tests}/{total_tests}")
        logger.info(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if passed_tests == total_tests:
            logger.info("🎉 All FERPA compliance requirements validated successfully!")
            return True
        else:
            logger.warning("⚠️  Some FERPA compliance components need attention")
            return False
    
    except Exception as e:
        logger.error(f"Validation failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        db.close()
        engine.dispose()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)