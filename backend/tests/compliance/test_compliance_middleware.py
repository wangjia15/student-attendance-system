"""
Test cases for FERPA Compliance Middleware

Comprehensive test suite for validating middleware functionality
including request filtering, consent verification, and access logging.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from fastapi import Request, Response, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.middleware.compliance import ComplianceMiddleware, get_compliant_db
from app.models.ferpa import DataAccessReason, ConsentType, ConsentStatus
from app.models.user import User, UserRole
from app.core.database import Base
from app.services.privacy_service import PrivacyService


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
def compliance_middleware():
    """Create ComplianceMiddleware instance"""
    return ComplianceMiddleware()


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
def mock_request():
    """Create mock request"""
    request = Mock(spec=Request)
    request.url = Mock()
    request.url.path = "/api/v1/students/1"
    request.method = "GET"
    request.query_params = {}
    request.headers = {"user-agent": "Test Browser"}
    request.client = Mock()
    request.client.host = "192.168.1.100"
    request.cookies = {}
    request.state = Mock()
    request.state.user_id = 2  # Teacher accessing student data
    return request


class TestMiddlewareActivation:
    """Test when middleware is activated"""
    
    def test_requires_compliance_check_student_endpoints(self, compliance_middleware):
        """Test that student data endpoints require compliance checking"""
        test_paths = [
            "/api/v1/students/123",
            "/api/v1/attendance/student/456",
            "/api/v1/grades/789",
            "/api/v1/reports/student-progress",
            "/api/v1/analytics/classroom"
        ]
        
        for path in test_paths:
            request = Mock()
            request.url = Mock()
            request.url.path = path
            
            assert compliance_middleware._requires_compliance_check(request) is True
            
    def test_does_not_require_compliance_check_other_endpoints(self, compliance_middleware):
        """Test that non-student endpoints don't require compliance checking"""
        test_paths = [
            "/api/v1/auth/login",
            "/api/v1/health",
            "/api/v1/system/status",
            "/api/v1/user/profile",
            "/docs"
        ]
        
        for path in test_paths:
            request = Mock()
            request.url = Mock()
            request.url.path = path
            
            assert compliance_middleware._requires_compliance_check(request) is False


class TestUserExtraction:
    """Test user ID extraction from requests"""
    
    def test_get_user_id_from_state(self, compliance_middleware):
        """Test extracting user ID from request state"""
        request = Mock()
        request.state = Mock()
        request.state.user_id = 42
        
        user_id = compliance_middleware._get_user_id(request)
        assert user_id == 42
        
    def test_get_user_id_no_state(self, compliance_middleware):
        """Test extracting user ID when no state exists"""
        request = Mock()
        request.state = Mock()
        delattr(request.state, 'user_id')
        
        user_id = compliance_middleware._get_user_id(request)
        assert user_id is None


class TestStudentIdExtraction:
    """Test student ID extraction from requests"""
    
    def test_extract_student_id_from_path_students(self, compliance_middleware):
        """Test extracting student ID from /students/ path"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/123/grades"
        request.query_params = {}
        
        student_id = compliance_middleware._extract_student_id(request)
        assert student_id == 123
        
    def test_extract_student_id_from_query_params(self, compliance_middleware):
        """Test extracting student ID from query parameters"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/attendance/records"
        request.query_params = {"student_id": "456"}
        
        student_id = compliance_middleware._extract_student_id(request)
        assert student_id == 456
        
    def test_extract_student_id_from_json_body(self, compliance_middleware):
        """Test extracting student ID from request body"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/grades/create"
        request.query_params = {}
        request._json = {"student_id": 789, "grade": "A"}
        
        student_id = compliance_middleware._extract_student_id(request)
        assert student_id == 789
        
    def test_extract_student_id_not_found(self, compliance_middleware):
        """Test when student ID cannot be extracted"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/system/health"
        request.query_params = {}
        
        student_id = compliance_middleware._extract_student_id(request)
        assert student_id is None


