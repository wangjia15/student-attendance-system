"""
Test cases for FERPA Privacy Service

Comprehensive test suite for validating FERPA compliance functionality
including consent management, access logging, and privacy controls.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.privacy_service import PrivacyService
from app.models.ferpa import (
    StudentConsent, DataAccessLog, DataRetentionPolicy, DataPurgeSchedule,
    ComplianceAuditLog, PrivacySettings, ConsentType, ConsentStatus,
    DataAccessReason, DataRetentionCategory
)
from app.models.user import User, UserRole
from app.core.database import Base


@pytest.fixture
def db_session():
    """Create test database session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()


@pytest.fixture
def privacy_service(db_session):
    """Create PrivacyService instance with test database"""
    return PrivacyService(db_session)


@pytest.fixture
def test_users(db_session):
    """Create test users"""
    student = User(
        id=1,
        email="student@test.edu",
        role=UserRole.STUDENT,
        first_name="Test",
        last_name="Student"
    )
    teacher = User(
        id=2,
        email="teacher@test.edu", 
        role=UserRole.TEACHER,
        first_name="Test",
        last_name="Teacher"
    )
    parent = User(
        id=3,
        email="parent@test.edu",
        role=UserRole.PARENT,
        first_name="Test",
        last_name="Parent"
    )
    
    db_session.add_all([student, teacher, parent])
    db_session.commit()
    
    return {
        "student": student,
        "teacher": teacher,
        "parent": parent
    }


class TestConsentManagement:
    """Test consent management functionality"""
    
    def test_request_consent_success(self, privacy_service, test_users):
        """Test successful consent request"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ATTENDANCE_RECORDS,
            purpose_description="Track attendance for academic progress",
            requested_by_id=teacher_id,
            data_categories=["attendance_records", "tardiness_data"],
            expiration_date=datetime.utcnow() + timedelta(days=365)
        )
        
        assert consent is not None
        assert consent.student_id == student_id
        assert consent.consent_type == ConsentType.ATTENDANCE_RECORDS
        assert consent.status == ConsentStatus.PENDING
        assert consent.purpose_description == "Track attendance for academic progress"
        
    def test_grant_consent_success(self, privacy_service, test_users):
        """Test successful consent granting"""
        student_id = test_users["student"].id
        parent_id = test_users["parent"].id
        teacher_id = test_users["teacher"].id
        
        # Create consent request
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ACADEMIC_RECORDS,
            purpose_description="Academic progress monitoring",
            requested_by_id=teacher_id
        )
        
        # Grant consent
        granted_consent = privacy_service.grant_consent(
            consent_id=consent.id,
            granted_by_id=parent_id,
            consent_method="digital_signature",
            ip_address="192.168.1.100",
            user_agent="Test Browser"
        )
        
        assert granted_consent.status == ConsentStatus.GRANTED
        assert granted_consent.granted_by_id == parent_id
        assert granted_consent.consent_method == "digital_signature"
        assert granted_consent.ip_address == "192.168.1.100"
        
    def test_withdraw_consent_success(self, privacy_service, test_users):
        """Test successful consent withdrawal"""
        student_id = test_users["student"].id
        parent_id = test_users["parent"].id
        teacher_id = test_users["teacher"].id
        
        # Create and grant consent
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.DISCIPLINARY_RECORDS,
            purpose_description="Disciplinary record access",
            requested_by_id=teacher_id
        )
        privacy_service.grant_consent(consent.id, parent_id)
        
        # Withdraw consent
        withdrawn_consent = privacy_service.withdraw_consent(
            consent_id=consent.id,
            withdrawn_by_id=parent_id,
            reason="Privacy concerns"
        )
        
        assert withdrawn_consent.status == ConsentStatus.WITHDRAWN
        assert withdrawn_consent.withdrawn_at is not None
        
    def test_get_active_consents(self, privacy_service, test_users):
        """Test retrieving active consents"""
        student_id = test_users["student"].id
        parent_id = test_users["parent"].id
        teacher_id = test_users["teacher"].id
        
        # Create multiple consents
        consent1 = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ATTENDANCE_RECORDS,
            purpose_description="Attendance tracking",
            requested_by_id=teacher_id
        )
        consent2 = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ACADEMIC_RECORDS,
            purpose_description="Grade monitoring",
            requested_by_id=teacher_id
        )
        
        # Grant both consents
        privacy_service.grant_consent(consent1.id, parent_id)
        privacy_service.grant_consent(consent2.id, parent_id)
        
        # Get active consents
        active_consents = privacy_service.get_active_consents(student_id)
        
        assert len(active_consents) == 2
        assert all(c.status == ConsentStatus.GRANTED for c in active_consents)
        
    def test_check_consent_required(self, privacy_service, test_users):
        """Test consent requirement checking"""
        student_id = test_users["student"].id
        
        # Check consent requirement for attendance records
        result = privacy_service.check_consent_required(
            student_id=student_id,
            data_type="attendance_records",
            purpose=DataAccessReason.EDUCATIONAL_INSTRUCTION
        )
        
        assert result["consent_required"] is True
        assert result["consent_type"] == ConsentType.ATTENDANCE_RECORDS
        assert result["consent_available"] is False
        assert result["violation_risk"] == "high"


class TestAccessLogging:
    """Test data access logging functionality"""
    
    def test_log_data_access_success(self, privacy_service, test_users):
        """Test successful data access logging"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        access_log = privacy_service.log_data_access(
            user_id=teacher_id,
            student_id=student_id,
            data_type="attendance_records",
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description="Checking student attendance",
            record_id=123,
            table_name="attendance_records",
            endpoint="/api/v1/attendance/student/1",
            ip_address="192.168.1.100",
            user_agent="Test Browser",
            session_id="test_session_123"
        )
        
        assert access_log is not None
        assert access_log.user_id == teacher_id
        assert access_log.student_id == student_id
        assert access_log.data_type == "attendance_records"
        assert access_log.action == "view"
        assert access_log.access_reason == DataAccessReason.EDUCATIONAL_INSTRUCTION
        assert access_log.ip_address == "192.168.1.100"
        
    def test_get_student_access_history(self, privacy_service, test_users):
        """Test retrieving student access history"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        # Create multiple access logs
        for i in range(3):
            privacy_service.log_data_access(
                user_id=teacher_id,
                student_id=student_id,
                data_type="attendance_records",
                action="view",
                access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
                purpose_description=f"Access {i+1}",
                record_id=i+1
            )
        
        # Get access history
        history = privacy_service.get_student_access_history(student_id, limit=10)
        
        assert len(history) == 3
        assert all(log.student_id == student_id for log in history)
        
    def test_detect_access_anomalies(self, privacy_service, test_users):
        """Test access anomaly detection"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        # Create high volume of access to trigger anomaly
        for i in range(60):
            privacy_service.log_data_access(
                user_id=teacher_id,
                student_id=student_id,
                data_type="attendance_records",
                action="view",
                access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
                purpose_description=f"Bulk access {i+1}",
                record_id=i+1
            )
        
        anomalies = privacy_service.detect_access_anomalies(student_id)
        
        assert len(anomalies) > 0
        high_volume_anomaly = next((a for a in anomalies if a["type"] == "high_volume_access"), None)
        assert high_volume_anomaly is not None
        assert high_volume_anomaly["access_count"] == 60


