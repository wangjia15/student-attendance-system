"""
Privacy Service

Comprehensive service for managing FERPA compliance, student data privacy,
and educational record protection in accordance with federal regulations.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
import json
import hashlib
import secrets
from enum import Enum

from app.core.database import get_db
from app.models.ferpa import (
    StudentConsent, DataAccessLog, DataRetentionPolicy, DataPurgeSchedule,
    ComplianceAuditLog, PrivacySettings, ConsentType, ConsentStatus,
    DataAccessReason, DataRetentionCategory
)
from app.models.user import User, UserRole
from app.models.attendance import AttendanceRecord


class PrivacyViolationType(str, Enum):
    """Types of privacy violations"""
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    CONSENT_VIOLATION = "consent_violation" 
    RETENTION_VIOLATION = "retention_violation"
    DISCLOSURE_VIOLATION = "disclosure_violation"


class PrivacyService:
    """Service for managing student data privacy and FERPA compliance"""
    
    def __init__(self, db: Session):
        self.db = db
        
    # === CONSENT MANAGEMENT ===
    
    def request_consent(
        self,
        student_id: int,
        consent_type: ConsentType,
        purpose_description: str,
        requested_by_id: int,
        data_categories: List[str] = None,
        recipient_organizations: List[str] = None,
        expiration_date: datetime = None,
        legal_basis: str = None,
        is_required_by_law: bool = False
    ) -> StudentConsent:
        """Request consent for data sharing from student or parent"""
        
        # Check if student is minor (requires parental consent)
        student = self.db.query(User).filter(User.id == student_id).first()
        if not student:
            raise ValueError(f"Student with ID {student_id} not found")
        
        # Create consent record
        consent = StudentConsent(
            student_id=student_id,
            granted_by_id=requested_by_id,  # Initially set to requestor, will change when granted
            consent_type=consent_type,
            status=ConsentStatus.PENDING,
            purpose_description=purpose_description,
            data_categories=json.dumps(data_categories) if data_categories else None,
            recipient_organizations=json.dumps(recipient_organizations) if recipient_organizations else None,
            effective_date=datetime.utcnow(),
            expiration_date=expiration_date,
            legal_basis=legal_basis,
            is_required_by_law=is_required_by_law
        )
        
        self.db.add(consent)
        self.db.commit()
        self.db.refresh(consent)
        
        # Log consent request
        self._log_compliance_event(
            "consent_requested",
            "consent",
            f"Consent requested for {consent_type.value} for student {student_id}",
            user_id=requested_by_id,
            affected_student_id=student_id
        )
        
        return consent
    
    def grant_consent(
        self,
        consent_id: int,
        granted_by_id: int,
        consent_method: str = "digital_signature",
        ip_address: str = None,
        user_agent: str = None
    ) -> StudentConsent:
        """Grant consent for data sharing"""
        
        consent = self.db.query(StudentConsent).filter(StudentConsent.id == consent_id).first()
        if not consent:
            raise ValueError(f"Consent record {consent_id} not found")
        
        if consent.status != ConsentStatus.PENDING:
            raise ValueError(f"Consent is not in pending status: {consent.status}")
        
        # Update consent record
        consent.status = ConsentStatus.GRANTED
        consent.granted_by_id = granted_by_id
        consent.consent_method = consent_method
        consent.ip_address = ip_address
        consent.user_agent = user_agent
        consent.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        # Log consent granted
        self._log_compliance_event(
            "consent_granted",
            "consent", 
            f"Consent granted for {consent.consent_type.value} for student {consent.student_id}",
            user_id=granted_by_id,
            affected_student_id=consent.student_id
        )
        
        return consent
    
    def withdraw_consent(
        self,
        consent_id: int,
        withdrawn_by_id: int,
        reason: str = None
    ) -> StudentConsent:
        """Withdraw previously granted consent"""
        
        consent = self.db.query(StudentConsent).filter(StudentConsent.id == consent_id).first()
        if not consent:
            raise ValueError(f"Consent record {consent_id} not found")
        
        if consent.status != ConsentStatus.GRANTED:
            raise ValueError(f"Can only withdraw granted consent, current status: {consent.status}")
        
        # Update consent record
        consent.status = ConsentStatus.WITHDRAWN
        consent.withdrawn_at = datetime.utcnow()
        consent.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        # Log consent withdrawal
        self._log_compliance_event(
            "consent_withdrawn",
            "consent",
            f"Consent withdrawn for {consent.consent_type.value} for student {consent.student_id}. Reason: {reason or 'Not specified'}",
            user_id=withdrawn_by_id,
            affected_student_id=consent.student_id
        )
        
        return consent
    
    def get_active_consents(self, student_id: int) -> List[StudentConsent]:
        """Get all active consents for a student"""
        
        return self.db.query(StudentConsent).filter(
            and_(
                StudentConsent.student_id == student_id,
                StudentConsent.status == ConsentStatus.GRANTED,
                or_(
                    StudentConsent.expiration_date.is_(None),
                    StudentConsent.expiration_date > datetime.utcnow()
                )
            )
        ).all()
    
    def check_consent_required(
        self,
        student_id: int,
        data_type: str,
        purpose: DataAccessReason,
        recipient: str = None
    ) -> Dict[str, Any]:
        """Check if consent is required and available for data access"""
        
        # Define which data types require consent
        consent_required_types = {
            "attendance_records": ConsentType.ATTENDANCE_RECORDS,
            "academic_records": ConsentType.ACADEMIC_RECORDS,
            "disciplinary_records": ConsentType.DISCIPLINARY_RECORDS,
            "health_records": ConsentType.HEALTH_RECORDS
        }
        
        # Check if consent is required for this data type
        required_consent_type = consent_required_types.get(data_type)
        
        result = {
            "consent_required": required_consent_type is not None,
            "consent_available": False,
            "consent_type": required_consent_type,
            "active_consents": [],
            "violation_risk": "low"
        }
        
        if not required_consent_type:
            # Directory information or other non-sensitive data
            if purpose in [DataAccessReason.DIRECTORY_REQUEST]:
                privacy_settings = self.get_privacy_settings(student_id)
                if not privacy_settings.directory_info_public:
                    result["consent_required"] = True
                    result["violation_risk"] = "medium"
            return result
        
        # Check for active consent
        active_consents = self.get_active_consents(student_id)
        matching_consents = [
            c for c in active_consents 
            if c.consent_type == required_consent_type
        ]
        
        result["active_consents"] = matching_consents
        result["consent_available"] = len(matching_consents) > 0
        
        if not result["consent_available"]:
            result["violation_risk"] = "high"
        
        return result
    
    # === ACCESS LOGGING ===
    
    def log_data_access(
        self,
        user_id: int,
        student_id: int,
        data_type: str,
        action: str,
        access_reason: DataAccessReason,
        purpose_description: str,
        record_id: int = None,
        table_name: str = None,
        endpoint: str = None,
        ip_address: str = None,
        user_agent: str = None,
        session_id: str = None,
        data_anonymized: bool = False
    ) -> DataAccessLog:
        """Log access to student educational records"""
        
        # Check if consent is required and available
        consent_check = self.check_consent_required(student_id, data_type, access_reason)
        consent_verified = consent_check["consent_available"] if consent_check["consent_required"] else True
        
        # Create access log
        access_log = DataAccessLog(
            user_id=user_id,
            student_id=student_id,
            data_type=data_type,
            record_id=record_id,
            table_name=table_name,
            access_reason=access_reason,
            purpose_description=purpose_description,
            action=action,
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            data_anonymized=data_anonymized,
            consent_verified=consent_verified
        )
        
        self.db.add(access_log)
        self.db.commit()
        self.db.refresh(access_log)
        
        # Check for potential violations
        if consent_check["violation_risk"] == "high":
            self._log_compliance_event(
                "potential_privacy_violation",
                "access",
                f"High-risk data access: {data_type} for student {student_id} without proper consent",
                severity_level="warning",
                user_id=user_id,
                affected_student_id=student_id,
                requires_action=True
            )
        
        return access_log
    
    def get_student_access_history(
        self,
        student_id: int,
        limit: int = 100,
        data_type: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[DataAccessLog]:
        """Get access history for a student's records"""
        
        query = self.db.query(DataAccessLog).filter(DataAccessLog.student_id == student_id)
        
        if data_type:
            query = query.filter(DataAccessLog.data_type == data_type)
        
        if start_date:
            query = query.filter(DataAccessLog.access_timestamp >= start_date)
            
        if end_date:
            query = query.filter(DataAccessLog.access_timestamp <= end_date)
        
        return query.order_by(desc(DataAccessLog.access_timestamp)).limit(limit).all()
    
    def detect_access_anomalies(self, student_id: int) -> List[Dict[str, Any]]:
        """Detect unusual access patterns that may indicate privacy violations"""
        
        anomalies = []
        
        # Get recent access logs (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_access = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.student_id == student_id,
                DataAccessLog.access_timestamp >= thirty_days_ago
            )
        ).all()
        
        # Detect unusual access volumes
        access_by_user = {}
        for log in recent_access:
            if log.user_id not in access_by_user:
                access_by_user[log.user_id] = []
            access_by_user[log.user_id].append(log)
        
        # Flag users with unusually high access
        for user_id, access_logs in access_by_user.items():
            if len(access_logs) > 50:  # More than 50 accesses in 30 days
                anomalies.append({
                    "type": "high_volume_access",
                    "user_id": user_id,
                    "access_count": len(access_logs),
                    "description": f"User {user_id} accessed student data {len(access_logs)} times in 30 days",
                    "severity": "medium"
                })
        
        # Detect access outside business hours
        after_hours_access = [
            log for log in recent_access
            if log.access_timestamp.hour < 7 or log.access_timestamp.hour > 19
        ]
        
        if len(after_hours_access) > 5:
            anomalies.append({
                "type": "after_hours_access",
                "access_count": len(after_hours_access),
                "description": f"{len(after_hours_access)} data accesses outside business hours",
                "severity": "medium"
            })
        
        # Detect access without proper consent
        unauthorized_access = [
            log for log in recent_access
            if not log.consent_verified and log.access_reason not in [
                DataAccessReason.SAFETY_EMERGENCY, 
                DataAccessReason.COURT_ORDER
            ]
        ]
        
        if unauthorized_access:
            anomalies.append({
                "type": "unauthorized_access",
                "access_count": len(unauthorized_access),
                "description": f"{len(unauthorized_access)} data accesses without proper consent",
                "severity": "high"
            })
        
        return anomalies
    
    # === PRIVACY SETTINGS ===
    
    def get_privacy_settings(self, student_id: int) -> PrivacySettings:
        """Get privacy settings for a student"""
        
        settings = self.db.query(PrivacySettings).filter(
            PrivacySettings.student_id == student_id
        ).first()
        
        if not settings:
            # Create default privacy settings
            settings = self._create_default_privacy_settings(student_id)
        
        return settings
    
    def update_privacy_settings(
        self,
        student_id: int,
        settings: Dict[str, Any],
        updated_by_id: int
    ) -> PrivacySettings:
        """Update privacy settings for a student"""
        
        privacy_settings = self.get_privacy_settings(student_id)
        
        # Update settings
        for key, value in settings.items():
            if hasattr(privacy_settings, key):
                setattr(privacy_settings, key, value)
        
        privacy_settings.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        # Log settings change
        self._log_compliance_event(
            "privacy_settings_updated",
            "privacy",
            f"Privacy settings updated for student {student_id}",
            user_id=updated_by_id,
            affected_student_id=student_id,
            technical_details=json.dumps(settings)
        )
        
        return privacy_settings
    
    # === DATA RETENTION ===
    
    def create_retention_policy(
        self,
        policy_name: str,
        category: DataRetentionCategory,
        retention_years: int,
        retention_months: int,
        retention_days: int,
        description: str,
        legal_basis: str,
        auto_purge: bool = True,
        warning_days: int = 30
    ) -> DataRetentionPolicy:
        """Create a new data retention policy"""
        
        policy = DataRetentionPolicy(
            policy_name=policy_name,
            category=category,
            retention_period_years=retention_years,
            retention_period_months=retention_months,
            retention_period_days=retention_days,
            description=description,
            legal_basis=legal_basis,
            auto_purge_enabled=auto_purge,
            warning_period_days=warning_days,
            effective_date=datetime.utcnow()
        )
        
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        
        return policy
    
    def schedule_data_purge(
        self,
        table_name: str,
        record_id: int,
        student_id: int,
        policy: DataRetentionPolicy,
        record_created_date: datetime
    ) -> DataPurgeSchedule:
        """Schedule data for purging based on retention policy"""
        
        # Calculate purge date
        purge_date = record_created_date + timedelta(
            days=policy.retention_period_years * 365 + 
                 policy.retention_period_months * 30 + 
                 policy.retention_period_days
        )
        
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name=table_name,
            record_id=record_id,
            student_id=student_id,
            scheduled_purge_date=purge_date,
            status="scheduled"
        )
        
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        
        return schedule
    
    def get_records_due_for_purge(self, days_ahead: int = 0) -> List[DataPurgeSchedule]:
        """Get records that are due for purging"""
        
        cutoff_date = datetime.utcnow() + timedelta(days=days_ahead)
        
        return self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= cutoff_date,
                DataPurgeSchedule.status.in_(["scheduled", "warned"])
            )
        ).all()
    
    def execute_data_purge(self, schedule_id: int, executed_by_id: int) -> bool:
        """Execute scheduled data purge"""
        
        schedule = self.db.query(DataPurgeSchedule).filter(
            DataPurgeSchedule.id == schedule_id
        ).first()
        
        if not schedule:
            return False
        
        if schedule.status not in ["scheduled", "warned"]:
            return False
        
        try:
            # Here you would implement the actual data deletion
            # This is a placeholder for the actual purge logic
            
            # Mark as purged
            schedule.status = "purged"
            schedule.actual_purge_date = datetime.utcnow()
            
            self.db.commit()
            
            # Log purge execution
            self._log_compliance_event(
                "data_purged",
                "retention",
                f"Data purged from {schedule.table_name} (record {schedule.record_id}) for student {schedule.student_id}",
                user_id=executed_by_id,
                affected_student_id=schedule.student_id
            )
            
            return True
            
        except Exception as e:
            self.db.rollback()
            
            self._log_compliance_event(
                "data_purge_failed",
                "retention",
                f"Failed to purge data from {schedule.table_name} (record {schedule.record_id}): {str(e)}",
                severity_level="error",
                user_id=executed_by_id,
                affected_student_id=schedule.student_id,
                requires_action=True
            )
            
            return False
    
    # === COMPLIANCE REPORTING ===
    
    def generate_compliance_report(
        self,
        start_date: datetime,
        end_date: datetime,
        report_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """Generate comprehensive compliance report"""
        
        report = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "consent_management": {},
            "data_access": {},
            "retention_compliance": {},
            "privacy_violations": {},
            "summary": {}
        }
        
        # Consent management statistics
        consent_stats = self._get_consent_statistics(start_date, end_date)
        report["consent_management"] = consent_stats
        
        # Data access statistics
        access_stats = self._get_access_statistics(start_date, end_date)
        report["data_access"] = access_stats
        
        # Retention compliance
        retention_stats = self._get_retention_statistics(start_date, end_date)
        report["retention_compliance"] = retention_stats
        
        # Privacy violations
        violations = self._get_privacy_violations(start_date, end_date)
        report["privacy_violations"] = violations
        
        # Generate summary
        report["summary"] = {
            "total_consents_processed": consent_stats.get("total_processed", 0),
            "total_data_accesses": access_stats.get("total_accesses", 0),
            "records_purged": retention_stats.get("records_purged", 0),
            "privacy_violations": len(violations.get("incidents", [])),
            "compliance_score": self._calculate_compliance_score(report)
        }
        
        return report
    
    # === PRIVATE HELPER METHODS ===
    
    def _create_default_privacy_settings(self, student_id: int) -> PrivacySettings:
        """Create default privacy settings for a student"""
        
        settings = PrivacySettings(
            student_id=student_id,
            directory_info_public=False,
            allow_name_disclosure=False,
            allow_photo_disclosure=False,
            allow_contact_disclosure=False,
            allow_academic_info_disclosure=False,
            allow_progress_notifications=True,
            allow_attendance_notifications=True,
            allow_emergency_contact=True,
            opt_in_research=False,
            opt_in_analytics=False,
            opt_in_third_party_services=False,
            parental_approval_required=False,
            parent_email_cc=False
        )
        
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        
        return settings
    
    def _log_compliance_event(
        self,
        event_type: str,
        event_category: str,
        description: str,
        severity_level: str = "info",
        user_id: int = None,
        affected_student_id: int = None,
        requires_action: bool = False,
        technical_details: str = None,
        ip_address: str = None,
        user_agent: str = None
    ) -> ComplianceAuditLog:
        """Log compliance-related events"""
        
        audit_log = ComplianceAuditLog(
            event_type=event_type,
            event_category=event_category,
            severity_level=severity_level,
            user_id=user_id,
            affected_student_id=affected_student_id,
            description=description,
            technical_details=technical_details,
            requires_action=requires_action,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)
        
        return audit_log
    
    def _get_consent_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get consent management statistics for reporting"""
        
        consents = self.db.query(StudentConsent).filter(
            and_(
                StudentConsent.created_at >= start_date,
                StudentConsent.created_at <= end_date
            )
        ).all()
        
        stats = {
            "total_processed": len(consents),
            "by_status": {},
            "by_type": {},
            "response_time_avg_hours": 0
        }
        
        for consent in consents:
            # Count by status
            status = consent.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            
            # Count by type
            consent_type = consent.consent_type.value
            stats["by_type"][consent_type] = stats["by_type"].get(consent_type, 0) + 1
        
        return stats
    
    def _get_access_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get data access statistics for reporting"""
        
        accesses = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.access_timestamp >= start_date,
                DataAccessLog.access_timestamp <= end_date
            )
        ).all()
        
        stats = {
            "total_accesses": len(accesses),
            "by_data_type": {},
            "by_reason": {},
            "consent_compliance_rate": 0
        }
        
        consented_access = 0
        
        for access in accesses:
            # Count by data type
            data_type = access.data_type
            stats["by_data_type"][data_type] = stats["by_data_type"].get(data_type, 0) + 1
            
            # Count by reason
            reason = access.access_reason.value
            stats["by_reason"][reason] = stats["by_reason"].get(reason, 0) + 1
            
            # Count consented access
            if access.consent_verified:
                consented_access += 1
        
        if len(accesses) > 0:
            stats["consent_compliance_rate"] = (consented_access / len(accesses)) * 100
        
        return stats
    
    def _get_retention_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get data retention statistics for reporting"""
        
        purges = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.actual_purge_date >= start_date,
                DataPurgeSchedule.actual_purge_date <= end_date,
                DataPurgeSchedule.status == "purged"
            )
        ).all()
        
        return {
            "records_purged": len(purges),
            "by_policy": {},
            "scheduled_purges_pending": self.db.query(DataPurgeSchedule).filter(
                DataPurgeSchedule.status.in_(["scheduled", "warned"])
            ).count()
        }
    
    def _get_privacy_violations(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get privacy violations for reporting"""
        
        violations = self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.created_at >= start_date,
                ComplianceAuditLog.created_at <= end_date,
                ComplianceAuditLog.severity_level.in_(["warning", "error", "critical"])
            )
        ).all()
        
        return {
            "incidents": [
                {
                    "id": v.id,
                    "type": v.event_type,
                    "severity": v.severity_level,
                    "description": v.description,
                    "date": v.created_at.isoformat(),
                    "resolved": v.resolved_at is not None
                }
                for v in violations
            ],
            "by_severity": {
                "warning": len([v for v in violations if v.severity_level == "warning"]),
                "error": len([v for v in violations if v.severity_level == "error"]),
                "critical": len([v for v in violations if v.severity_level == "critical"])
            }
        }
    
    def _calculate_compliance_score(self, report: Dict[str, Any]) -> float:
        """Calculate overall compliance score based on report metrics"""
        
        score = 100.0
        
        # Deduct for privacy violations
        violations = report["privacy_violations"]
        critical_violations = violations["by_severity"].get("critical", 0)
        error_violations = violations["by_severity"].get("error", 0)
        warning_violations = violations["by_severity"].get("warning", 0)
        
        score -= (critical_violations * 10) + (error_violations * 5) + (warning_violations * 1)
        
        # Deduct for low consent compliance
        consent_rate = report["data_access"].get("consent_compliance_rate", 100)
        if consent_rate < 95:
            score -= (95 - consent_rate) * 2
        
        return max(0.0, min(100.0, score))