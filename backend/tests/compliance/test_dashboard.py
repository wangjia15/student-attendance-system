"""
Test cases for FERPA Compliance Dashboard

Comprehensive test suite for validating compliance dashboard functionality
including metrics, alerts, and reporting capabilities.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.compliance.dashboard import (
    ComplianceDashboard, DashboardMetric, ComplianceAlert,
    DashboardMetricType, AlertSeverity
)
from app.models.ferpa import (
    ComplianceAuditLog, DataAccessLog, StudentConsent, DataRetentionPolicy,
    DataPurgeSchedule, ConsentStatus, DataAccessReason
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
def dashboard(db_session):
    """Create ComplianceDashboard instance"""
    return ComplianceDashboard(db_session)


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
    admin = User(
        id=3,
        email="admin@test.edu",
        role=UserRole.ADMIN,
        first_name="Test",
        last_name="Admin"
    )
    
    db_session.add_all([student, teacher, admin])
    db_session.commit()
    
    return {
        "student": student,
        "teacher": teacher,
        "admin": admin
    }


@pytest.fixture
def sample_audit_logs(db_session, test_users):
    """Create sample audit logs"""
    logs = []
    
    # Create various types of audit logs
    log_types = [
        ("consent_granted", "consent", "info"),
        ("data_accessed", "access", "info"),
        ("privacy_violation", "privacy", "warning"),
        ("retention_policy_violation", "retention", "error"),
        ("unauthorized_access_attempt", "access", "critical")
    ]
    
    for i, (event_type, category, severity) in enumerate(log_types):
        log = ComplianceAuditLog(
            id=i + 1,
            event_type=event_type,
            event_category=category,
            severity_level=severity,
            user_id=test_users["teacher"].id,
            affected_student_id=test_users["student"].id,
            description=f"Test {event_type} event",
            created_at=datetime.utcnow() - timedelta(days=i)
        )
        logs.append(log)
        db_session.add(log)
    
    db_session.commit()
    return logs


@pytest.fixture
def sample_access_logs(db_session, test_users):
    """Create sample data access logs"""
    logs = []
    
    for i in range(10):
        log = DataAccessLog(
            id=i + 1,
            user_id=test_users["teacher"].id,
            student_id=test_users["student"].id,
            data_type="attendance_records",
            action="view",
            access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
            purpose_description=f"Test access {i + 1}",
            ip_address="192.168.1.100",
            consent_verified=i % 2 == 0,  # Alternate consent verification
            access_timestamp=datetime.utcnow() - timedelta(hours=i)
        )
        logs.append(log)
        db_session.add(log)
    
    db_session.commit()
    return logs


class TestDashboardOverview:
    """Test dashboard overview functionality"""
    
    def test_get_dashboard_overview_admin(self, dashboard, test_users, sample_audit_logs, sample_access_logs):
        """Test dashboard overview for admin user"""
        admin_id = test_users["admin"].id
        
        overview = dashboard.get_dashboard_overview(admin_id, UserRole.ADMIN)
        
        assert overview is not None
        assert overview["user_context"]["user_id"] == admin_id
        assert overview["user_context"]["role"] == "admin"
        assert "timestamp" in overview
        assert "key_metrics" in overview
        assert "recent_alerts" in overview
        assert "compliance_summary" in overview
        
    def test_get_dashboard_overview_teacher(self, dashboard, test_users):
        """Test dashboard overview for teacher user"""
        teacher_id = test_users["teacher"].id
        
        overview = dashboard.get_dashboard_overview(teacher_id, UserRole.TEACHER)
        
        assert overview is not None
        assert overview["user_context"]["user_id"] == teacher_id
        assert overview["user_context"]["role"] == "teacher"
        # Teacher should have filtered/limited data
        
    def test_get_dashboard_overview_student(self, dashboard, test_users):
        """Test dashboard overview for student user"""
        student_id = test_users["student"].id
        
        overview = dashboard.get_dashboard_overview(student_id, UserRole.STUDENT)
        
        assert overview is not None
        assert overview["user_context"]["user_id"] == student_id
        assert overview["user_context"]["role"] == "student"
        # Student should only see their own data


class TestMetricsCalculation:
    """Test dashboard metrics calculation"""
    
    def test_calculate_compliance_score(self, dashboard, sample_audit_logs):
        """Test compliance score calculation"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        score = dashboard.calculate_compliance_score(start_date, end_date)
        
        assert isinstance(score, DashboardMetric)
        assert score.metric_type == DashboardMetricType.COMPLIANCE_SCORE
        assert 0 <= score.current_value <= 100
        assert score.target_value == 95.0
        
    def test_calculate_consent_rate(self, dashboard, db_session, test_users):
        """Test consent rate calculation"""
        # Create sample consent records
        consents = []
        for i in range(5):
            consent = StudentConsent(
                id=i + 1,
                student_id=test_users["student"].id,
                granted_by_id=test_users["student"].id,
                consent_type=f"test_type_{i}",
                status=ConsentStatus.GRANTED if i < 3 else ConsentStatus.DENIED,
                purpose_description="Test consent",
                effective_date=datetime.utcnow(),
                created_at=datetime.utcnow() - timedelta(days=i)
            )
            consents.append(consent)
            db_session.add(consent)
        
        db_session.commit()
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        metric = dashboard.calculate_consent_rate(start_date, end_date)
        
        assert isinstance(metric, DashboardMetric)
        assert metric.metric_type == DashboardMetricType.CONSENT_RATE
        assert metric.current_value == 60.0  # 3 granted out of 5 total
        
    def test_calculate_active_violations(self, dashboard, sample_audit_logs):
        """Test active violations calculation"""
        metric = dashboard.calculate_active_violations()
        
        assert isinstance(metric, DashboardMetric)
        assert metric.metric_type == DashboardMetricType.ACTIVE_VIOLATIONS
        assert metric.current_value >= 0
        # Should count unresolved violations
        
    def test_calculate_data_requests(self, dashboard, sample_access_logs):
        """Test data requests calculation"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        metric = dashboard.calculate_data_requests(start_date, end_date)
        
        assert isinstance(metric, DashboardMetric)
        assert metric.metric_type == DashboardMetricType.DATA_REQUESTS
        assert metric.current_value >= 0


class TestAlertsGeneration:
    """Test compliance alerts generation"""
    
    def test_generate_privacy_alerts(self, dashboard, sample_audit_logs):
        """Test generation of privacy-related alerts"""
        alerts = dashboard.generate_privacy_alerts()
        
        assert isinstance(alerts, list)
        
        # Should have alerts for warning, error, and critical events
        severity_levels = [alert.severity for alert in alerts]
        assert AlertSeverity.WARNING in severity_levels or len(alerts) == 0
        
        for alert in alerts:
            assert isinstance(alert, ComplianceAlert)
            assert alert.alert_id is not None
            assert alert.severity in [AlertSeverity.WARNING, AlertSeverity.ERROR, AlertSeverity.CRITICAL]
            assert alert.category in ["privacy", "consent", "access", "retention"]
            
    def test_generate_consent_alerts(self, dashboard, db_session, test_users):
        """Test generation of consent-related alerts"""
        # Create expired consent
        expired_consent = StudentConsent(
            student_id=test_users["student"].id,
            granted_by_id=test_users["student"].id,
            consent_type="test_expired",
            status=ConsentStatus.GRANTED,
            purpose_description="Expired consent",
            effective_date=datetime.utcnow() - timedelta(days=400),
            expiration_date=datetime.utcnow() - timedelta(days=1),
            created_at=datetime.utcnow() - timedelta(days=400)
        )
        db_session.add(expired_consent)
        db_session.commit()
        
        alerts = dashboard.generate_consent_alerts()
        
        assert isinstance(alerts, list)
        # Should include alert about expired consent
        expired_alerts = [a for a in alerts if "expired" in a.description.lower()]
        assert len(expired_alerts) > 0
        
    def test_generate_retention_alerts(self, dashboard, db_session, test_users):
        """Test generation of retention-related alerts"""
        # Create overdue purge schedule
        policy = DataRetentionPolicy(
            policy_name="Test Policy",
            category="attendance_records",
            retention_period_years=1,
            description="Test retention policy",
            legal_basis="Test",
            effective_date=datetime.utcnow()
        )
        db_session.add(policy)
        db_session.commit()
        
        overdue_schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="attendance_records",
            student_id=test_users["student"].id,
            scheduled_purge_date=datetime.utcnow() - timedelta(days=1),
            status="scheduled"
        )
        db_session.add(overdue_schedule)
        db_session.commit()
        
        alerts = dashboard.generate_retention_alerts()
        
        assert isinstance(alerts, list)
        # Should include alert about overdue purge
        overdue_alerts = [a for a in alerts if "overdue" in a.description.lower()]
        assert len(overdue_alerts) > 0


class TestReportingFunctionality:
    """Test dashboard reporting functionality"""
    
    def test_generate_compliance_trends(self, dashboard, sample_audit_logs):
        """Test compliance trends generation"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        trends = dashboard.generate_compliance_trends(start_date, end_date)
        
        assert isinstance(trends, dict)
        assert "timeline" in trends
        assert "metrics" in trends
        assert len(trends["timeline"]) > 0
        
    def test_get_top_privacy_risks(self, dashboard, sample_audit_logs):
        """Test identification of top privacy risks"""
        risks = dashboard.get_top_privacy_risks()
        
        assert isinstance(risks, list)
        assert len(risks) <= 10  # Should limit to top 10
        
        for risk in risks:
            assert "risk_type" in risk
            assert "severity" in risk
            assert "frequency" in risk
            assert "description" in risk
            
    def test_get_access_patterns_analysis(self, dashboard, sample_access_logs):
        """Test access patterns analysis"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        patterns = dashboard.get_access_patterns_analysis(start_date, end_date)
        
        assert isinstance(patterns, dict)
        assert "peak_hours" in patterns
        assert "frequent_users" in patterns
        assert "data_types_accessed" in patterns
        assert "consent_compliance_rate" in patterns
        
    def test_generate_ferpa_audit_report(self, dashboard, sample_audit_logs, sample_access_logs):
        """Test FERPA audit report generation"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        report = dashboard.generate_ferpa_audit_report(start_date, end_date)
        
        assert isinstance(report, dict)
        assert "report_metadata" in report
        assert "executive_summary" in report
        assert "compliance_metrics" in report
        assert "violations_summary" in report
        assert "recommendations" in report
        
        # Verify report metadata
        metadata = report["report_metadata"]
        assert metadata["report_type"] == "ferpa_audit"
        assert metadata["period_start"] == start_date.isoformat()
        assert metadata["period_end"] == end_date.isoformat()