class TestPrivacySettings:
    """Test privacy settings management"""
    
    def test_get_privacy_settings_creates_defaults(self, privacy_service, test_users):
        """Test that privacy settings are created with defaults if not exist"""
        student_id = test_users["student"].id
        
        settings = privacy_service.get_privacy_settings(student_id)
        
        assert settings is not None
        assert settings.student_id == student_id
        assert settings.directory_info_public is False
        assert settings.allow_progress_notifications is True
        
    def test_update_privacy_settings(self, privacy_service, test_users):
        """Test updating privacy settings"""
        student_id = test_users["student"].id
        parent_id = test_users["parent"].id
        
        # Get initial settings
        settings = privacy_service.get_privacy_settings(student_id)
        assert settings.directory_info_public is False
        
        # Update settings
        updated_settings = privacy_service.update_privacy_settings(
            student_id=student_id,
            settings={
                "directory_info_public": True,
                "allow_name_disclosure": True
            },
            updated_by_id=parent_id
        )
        
        assert updated_settings.directory_info_public is True
        assert updated_settings.allow_name_disclosure is True


class TestDataRetention:
    """Test data retention and purging functionality"""
    
    def test_create_retention_policy(self, privacy_service):
        """Test creating data retention policy"""
        policy = privacy_service.create_retention_policy(
            policy_name="Attendance Records Retention",
            category=DataRetentionCategory.ATTENDANCE_RECORDS,
            retention_years=7,
            retention_months=0,
            retention_days=0,
            description="Retain attendance records for 7 years per FERPA requirements",
            legal_basis="FERPA Section 99.3",
            auto_purge=True,
            warning_days=30
        )
        
        assert policy is not None
        assert policy.policy_name == "Attendance Records Retention"
        assert policy.category == DataRetentionCategory.ATTENDANCE_RECORDS
        assert policy.retention_period_years == 7
        assert policy.auto_purge_enabled is True
        
    def test_schedule_data_purge(self, privacy_service, test_users):
        """Test scheduling data for purging"""
        student_id = test_users["student"].id
        
        # Create retention policy
        policy = privacy_service.create_retention_policy(
            policy_name="Test Policy",
            category=DataRetentionCategory.ATTENDANCE_RECORDS,
            retention_years=1,
            retention_months=0,
            retention_days=0,
            description="Test policy",
            legal_basis="Test"
        )
        
        # Schedule purge
        schedule = privacy_service.schedule_data_purge(
            table_name="attendance_records",
            record_id=123,
            student_id=student_id,
            policy=policy,
            record_created_date=datetime.utcnow() - timedelta(days=300)
        )
        
        assert schedule is not None
        assert schedule.policy_id == policy.id
        assert schedule.table_name == "attendance_records"
        assert schedule.record_id == 123
        assert schedule.student_id == student_id
        assert schedule.status == "scheduled"
        
    def test_get_records_due_for_purge(self, privacy_service, test_users):
        """Test getting records due for purging"""
        student_id = test_users["student"].id
        
        # Create retention policy
        policy = privacy_service.create_retention_policy(
            policy_name="Short Retention Test",
            category=DataRetentionCategory.ATTENDANCE_RECORDS,
            retention_years=0,
            retention_months=0,
            retention_days=1,
            description="Short retention for testing",
            legal_basis="Test"
        )
        
        # Schedule purge in the past (should be due)
        privacy_service.schedule_data_purge(
            table_name="attendance_records",
            record_id=456,
            student_id=student_id,
            policy=policy,
            record_created_date=datetime.utcnow() - timedelta(days=10)
        )
        
        due_records = privacy_service.get_records_due_for_purge()
        
        assert len(due_records) >= 1
        assert any(record.record_id == 456 for record in due_records)


