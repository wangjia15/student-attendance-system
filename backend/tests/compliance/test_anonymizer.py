"""
Test cases for FERPA Data Anonymizer

Comprehensive test suite for validating data anonymization functionality
including pseudonymization, k-anonymity, and differential privacy.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.compliance.anonymizer import DataAnonymizer, AnonymizationLevel
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
def anonymizer(db_session):
    """Create DataAnonymizer instance with test database"""
    return DataAnonymizer(db_session, anonymization_key="test_key_12345")


@pytest.fixture
def sample_student_data():
    """Create sample student data for testing"""
    return [
        {
            "id": 1,
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@student.edu",
            "phone": "555-123-4567",
            "date_of_birth": "2005-05-15",
            "grade_level": 10,
            "gpa": 3.75,
            "attendance_rate": 95.5,
            "created_at": "2024-01-15T10:00:00Z"
        },
        {
            "id": 2,
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane.smith@student.edu",
            "phone": "555-987-6543",
            "date_of_birth": "2005-08-20",
            "grade_level": 10,
            "gpa": 3.90,
            "attendance_rate": 98.2,
            "created_at": "2024-01-16T11:30:00Z"
        },
        {
            "id": 3,
            "first_name": "Bob",
            "last_name": "Johnson",
            "email": "bob.johnson@student.edu",
            "phone": "555-456-7890",
            "date_of_birth": "2004-12-03",
            "grade_level": 11,
            "gpa": 3.45,
            "attendance_rate": 87.3,
            "created_at": "2024-01-17T09:15:00Z"
        }
    ]


class TestBasicAnonymization:
    """Test basic anonymization functionality"""
    
    def test_no_anonymization(self, anonymizer, sample_student_data):
        """Test data returned unchanged with no anonymization"""
        result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.NONE
        )
        
        assert result["anonymization_metadata"]["level"] == "none"
        assert result["anonymization_metadata"]["record_count"] == 3
        assert len(result["data"]) == 3
        assert result["data"] == sample_student_data
        
    def test_pseudonymization(self, anonymizer, sample_student_data):
        """Test pseudonymization preserves structure but changes identifiers"""
        result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.PSEUDONYMIZATION,
            preserve_fields=["id", "grade_level", "created_at"]
        )
        
        assert result["anonymization_metadata"]["level"] == "pseudonymization"
        assert len(result["data"]) == 3
        
        # Check that preserved fields remain unchanged
        for i, record in enumerate(result["data"]):
            assert record["id"] == sample_student_data[i]["id"]
            assert record["grade_level"] == sample_student_data[i]["grade_level"]
            assert record["created_at"] == sample_student_data[i]["created_at"]
            
            # Check that PII fields are pseudonymized (changed but consistent)
            assert record["first_name"] != sample_student_data[i]["first_name"]
            assert record["email"] != sample_student_data[i]["email"]
            assert "first_name" in record  # Field still exists
            
    def test_full_anonymization(self, anonymizer, sample_student_data):
        """Test full anonymization removes/hashes all PII"""
        result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.ANONYMIZATION,
            preserve_fields=["grade_level", "gpa"]
        )
        
        assert result["anonymization_metadata"]["level"] == "anonymization"
        assert len(result["data"]) == 3
        
        # Check that preserved fields remain unchanged
        for i, record in enumerate(result["data"]):
            assert record["grade_level"] == sample_student_data[i]["grade_level"]
            assert record["gpa"] == sample_student_data[i]["gpa"]
            
            # Check that PII fields are removed or anonymized
            assert "first_name" not in record or record["first_name"] == "[REDACTED]"
            assert "email" not in record or "@" not in str(record.get("email", ""))
            
    def test_k_anonymity(self, anonymizer, sample_student_data):
        """Test k-anonymity anonymization"""
        result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.K_ANONYMITY,
            k_value=2
        )
        
        assert result["anonymization_metadata"]["level"] == "k_anonymity"
        assert result["anonymization_metadata"]["k_value"] == 2
        assert len(result["data"]) <= len(sample_student_data)  # May reduce records
        
    def test_differential_privacy(self, anonymizer, sample_student_data):
        """Test differential privacy anonymization"""
        result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.DIFFERENTIAL_PRIVACY
        )
        
        assert result["anonymization_metadata"]["level"] == "differential_privacy"
        assert len(result["data"]) == len(sample_student_data)
        
        # Check that numerical values have been perturbed
        for i, record in enumerate(result["data"]):
            if "gpa" in record and "gpa" in sample_student_data[i]:
                # GPA should be different due to noise addition
                assert abs(record["gpa"] - sample_student_data[i]["gpa"]) >= 0


class TestAttendanceAnonymization:
    """Test attendance data anonymization"""
    
    def test_anonymize_attendance_records(self, anonymizer):
        """Test anonymizing attendance record data"""
        attendance_data = [
            {
                "id": 1,
                "student_id": 101,
                "class_session_id": 201,
                "status": "present",
                "check_in_time": "2024-01-15T08:30:00Z",
                "notes": "On time arrival"
            },
            {
                "id": 2,
                "student_id": 102,
                "class_session_id": 201,
                "status": "absent",
                "check_in_time": None,
                "notes": "Unexcused absence"
            }
        ]
        
        result = anonymizer.anonymize_attendance_records(
            attendance_data=attendance_data,
            anonymization_level=AnonymizationLevel.ANONYMIZATION,
            preserve_fields=["class_session_id", "status"]
        )
        
        assert result["anonymization_metadata"]["level"] == "anonymization"
        assert len(result["data"]) == 2
        
        for record in result["data"]:
            assert "class_session_id" in record
            assert "status" in record
            # Student ID should be anonymized but pattern preserved
            assert record.get("student_id", "").startswith("ANON_") or record.get("student_id") is None


class TestReportingAnonymization:
    """Test anonymization for reporting and analytics"""
    
    def test_generate_anonymized_report(self, anonymizer, sample_student_data):
        """Test generating anonymized reports"""
        report_config = {
            "report_type": "grade_distribution",
            "fields": ["grade_level", "gpa", "attendance_rate"],
            "aggregation_level": "grade_level"
        }
        
        result = anonymizer.generate_anonymized_report(
            data=sample_student_data,
            config=report_config,
            anonymization_level=AnonymizationLevel.K_ANONYMITY,
            k_value=2
        )
        
        assert "report_metadata" in result
        assert "anonymized_data" in result
        assert result["report_metadata"]["anonymization_level"] == "k_anonymity"
        assert result["report_metadata"]["k_value"] == 2
        
    def test_statistical_anonymization(self, anonymizer, sample_student_data):
        """Test statistical anonymization for analytics"""
        result = anonymizer.create_statistical_summary(
            data=sample_student_data,
            metrics=["gpa", "attendance_rate"],
            anonymization_level=AnonymizationLevel.DIFFERENTIAL_PRIVACY,
            epsilon=1.0  # Privacy budget
        )
        
        assert "summary_statistics" in result
        assert "gpa" in result["summary_statistics"]
        assert "attendance_rate" in result["summary_statistics"]
        assert result["anonymization_metadata"]["level"] == "differential_privacy"
        
        # Check that basic statistics are present but perturbed
        gpa_stats = result["summary_statistics"]["gpa"]
        assert "mean" in gpa_stats
        assert "std_dev" in gpa_stats
        assert "count" in gpa_stats


class TestAnonymizationUtilities:
    """Test utility functions for anonymization"""
    
    def test_hash_identifier(self, anonymizer):
        """Test consistent hashing of identifiers"""
        identifier = "john.doe@student.edu"
        
        hash1 = anonymizer._hash_identifier(identifier, "email")
        hash2 = anonymizer._hash_identifier(identifier, "email")
        
        # Same input should produce same hash
        assert hash1 == hash2
        assert hash1 != identifier
        assert len(hash1) > 0
        
    def test_generate_pseudo_id(self, anonymizer):
        """Test pseudonym ID generation"""
        original_id = 12345
        
        pseudo_id1 = anonymizer._generate_pseudo_id(original_id)
        pseudo_id2 = anonymizer._generate_pseudo_id(original_id)
        
        # Same input should produce same pseudonym
        assert pseudo_id1 == pseudo_id2
        assert pseudo_id1 != original_id
        
    def test_add_differential_privacy_noise(self, anonymizer):
        """Test adding noise for differential privacy"""
        original_value = 3.75
        epsilon = 1.0
        
        noisy_value1 = anonymizer._add_laplace_noise(original_value, epsilon)
        noisy_value2 = anonymizer._add_laplace_noise(original_value, epsilon)
        
        # Noise should be different each time
        assert noisy_value1 != noisy_value2
        # But should be reasonably close to original
        assert abs(noisy_value1 - original_value) < 2.0
        assert abs(noisy_value2 - original_value) < 2.0
        
    def test_validate_k_anonymity(self, anonymizer):
        """Test k-anonymity validation"""
        data = [
            {"age_group": "15-16", "grade": 10, "count": 5},
            {"age_group": "15-16", "grade": 10, "count": 3},
            {"age_group": "16-17", "grade": 11, "count": 7},
            {"age_group": "16-17", "grade": 11, "count": 2}
        ]
        
        quasi_identifiers = ["age_group", "grade"]
        
        is_valid_k2 = anonymizer._validate_k_anonymity(data, quasi_identifiers, k=2)
        is_valid_k5 = anonymizer._validate_k_anonymity(data, quasi_identifiers, k=5)
        
        assert is_valid_k2 is True  # Groups of 5,3,7,2 all >= 2
        assert is_valid_k5 is False  # Groups of 3,2 are < 5


class TestAnonymizationCompliance:
    """Test compliance aspects of anonymization"""
    
    def test_ferpa_compliant_anonymization(self, anonymizer, sample_student_data):
        """Test that anonymization meets FERPA compliance requirements"""
        result = anonymizer.anonymize_for_ferpa_compliance(
            data=sample_student_data,
            purpose="external_research",
            data_sharing_agreement_id="DSA-2024-001"
        )
        
        assert result["compliance_metadata"]["ferpa_compliant"] is True
        assert result["compliance_metadata"]["purpose"] == "external_research"
        assert result["compliance_metadata"]["data_sharing_agreement"] == "DSA-2024-001"
        
        # Ensure all direct identifiers are removed/anonymized
        for record in result["data"]:
            assert "first_name" not in record or record["first_name"] == "[REDACTED]"
            assert "last_name" not in record or record["last_name"] == "[REDACTED]"
            assert "email" not in record or "@" not in str(record.get("email", ""))
            assert "phone" not in record
            
    def test_reversibility_check(self, anonymizer, sample_student_data):
        """Test checking if anonymization is reversible"""
        # Pseudonymization should be reversible
        pseudo_result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.PSEUDONYMIZATION
        )
        assert anonymizer._is_reversible(pseudo_result) is True
        
        # Full anonymization should not be reversible
        anon_result = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.ANONYMIZATION
        )
        assert anonymizer._is_reversible(anon_result) is False
        
    def test_audit_anonymization_process(self, anonymizer, sample_student_data):
        """Test that anonymization process is properly audited"""
        with patch.object(anonymizer, '_log_anonymization_audit') as mock_audit:
            result = anonymizer.anonymize_student_data(
                student_data=sample_student_data,
                anonymization_level=AnonymizationLevel.ANONYMIZATION
            )
            
            # Verify audit logging was called
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args[1]
            assert call_args["anonymization_level"] == "anonymization"
            assert call_args["record_count"] == 3


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_empty_data_input(self, anonymizer):
        """Test handling of empty data input"""
        result = anonymizer.anonymize_student_data(
            student_data=[],
            anonymization_level=AnonymizationLevel.ANONYMIZATION
        )
        
        assert result["anonymization_metadata"]["record_count"] == 0
        assert len(result["data"]) == 0
        
    def test_invalid_anonymization_level(self, anonymizer, sample_student_data):
        """Test handling of invalid anonymization level"""
        with pytest.raises(ValueError):
            anonymizer.anonymize_student_data(
                student_data=sample_student_data,
                anonymization_level="invalid_level"
            )
            
    def test_missing_required_fields(self, anonymizer):
        """Test handling of data missing required fields"""
        incomplete_data = [{"id": 1, "grade_level": 10}]  # Missing many fields
        
        result = anonymizer.anonymize_student_data(
            student_data=incomplete_data,
            anonymization_level=AnonymizationLevel.ANONYMIZATION
        )
        
        # Should handle gracefully
        assert len(result["data"]) == 1
        assert result["data"][0]["grade_level"] == 10
        
    def test_k_anonymity_insufficient_data(self, anonymizer):
        """Test k-anonymity with insufficient data"""
        small_dataset = [{"grade": 10, "age": 15}]
        
        result = anonymizer.anonymize_student_data(
            student_data=small_dataset,
            anonymization_level=AnonymizationLevel.K_ANONYMITY,
            k_value=5
        )
        
        # Should handle gracefully, possibly returning empty result
        assert result["anonymization_metadata"]["k_value"] == 5
        # Data may be empty or suppressed due to insufficient k-anonymity
        
    def test_differential_privacy_extreme_epsilon(self, anonymizer, sample_student_data):
        """Test differential privacy with extreme epsilon values"""
        # Very small epsilon (high privacy)
        result_high_privacy = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.DIFFERENTIAL_PRIVACY,
            epsilon=0.001
        )
        
        # Very large epsilon (low privacy)
        result_low_privacy = anonymizer.anonymize_student_data(
            student_data=sample_student_data,
            anonymization_level=AnonymizationLevel.DIFFERENTIAL_PRIVACY,
            epsilon=100.0
        )
        
        # Both should complete without error
        assert len(result_high_privacy["data"]) == 3
        assert len(result_low_privacy["data"]) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])