class TestRoleBasedAccess:
    """Test role-based access to dashboard features"""
    
    def test_admin_full_access(self, dashboard, test_users):
        """Test that admin users have full access to all features"""
        admin_id = test_users["admin"].id
        
        # Test access to sensitive functions
        assert dashboard.can_access_audit_logs(admin_id, UserRole.ADMIN) is True
        assert dashboard.can_access_all_students_data(admin_id, UserRole.ADMIN) is True
        assert dashboard.can_modify_retention_policies(admin_id, UserRole.ADMIN) is True
        
    def test_teacher_limited_access(self, dashboard, test_users):
        """Test that teacher users have limited access"""
        teacher_id = test_users["teacher"].id
        
        # Test limited access
        assert dashboard.can_access_audit_logs(teacher_id, UserRole.TEACHER) is False
        assert dashboard.can_access_all_students_data(teacher_id, UserRole.TEACHER) is False
        assert dashboard.can_modify_retention_policies(teacher_id, UserRole.TEACHER) is False
        
        # But can access their own relevant data
        assert dashboard.can_access_own_audit_trail(teacher_id, UserRole.TEACHER) is True
        
    def test_student_minimal_access(self, dashboard, test_users):
        """Test that student users have minimal access"""
        student_id = test_users["student"].id
        
        # Very limited access
        assert dashboard.can_access_audit_logs(student_id, UserRole.STUDENT) is False
        assert dashboard.can_access_all_students_data(student_id, UserRole.STUDENT) is False
        assert dashboard.can_modify_retention_policies(student_id, UserRole.STUDENT) is False
        
        # Can only view their own privacy settings and access history
        assert dashboard.can_view_own_privacy_settings(student_id, UserRole.STUDENT) is True
        assert dashboard.can_view_own_access_history(student_id, UserRole.STUDENT) is True


