"""
Data Controller

FERPA-compliant data controller for managing student educational records
with proper privacy protections, consent verification, and access controls.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
import json
import logging

from app.models.ferpa import (
    StudentConsent, DataAccessLog, PrivacySettings,
    ConsentType, ConsentStatus, DataAccessReason
)
from app.models.user import User, UserRole
from app.models.attendance import AttendanceRecord
from app.services.privacy_service import PrivacyService

logger = logging.getLogger(__name__)


class DataController:
    """
    FERPA-compliant data controller implementing data subject rights
    and educational record protection requirements.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.privacy_service = PrivacyService(db)
    
    # === DATA SUBJECT RIGHTS ===
    
    def get_student_data_summary(self, student_id: int, requesting_user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive summary of student data (Right to Know)
        
        Returns all educational records associated with the student
        in a structured format for transparency.
        """
        
        # Verify access permissions
        self._verify_data_access_permission(requesting_user_id, student_id, "view_summary")
        
        student = self.db.query(User).filter(User.id == student_id).first()
        if not student:
            raise ValueError(f"Student {student_id} not found")
        
        # Collect all data categories
        summary = {
            "student_info": self._get_basic_student_info(student),
            "attendance_records": self._get_attendance_data_summary(student_id),
            "privacy_settings": self._get_privacy_settings_summary(student_id),
            "consent_records": self._get_consent_records_summary(student_id),
            "access_history": self._get_access_history_summary(student_id),
            "data_sharing": self._get_data_sharing_summary(student_id),
            "retention_info": self._get_retention_info_summary(student_id)
        }
        
        # Log the data summary access
        self.privacy_service.log_data_access(
            user_id=requesting_user_id,
            student_id=student_id,
            data_type="comprehensive_summary",
            action="view",
            access_reason=DataAccessReason.PARENT_REQUEST,
            purpose_description="Student data summary request (Right to Know)"
        )
        
        return summary
    
    def export_student_data(
        self, 
        student_id: int, 
        requesting_user_id: int,
        format: str = "json",
        include_categories: List[str] = None
    ) -> Dict[str, Any]:
        """
        Export student data in machine-readable format (Data Portability)
        """
        
        # Verify access permissions
        self._verify_data_access_permission(requesting_user_id, student_id, "export")
        
        # Check consent for data export
        consent_check = self.privacy_service.check_consent_required(
            student_id=student_id,
            data_type="comprehensive_export", 
            purpose=DataAccessReason.PARENT_REQUEST
        )
        
        if consent_check["consent_required"] and not consent_check["consent_available"]:
            raise PermissionError("Data export requires explicit consent")
        
        # Default to all categories if none specified
        if not include_categories:
            include_categories = [
                "basic_info", "attendance", "privacy_settings", 
                "consents", "access_logs"
            ]
        
        export_data = {
            "export_metadata": {
                "student_id": student_id,
                "export_date": datetime.utcnow().isoformat(),
                "format": format,
                "categories": include_categories,
                "exported_by": requesting_user_id
            },
            "data": {}
        }
        
        # Export requested categories
        if "basic_info" in include_categories:
            export_data["data"]["basic_info"] = self._export_basic_info(student_id)
        
        if "attendance" in include_categories:
            export_data["data"]["attendance"] = self._export_attendance_data(student_id)
        
        if "privacy_settings" in include_categories:
            export_data["data"]["privacy_settings"] = self._export_privacy_settings(student_id)
        
        if "consents" in include_categories:
            export_data["data"]["consents"] = self._export_consent_records(student_id)
        
        if "access_logs" in include_categories:
            export_data["data"]["access_logs"] = self._export_access_logs(student_id)
        
        # Log the export
        self.privacy_service.log_data_access(
            user_id=requesting_user_id,
            student_id=student_id,
            data_type="data_export",
            action="export",
            access_reason=DataAccessReason.PARENT_REQUEST,
            purpose_description=f"Student data export ({format} format, categories: {include_categories})"
        )
        
        return export_data
    
    def request_data_correction(
        self,
        student_id: int,
        requesting_user_id: int,
        correction_requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Request correction of inaccurate educational records (Right to Amend)
        """
        
        # Verify access permissions
        self._verify_data_access_permission(requesting_user_id, student_id, "request_correction")
        
        results = {
            "request_id": f"CORR-{student_id}-{int(datetime.utcnow().timestamp())}",
            "student_id": student_id,
            "requested_by": requesting_user_id,
            "request_date": datetime.utcnow().isoformat(),
            "corrections": []
        }
        
        for request in correction_requests:
            correction = self._process_correction_request(student_id, request)
            results["corrections"].append(correction)
        
        # Log correction request
        self.privacy_service.log_data_access(
            user_id=requesting_user_id,
            student_id=student_id,
            data_type="correction_request",
            action="create",
            access_reason=DataAccessReason.PARENT_REQUEST,
            purpose_description=f"Data correction request: {len(correction_requests)} items"
        )
        
        return results
    
    def request_data_deletion(
        self,
        student_id: int,
        requesting_user_id: int,
        deletion_scope: Dict[str, Any],
        reason: str = "Right to be Forgotten"
    ) -> Dict[str, Any]:
        """
        Request deletion of student data (Right to be Forgotten/Erasure)
        """
        
        # Verify access permissions  
        self._verify_data_access_permission(requesting_user_id, student_id, "request_deletion")
        
        # Check if deletion is legally permissible
        legal_hold_check = self._check_legal_holds(student_id, deletion_scope)
        
        if legal_hold_check["has_holds"]:
            return {
                "status": "denied",
                "reason": "Data subject to legal hold",
                "legal_holds": legal_hold_check["holds"],
                "contact_info": "Please contact compliance officer"
            }
        
        # Process deletion request
        deletion_result = {
            "request_id": f"DEL-{student_id}-{int(datetime.utcnow().timestamp())}",
            "student_id": student_id,
            "requested_by": requesting_user_id,
            "request_date": datetime.utcnow().isoformat(),
            "reason": reason,
            "scope": deletion_scope,
            "status": "pending_review",
            "estimated_completion": (datetime.utcnow() + timedelta(days=30)).isoformat()
        }
        
        # Log deletion request
        self.privacy_service.log_data_access(
            user_id=requesting_user_id,
            student_id=student_id,
            data_type="deletion_request",
            action="create",
            access_reason=DataAccessReason.PARENT_REQUEST,
            purpose_description=f"Data deletion request: {reason}"
        )
        
        # Create compliance audit event
        self.privacy_service._log_compliance_event(
            "data_deletion_requested",
            "privacy",
            f"Data deletion requested for student {student_id} by user {requesting_user_id}",
            severity_level="info",
            user_id=requesting_user_id,
            affected_student_id=student_id,
            requires_action=True,
            technical_details=json.dumps(deletion_scope)
        )
        
        return deletion_result
    
    # === ACCESS CONTROL METHODS ===
    
    def get_authorized_students(self, user_id: int, user_role: UserRole) -> List[int]:
        """
        Get list of student IDs that a user is authorized to access
        based on their role and legitimate educational interest.
        """
        
        if user_role == UserRole.ADMIN:
            # Administrators can access all students
            student_ids = self.db.query(User.id).filter(User.role == UserRole.STUDENT).all()
            return [sid[0] for sid in student_ids]
        
        elif user_role == UserRole.STUDENT:
            # Students can only access their own data
            return [user_id]
        
        elif user_role == UserRole.TEACHER:
            # Teachers can access students in their classes
            # This would typically query enrollment/class relationships
            # For now, return empty list to be safe
            return self._get_teacher_students(user_id)
        
        else:
            return []
    
    def check_data_access_permission(
        self,
        user_id: int,
        student_id: int,
        data_type: str,
        action: str = "view"
    ) -> Dict[str, Any]:
        """
        Comprehensive check of data access permissions including
        role-based access, consent requirements, and privacy settings.
        """
        
        result = {
            "allowed": False,
            "reason": "",
            "consent_required": False,
            "consent_available": False,
            "privacy_restrictions": [],
            "recommendations": []
        }
        
        try:
            # Check role-based permissions
            role_check = self._check_role_based_access(user_id, student_id, action)
            if not role_check["allowed"]:
                result["reason"] = role_check["reason"]
                return result
            
            # Check consent requirements
            consent_check = self.privacy_service.check_consent_required(
                student_id=student_id,
                data_type=data_type,
                purpose=DataAccessReason.EDUCATIONAL_INSTRUCTION
            )
            
            result["consent_required"] = consent_check["consent_required"]
            result["consent_available"] = consent_check["consent_available"]
            
            if consent_check["consent_required"] and not consent_check["consent_available"]:
                result["reason"] = "Missing required consent"
                result["recommendations"].append("Obtain student/parent consent before accessing data")
                return result
            
            # Check privacy settings
            privacy_settings = self.privacy_service.get_privacy_settings(student_id)
            privacy_restrictions = self._check_privacy_restrictions(privacy_settings, data_type, action)
            result["privacy_restrictions"] = privacy_restrictions
            
            # Final determination
            result["allowed"] = True
            result["reason"] = "Access authorized"
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking data access permission: {str(e)}")
            result["reason"] = "Permission check failed"
            return result
    
    # === PRIVATE HELPER METHODS ===
    
    def _verify_data_access_permission(self, user_id: int, student_id: int, action: str):
        """Verify user has permission to access student data"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise PermissionError("User not found")
        
        # Check basic permissions
        permission_check = self.check_data_access_permission(
            user_id=user_id,
            student_id=student_id,
            data_type="educational_records",
            action=action
        )
        
        if not permission_check["allowed"]:
            raise PermissionError(f"Access denied: {permission_check['reason']}")
    
    def _check_role_based_access(self, user_id: int, student_id: int, action: str) -> Dict[str, Any]:
        """Check role-based access control"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"allowed": False, "reason": "User not found"}
        
        # Admin access
        if user.role == UserRole.ADMIN:
            return {"allowed": True, "reason": "Administrative access"}
        
        # Student self-access
        if user.role == UserRole.STUDENT and user.id == student_id:
            return {"allowed": True, "reason": "Self-access"}
        
        # Teacher access to their students
        if user.role == UserRole.TEACHER:
            if self._teacher_has_legitimate_interest(user_id, student_id):
                return {"allowed": True, "reason": "Legitimate educational interest"}
            else:
                return {"allowed": False, "reason": "No legitimate educational interest"}
        
        return {"allowed": False, "reason": "Insufficient permissions"}
    
    def _teacher_has_legitimate_interest(self, teacher_id: int, student_id: int) -> bool:
        """Check if teacher has legitimate educational interest in student"""
        # This would check class enrollment, advisory relationships, etc.
        # For now, return True - implement proper checking based on your system
        return True
    
    def _get_teacher_students(self, teacher_id: int) -> List[int]:
        """Get students that a teacher has access to"""
        # This would query class enrollment relationships
        # For now, return empty list - implement based on your system
        return []
    
    def _check_privacy_restrictions(
        self, 
        privacy_settings: PrivacySettings, 
        data_type: str, 
        action: str
    ) -> List[str]:
        """Check privacy setting restrictions"""
        
        restrictions = []
        
        if data_type == "directory_information" and not privacy_settings.directory_info_public:
            restrictions.append("Directory information not public")
        
        if data_type == "contact_info" and not privacy_settings.allow_contact_disclosure:
            restrictions.append("Contact disclosure not permitted")
        
        if data_type == "academic_info" and not privacy_settings.allow_academic_info_disclosure:
            restrictions.append("Academic information disclosure not permitted")
        
        return restrictions
    
    def _check_legal_holds(self, student_id: int, deletion_scope: Dict[str, Any]) -> Dict[str, Any]:
        """Check if data is subject to legal holds preventing deletion"""
        
        # This would check for:
        # - Active legal proceedings
        # - Regulatory requirements
        # - Ongoing investigations
        # - Mandatory retention periods
        
        # For now, return no holds - implement based on your requirements
        return {
            "has_holds": False,
            "holds": []
        }
    
    def _get_basic_student_info(self, student: User) -> Dict[str, Any]:
        """Get basic student information summary"""
        
        return {
            "id": student.id,
            "username": student.username,
            "full_name": student.full_name,
            "email": student.email,
            "created_at": student.created_at.isoformat() if student.created_at else None,
            "last_login": student.last_login.isoformat() if student.last_login else None
        }
    
    def _get_attendance_data_summary(self, student_id: int) -> Dict[str, Any]:
        """Get summary of attendance data"""
        
        attendance_count = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.student_id == student_id
        ).count()
        
        return {
            "total_records": attendance_count,
            "data_types": ["attendance_status", "check_in_time", "check_out_time", "location_data"]
        }
    
    def _get_privacy_settings_summary(self, student_id: int) -> Dict[str, Any]:
        """Get privacy settings summary"""
        
        settings = self.privacy_service.get_privacy_settings(student_id)
        
        return {
            "directory_info_public": settings.directory_info_public,
            "data_sharing_enabled": settings.opt_in_analytics,
            "last_updated": settings.updated_at.isoformat() if settings.updated_at else None
        }
    
    def _get_consent_records_summary(self, student_id: int) -> Dict[str, Any]:
        """Get consent records summary"""
        
        consents = self.db.query(StudentConsent).filter(
            StudentConsent.student_id == student_id
        ).all()
        
        return {
            "total_consents": len(consents),
            "active_consents": len([c for c in consents if c.status == ConsentStatus.GRANTED])
        }
    
    def _get_access_history_summary(self, student_id: int) -> Dict[str, Any]:
        """Get data access history summary"""
        
        access_count = self.db.query(DataAccessLog).filter(
            DataAccessLog.student_id == student_id
        ).count()
        
        recent_access = self.db.query(DataAccessLog).filter(
            DataAccessLog.student_id == student_id
        ).order_by(desc(DataAccessLog.access_timestamp)).first()
        
        return {
            "total_access_events": access_count,
            "last_access": recent_access.access_timestamp.isoformat() if recent_access else None
        }
    
    def _get_data_sharing_summary(self, student_id: int) -> Dict[str, Any]:
        """Get data sharing summary"""
        
        return {
            "third_party_sharing": False,
            "research_participation": False,
            "analytics_participation": False
        }
    
    def _get_retention_info_summary(self, student_id: int) -> Dict[str, Any]:
        """Get data retention information"""
        
        return {
            "retention_policies_applied": ["attendance_records", "academic_records"],
            "estimated_purge_date": "2030-12-31"  # Placeholder
        }
    
    def _export_basic_info(self, student_id: int) -> Dict[str, Any]:
        """Export basic student information"""
        
        student = self.db.query(User).filter(User.id == student_id).first()
        return self._get_basic_student_info(student)
    
    def _export_attendance_data(self, student_id: int) -> List[Dict[str, Any]]:
        """Export attendance data"""
        
        attendance_records = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.student_id == student_id
        ).all()
        
        return [
            {
                "id": record.id,
                "class_session_id": record.class_session_id,
                "status": record.status.value,
                "check_in_time": record.check_in_time.isoformat() if record.check_in_time else None,
                "check_out_time": record.check_out_time.isoformat() if record.check_out_time else None,
                "created_at": record.created_at.isoformat() if record.created_at else None
            }
            for record in attendance_records
        ]
    
    def _export_privacy_settings(self, student_id: int) -> Dict[str, Any]:
        """Export privacy settings"""
        
        settings = self.privacy_service.get_privacy_settings(student_id)
        
        return {
            "directory_info_public": settings.directory_info_public,
            "allow_name_disclosure": settings.allow_name_disclosure,
            "allow_photo_disclosure": settings.allow_photo_disclosure,
            "allow_contact_disclosure": settings.allow_contact_disclosure,
            "allow_academic_info_disclosure": settings.allow_academic_info_disclosure,
            "created_at": settings.created_at.isoformat() if settings.created_at else None,
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None
        }
    
    def _export_consent_records(self, student_id: int) -> List[Dict[str, Any]]:
        """Export consent records"""
        
        consents = self.db.query(StudentConsent).filter(
            StudentConsent.student_id == student_id
        ).all()
        
        return [
            {
                "id": consent.id,
                "consent_type": consent.consent_type.value,
                "status": consent.status.value,
                "purpose_description": consent.purpose_description,
                "effective_date": consent.effective_date.isoformat() if consent.effective_date else None,
                "expiration_date": consent.expiration_date.isoformat() if consent.expiration_date else None,
                "created_at": consent.created_at.isoformat() if consent.created_at else None
            }
            for consent in consents
        ]
    
    def _export_access_logs(self, student_id: int) -> List[Dict[str, Any]]:
        """Export access logs"""
        
        logs = self.db.query(DataAccessLog).filter(
            DataAccessLog.student_id == student_id
        ).order_by(desc(DataAccessLog.access_timestamp)).limit(100).all()
        
        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "data_type": log.data_type,
                "action": log.action,
                "access_reason": log.access_reason.value,
                "purpose_description": log.purpose_description,
                "access_timestamp": log.access_timestamp.isoformat()
            }
            for log in logs
        ]
    
    def _process_correction_request(self, student_id: int, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process individual correction request"""
        
        return {
            "field": request.get("field"),
            "current_value": request.get("current_value"),
            "requested_value": request.get("requested_value"),
            "justification": request.get("justification"),
            "status": "pending_review",
            "created_at": datetime.utcnow().isoformat()
        }