class TestAccessPermissions:
    """Test access permission checking"""
    
    @pytest.mark.asyncio
    async def test_admin_can_access_all_data(self, compliance_middleware, test_users):
        """Test that administrators can access all student data"""
        admin = test_users["admin"]
        student_id = test_users["student"].id
        request = Mock()
        
        # Should not raise exception
        await compliance_middleware._check_access_permissions(admin, student_id, request)
        
    @pytest.mark.asyncio
    async def test_student_can_access_own_data(self, compliance_middleware, test_users):
        """Test that students can access their own data"""
        student = test_users["student"]
        request = Mock()
        
        # Should not raise exception
        await compliance_middleware._check_access_permissions(student, student.id, request)
        
    @pytest.mark.asyncio
    async def test_student_cannot_access_other_data(self, compliance_middleware, test_users):
        """Test that students cannot access other students' data"""
        student = test_users["student"]
        other_student_id = 999
        request = Mock()
        
        with pytest.raises(HTTPException) as exc_info:
            await compliance_middleware._check_access_permissions(student, other_student_id, request)
        
        assert exc_info.value.status_code == 403
        assert "Students can only access their own" in str(exc_info.value.detail)
        
    @pytest.mark.asyncio
    async def test_teacher_access_with_relationship(self, compliance_middleware, test_users):
        """Test teacher access when they have educational relationship"""
        teacher = test_users["teacher"]
        student_id = test_users["student"].id
        request = Mock()
        
        # Mock the relationship check to return True
        with patch.object(compliance_middleware, '_teacher_has_access_to_student', return_value=True):
            # Should not raise exception
            await compliance_middleware._check_access_permissions(teacher, student_id, request)
            
    @pytest.mark.asyncio
    async def test_teacher_access_without_relationship(self, compliance_middleware, test_users):
        """Test teacher access denied when no educational relationship"""
        teacher = test_users["teacher"]
        student_id = 999
        request = Mock()
        
        # Mock the relationship check to return False
        with patch.object(compliance_middleware, '_teacher_has_access_to_student', return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await compliance_middleware._check_access_permissions(teacher, student_id, request)
            
            assert exc_info.value.status_code == 403
            assert "No educational relationship" in str(exc_info.value.detail)


class TestConsentVerification:
    """Test consent verification functionality"""
    
    @pytest.mark.asyncio
    async def test_consent_verification_required_missing(self, compliance_middleware, db_session):
        """Test consent verification when consent is required but missing"""
        user_id = 2
        student_id = 1
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1/grades"
        request.method = "GET"
        
        # Mock privacy service to require consent but not have it available
        mock_privacy_service = Mock()
        mock_privacy_service.check_consent_required.return_value = {
            "consent_required": True,
            "consent_available": False
        }
        compliance_middleware.privacy_service = mock_privacy_service
        
        with pytest.raises(HTTPException) as exc_info:
            await compliance_middleware._verify_consent(user_id, student_id, request)
        
        assert exc_info.value.status_code == 403
        assert "requires student/parent consent" in str(exc_info.value.detail)
        
    @pytest.mark.asyncio
    async def test_consent_verification_emergency_access(self, compliance_middleware, db_session):
        """Test that emergency access bypasses consent requirements"""
        user_id = 2
        student_id = 1
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/emergency/student/1"
        request.method = "GET"
        
        # Mock privacy service to require consent but not have it available
        mock_privacy_service = Mock()
        mock_privacy_service.check_consent_required.return_value = {
            "consent_required": True,
            "consent_available": False
        }
        compliance_middleware.privacy_service = mock_privacy_service
        
        # Should not raise exception for emergency access
        await compliance_middleware._verify_consent(user_id, student_id, request)
        
    @pytest.mark.asyncio
    async def test_consent_verification_available(self, compliance_middleware, db_session):
        """Test consent verification when consent is available"""
        user_id = 2
        student_id = 1
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1/attendance"
        request.method = "GET"
        
        # Mock privacy service to have consent available
        mock_privacy_service = Mock()
        mock_privacy_service.check_consent_required.return_value = {
            "consent_required": True,
            "consent_available": True
        }
        compliance_middleware.privacy_service = mock_privacy_service
        
        # Should not raise exception
        await compliance_middleware._verify_consent(user_id, student_id, request)


class TestDataOperationDetermination:
    """Test determination of data operations"""
    
    def test_determine_data_operation_attendance(self, compliance_middleware):
        """Test data operation determination for attendance endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/attendance/student/123"
        request.method = "GET"
        
        data_type, action = compliance_middleware._determine_data_operation(request)
        
        assert data_type == "attendance_records"
        assert action == "view"
        
    def test_determine_data_operation_grades(self, compliance_middleware):
        """Test data operation determination for grades endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/grades/update"
        request.method = "PUT"
        
        data_type, action = compliance_middleware._determine_data_operation(request)
        
        assert data_type == "academic_records"
        assert action == "update"
        
    def test_determine_data_operation_export(self, compliance_middleware):
        """Test data operation determination for export endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/reports/export/student-data"
        request.method = "GET"
        
        data_type, action = compliance_middleware._determine_data_operation(request)
        
        assert data_type == "reports"
        assert action == "export"


class TestAccessReasonDetermination:
    """Test determination of access reasons"""
    
    def test_determine_access_reason_analytics(self, compliance_middleware):
        """Test access reason for analytics endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/analytics/student-performance"
        
        reason = compliance_middleware._determine_access_reason(request)
        assert reason == DataAccessReason.LEGITIMATE_RESEARCH
        
    def test_determine_access_reason_attendance(self, compliance_middleware):
        """Test access reason for attendance endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/attendance/take"
        
        reason = compliance_middleware._determine_access_reason(request)
        assert reason == DataAccessReason.EDUCATIONAL_INSTRUCTION
        
    def test_determine_access_reason_emergency(self, compliance_middleware):
        """Test access reason for emergency endpoints"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/emergency/student-contact"
        
        reason = compliance_middleware._determine_access_reason(request)
        assert reason == DataAccessReason.SAFETY_EMERGENCY


class TestClientInformation:
    """Test extraction of client information"""
    
    def test_get_client_ip_forwarded_for(self, compliance_middleware):
        """Test IP extraction from X-Forwarded-For header"""
        request = Mock()
        request.headers = {"X-Forwarded-For": "203.0.113.1, 192.168.1.100"}
        
        ip = compliance_middleware._get_client_ip(request)
        assert ip == "203.0.113.1"
        
    def test_get_client_ip_real_ip(self, compliance_middleware):
        """Test IP extraction from X-Real-IP header"""
        request = Mock()
        request.headers = {"X-Real-IP": "203.0.113.2"}
        
        ip = compliance_middleware._get_client_ip(request)
        assert ip == "203.0.113.2"
        
    def test_get_client_ip_direct(self, compliance_middleware):
        """Test IP extraction from direct client connection"""
        request = Mock()
        request.headers = {}
        request.client = Mock()
        request.client.host = "203.0.113.3"
        
        ip = compliance_middleware._get_client_ip(request)
        assert ip == "203.0.113.3"
        
    def test_get_session_id_from_cookie(self, compliance_middleware):
        """Test session ID extraction from cookie"""
        request = Mock()
        request.cookies = {"session_id": "abc123def456"}
        request.headers = {}
        
        session_id = compliance_middleware._get_session_id(request)
        assert session_id == "abc123def456"
        
    def test_get_session_id_from_header(self, compliance_middleware):
        """Test session ID extraction from header"""
        request = Mock()
        request.cookies = {}
        request.headers = {"X-Session-ID": "xyz789uvw012"}
        
        session_id = compliance_middleware._get_session_id(request)
        assert session_id == "xyz789uvw012"


class TestMiddlewareIntegration:
    """Test full middleware integration"""
    
    @pytest.mark.asyncio
    async def test_successful_request_processing(self, compliance_middleware, test_users, db_session):
        """Test successful processing of compliant request"""
        # Mock dependencies
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1"
        request.method = "GET"
        request.state = Mock()
        request.state.user_id = test_users["admin"].id  # Admin can access
        request.headers = {"user-agent": "Test Browser"}
        request.client = Mock()
        request.client.host = "192.168.1.100"
        request.cookies = {}
        request.query_params = {}
        
        # Mock call_next function
        response = Mock(spec=Response)
        response.headers = {}
        call_next = AsyncMock(return_value=response)
        
        # Mock database and privacy service
        with patch('app.middleware.compliance.get_db') as mock_get_db:
            mock_get_db.return_value.__next__.return_value = db_session
            
            with patch.object(compliance_middleware, '_requires_compliance_check', return_value=True):
                with patch.object(compliance_middleware, '_extract_student_id', return_value=1):
                    with patch.object(compliance_middleware, '_check_access_permissions'):
                        with patch.object(compliance_middleware, '_verify_consent'):
                            result = await compliance_middleware.process_request(request, call_next)
                            
                            assert result == response
                            assert result.headers["X-FERPA-Compliant"] == "true"
                            assert result.headers["X-Privacy-Protected"] == "true"
                            
    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, compliance_middleware, db_session):
        """Test that unauthenticated requests are rejected"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1"
        request.method = "GET"
        request.state = Mock()
        request.state.user_id = None  # No user ID
        request.headers = {"user-agent": "Test Browser"}
        request.client = Mock()
        request.client.host = "192.168.1.100"
        
        call_next = AsyncMock()
        
        with patch('app.middleware.compliance.get_db') as mock_get_db:
            mock_get_db.return_value.__next__.return_value = db_session
            
            with patch.object(compliance_middleware, '_requires_compliance_check', return_value=True):
                with pytest.raises(HTTPException) as exc_info:
                    await compliance_middleware.process_request(request, call_next)
                
                assert exc_info.value.status_code == 401
                assert "Authentication required" in str(exc_info.value.detail)
                
    @pytest.mark.asyncio
    async def test_access_logging_performed(self, compliance_middleware, test_users, db_session):
        """Test that access is properly logged"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1/attendance"
        request.method = "GET"
        request.state = Mock()
        request.state.user_id = test_users["teacher"].id
        request.headers = {"user-agent": "Test Browser"}
        request.client = Mock()
        request.client.host = "192.168.1.100"
        request.cookies = {"session_id": "test_session"}
        request.query_params = {}
        
        response = Mock(spec=Response)
        response.headers = {}
        call_next = AsyncMock(return_value=response)
        
        with patch('app.middleware.compliance.get_db') as mock_get_db:
            mock_get_db.return_value.__next__.return_value = db_session
            
            mock_privacy_service = Mock()
            mock_privacy_service.log_data_access = Mock()
            
            with patch.object(compliance_middleware, '_requires_compliance_check', return_value=True):
                with patch.object(compliance_middleware, '_extract_student_id', return_value=1):
                    with patch.object(compliance_middleware, '_check_access_permissions'):
                        with patch.object(compliance_middleware, '_verify_consent'):
                            compliance_middleware.privacy_service = mock_privacy_service
                            
                            await compliance_middleware.process_request(request, call_next)
                            
                            # Verify access was logged
                            mock_privacy_service.log_data_access.assert_called_once()
                            call_args = mock_privacy_service.log_data_access.call_args[1]
                            assert call_args["user_id"] == test_users["teacher"].id
                            assert call_args["student_id"] == 1
                            assert call_args["data_type"] == "attendance_records"
                            assert call_args["action"] == "view"


class TestErrorHandling:
    """Test error handling scenarios"""
    
    @pytest.mark.asyncio
    async def test_middleware_exception_handling(self, compliance_middleware, db_session):
        """Test that middleware properly handles and logs exceptions"""
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/students/1"
        request.headers = {"user-agent": "Test Browser"}
        request.client = Mock()
        request.client.host = "192.168.1.100"
        
        # Mock call_next to raise an exception
        call_next = AsyncMock(side_effect=Exception("Test error"))
        
        with patch('app.middleware.compliance.get_db') as mock_get_db:
            mock_get_db.return_value.__next__.return_value = db_session
            
            mock_privacy_service = Mock()
            mock_privacy_service._log_compliance_event = Mock()
            
            with patch.object(compliance_middleware, '_requires_compliance_check', return_value=False):
                compliance_middleware.privacy_service = mock_privacy_service
                
                with pytest.raises(HTTPException) as exc_info:
                    await compliance_middleware.process_request(request, call_next)
                
                assert exc_info.value.status_code == 500
                assert "Compliance check failed" in str(exc_info.value.detail)
                
                # Verify error was logged
                mock_privacy_service._log_compliance_event.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])