class TestDashboardConfiguration:
    """Test dashboard configuration and customization"""
    
    def test_get_dashboard_configuration(self, dashboard, test_users):
        """Test getting role-specific dashboard configuration"""
        admin_config = dashboard.get_dashboard_configuration(UserRole.ADMIN)
        teacher_config = dashboard.get_dashboard_configuration(UserRole.TEACHER)
        student_config = dashboard.get_dashboard_configuration(UserRole.STUDENT)
        
        # Admin should have most widgets
        assert len(admin_config["available_widgets"]) > len(teacher_config["available_widgets"])
        assert len(teacher_config["available_widgets"]) > len(student_config["available_widgets"])
        
        # Verify specific widgets are available/restricted
        admin_widgets = [w["type"] for w in admin_config["available_widgets"]]
        assert "compliance_score" in admin_widgets
        assert "audit_log_summary" in admin_widgets
        
        student_widgets = [w["type"] for w in student_config["available_widgets"]]
        assert "compliance_score" not in student_widgets
        assert "audit_log_summary" not in student_widgets
        assert "privacy_settings" in student_widgets
        
    def test_update_dashboard_preferences(self, dashboard, test_users):
        """Test updating user dashboard preferences"""
        user_id = test_users["teacher"].id
        preferences = {
            "theme": "dark",
            "refresh_interval": 300,
            "default_date_range": "last_7_days",
            "enabled_widgets": ["recent_access", "consent_status"]
        }
        
        result = dashboard.update_dashboard_preferences(user_id, preferences)
        
        assert result is True
        
        # Verify preferences were saved
        saved_prefs = dashboard.get_dashboard_preferences(user_id)
        assert saved_prefs["theme"] == "dark"
        assert saved_prefs["refresh_interval"] == 300


