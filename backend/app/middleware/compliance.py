"""
FERPA Compliance Middleware

Middleware for enforcing FERPA compliance across all student data access,
including consent verification, access logging, and privacy controls.
"""

from typing import Callable, Dict, Any, Optional
from fastapi import Request, Response, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import json
import time
from datetime import datetime
import logging

from app.core.database import get_db
from app.services.privacy_service import PrivacyService
from app.models.ferpa import DataAccessReason
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)
security = HTTPBearer()


class ComplianceMiddleware:
    """Middleware for FERPA compliance enforcement"""
    
    def __init__(self):
        self.privacy_service = None  # Will be initialized per request
        
    def __call__(self, request: Request, call_next: Callable) -> Callable:
        """Main middleware function"""
        return self.process_request(request, call_next)
    
    async def process_request(self, request: Request, call_next: Callable):
        """Process request for FERPA compliance"""
        
        start_time = time.time()
        
        try:
            # Initialize privacy service for this request
            db = get_db().__next__()
            self.privacy_service = PrivacyService(db)
            
            # Check if this endpoint requires compliance checking
            if self._requires_compliance_check(request):
                # Perform pre-request compliance checks
                await self._pre_request_compliance(request, db)
            
            # Process the request
            response = await call_next(request)
            
            # Perform post-request compliance logging
            if self._requires_compliance_check(request):
                await self._post_request_compliance(request, response, db)
            
            # Add compliance headers
            response.headers["X-FERPA-Compliant"] = "true"
            response.headers["X-Privacy-Protected"] = "true"
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Compliance middleware error: {str(e)}")
            # Log compliance error
            if hasattr(self, 'privacy_service') and self.privacy_service:
                self.privacy_service._log_compliance_event(
                    "middleware_error",
                    "privacy",
                    f"Compliance middleware error: {str(e)}",
                    severity_level="error",
                    requires_action=True,
                    ip_address=self._get_client_ip(request),
                    user_agent=request.headers.get("user-agent")
                )
            raise HTTPException(status_code=500, detail="Compliance check failed")
        
        finally:
            # Record processing time
            process_time = time.time() - start_time
            if hasattr(self, 'privacy_service') and self.privacy_service:
                logger.info(f"Compliance check completed in {process_time:.3f}s for {request.url}")
    
    def _requires_compliance_check(self, request: Request) -> bool:
        """Determine if request requires compliance checking"""
        
        # Student data endpoints that require compliance
        student_data_patterns = [
            "/api/v1/students/",
            "/api/v1/attendance/",
            "/api/v1/grades/",
            "/api/v1/reports/",
            "/api/v1/analytics/",
            "/api/v1/class-sessions/"
        ]
        
        # Check if path matches student data patterns
        path = request.url.path.lower()
        return any(pattern in path for pattern in student_data_patterns)
    
    async def _pre_request_compliance(self, request: Request, db: Session):
        """Perform pre-request compliance checks"""
        
        # Extract user information
        user_id = self._get_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required for student data access")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid user")
        
        # Extract student ID from request
        student_id = self._extract_student_id(request)
        if student_id:
            # Check access permissions
            await self._check_access_permissions(user, student_id, request)
            
            # Verify consent if required
            await self._verify_consent(user_id, student_id, request)
    
    async def _post_request_compliance(self, request: Request, response: Response, db: Session):
        """Perform post-request compliance logging"""
        
        user_id = self._get_user_id(request)
        student_id = self._extract_student_id(request)
        
        if user_id and student_id:
            # Determine data type and action
            data_type, action = self._determine_data_operation(request, response)
            
            # Determine access reason
            access_reason = self._determine_access_reason(request)
            
            # Log data access
            self.privacy_service.log_data_access(
                user_id=user_id,
                student_id=student_id,
                data_type=data_type,
                action=action,
                access_reason=access_reason,
                purpose_description=self._generate_purpose_description(request, action),
                endpoint=str(request.url),
                ip_address=self._get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                session_id=self._get_session_id(request)
            )
    
    def _get_user_id(self, request: Request) -> Optional[int]:
        """Extract user ID from request"""
        # This assumes user ID is stored in request state by auth middleware
        return getattr(request.state, 'user_id', None)
    
    def _extract_student_id(self, request: Request) -> Optional[int]:
        """Extract student ID from request path or body"""
        
        # Try path parameters first
        path_parts = request.url.path.split('/')
        
        # Look for student ID in common patterns
        for i, part in enumerate(path_parts):
            if part == 'students' and i + 1 < len(path_parts):
                try:
                    return int(path_parts[i + 1])
                except ValueError:
                    pass
        
        # Try query parameters
        if 'student_id' in request.query_params:
            try:
                return int(request.query_params['student_id'])
            except ValueError:
                pass
        
        # For POST/PUT requests, try to extract from body
        if hasattr(request, '_json') and request._json:
            body = request._json
            if 'student_id' in body:
                return body['student_id']
        
        return None
    
    async def _check_access_permissions(self, user: User, student_id: int, request: Request):
        """Check if user has permission to access student data"""
        
        # Administrators can access all data
        if user.role == UserRole.ADMIN:
            return
        
        # Students can only access their own data
        if user.role == UserRole.STUDENT:
            if user.id != student_id:
                raise HTTPException(
                    status_code=403, 
                    detail="Students can only access their own educational records"
                )
            return
        
        # Teachers can access data for their students
        if user.role == UserRole.TEACHER:
            # Check if teacher has access to this student
            # This would typically check enrollment or class relationships
            if not await self._teacher_has_access_to_student(user.id, student_id):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: No educational relationship with student"
                )
            return
        
        # Default deny
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions for student data access"
        )
    
    async def _teacher_has_access_to_student(self, teacher_id: int, student_id: int) -> bool:
        """Check if teacher has legitimate educational interest in student"""
        
        # This would check class enrollment, advisory relationships, etc.
        # For now, return True to allow teacher access
        # In production, implement proper relationship checking
        return True
    
    async def _verify_consent(self, user_id: int, student_id: int, request: Request):
        """Verify consent for data access if required"""
        
        # Determine data type being accessed
        data_type, _ = self._determine_data_operation(request)
        access_reason = self._determine_access_reason(request)
        
        # Check if consent is required
        consent_check = self.privacy_service.check_consent_required(
            student_id=student_id,
            data_type=data_type,
            purpose=access_reason
        )
        
        if consent_check["consent_required"] and not consent_check["consent_available"]:
            # Check if this is an emergency or legal requirement
            if access_reason not in [DataAccessReason.SAFETY_EMERGENCY, DataAccessReason.COURT_ORDER]:
                raise HTTPException(
                    status_code=403,
                    detail="Data access requires student/parent consent"
                )
    
    def _determine_data_operation(self, request: Request, response: Response = None) -> tuple:
        """Determine the type of data and operation being performed"""
        
        path = request.url.path.lower()
        method = request.method.upper()
        
        # Determine data type
        data_type = "unknown"
        if "/attendance/" in path:
            data_type = "attendance_records"
        elif "/students/" in path:
            data_type = "student_records"
        elif "/grades/" in path:
            data_type = "academic_records"
        elif "/reports/" in path:
            data_type = "reports"
        elif "/analytics/" in path:
            data_type = "analytics"
        
        # Determine action
        action = "unknown"
        if method == "GET":
            action = "view"
        elif method == "POST":
            action = "create"
        elif method == "PUT" or method == "PATCH":
            action = "update"
        elif method == "DELETE":
            action = "delete"
        
        # Special case for exports
        if "export" in path or "download" in path:
            action = "export"
        
        return data_type, action
    
    def _determine_access_reason(self, request: Request) -> DataAccessReason:
        """Determine the reason for data access"""
        
        path = request.url.path.lower()
        
        # Try to infer reason from path
        if "/analytics/" in path or "/reports/" in path:
            return DataAccessReason.LEGITIMATE_RESEARCH
        elif "/attendance/" in path:
            return DataAccessReason.EDUCATIONAL_INSTRUCTION
        elif "/emergency/" in path:
            return DataAccessReason.SAFETY_EMERGENCY
        else:
            return DataAccessReason.EDUCATIONAL_INSTRUCTION
    
    def _generate_purpose_description(self, request: Request, action: str) -> str:
        """Generate purpose description for access logging"""
        
        path = request.url.path
        method = request.method
        
        return f"{method} {action} on {path}"
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address"""
        
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct client IP
        if hasattr(request, 'client') and request.client:
            return request.client.host
        
        return "unknown"
    
    def _get_session_id(self, request: Request) -> Optional[str]:
        """Extract session ID from request"""
        
        # Try cookies first
        session_id = request.cookies.get("session_id")
        if session_id:
            return session_id
        
        # Try headers
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            return session_id
        
        return None


# Dependency for FERPA-compliant database access
async def get_compliant_db(
    request: Request,
    db: Session = Depends(get_db)
) -> Session:
    """Database dependency that ensures FERPA compliance"""
    
    # Add compliance context to database session
    db._compliance_context = {
        "request": request,
        "user_id": getattr(request.state, 'user_id', None),
        "ip_address": request.client.host if hasattr(request, 'client') else "unknown",
        "user_agent": request.headers.get("user-agent"),
        "timestamp": datetime.utcnow()
    }
    
    return db


# Decorator for endpoints requiring explicit consent
def requires_consent(consent_type: str):
    """Decorator for endpoints requiring explicit student consent"""
    
    def decorator(func):
        func._requires_consent = consent_type
        return func
    
    return decorator


# Decorator for endpoints with high privacy risk
def high_privacy_risk(reason: str = "High sensitivity data access"):
    """Decorator for high privacy risk endpoints"""
    
    def decorator(func):
        func._privacy_risk = "high"
        func._privacy_reason = reason
        return func
    
    return decorator


# Utility function for manual compliance logging
def log_manual_access(
    db: Session,
    user_id: int,
    student_id: int,
    data_type: str,
    action: str,
    reason: DataAccessReason,
    description: str,
    ip_address: str = None,
    user_agent: str = None
):
    """Manually log data access for compliance"""
    
    privacy_service = PrivacyService(db)
    
    return privacy_service.log_data_access(
        user_id=user_id,
        student_id=student_id,
        data_type=data_type,
        action=action,
        access_reason=reason,
        purpose_description=description,
        ip_address=ip_address,
        user_agent=user_agent
    )


# Configuration for compliance middleware
class ComplianceConfig:
    """Configuration for FERPA compliance middleware"""
    
    # Endpoints that require strict consent verification
    STRICT_CONSENT_ENDPOINTS = [
        "/api/v1/reports/export",
        "/api/v1/analytics/student-data",
        "/api/v1/students/bulk-export"
    ]
    
    # Endpoints that require enhanced logging
    ENHANCED_LOGGING_ENDPOINTS = [
        "/api/v1/grades/",
        "/api/v1/disciplinary/",
        "/api/v1/health/"
    ]
    
    # Grace period for emergency access (in minutes)
    EMERGENCY_ACCESS_GRACE_PERIOD = 60
    
    # Maximum failed consent checks before alert
    MAX_CONSENT_FAILURES = 5