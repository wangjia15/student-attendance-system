"""
Test cases for FERPA Data Retention Engine

Comprehensive test suite for validating automated data retention
and purging functionality for FERPA compliance.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.compliance.retention_engine import DataRetentionEngine
from app.models.ferpa import (
    DataRetentionPolicy, DataPurgeSchedule, DataRetentionCategory
)
from app.models.user import User, UserRole
from app.models.attendance import AttendanceRecord
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
def retention_engine(db_session):
    """Create DataRetentionEngine instance"""
    return DataRetentionEngine(db_session)


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
    
    db_session.add_all([student, teacher])
    db_session.commit()
    
    return {"student": student, "teacher": teacher}


@pytest.fixture
def sample_retention_policies(db_session):
    """Create sample retention policies"""
    policies = []
    
    # Attendance records policy - 7 years
    policy1 = DataRetentionPolicy(
        id=1,
        policy_name="Attendance Records Retention",
        category=DataRetentionCategory.ATTENDANCE_RECORDS,
        retention_period_years=7,
        retention_period_months=0,
        retention_period_days=0,
        description="Retain attendance records for 7 years per FERPA requirements",
        legal_basis="FERPA Section 99.3",
        auto_purge_enabled=True,
        warning_period_days=30,
        effective_date=datetime.utcnow()
    )
    
    # Academic records policy - 5 years
    policy2 = DataRetentionPolicy(
        id=2,
        policy_name="Academic Records Retention",
        category=DataRetentionCategory.ACADEMIC_RECORDS,
        retention_period_years=5,
        retention_period_months=0,
        retention_period_days=0,
        description="Retain academic records for 5 years",
        legal_basis="FERPA requirements",
        auto_purge_enabled=True,
        warning_period_days=60,
        effective_date=datetime.utcnow()
    )
    
    # Short-term policy for testing
    policy3 = DataRetentionPolicy(
        id=3,
        policy_name="Test Short Retention",
        category=DataRetentionCategory.COMMUNICATION_LOGS,
        retention_period_years=0,
        retention_period_months=0,
        retention_period_days=30,
        description="Short retention for testing",
        legal_basis="Test purposes",
        auto_purge_enabled=True,
        warning_period_days=5,
        effective_date=datetime.utcnow()
    )
    
    policies = [policy1, policy2, policy3]
    db_session.add_all(policies)
    db_session.commit()
    
    return policies


class TestRetentionPolicyManagement:
    """Test retention policy management functionality"""
    
    def test_create_retention_policy(self, retention_engine):
        """Test creating new retention policy"""
        policy = retention_engine.create_retention_policy(
            policy_name="Test Policy",
            category=DataRetentionCategory.DISCIPLINARY_RECORDS,
            retention_years=3,
            retention_months=6,
            retention_days=15,
            description="Test disciplinary records retention",
            legal_basis="School district policy",
            auto_purge_enabled=True,
            warning_period_days=45
        )
        
        assert policy is not None
        assert policy.policy_name == "Test Policy"
        assert policy.category == DataRetentionCategory.DISCIPLINARY_RECORDS
        assert policy.retention_period_years == 3
        assert policy.retention_period_months == 6
        assert policy.retention_period_days == 15
        assert policy.auto_purge_enabled is True
        assert policy.warning_period_days == 45
        
    def test_get_retention_policies_by_category(self, retention_engine, sample_retention_policies):
        """Test retrieving retention policies by category"""
        policies = retention_engine.get_retention_policies_by_category(
            DataRetentionCategory.ATTENDANCE_RECORDS
        )
        
        assert len(policies) == 1
        assert policies[0].category == DataRetentionCategory.ATTENDANCE_RECORDS
        assert policies[0].policy_name == "Attendance Records Retention"
        
    def test_update_retention_policy(self, retention_engine, sample_retention_policies):
        """Test updating existing retention policy"""
        policy = sample_retention_policies[0]  # Attendance policy
        
        updated_policy = retention_engine.update_retention_policy(
            policy_id=policy.id,
            updates={
                "retention_period_years": 10,
                "warning_period_days": 45
            }
        )
        
        assert updated_policy.retention_period_years == 10
        assert updated_policy.warning_period_days == 45
        assert updated_policy.policy_name == "Attendance Records Retention"  # Unchanged
        
    def test_deactivate_retention_policy(self, retention_engine, sample_retention_policies):
        """Test deactivating retention policy"""
        policy = sample_retention_policies[0]
        
        deactivated = retention_engine.deactivate_retention_policy(policy.id)
        
        assert deactivated.is_active is False


class TestDataPurgeScheduling:
    """Test data purge scheduling functionality"""
    
    def test_schedule_record_for_purge(self, retention_engine, sample_retention_policies, test_users):
        """Test scheduling individual record for purge"""
        policy = sample_retention_policies[0]  # 7-year attendance policy
        student_id = test_users["student"].id
        
        # Simulate old record
        record_created_date = datetime.utcnow() - timedelta(days=2500)  # ~6.8 years ago
        
        schedule = retention_engine.schedule_record_for_purge(
            table_name="attendance_records",
            record_id=123,
            student_id=student_id,
            policy=policy,
            record_created_date=record_created_date
        )
        
        assert schedule is not None
        assert schedule.table_name == "attendance_records"
        assert schedule.record_id == 123
        assert schedule.student_id == student_id
        assert schedule.policy_id == policy.id
        assert schedule.status == "scheduled"
        
        # Calculate expected purge date
        expected_purge = record_created_date + timedelta(days=365 * 7)  # 7 years
        actual_purge = schedule.scheduled_purge_date
        
        # Should be within a day of expected (accounting for calculation differences)
        assert abs((actual_purge - expected_purge).total_seconds()) < 86400
        
    def test_bulk_schedule_records(self, retention_engine, sample_retention_policies, test_users):
        """Test bulk scheduling of records for purge"""
        policy = sample_retention_policies[2]  # 30-day policy
        student_id = test_users["student"].id
        
        # Create list of old records
        records_to_schedule = [
            {
                "table_name": "communication_logs",
                "record_id": i,
                "student_id": student_id,
                "record_created_date": datetime.utcnow() - timedelta(days=20 + i)
            }
            for i in range(1, 6)  # 5 records
        ]
        
        schedules = retention_engine.bulk_schedule_records_for_purge(
            records=records_to_schedule,
            policy=policy
        )
        
        assert len(schedules) == 5
        assert all(s.policy_id == policy.id for s in schedules)
        assert all(s.status == "scheduled" for s in schedules)
        
    def test_auto_schedule_by_policy(self, retention_engine, sample_retention_policies):
        """Test automatic scheduling based on policy scanning"""
        policy = sample_retention_policies[2]  # 30-day policy
        
        # This would normally scan database tables for records matching the policy
        # For testing, we'll mock the database scan
        with patch.object(retention_engine, '_scan_table_for_expired_records') as mock_scan:
            mock_scan.return_value = [
                {"table_name": "communication_logs", "record_id": 1, "student_id": 1, "created_date": datetime.utcnow() - timedelta(days=35)},
                {"table_name": "communication_logs", "record_id": 2, "student_id": 1, "created_date": datetime.utcnow() - timedelta(days=40)}
            ]
            
            scheduled_count = retention_engine.auto_schedule_by_policy(policy.id)
            
            assert scheduled_count == 2
            mock_scan.assert_called_once()


class TestPurgeExecution:
    """Test data purge execution functionality"""
    
    def test_get_records_due_for_purge(self, retention_engine, sample_retention_policies, test_users):
        """Test getting records that are due for purging"""
        policy = sample_retention_policies[2]  # 30-day policy
        student_id = test_users["student"].id
        
        # Create overdue purge schedule
        overdue_schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=999,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() - timedelta(days=1),  # Due yesterday
            status="scheduled"
        )
        retention_engine.db.add(overdue_schedule)
        retention_engine.db.commit()
        
        due_records = retention_engine.get_records_due_for_purge(days_ahead=0)
        
        assert len(due_records) >= 1
        assert any(record.record_id == 999 for record in due_records)
        assert all(record.scheduled_purge_date <= datetime.utcnow() for record in due_records)
        
    def test_get_records_needing_warning(self, retention_engine, sample_retention_policies, test_users):
        """Test getting records that need purge warnings"""
        policy = sample_retention_policies[0]  # 30-day warning period
        student_id = test_users["student"].id
        
        # Create schedule that needs warning
        warning_schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="attendance_records",
            record_id=888,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() + timedelta(days=15),  # Within warning period
            status="scheduled"
        )
        retention_engine.db.add(warning_schedule)
        retention_engine.db.commit()
        
        warning_records = retention_engine.get_records_needing_warning()
        
        assert len(warning_records) >= 1
        assert any(record.record_id == 888 for record in warning_records)
        
    def test_send_purge_warning(self, retention_engine, sample_retention_policies, test_users):
        """Test sending purge warning"""
        policy = sample_retention_policies[0]
        student_id = test_users["student"].id
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="attendance_records",
            record_id=777,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() + timedelta(days=15),
            status="scheduled"
        )
        retention_engine.db.add(schedule)
        retention_engine.db.commit()
        
        with patch.object(retention_engine, '_send_notification') as mock_notify:
            result = retention_engine.send_purge_warning(schedule.id)
            
            assert result is True
            mock_notify.assert_called_once()
            
            # Refresh to check status update
            retention_engine.db.refresh(schedule)
            assert schedule.status == "warned"
            assert schedule.warning_sent_date is not None
            
    def test_execute_purge_single_record(self, retention_engine, sample_retention_policies, test_users):
        """Test executing purge for single record"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=666,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() - timedelta(days=1),
            status="warned"
        )
        retention_engine.db.add(schedule)
        retention_engine.db.commit()
        
        with patch.object(retention_engine, '_execute_actual_purge') as mock_purge:
            mock_purge.return_value = True
            
            result = retention_engine.execute_purge(schedule.id, executed_by_id=test_users["teacher"].id)
            
            assert result is True
            mock_purge.assert_called_once()
            
            # Check status update
            retention_engine.db.refresh(schedule)
            assert schedule.status == "purged"
            assert schedule.actual_purge_date is not None
            
    def test_execute_bulk_purge(self, retention_engine, sample_retention_policies, test_users):
        """Test executing bulk purge operation"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        # Create multiple schedules due for purge
        schedules = []
        for i in range(3):
            schedule = DataPurgeSchedule(
                policy_id=policy.id,
                table_name="communication_logs",
                record_id=500 + i,
                student_id=student_id,
                scheduled_purge_date=datetime.utcnow() - timedelta(days=1),
                status="warned"
            )
            schedules.append(schedule)
            retention_engine.db.add(schedule)
        
        retention_engine.db.commit()
        
        schedule_ids = [s.id for s in schedules]
        
        with patch.object(retention_engine, '_execute_actual_purge') as mock_purge:
            mock_purge.return_value = True
            
            results = retention_engine.execute_bulk_purge(
                schedule_ids=schedule_ids,
                executed_by_id=test_users["teacher"].id
            )
            
            assert len(results) == 3
            assert all(r["success"] for r in results)
            assert mock_purge.call_count == 3


class TestPurgeExemptions:
    """Test purge exemption functionality"""
    
    def test_grant_purge_exemption(self, retention_engine, sample_retention_policies, test_users):
        """Test granting exemption from purge"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=555,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() - timedelta(days=1),
            status="scheduled"
        )
        retention_engine.db.add(schedule)
        retention_engine.db.commit()
        
        exemption = retention_engine.grant_purge_exemption(
            schedule_id=schedule.id,
            reason="Required for ongoing investigation",
            granted_by_id=test_users["teacher"].id,
            exemption_period_days=90
        )
        
        assert exemption is not None
        retention_engine.db.refresh(schedule)
        assert schedule.status == "exempted"
        assert schedule.exemption_reason == "Required for ongoing investigation"
        assert schedule.exemption_granted_by == test_users["teacher"].id
        assert schedule.exemption_expires is not None
        
    def test_revoke_purge_exemption(self, retention_engine, sample_retention_policies, test_users):
        """Test revoking purge exemption"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=444,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() + timedelta(days=30),
            status="exempted",
            exemption_reason="Test exemption",
            exemption_granted_by=test_users["teacher"].id,
            exemption_expires=datetime.utcnow() + timedelta(days=90)
        )
        retention_engine.db.add(schedule)
        retention_engine.db.commit()
        
        result = retention_engine.revoke_purge_exemption(
            schedule_id=schedule.id,
            revoked_by_id=test_users["teacher"].id,
            reason="Investigation completed"
        )
        
        assert result is True
        retention_engine.db.refresh(schedule)
        assert schedule.status == "scheduled"
        assert schedule.exemption_reason is None
        
    def test_check_expired_exemptions(self, retention_engine, sample_retention_policies, test_users):
        """Test checking for expired exemptions"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        # Create exemption that expired yesterday
        expired_schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=333,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() + timedelta(days=30),
            status="exempted",
            exemption_reason="Expired exemption",
            exemption_granted_by=test_users["teacher"].id,
            exemption_expires=datetime.utcnow() - timedelta(days=1)
        )
        retention_engine.db.add(expired_schedule)
        retention_engine.db.commit()
        
        expired_exemptions = retention_engine.check_expired_exemptions()
        
        assert len(expired_exemptions) >= 1
        assert any(e.record_id == 333 for e in expired_exemptions)