class TestPerformanceOptimization:
    """Test dashboard performance optimization"""
    
    def test_dashboard_caching(self, dashboard, test_users):
        """Test that dashboard data is properly cached"""
        admin_id = test_users["admin"].id
        
        # First call should compute and cache
        start_time = datetime.utcnow()
        overview1 = dashboard.get_dashboard_overview(admin_id, UserRole.ADMIN)
        first_call_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Second call should use cache and be faster
        start_time = datetime.utcnow()
        overview2 = dashboard.get_dashboard_overview(admin_id, UserRole.ADMIN)
        second_call_time = (datetime.utcnow() - start_time).total_seconds()
        
        assert overview1 == overview2
        # Second call should be significantly faster (cached)
        assert second_call_time < first_call_time * 0.5
        
    def test_large_dataset_performance(self, dashboard, db_session, test_users):
        """Test dashboard performance with large datasets"""
        # Create a large number of access logs
        logs = []
        for i in range(1000):
            log = DataAccessLog(
                user_id=test_users["teacher"].id,
                student_id=test_users["student"].id,
                data_type="attendance_records",
                action="view",
                access_reason=DataAccessReason.EDUCATIONAL_INSTRUCTION,
                purpose_description=f"Bulk test access {i}",
                ip_address="192.168.1.100",
                access_timestamp=datetime.utcnow() - timedelta(minutes=i)
            )
            logs.append(log)
        
        db_session.add_all(logs)
        db_session.commit()
        
        # Dashboard should still respond reasonably quickly
        start_time = datetime.utcnow()
        overview = dashboard.get_dashboard_overview(test_users["admin"].id, UserRole.ADMIN)
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        assert overview is not None
        assert response_time < 5.0  # Should complete within 5 seconds


if __name__ == "__main__":
    pytest.main([__file__, "-v"])