class TestComplianceReporting:
    """Test compliance reporting functionality"""
    
    def test_generate_compliance_report(self, privacy_service, test_users):
        """Test generating comprehensive compliance report"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        parent_id = test_users["parent"].id
        
        # Create some test data
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ATTENDANCE_RECORDS,
            purpose_description="Test consent",
            requested_by_id=teacher_id
        )
        privacy_service.grant_consent(consent.id, parent_id)
        
        privacy_service.log_data_access(
            user_id=teacher_id,
            student_id=student_id,
            data_type="attendance_records",
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description="Test access"
        )
        
        # Generate report
        start_date = datetime.utcnow() - timedelta(days=7)
        end_date = datetime.utcnow() + timedelta(days=1)
        
        report = privacy_service.generate_compliance_report(
            start_date=start_date,
            end_date=end_date,
            report_type="comprehensive"
        )
        
        assert report is not None
        assert "consent_management" in report
        assert "data_access" in report
        assert "retention_compliance" in report
        assert "privacy_violations" in report
        assert "summary" in report
        assert report["summary"]["total_consents_processed"] >= 1
        assert report["summary"]["total_data_accesses"] >= 1


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_request_consent_invalid_student(self, privacy_service):
        """Test consent request with invalid student ID"""
        with pytest.raises(ValueError, match="Student with ID 999 not found"):
            privacy_service.request_consent(
                student_id=999,
                consent_type=ConsentType.ATTENDANCE_RECORDS,
                purpose_description="Test",
                requested_by_id=1
            )
    
    def test_grant_consent_invalid_id(self, privacy_service):
        """Test granting consent with invalid consent ID"""
        with pytest.raises(ValueError, match="Consent record 999 not found"):
            privacy_service.grant_consent(
                consent_id=999,
                granted_by_id=1
            )
    
    def test_withdraw_non_granted_consent(self, privacy_service, test_users):
        """Test withdrawing consent that hasn't been granted"""
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ATTENDANCE_RECORDS,
            purpose_description="Test",
            requested_by_id=teacher_id
        )
        
        with pytest.raises(ValueError, match="Can only withdraw granted consent"):
            privacy_service.withdraw_consent(consent.id, teacher_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])