class TestRetentionReporting:
    """Test retention reporting functionality"""
    
    def test_generate_retention_report(self, retention_engine, sample_retention_policies, test_users):
        """Test generating retention compliance report"""
        # Create some test schedules
        policy = sample_retention_policies[0]
        student_id = test_users["student"].id
        
        schedules = []
        statuses = ["scheduled", "warned", "purged", "exempted"]
        for i, status in enumerate(statuses):
            schedule = DataPurgeSchedule(
                policy_id=policy.id,
                table_name="attendance_records",
                record_id=200 + i,
                student_id=student_id,
                scheduled_purge_date=datetime.utcnow() + timedelta(days=i * 10),
                status=status,
                actual_purge_date=datetime.utcnow() if status == "purged" else None
            )
            schedules.append(schedule)
            retention_engine.db.add(schedule)
        
        retention_engine.db.commit()
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        report = retention_engine.generate_retention_report(start_date, end_date)
        
        assert isinstance(report, dict)
        assert "report_metadata" in report
        assert "policy_compliance" in report
        assert "purge_statistics" in report
        assert "exemption_summary" in report
        assert "upcoming_purges" in report
        
    def test_get_retention_statistics(self, retention_engine, sample_retention_policies):
        """Test getting retention statistics"""
        stats = retention_engine.get_retention_statistics()
        
        assert isinstance(stats, dict)
        assert "total_policies" in stats
        assert "active_policies" in stats
        assert "total_scheduled_purges" in stats
        assert "overdue_purges" in stats
        assert "exempted_records" in stats
        
        assert stats["total_policies"] >= len(sample_retention_policies)
        
    def test_get_policy_compliance_summary(self, retention_engine, sample_retention_policies):
        """Test getting policy compliance summary"""
        policy = sample_retention_policies[0]
        
        summary = retention_engine.get_policy_compliance_summary(policy.id)
        
        assert isinstance(summary, dict)
        assert "policy_details" in summary
        assert "scheduled_records" in summary
        assert "compliance_rate" in summary
        assert "average_retention_time" in summary


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_purge_nonexistent_schedule(self, retention_engine, test_users):
        """Test purging non-existent schedule"""
        result = retention_engine.execute_purge(
            schedule_id=99999,
            executed_by_id=test_users["teacher"].id
        )
        
        assert result is False
        
    def test_invalid_policy_category(self, retention_engine):
        """Test creating policy with invalid category"""
        with pytest.raises(ValueError):
            retention_engine.create_retention_policy(
                policy_name="Invalid Policy",
                category="invalid_category",
                retention_years=1,
                retention_months=0,
                retention_days=0,
                description="Invalid policy",
                legal_basis="Test"
            )
            
    def test_negative_retention_periods(self, retention_engine):
        """Test handling negative retention periods"""
        with pytest.raises(ValueError):
            retention_engine.create_retention_policy(
                policy_name="Negative Policy",
                category=DataRetentionCategory.ATTENDANCE_RECORDS,
                retention_years=-1,
                retention_months=0,
                retention_days=0,
                description="Negative retention",
                legal_basis="Test"
            )
            
    def test_purge_execution_failure(self, retention_engine, sample_retention_policies, test_users):
        """Test handling purge execution failure"""
        policy = sample_retention_policies[2]
        student_id = test_users["student"].id
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name="communication_logs",
            record_id=111,
            student_id=student_id,
            scheduled_purge_date=datetime.utcnow() - timedelta(days=1),
            status="warned"
        )
        retention_engine.db.add(schedule)
        retention_engine.db.commit()
        
        # Mock purge to fail
        with patch.object(retention_engine, '_execute_actual_purge') as mock_purge:
            mock_purge.side_effect = Exception("Database error")
            
            result = retention_engine.execute_purge(
                schedule.id, 
                executed_by_id=test_users["teacher"].id
            )
            
            assert result is False
            
            # Status should remain unchanged
            retention_engine.db.refresh(schedule)
            assert schedule.status == "warned"
            assert schedule.actual_purge_date is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])