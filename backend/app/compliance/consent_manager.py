"""
Consent Manager

FERPA-compliant consent management system for handling student and parent
consent for data sharing, processing, and disclosure of educational records.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
import json
import logging
from enum import Enum

from app.models.ferpa import (
    StudentConsent, ConsentType, ConsentStatus, DataAccessReason
)
from app.models.user import User, UserRole
from app.services.privacy_service import PrivacyService

logger = logging.getLogger(__name__)


class ConsentRequestType(str, Enum):
    """Types of consent requests"""
    INITIAL = "initial"
    RENEWAL = "renewal"
    MODIFICATION = "modification"
    EMERGENCY = "emergency"


class ConsentManager:
    """
    Manages FERPA consent workflows including request generation,
    consent collection, validation, and lifecycle management.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.privacy_service = PrivacyService(db)
    
    # === CONSENT WORKFLOW MANAGEMENT ===
    
    def create_consent_request(
        self,
        student_id: int,
        consent_type: ConsentType,
        purpose: str,
        requested_by_id: int,
        request_type: ConsentRequestType = ConsentRequestType.INITIAL,
        urgency: str = "normal",
        data_categories: List[str] = None,
        recipients: List[str] = None,
        duration_months: int = 12,
        legal_basis: str = None,
        parent_notification_required: bool = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create a comprehensive consent request with all required information
        """
        
        # Validate student exists
        student = self.db.query(User).filter(User.id == student_id).first()
        if not student:
            raise ValueError(f"Student {student_id} not found")
        
        # Determine if parental consent is required
        if parent_notification_required is None:
            parent_notification_required = self._requires_parental_consent(student_id)
        
        # Calculate expiration date
        expiration_date = datetime.utcnow() + timedelta(days=duration_months * 30)
        
        # Create consent record
        consent_request = {
            "request_id": f"CR-{student_id}-{int(datetime.utcnow().timestamp())}",
            "student_id": student_id,
            "consent_type": consent_type.value,
            "purpose": purpose,
            "requested_by_id": requested_by_id,
            "request_type": request_type.value,
            "urgency": urgency,
            "data_categories": data_categories or [],
            "recipients": recipients or [],
            "duration_months": duration_months,
            "expiration_date": expiration_date.isoformat(),
            "legal_basis": legal_basis,
            "parent_notification_required": parent_notification_required,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        # Store in database using privacy service
        consent_record = self.privacy_service.request_consent(
            student_id=student_id,
            consent_type=consent_type,
            purpose_description=purpose,
            requested_by_id=requested_by_id,
            data_categories=data_categories,
            recipient_organizations=recipients,
            expiration_date=expiration_date,
            legal_basis=legal_basis
        )
        
        consent_request["consent_id"] = consent_record.id
        
        # Generate consent form
        consent_form = self._generate_consent_form(consent_request)
        
        # Send notifications
        self._send_consent_notifications(consent_request, consent_form)
        
        return {
            "consent_request": consent_request,
            "consent_form": consent_form,
            "next_steps": self._get_next_steps(consent_request)
        }
    
    def process_consent_response(
        self,
        consent_id: int,
        response: str,  # "grant", "deny", "request_modification"
        responding_user_id: int,
        signature_data: Dict[str, Any] = None,
        modifications_requested: List[Dict[str, Any]] = None,
        ip_address: str = None,
        user_agent: str = None
    ) -> Dict[str, Any]:
        """
        Process consent response from student or parent
        """
        
        consent = self.db.query(StudentConsent).filter(StudentConsent.id == consent_id).first()
        if not consent:
            raise ValueError(f"Consent record {consent_id} not found")
        
        if consent.status != ConsentStatus.PENDING:
            raise ValueError(f"Consent not in pending status: {consent.status}")
        
        response_data = {
            "consent_id": consent_id,
            "response": response,
            "responding_user_id": responding_user_id,
            "response_timestamp": datetime.utcnow().isoformat(),
            "signature_data": signature_data,
            "modifications_requested": modifications_requested
        }
        
        if response == "grant":
            # Grant consent
            updated_consent = self.privacy_service.grant_consent(
                consent_id=consent_id,
                granted_by_id=responding_user_id,
                consent_method="digital_signature" if signature_data else "online_form",
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            response_data["status"] = "granted"
            response_data["effective_date"] = updated_consent.effective_date.isoformat()
            response_data["expiration_date"] = updated_consent.expiration_date.isoformat() if updated_consent.expiration_date else None
            
            # Send confirmation
            self._send_consent_confirmation(consent, "granted")
            
        elif response == "deny":
            # Deny consent
            consent.status = ConsentStatus.DENIED
            consent.updated_at = datetime.utcnow()
            self.db.commit()
            
            response_data["status"] = "denied"
            
            # Send confirmation
            self._send_consent_confirmation(consent, "denied")
            
            # Log denial
            self.privacy_service._log_compliance_event(
                "consent_denied",
                "consent",
                f"Consent denied for {consent.consent_type.value} for student {consent.student_id}",
                user_id=responding_user_id,
                affected_student_id=consent.student_id
            )
            
        elif response == "request_modification":
            # Request modifications
            response_data["status"] = "modification_requested"
            
            # Create modification request
            modification_request = self._create_modification_request(
                consent, modifications_requested, responding_user_id
            )
            
            response_data["modification_request"] = modification_request
            
        return response_data
    
    def renew_consent(
        self,
        original_consent_id: int,
        renewal_requested_by: int,
        new_duration_months: int = 12,
        modifications: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Renew expiring consent with optional modifications
        """
        
        original_consent = self.db.query(StudentConsent).filter(
            StudentConsent.id == original_consent_id
        ).first()
        
        if not original_consent:
            raise ValueError(f"Original consent {original_consent_id} not found")
        
        # Create renewal request
        renewal_request = self.create_consent_request(
            student_id=original_consent.student_id,
            consent_type=original_consent.consent_type,
            purpose=f"Renewal of: {original_consent.purpose_description}",
            requested_by_id=renewal_requested_by,
            request_type=ConsentRequestType.RENEWAL,
            duration_months=new_duration_months,
            data_categories=json.loads(original_consent.data_categories) if original_consent.data_categories else None,
            recipients=json.loads(original_consent.recipient_organizations) if original_consent.recipient_organizations else None,
            metadata={
                "original_consent_id": original_consent_id,
                "renewal": True,
                "modifications": modifications or {}
            }
        )
        
        return renewal_request
    
    def withdraw_consent(
        self,
        consent_id: int,
        withdrawn_by_id: int,
        reason: str,
        effective_date: datetime = None
    ) -> Dict[str, Any]:
        """
        Withdraw previously granted consent
        """
        
        if not effective_date:
            effective_date = datetime.utcnow()
        
        # Use privacy service to withdraw consent
        withdrawn_consent = self.privacy_service.withdraw_consent(
            consent_id=consent_id,
            withdrawn_by_id=withdrawn_by_id,
            reason=reason
        )
        
        # Create withdrawal record
        withdrawal_record = {
            "consent_id": consent_id,
            "withdrawn_by_id": withdrawn_by_id,
            "reason": reason,
            "effective_date": effective_date.isoformat(),
            "withdrawal_timestamp": datetime.utcnow().isoformat(),
            "data_usage_stop_required": True,
            "notification_sent": False
        }
        
        # Send withdrawal notifications
        self._send_withdrawal_notifications(withdrawn_consent, withdrawal_record)
        
        # Schedule data usage cessation
        self._schedule_data_usage_stop(withdrawn_consent, effective_date)
        
        return withdrawal_record
    
    # === CONSENT VALIDATION AND CHECKING ===
    
    def validate_consent_for_access(
        self,
        student_id: int,
        data_type: str,
        access_purpose: DataAccessReason,
        requesting_user_id: int
    ) -> Dict[str, Any]:
        """
        Validate that proper consent exists for data access
        """
        
        validation_result = {
            "valid": False,
            "consent_required": False,
            "active_consents": [],
            "missing_consents": [],
            "recommendations": []
        }
        
        # Check if consent is required
        consent_check = self.privacy_service.check_consent_required(
            student_id=student_id,
            data_type=data_type,
            purpose=access_purpose
        )
        
        validation_result["consent_required"] = consent_check["consent_required"]
        
        if not consent_check["consent_required"]:
            validation_result["valid"] = True
            validation_result["recommendations"].append("No consent required for this data access")
            return validation_result
        
        # Get active consents
        active_consents = self.privacy_service.get_active_consents(student_id)
        validation_result["active_consents"] = [
            {
                "id": c.id,
                "type": c.consent_type.value,
                "purpose": c.purpose_description,
                "expiration": c.expiration_date.isoformat() if c.expiration_date else None
            }
            for c in active_consents
        ]
        
        # Check for matching consent
        required_consent_type = self._map_data_type_to_consent_type(data_type)
        matching_consents = [
            c for c in active_consents 
            if c.consent_type == required_consent_type
        ]
        
        if matching_consents:
            validation_result["valid"] = True
            validation_result["recommendations"].append("Valid consent found")
        else:
            validation_result["missing_consents"].append(required_consent_type.value)
            validation_result["recommendations"].append(f"Request {required_consent_type.value} consent")
        
        return validation_result
    
    def get_consent_status_summary(self, student_id: int) -> Dict[str, Any]:
        """
        Get comprehensive consent status summary for a student
        """
        
        all_consents = self.db.query(StudentConsent).filter(
            StudentConsent.student_id == student_id
        ).order_by(desc(StudentConsent.created_at)).all()
        
        summary = {
            "student_id": student_id,
            "total_consents": len(all_consents),
            "by_status": {},
            "by_type": {},
            "active_consents": [],
            "expiring_soon": [],
            "recent_activity": []
        }
        
        # Count by status and type
        for consent in all_consents:
            status = consent.status.value
            consent_type = consent.consent_type.value
            
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
            summary["by_type"][consent_type] = summary["by_type"].get(consent_type, 0) + 1
        
        # Get active consents
        active_consents = self.privacy_service.get_active_consents(student_id)
        summary["active_consents"] = [
            {
                "id": c.id,
                "type": c.consent_type.value,
                "purpose": c.purpose_description,
                "granted_date": c.effective_date.isoformat(),
                "expiration_date": c.expiration_date.isoformat() if c.expiration_date else None,
                "days_until_expiration": self._calculate_days_until_expiration(c.expiration_date)
            }
            for c in active_consents
        ]
        
        # Find consents expiring soon (within 30 days)
        thirty_days_from_now = datetime.utcnow() + timedelta(days=30)
        expiring_soon = [
            c for c in active_consents
            if c.expiration_date and c.expiration_date <= thirty_days_from_now
        ]
        
        summary["expiring_soon"] = [
            {
                "id": c.id,
                "type": c.consent_type.value,
                "expiration_date": c.expiration_date.isoformat(),
                "days_remaining": self._calculate_days_until_expiration(c.expiration_date)
            }
            for c in expiring_soon
        ]
        
        # Recent activity (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_activity = [
            {
                "id": c.id,
                "type": c.consent_type.value,
                "status": c.status.value,
                "date": c.created_at.isoformat() if c.created_at else None,
                "action": "granted" if c.status == ConsentStatus.GRANTED else "requested"
            }
            for c in all_consents
            if c.created_at and c.created_at >= thirty_days_ago
        ]
        
        summary["recent_activity"] = sorted(
            recent_activity, 
            key=lambda x: x["date"], 
            reverse=True
        )[:10]
        
        return summary
    
    # === CONSENT FORM GENERATION ===
    
    def generate_consent_form_url(
        self,
        consent_id: int,
        recipient_type: str = "student"  # "student" or "parent"
    ) -> str:
        """
        Generate secure URL for consent form completion
        """
        
        # In a real implementation, this would generate a secure token
        # and create a time-limited URL
        base_url = "https://attendance-system.edu"
        secure_token = f"ct_{consent_id}_{int(datetime.utcnow().timestamp())}"
        
        return f"{base_url}/consent/{consent_id}/{recipient_type}?token={secure_token}"
    
    def get_consent_form_data(self, consent_id: int) -> Dict[str, Any]:
        """
        Get consent form data for display to user
        """
        
        consent = self.db.query(StudentConsent).filter(StudentConsent.id == consent_id).first()
        if not consent:
            raise ValueError(f"Consent {consent_id} not found")
        
        student = self.db.query(User).filter(User.id == consent.student_id).first()
        
        form_data = {
            "consent_id": consent_id,
            "student_info": {
                "id": student.id,
                "name": student.full_name,
                "email": student.email
            },
            "consent_details": {
                "type": consent.consent_type.value,
                "purpose": consent.purpose_description,
                "data_categories": json.loads(consent.data_categories) if consent.data_categories else [],
                "recipients": json.loads(consent.recipient_organizations) if consent.recipient_organizations else [],
                "effective_date": consent.effective_date.isoformat(),
                "expiration_date": consent.expiration_date.isoformat() if consent.expiration_date else None,
                "legal_basis": consent.legal_basis
            },
            "form_elements": self._generate_form_elements(consent),
            "privacy_notice": self._generate_privacy_notice(consent),
            "signature_required": True,
            "parent_signature_required": self._requires_parental_consent(consent.student_id)
        }
        
        return form_data
    
    # === PRIVATE HELPER METHODS ===
    
    def _requires_parental_consent(self, student_id: int) -> bool:
        """Check if student is minor requiring parental consent"""
        # In a real system, this would check student age/grade level
        # For now, assume all students require parental consent
        return True
    
    def _map_data_type_to_consent_type(self, data_type: str) -> ConsentType:
        """Map data type to required consent type"""
        
        mapping = {
            "attendance_records": ConsentType.ATTENDANCE_RECORDS,
            "academic_records": ConsentType.ACADEMIC_RECORDS,
            "disciplinary_records": ConsentType.DISCIPLINARY_RECORDS,
            "health_records": ConsentType.HEALTH_RECORDS,
            "directory_information": ConsentType.DIRECTORY_INFORMATION
        }
        
        return mapping.get(data_type, ConsentType.ACADEMIC_RECORDS)
    
    def _generate_consent_form(self, consent_request: Dict[str, Any]) -> Dict[str, Any]:
        """Generate consent form structure"""
        
        return {
            "form_id": f"CF-{consent_request['consent_id']}",
            "title": f"Consent for {consent_request['consent_type'].title()}",
            "description": consent_request['purpose'],
            "sections": [
                {
                    "title": "Data Collection and Use",
                    "content": f"We are requesting permission to {consent_request['purpose'].lower()}"
                },
                {
                    "title": "Data Categories",
                    "content": "The following types of information will be involved:",
                    "items": consent_request['data_categories']
                },
                {
                    "title": "Data Recipients",
                    "content": "Information may be shared with:",
                    "items": consent_request['recipients']
                },
                {
                    "title": "Duration",
                    "content": f"This consent is valid for {consent_request['duration_months']} months"
                },
                {
                    "title": "Your Rights",
                    "content": "You have the right to withdraw this consent at any time"
                }
            ],
            "signature_fields": [
                {"name": "student_signature", "required": True, "label": "Student Signature"},
                {"name": "parent_signature", "required": consent_request['parent_notification_required'], "label": "Parent/Guardian Signature"}
            ]
        }
    
    def _send_consent_notifications(self, consent_request: Dict[str, Any], consent_form: Dict[str, Any]):
        """Send consent request notifications"""
        # This would integrate with notification system
        logger.info(f"Sending consent notification for request {consent_request['request_id']}")
    
    def _send_consent_confirmation(self, consent: StudentConsent, response_type: str):
        """Send consent response confirmation"""
        logger.info(f"Sending consent {response_type} confirmation for consent {consent.id}")
    
    def _send_withdrawal_notifications(self, consent: StudentConsent, withdrawal_record: Dict[str, Any]):
        """Send consent withdrawal notifications"""
        logger.info(f"Sending withdrawal notification for consent {consent.id}")
    
    def _get_next_steps(self, consent_request: Dict[str, Any]) -> List[str]:
        """Get next steps for consent request"""
        
        steps = []
        
        if consent_request['parent_notification_required']:
            steps.append("Parent/guardian notification will be sent")
            steps.append("Both student and parent signatures required")
        else:
            steps.append("Student signature required")
        
        if consent_request['urgency'] == "high":
            steps.append("Expedited processing due to urgency")
        
        steps.append(f"Response required by {consent_request['expiration_date']}")
        
        return steps
    
    def _create_modification_request(
        self,
        consent: StudentConsent,
        modifications: List[Dict[str, Any]],
        requesting_user_id: int
    ) -> Dict[str, Any]:
        """Create modification request for consent"""
        
        return {
            "modification_id": f"MOD-{consent.id}-{int(datetime.utcnow().timestamp())}",
            "original_consent_id": consent.id,
            "requested_by": requesting_user_id,
            "modifications": modifications,
            "status": "pending_review",
            "created_at": datetime.utcnow().isoformat()
        }
    
    def _schedule_data_usage_stop(self, consent: StudentConsent, effective_date: datetime):
        """Schedule cessation of data usage after consent withdrawal"""
        logger.info(f"Scheduling data usage stop for consent {consent.id} effective {effective_date}")
    
    def _calculate_days_until_expiration(self, expiration_date: datetime) -> int:
        """Calculate days until consent expiration"""
        
        if not expiration_date:
            return -1  # No expiration
        
        delta = expiration_date - datetime.utcnow()
        return max(0, delta.days)
    
    def _generate_form_elements(self, consent: StudentConsent) -> List[Dict[str, Any]]:
        """Generate form elements for consent form"""
        
        elements = [
            {
                "type": "checkbox",
                "name": "acknowledge_purpose",
                "label": "I acknowledge the purpose of this consent",
                "required": True
            },
            {
                "type": "checkbox", 
                "name": "understand_rights",
                "label": "I understand my rights regarding this consent",
                "required": True
            },
            {
                "type": "signature",
                "name": "student_signature",
                "label": "Student Signature",
                "required": True
            }
        ]
        
        if self._requires_parental_consent(consent.student_id):
            elements.append({
                "type": "signature",
                "name": "parent_signature", 
                "label": "Parent/Guardian Signature",
                "required": True
            })
        
        return elements
    
    def _generate_privacy_notice(self, consent: StudentConsent) -> str:
        """Generate privacy notice for consent form"""
        
        return """
        PRIVACY NOTICE: This consent form is governed by the Family Educational Rights 
        and Privacy Act (FERPA). Your educational records are protected by federal law. 
        By providing consent, you are authorizing specific uses of your educational 
        information as described above. You have the right to withdraw this consent 
        at any time by contacting our Privacy Officer.
        """