"""
FERPA Compliance Integration Tests

End-to-end integration tests verifying that all FERPA compliance components
work together properly to provide comprehensive privacy protection.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.privacy_service import PrivacyService
from app.compliance.anonymizer import DataAnonymizer, AnonymizationLevel
from app.compliance.dashboard import ComplianceDashboard
from app.compliance.retention_engine import DataRetentionEngine
from app.compliance.training_materials import FERPATrainingSystem

from app.models.ferpa import (
    StudentConsent, DataAccessLog, DataRetentionPolicy, 
    ConsentType, ConsentStatus, DataAccessReason, DataRetentionCategory
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
def ferpa_system(db_session):
    """Create integrated FERPA system with all components"""
    return {
        "privacy_service": PrivacyService(db_session),
        "anonymizer": DataAnonymizer(db_session),
        "dashboard": ComplianceDashboard(db_session),
        "retention_engine": DataRetentionEngine(db_session),
        "training_system": FERPATrainingSystem(db_session)
    }


@pytest.fixture
def test_users(db_session):
    """Create comprehensive test users"""
    users = {
        "student": User(
            id=1,
            email="student@test.edu",
            role=UserRole.STUDENT,
            first_name="Test",
            last_name="Student"
        ),
        "teacher": User(
            id=2,
            email="teacher@test.edu",
            role=UserRole.TEACHER,
            first_name="Test",
            last_name="Teacher"
        ),
        "admin": User(
            id=3,
            email="admin@test.edu",
            role=UserRole.ADMIN,
            first_name="Test",
            last_name="Admin"
        ),
        "parent": User(
            id=4,
            email="parent@test.edu",
            role=UserRole.PARENT,
            first_name="Test",
            last_name="Parent"
        )
    }
    
    for user in users.values():
        db_session.add(user)
    db_session.commit()
    
    return users


class TestCompleteDataLifecycle:
    """Test complete lifecycle of student data with FERPA compliance"""
    
    def test_data_access_with_consent_verification(self, ferpa_system, test_users):
        """Test complete data access flow with consent verification"""
        privacy_service = ferpa_system["privacy_service"]
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        parent_id = test_users["parent"].id
        
        # Step 1: Request consent for data sharing
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ATTENDANCE_RECORDS,
            purpose_description="Monitor attendance for academic support",
            requested_by_id=teacher_id,
            data_categories=["attendance_records", "tardiness_data"]
        )
        
        assert consent.status == ConsentStatus.PENDING
        
        # Step 2: Parent grants consent
        granted_consent = privacy_service.grant_consent(
            consent_id=consent.id,
            granted_by_id=parent_id,
            consent_method="digital_signature"
        )
        
        assert granted_consent.status == ConsentStatus.GRANTED
        
        # Step 3: Teacher accesses data (should be logged)
        access_log = privacy_service.log_data_access(
            user_id=teacher_id,
            student_id=student_id,
            data_type="attendance_records",
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description="Checking student attendance patterns"
        )
        
        assert access_log.consent_verified is True
        assert access_log.user_id == teacher_id
        assert access_log.student_id == student_id
        
        # Step 4: Verify no privacy violations detected
        anomalies = privacy_service.detect_access_anomalies(student_id)
        unauthorized_anomalies = [a for a in anomalies if a["type"] == "unauthorized_access"]
        assert len(unauthorized_anomalies) == 0
        
    def test_data_retention_and_purging_workflow(self, ferpa_system, test_users):
        """Test complete data retention and purging workflow"""
        privacy_service = ferpa_system["privacy_service"]
        retention_engine = ferpa_system["retention_engine"]
        student_id = test_users["student"].id
        
        # Step 1: Create retention policy
        policy = retention_engine.create_retention_policy(
            policy_name="Test Attendance Retention",
            category=DataRetentionCategory.ATTENDANCE_RECORDS,
            retention_years=0,
            retention_months=0,
            retention_days=30,  # Short for testing
            description="30-day retention for testing",
            legal_basis="Test policy",
            auto_purge_enabled=True,
            warning_period_days=5
        )
        
        assert policy.auto_purge_enabled is True
        
        # Step 2: Schedule old record for purging
        old_record_date = datetime.utcnow() - timedelta(days=35)
        schedule = retention_engine.schedule_record_for_purge(
            table_name="attendance_records",
            record_id=123,
            student_id=student_id,
            policy=policy,
            record_created_date=old_record_date
        )
        
        assert schedule.status == "scheduled"
        
        # Step 3: Check records due for purge
        due_records = retention_engine.get_records_due_for_purge()
        assert len(due_records) >= 1
        assert schedule.id in [r.id for r in due_records]
        
        # Step 4: Send warning notification
        warning_result = retention_engine.send_purge_warning(schedule.id)
        assert warning_result is True
        
        # Refresh schedule
        privacy_service.db.refresh(schedule)
        assert schedule.status == "warned"
        
        # Step 5: Execute purge (mocked)
        with patch.object(retention_engine, '_execute_actual_purge', return_value=True):
            purge_result = retention_engine.execute_purge(
                schedule.id,
                executed_by_id=test_users["admin"].id
            )
            
            assert purge_result is True
            
            # Verify purge was logged
            privacy_service.db.refresh(schedule)
            assert schedule.status == "purged"
            assert schedule.actual_purge_date is not None
            
    def test_data_anonymization_for_reporting(self, ferpa_system, test_users):
        """Test data anonymization workflow for external reporting"""
        anonymizer = ferpa_system["anonymizer"]
        privacy_service = ferpa_system["privacy_service"]
        
        # Step 1: Create sample student data
        student_data = [
            {
                "id": test_users["student"].id,
                "first_name": "Test",
                "last_name": "Student",
                "email": "student@test.edu",
                "grade_level": 10,
                "gpa": 3.75,
                "attendance_rate": 95.5
            }
        ]
        
        # Step 2: Anonymize data for external sharing
        anonymized_result = anonymizer.anonymize_student_data(
            student_data=student_data,
            anonymization_level=AnonymizationLevel.ANONYMIZATION,
            preserve_fields=["grade_level", "gpa", "attendance_rate"]
        )
        
        assert anonymized_result["anonymization_metadata"]["level"] == "anonymization"
        assert len(anonymized_result["data"]) == 1
        
        anonymized_record = anonymized_result["data"][0]
        
        # Step 3: Verify PII is removed/anonymized
        assert anonymized_record["grade_level"] == 10  # Preserved
        assert anonymized_record["gpa"] == 3.75  # Preserved
        assert anonymized_record["attendance_rate"] == 95.5  # Preserved
        
        # PII should be removed or anonymized
        assert "first_name" not in anonymized_record or anonymized_record["first_name"] == "[REDACTED]"
        assert "email" not in anonymized_record or "@" not in str(anonymized_record.get("email", ""))
        
        # Step 4: Log anonymization activity
        privacy_service.log_data_access(
            user_id=test_users["admin"].id,
            student_id=test_users["student"].id,
            data_type="student_records",
            action="export",
            access_reason=DataAccessReason.LEGITIMATE_RESEARCH,
            purpose_description="Anonymized data export for external research",
            data_anonymized=True
        )


class TestComplianceDashboardIntegration:
    """Test dashboard integration with all compliance components"""
    
    def test_comprehensive_dashboard_data(self, ferpa_system, test_users):
        """Test that dashboard aggregates data from all compliance components"""
        privacy_service = ferpa_system["privacy_service"]
        dashboard = ferpa_system["dashboard"]
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        admin_id = test_users["admin"].id
        
        # Create test compliance data
        # 1. Consent records
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ACADEMIC_RECORDS,
            purpose_description="Academic monitoring",
            requested_by_id=teacher_id
        )
        privacy_service.grant_consent(consent.id, test_users["parent"].id)
        
        # 2. Access logs
        privacy_service.log_data_access(
            user_id=teacher_id,
            student_id=student_id,
            data_type="academic_records",
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description="Grade review"
        )
        
        # 3. Compliance audit events
        privacy_service._log_compliance_event(
            "data_access_review",
            "access",
            "Routine data access review",
            severity_level="info",
            user_id=teacher_id,
            affected_student_id=student_id
        )
        
        # Get dashboard overview
        dashboard_data = dashboard.get_dashboard_overview(admin_id, UserRole.ADMIN)
        
        assert dashboard_data is not None
        assert "key_metrics" in dashboard_data
        assert "recent_alerts" in dashboard_data
        assert "compliance_summary" in dashboard_data
        
        # Verify metrics include our test data
        metrics = dashboard_data.get("key_metrics", [])
        metric_types = [m.get("metric_type") for m in metrics if isinstance(m, dict)]
        
        # Should have compliance score and other key metrics
        assert any("compliance" in str(mt) for mt in metric_types)
        
    def test_privacy_violation_detection_and_alerting(self, ferpa_system, test_users):
        """Test integrated privacy violation detection and alerting"""
        privacy_service = ferpa_system["privacy_service"]
        dashboard = ferpa_system["dashboard"]
        student_id = test_users["student"].id
        teacher_id = test_users["teacher"].id
        
        # Create access without proper consent (violation)
        access_log = privacy_service.log_data_access(
            user_id=teacher_id,
            student_id=student_id,
            data_type="disciplinary_records",  # Sensitive data
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description="Checking disciplinary records"
        )
        
        # This should trigger a violation since no consent exists for disciplinary records
        
        # Generate privacy alerts
        alerts = dashboard.generate_privacy_alerts()
        
        # Should have at least one alert for potential violation
        violation_alerts = [a for a in alerts if "violation" in a.description.lower()]
        assert len(violation_alerts) > 0
        
        high_risk_alerts = [a for a in alerts if a.severity.value in ["error", "critical"]]
        assert len(high_risk_alerts) > 0


class TestTrainingComplianceIntegration:
    """Test training system integration with compliance monitoring"""
    
    def test_staff_training_compliance_tracking(self, ferpa_system, test_users):
        """Test comprehensive staff training compliance tracking"""
        training_system = ferpa_system["training_system"]
        dashboard = ferpa_system["dashboard"]
        teacher_id = test_users["teacher"].id
        
        # Step 1: Get training plan for teacher
        training_plan = training_system.get_role_based_training_plan(UserRole.TEACHER)
        
        assert "recommended_modules" in training_plan
        assert len(training_plan["recommended_modules"]) > 0
        
        # Step 2: Complete training module
        module_result = training_system.complete_training_module(
            user_id=teacher_id,
            module_id="ferpa_overview",
            completion_data={
                "duration_minutes": 45,
                "score": 85,
                "completed_at": datetime.utcnow().isoformat()
            }
        )
        
        assert module_result["success"] is True
        
        # Step 3: Take assessment
        assessment_result = training_system.submit_assessment(
            user_id=teacher_id,
            module_id="ferpa_overview",
            responses={
                "q1": "A",
                "q2": "B",
                "q3": "C"
            }
        )
        
        # Assume passing score
        assessment_result["score"] = 85
        assessment_result["passed"] = True
        
        # Step 4: Generate compliance report that includes training status
        compliance_report = training_system.generate_training_compliance_report()
        
        assert "overall_metrics" in compliance_report
        assert "role_breakdown" in compliance_report
        assert compliance_report["overall_metrics"]["total_staff"] >= 1


class TestEndToEndComplianceScenario:
    """Test complete end-to-end compliance scenario"""
    
    def test_student_data_request_fulfillment(self, ferpa_system, test_users):
        """Test complete scenario of fulfilling student data request"""
        privacy_service = ferpa_system["privacy_service"]
        anonymizer = ferpa_system["anonymizer"]
        dashboard = ferpa_system["dashboard"]
        
        student_id = test_users["student"].id
        admin_id = test_users["admin"].id
        parent_id = test_users["parent"].id
        
        # Scenario: Parent requests complete educational records for their child
        
        # Step 1: Verify parent relationship and request consent
        consent = privacy_service.request_consent(
            student_id=student_id,
            consent_type=ConsentType.ACADEMIC_RECORDS,
            purpose_description="Parent request for complete educational records",
            requested_by_id=parent_id,
            data_categories=["academic_records", "attendance_records", "disciplinary_records"]
        )
        
        # Step 2: Parent grants consent (self-granted in this case)
        granted_consent = privacy_service.grant_consent(
            consent_id=consent.id,
            granted_by_id=parent_id,
            consent_method="digital_signature"
        )
        
        assert granted_consent.status == ConsentStatus.GRANTED
        
        # Step 3: Admin fulfills request with access logging
        access_log = privacy_service.log_data_access(
            user_id=admin_id,
            student_id=student_id,
            data_type="academic_records",
            action="export",
            access_reason=DataAccessReason.PARENT_REQUEST,
            purpose_description="Fulfilling parent request for educational records"
        )
        
        assert access_log.consent_verified is True
        
        # Step 4: Generate summary report for compliance audit
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=1)
        
        compliance_report = privacy_service.generate_compliance_report(
            start_date=start_date,
            end_date=end_date
        )
        
        assert compliance_report["summary"]["total_data_accesses"] >= 1
        assert compliance_report["summary"]["total_consents_processed"] >= 1
        assert compliance_report["summary"]["compliance_score"] > 80  # Should be high
        
        # Step 5: Verify no privacy violations occurred
        violations = compliance_report["privacy_violations"]["incidents"]
        critical_violations = [v for v in violations if v["severity"] == "critical"]
        assert len(critical_violations) == 0
        
    def test_external_research_data_sharing(self, ferpa_system, test_users):
        """Test scenario of sharing anonymized data for external research"""
        privacy_service = ferpa_system["privacy_service"]
        anonymizer = ferpa_system["anonymizer"]
        retention_engine = ferpa_system["retention_engine"]
        
        admin_id = test_users["admin"].id
        student_id = test_users["student"].id
        
        # Scenario: University researcher requests anonymized student performance data
        
        # Step 1: Create anonymized dataset
        student_data = [
            {
                "id": student_id,
                "first_name": "Test",
                "last_name": "Student",
                "email": "student@test.edu",
                "grade_level": 11,
                "gpa": 3.8,
                "attendance_rate": 92.3,
                "course_completion_rate": 98.5
            }
        ]
        
        # Step 2: Apply strong anonymization for external sharing
        anonymized_data = anonymizer.anonymize_student_data(
            student_data=student_data,
            anonymization_level=AnonymizationLevel.K_ANONYMITY,
            preserve_fields=["grade_level"],
            k_value=5
        )
        
        assert anonymized_data["anonymization_metadata"]["level"] == "k_anonymity"
        assert anonymized_data["anonymization_metadata"]["k_value"] == 5
        
        # Step 3: Log data sharing activity
        sharing_log = privacy_service.log_data_access(
            user_id=admin_id,
            student_id=student_id,
            data_type="student_records",
            action="export",
            access_reason=DataAccessReason.LEGITIMATE_RESEARCH,
            purpose_description="Anonymized data sharing for external educational research",
            data_anonymized=True
        )
        
        assert sharing_log.data_anonymized is True
        assert sharing_log.access_reason == DataAccessReason.LEGITIMATE_RESEARCH
        
        # Step 4: Schedule original detailed data for retention review
        policy = retention_engine.create_retention_policy(
            policy_name="Research Data Retention",
            category=DataRetentionCategory.ACADEMIC_RECORDS,
            retention_years=7,
            retention_months=0,
            retention_days=0,
            description="Retain detailed academic records per FERPA",
            legal_basis="FERPA requirements"
        )
        
        # Step 5: Verify compliance audit trail
        audit_events = privacy_service.db.query(
            privacy_service.db.model_class("ComplianceAuditLog")
        ).filter(
            privacy_service.db.model_class("ComplianceAuditLog").affected_student_id == student_id
        ).all()
        
        # Should have multiple audit events from this process
        assert len(audit_events) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])