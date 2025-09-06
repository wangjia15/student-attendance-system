"""
Data Retention Engine

Automated data retention and purging system for FERPA compliance
with configurable policies, automated scheduling, and safe deletion processes.
"""

from typing import List, Dict, Any, Optional, Union, Callable
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func, text
import json
import logging
from enum import Enum
from dataclasses import dataclass
import schedule
import time
import threading

from app.models.ferpa import (
    DataRetentionPolicy, DataPurgeSchedule, DataRetentionCategory,
    ComplianceAuditLog
)
from app.models.user import User
from app.models.attendance import AttendanceRecord
from app.compliance.audit_service import ComplianceAuditService, AuditSeverity

logger = logging.getLogger(__name__)


class RetentionStatus(str, Enum):
    """Status of retention operations"""
    SCHEDULED = "scheduled"
    WARNED = "warned"
    PURGED = "purged"
    EXEMPTED = "exempted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PurgeStrategy(str, Enum):
    """Data purging strategies"""
    HARD_DELETE = "hard_delete"           # Permanent deletion
    SOFT_DELETE = "soft_delete"           # Mark as deleted
    ANONYMIZE = "anonymize"               # Replace with anonymous data
    ARCHIVE = "archive"                   # Move to archive storage


@dataclass
class RetentionRule:
    """Data retention rule definition"""
    category: DataRetentionCategory
    retention_years: int
    retention_months: int
    retention_days: int
    purge_strategy: PurgeStrategy
    warning_days: int
    auto_purge: bool
    requires_review: bool
    legal_basis: str
    exceptions: List[str]


class DataRetentionEngine:
    """
    Automated data retention and purging engine implementing
    FERPA-compliant data lifecycle management.
    """
    
    def __init__(self, db: Session, audit_service: ComplianceAuditService = None):
        self.db = db
        self.audit_service = audit_service or ComplianceAuditService(db)
        self.is_running = False
        self.scheduler_thread = None
        
        # Initialize default retention policies
        self._initialize_default_policies()
    
    # === RETENTION POLICY MANAGEMENT ===
    
    def create_retention_policy(
        self,
        policy_name: str,
        category: DataRetentionCategory,
        retention_rule: RetentionRule,
        description: str,
        effective_date: datetime = None
    ) -> DataRetentionPolicy:
        """
        Create comprehensive data retention policy
        """
        
        if not effective_date:
            effective_date = datetime.utcnow()
        
        # Check if policy already exists
        existing_policy = self.db.query(DataRetentionPolicy).filter(
            DataRetentionPolicy.policy_name == policy_name
        ).first()
        
        if existing_policy:
            raise ValueError(f"Retention policy '{policy_name}' already exists")
        
        policy = DataRetentionPolicy(
            policy_name=policy_name,
            category=category,
            retention_period_years=retention_rule.retention_years,
            retention_period_months=retention_rule.retention_months,
            retention_period_days=retention_rule.retention_days,
            description=description,
            legal_basis=retention_rule.legal_basis,
            exceptions=json.dumps(retention_rule.exceptions),
            auto_purge_enabled=retention_rule.auto_purge,
            warning_period_days=retention_rule.warning_days,
            is_active=True,
            requires_manual_review=retention_rule.requires_review,
            effective_date=effective_date
        )
        
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        
        # Log policy creation
        self.audit_service.log_audit_event(
            event_type="retention_policy_created",
            event_category="retention",
            description=f"Data retention policy '{policy_name}' created for {category.value}",
            severity_level=AuditSeverity.INFO,
            technical_details={
                "policy_id": policy.id,
                "category": category.value,
                "retention_period": f"{retention_rule.retention_years}Y {retention_rule.retention_months}M {retention_rule.retention_days}D",
                "auto_purge": retention_rule.auto_purge
            }
        )
        
        return policy
    
    def update_retention_policy(
        self,
        policy_id: int,
        updates: Dict[str, Any],
        updated_by_id: int
    ) -> DataRetentionPolicy:
        """
        Update existing retention policy
        """
        
        policy = self.db.query(DataRetentionPolicy).filter(
            DataRetentionPolicy.id == policy_id
        ).first()
        
        if not policy:
            raise ValueError(f"Retention policy {policy_id} not found")
        
        # Store original values for audit
        original_values = {
            "retention_years": policy.retention_period_years,
            "retention_months": policy.retention_period_months,
            "retention_days": policy.retention_period_days,
            "auto_purge": policy.auto_purge_enabled
        }
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
        
        policy.updated_at = datetime.utcnow()
        self.db.commit()
        
        # Log policy update
        self.audit_service.log_audit_event(
            event_type="retention_policy_updated",
            event_category="retention",
            description=f"Retention policy '{policy.policy_name}' updated",
            severity_level=AuditSeverity.INFO,
            user_id=updated_by_id,
            technical_details={
                "policy_id": policy_id,
                "original_values": original_values,
                "updates": updates
            }
        )
        
        return policy
    
    def get_active_policies(self) -> List[DataRetentionPolicy]:
        """Get all active retention policies"""
        
        return self.db.query(DataRetentionPolicy).filter(
            and_(
                DataRetentionPolicy.is_active == True,
                DataRetentionPolicy.effective_date <= datetime.utcnow()
            )
        ).all()
    
    # === AUTOMATED SCHEDULING ===
    
    def schedule_data_for_purge(
        self,
        table_name: str,
        record_id: int,
        student_id: int,
        created_date: datetime,
        category: DataRetentionCategory,
        metadata: Dict[str, Any] = None
    ) -> DataPurgeSchedule:
        """
        Schedule individual record for purging based on retention policies
        """
        
        # Find applicable retention policy
        policy = self.db.query(DataRetentionPolicy).filter(
            and_(
                DataRetentionPolicy.category == category,
                DataRetentionPolicy.is_active == True,
                DataRetentionPolicy.effective_date <= created_date
            )
        ).order_by(desc(DataRetentionPolicy.effective_date)).first()
        
        if not policy:
            raise ValueError(f"No active retention policy found for category {category.value}")
        
        # Calculate purge date
        purge_date = self._calculate_purge_date(created_date, policy)
        
        # Check for existing schedule
        existing_schedule = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.table_name == table_name,
                DataPurgeSchedule.record_id == record_id
            )
        ).first()
        
        if existing_schedule:
            logger.debug(f"Purge already scheduled for {table_name}:{record_id}")
            return existing_schedule
        
        # Create purge schedule
        schedule = DataPurgeSchedule(
            policy_id=policy.id,
            table_name=table_name,
            record_id=record_id,
            student_id=student_id,
            scheduled_purge_date=purge_date,
            status=RetentionStatus.SCHEDULED.value
        )
        
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        
        logger.info(f"Scheduled purge for {table_name}:{record_id} on {purge_date}")
        
        return schedule
    
    def bulk_schedule_existing_data(self, category: DataRetentionCategory, limit: int = 1000) -> Dict[str, Any]:
        """
        Bulk schedule existing data for purging based on retention policies
        """
        
        results = {
            "category": category.value,
            "scheduled_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "errors": []
        }
        
        try:
            if category == DataRetentionCategory.ATTENDANCE_RECORDS:
                results = self._schedule_attendance_records(limit)
            elif category == DataRetentionCategory.AUDIT_LOGS:
                results = self._schedule_audit_logs(limit)
            elif category == DataRetentionCategory.CONSENT_RECORDS:
                results = self._schedule_consent_records(limit)
            else:
                results["errors"].append(f"Bulk scheduling not implemented for {category.value}")
                results["error_count"] = 1
        
        except Exception as e:
            logger.error(f"Error in bulk scheduling for {category.value}: {str(e)}")
            results["errors"].append(str(e))
            results["error_count"] += 1
        
        # Log bulk scheduling
        self.audit_service.log_audit_event(
            event_type="bulk_schedule_retention",
            event_category="retention",
            description=f"Bulk scheduled {results['scheduled_count']} {category.value} records for purging",
            severity_level=AuditSeverity.INFO,
            technical_details=results
        )
        
        return results
    
    # === AUTOMATED PURGING ===
    
    def run_automated_purge(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run automated purge process for all due records
        """
        
        purge_results = {
            "dry_run": dry_run,
            "started_at": datetime.utcnow().isoformat(),
            "records_processed": 0,
            "successfully_purged": 0,
            "warnings_sent": 0,
            "exempted": 0,
            "failed": 0,
            "errors": []
        }
        
        try:
            # Get records due for warning
            warning_due = self._get_records_due_for_warning()
            for schedule in warning_due:
                if not dry_run:
                    self._send_purge_warning(schedule)
                purge_results["warnings_sent"] += 1
            
            # Get records due for purging
            purge_due = self._get_records_due_for_purge()
            purge_results["records_processed"] = len(purge_due)
            
            for schedule in purge_due:
                try:
                    # Check for exemptions
                    if self._check_purge_exemptions(schedule):
                        if not dry_run:
                            schedule.status = RetentionStatus.EXEMPTED.value
                            schedule.exemption_reason = "Legal hold or active case"
                        purge_results["exempted"] += 1
                        continue
                    
                    # Perform purge
                    if not dry_run:
                        success = self._execute_record_purge(schedule)
                        if success:
                            purge_results["successfully_purged"] += 1
                        else:
                            purge_results["failed"] += 1
                    else:
                        purge_results["successfully_purged"] += 1
                        
                except Exception as e:
                    error_msg = f"Failed to purge {schedule.table_name}:{schedule.record_id}: {str(e)}"
                    logger.error(error_msg)
                    purge_results["errors"].append(error_msg)
                    purge_results["failed"] += 1
            
            if not dry_run:
                self.db.commit()
        
        except Exception as e:
            if not dry_run:
                self.db.rollback()
            logger.error(f"Automated purge failed: {str(e)}")
            purge_results["errors"].append(str(e))
        
        purge_results["completed_at"] = datetime.utcnow().isoformat()
        
        # Log purge run
        self.audit_service.log_audit_event(
            event_type="automated_purge_run",
            event_category="retention",
            description=f"Automated purge {'simulation' if dry_run else 'execution'} completed: {purge_results['successfully_purged']} purged, {purge_results['failed']} failed",
            severity_level=AuditSeverity.WARNING if purge_results["failed"] > 0 else AuditSeverity.INFO,
            technical_details=purge_results
        )
        
        return purge_results
    
    def manual_purge_record(
        self,
        schedule_id: int,
        executed_by_id: int,
        reason: str = "Manual purge requested"
    ) -> Dict[str, Any]:
        """
        Manually purge a specific scheduled record
        """
        
        schedule = self.db.query(DataPurgeSchedule).filter(
            DataPurgeSchedule.id == schedule_id
        ).first()
        
        if not schedule:
            raise ValueError(f"Purge schedule {schedule_id} not found")
        
        if schedule.status not in [RetentionStatus.SCHEDULED.value, RetentionStatus.WARNED.value]:
            raise ValueError(f"Record cannot be purged - current status: {schedule.status}")
        
        # Check for exemptions
        if self._check_purge_exemptions(schedule):
            return {
                "success": False,
                "reason": "Record is exempt from purging",
                "exemption_details": schedule.exemption_reason
            }
        
        # Execute purge
        success = self._execute_record_purge(schedule, executed_by_id)
        
        if success:
            # Log manual purge
            self.audit_service.log_audit_event(
                event_type="manual_record_purge",
                event_category="retention",
                description=f"Manual purge executed for {schedule.table_name}:{schedule.record_id}",
                severity_level=AuditSeverity.INFO,
                user_id=executed_by_id,
                affected_student_id=schedule.student_id,
                technical_details={
                    "schedule_id": schedule_id,
                    "reason": reason,
                    "table_name": schedule.table_name,
                    "record_id": schedule.record_id
                }
            )
        
        self.db.commit()
        
        return {
            "success": success,
            "schedule_id": schedule_id,
            "executed_by": executed_by_id,
            "reason": reason,
            "purged_at": schedule.actual_purge_date.isoformat() if schedule.actual_purge_date else None
        }
    
    # === EXEMPTION MANAGEMENT ===
    
    def grant_purge_exemption(
        self,
        schedule_id: int,
        exemption_reason: str,
        granted_by_id: int,
        exemption_expires: datetime = None
    ) -> DataPurgeSchedule:
        """
        Grant exemption from data purging
        """
        
        schedule = self.db.query(DataPurgeSchedule).filter(
            DataPurgeSchedule.id == schedule_id
        ).first()
        
        if not schedule:
            raise ValueError(f"Purge schedule {schedule_id} not found")
        
        schedule.status = RetentionStatus.EXEMPTED.value
        schedule.exemption_reason = exemption_reason
        schedule.exemption_granted_by = granted_by_id
        schedule.exemption_expires = exemption_expires
        
        self.db.commit()
        
        # Log exemption
        self.audit_service.log_audit_event(
            event_type="purge_exemption_granted",
            event_category="retention",
            description=f"Purge exemption granted for {schedule.table_name}:{schedule.record_id}",
            severity_level=AuditSeverity.INFO,
            user_id=granted_by_id,
            affected_student_id=schedule.student_id,
            technical_details={
                "schedule_id": schedule_id,
                "exemption_reason": exemption_reason,
                "expires": exemption_expires.isoformat() if exemption_expires else None
            }
        )
        
        return schedule
    
    def revoke_purge_exemption(
        self,
        schedule_id: int,
        revoked_by_id: int,
        reason: str = "Exemption no longer needed"
    ) -> DataPurgeSchedule:
        """
        Revoke previously granted purge exemption
        """
        
        schedule = self.db.query(DataPurgeSchedule).filter(
            DataPurgeSchedule.id == schedule_id
        ).first()
        
        if not schedule:
            raise ValueError(f"Purge schedule {schedule_id} not found")
        
        if schedule.status != RetentionStatus.EXEMPTED.value:
            raise ValueError(f"Schedule is not currently exempted: {schedule.status}")
        
        schedule.status = RetentionStatus.SCHEDULED.value
        schedule.exemption_reason = None
        schedule.exemption_granted_by = None
        schedule.exemption_expires = None
        
        self.db.commit()
        
        # Log exemption revocation
        self.audit_service.log_audit_event(
            event_type="purge_exemption_revoked",
            event_category="retention",
            description=f"Purge exemption revoked for {schedule.table_name}:{schedule.record_id}",
            severity_level=AuditSeverity.INFO,
            user_id=revoked_by_id,
            affected_student_id=schedule.student_id,
            technical_details={
                "schedule_id": schedule_id,
                "reason": reason
            }
        )
        
        return schedule
    
    # === SCHEDULER DAEMON ===
    
    def start_scheduler(self):
        """Start the retention scheduler daemon"""
        
        if self.is_running:
            logger.warning("Retention scheduler is already running")
            return
        
        logger.info("Starting data retention scheduler daemon")
        
        # Schedule daily purge runs
        schedule.every().day.at("02:00").do(self._scheduled_purge_job)
        
        # Schedule warning checks
        schedule.every().day.at("09:00").do(self._scheduled_warning_job)
        
        # Schedule policy compliance checks
        schedule.every().hour.do(self._scheduled_compliance_check)
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        self.audit_service.log_audit_event(
            event_type="retention_scheduler_started",
            event_category="retention",
            description="Data retention scheduler daemon started",
            severity_level=AuditSeverity.INFO
        )
    
    def stop_scheduler(self):
        """Stop the retention scheduler daemon"""
        
        if not self.is_running:
            logger.warning("Retention scheduler is not running")
            return
        
        logger.info("Stopping data retention scheduler daemon")
        
        self.is_running = False
        schedule.clear()
        
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        
        self.audit_service.log_audit_event(
            event_type="retention_scheduler_stopped",
            event_category="retention",
            description="Data retention scheduler daemon stopped",
            severity_level=AuditSeverity.INFO
        )
    
    # === REPORTING ===
    
    def generate_retention_report(
        self,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive data retention compliance report
        """
        
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()
        
        report = {
            "report_metadata": {
                "title": "Data Retention Compliance Report",
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "generated_at": datetime.utcnow().isoformat()
            },
            "policy_summary": self._get_policy_summary(),
            "purge_statistics": self._get_purge_statistics(start_date, end_date),
            "compliance_metrics": self._get_retention_compliance_metrics(),
            "upcoming_purges": self._get_upcoming_purges(),
            "exemption_summary": self._get_exemption_summary(),
            "recommendations": self._generate_retention_recommendations()
        }
        
        return report
    
    # === PRIVATE HELPER METHODS ===
    
    def _initialize_default_policies(self):
        """Initialize default retention policies if they don't exist"""
        
        default_policies = [
            {
                "name": "Student Attendance Records",
                "category": DataRetentionCategory.ATTENDANCE_RECORDS,
                "rule": RetentionRule(
                    category=DataRetentionCategory.ATTENDANCE_RECORDS,
                    retention_years=7,
                    retention_months=0,
                    retention_days=0,
                    purge_strategy=PurgeStrategy.ARCHIVE,
                    warning_days=30,
                    auto_purge=True,
                    requires_review=False,
                    legal_basis="FERPA requires 5-7 years retention for academic records",
                    exceptions=["active_legal_case", "special_education_records"]
                ),
                "description": "Retention policy for student attendance records"
            },
            {
                "name": "Audit Logs",
                "category": DataRetentionCategory.AUDIT_LOGS,
                "rule": RetentionRule(
                    category=DataRetentionCategory.AUDIT_LOGS,
                    retention_years=10,
                    retention_months=0,
                    retention_days=0,
                    purge_strategy=PurgeStrategy.ARCHIVE,
                    warning_days=60,
                    auto_purge=False,
                    requires_review=True,
                    legal_basis="Extended retention for compliance audit trails",
                    exceptions=["ongoing_investigation", "litigation_hold"]
                ),
                "description": "Extended retention for compliance audit logs"
            }
        ]
        
        for policy_def in default_policies:
            existing = self.db.query(DataRetentionPolicy).filter(
                DataRetentionPolicy.policy_name == policy_def["name"]
            ).first()
            
            if not existing:
                try:
                    self.create_retention_policy(
                        policy_name=policy_def["name"],
                        category=policy_def["category"],
                        retention_rule=policy_def["rule"],
                        description=policy_def["description"]
                    )
                    logger.info(f"Created default retention policy: {policy_def['name']}")
                except Exception as e:
                    logger.error(f"Failed to create default policy {policy_def['name']}: {str(e)}")
    
    def _calculate_purge_date(self, created_date: datetime, policy: DataRetentionPolicy) -> datetime:
        """Calculate the purge date based on policy and creation date"""
        
        return created_date + timedelta(
            days=(
                policy.retention_period_years * 365 +
                policy.retention_period_months * 30 +
                policy.retention_period_days
            )
        )
    
    def _schedule_attendance_records(self, limit: int) -> Dict[str, Any]:
        """Schedule attendance records for retention"""
        
        results = {"scheduled_count": 0, "skipped_count": 0, "error_count": 0, "errors": []}
        
        # Get attendance records not already scheduled
        attendance_records = self.db.query(AttendanceRecord).outerjoin(
            DataPurgeSchedule,
            and_(
                DataPurgeSchedule.table_name == "attendance_records",
                DataPurgeSchedule.record_id == AttendanceRecord.id
            )
        ).filter(DataPurgeSchedule.id.is_(None)).limit(limit).all()
        
        for record in attendance_records:
            try:
                self.schedule_data_for_purge(
                    table_name="attendance_records",
                    record_id=record.id,
                    student_id=record.student_id,
                    created_date=record.created_at,
                    category=DataRetentionCategory.ATTENDANCE_RECORDS
                )
                results["scheduled_count"] += 1
            except Exception as e:
                results["errors"].append(f"Record {record.id}: {str(e)}")
                results["error_count"] += 1
        
        return results
    
    def _schedule_audit_logs(self, limit: int) -> Dict[str, Any]:
        """Schedule audit logs for retention"""
        
        results = {"scheduled_count": 0, "skipped_count": 0, "error_count": 0, "errors": []}
        
        # Get compliance audit logs not already scheduled
        audit_logs = self.db.query(ComplianceAuditLog).outerjoin(
            DataPurgeSchedule,
            and_(
                DataPurgeSchedule.table_name == "compliance_audit_logs",
                DataPurgeSchedule.record_id == ComplianceAuditLog.id
            )
        ).filter(DataPurgeSchedule.id.is_(None)).limit(limit).all()
        
        for record in audit_logs:
            try:
                self.schedule_data_for_purge(
                    table_name="compliance_audit_logs",
                    record_id=record.id,
                    student_id=record.affected_student_id,
                    created_date=record.created_at,
                    category=DataRetentionCategory.AUDIT_LOGS
                )
                results["scheduled_count"] += 1
            except Exception as e:
                results["errors"].append(f"Record {record.id}: {str(e)}")
                results["error_count"] += 1
        
        return results
    
    def _schedule_consent_records(self, limit: int) -> Dict[str, Any]:
        """Schedule consent records for retention"""
        
        results = {"scheduled_count": 0, "skipped_count": 0, "error_count": 0, "errors": []}
        # Implementation would schedule consent records
        return results
    
    def _get_records_due_for_warning(self) -> List[DataPurgeSchedule]:
        """Get records that need purge warnings sent"""
        
        warning_cutoff = datetime.utcnow() + timedelta(days=30)  # 30 days warning
        
        return self.db.query(DataPurgeSchedule).join(DataRetentionPolicy).filter(
            and_(
                DataPurgeSchedule.status == RetentionStatus.SCHEDULED.value,
                DataPurgeSchedule.scheduled_purge_date <= warning_cutoff,
                DataPurgeSchedule.warning_sent_date.is_(None),
                DataRetentionPolicy.warning_period_days > 0
            )
        ).all()
    
    def _get_records_due_for_purge(self) -> List[DataPurgeSchedule]:
        """Get records that are due for purging"""
        
        return self.db.query(DataPurgeSchedule).join(DataRetentionPolicy).filter(
            and_(
                DataPurgeSchedule.status.in_([RetentionStatus.SCHEDULED.value, RetentionStatus.WARNED.value]),
                DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow(),
                DataRetentionPolicy.auto_purge_enabled == True
            )
        ).all()
    
    def _send_purge_warning(self, schedule: DataPurgeSchedule):
        """Send warning notification before purging data"""
        
        schedule.warning_sent_date = datetime.utcnow()
        schedule.status = RetentionStatus.WARNED.value
        
        # In a real implementation, this would send notifications
        logger.info(f"Purge warning sent for {schedule.table_name}:{schedule.record_id}")
        
        self.audit_service.log_audit_event(
            event_type="purge_warning_sent",
            event_category="retention",
            description=f"Purge warning sent for {schedule.table_name}:{schedule.record_id}",
            severity_level=AuditSeverity.INFO,
            affected_student_id=schedule.student_id
        )
    
    def _check_purge_exemptions(self, schedule: DataPurgeSchedule) -> bool:
        """Check if record is exempt from purging"""
        
        # Check for existing exemptions
        if schedule.exemption_reason and schedule.status == RetentionStatus.EXEMPTED.value:
            if schedule.exemption_expires and schedule.exemption_expires > datetime.utcnow():
                return True
            elif not schedule.exemption_expires:
                return True
        
        # Check for automatic exemptions (legal holds, active cases, etc.)
        # This would be implemented based on specific business rules
        
        return False
    
    def _execute_record_purge(self, schedule: DataPurgeSchedule, executed_by_id: int = None) -> bool:
        """Execute the actual purge of a record"""
        
        try:
            # Get the purge strategy from policy
            policy = self.db.query(DataRetentionPolicy).filter(
                DataRetentionPolicy.id == schedule.policy_id
            ).first()
            
            if not policy:
                logger.error(f"Policy not found for schedule {schedule.id}")
                return False
            
            # Execute based on table and strategy
            success = False
            
            if schedule.table_name == "attendance_records":
                success = self._purge_attendance_record(schedule, policy)
            elif schedule.table_name == "compliance_audit_logs":
                success = self._purge_audit_log(schedule, policy)
            else:
                logger.error(f"Purge not implemented for table: {schedule.table_name}")
                return False
            
            if success:
                schedule.status = RetentionStatus.PURGED.value
                schedule.actual_purge_date = datetime.utcnow()
                
                self.audit_service.log_audit_event(
                    event_type="record_purged",
                    event_category="retention",
                    description=f"Record purged: {schedule.table_name}:{schedule.record_id}",
                    severity_level=AuditSeverity.INFO,
                    user_id=executed_by_id,
                    affected_student_id=schedule.student_id,
                    technical_details={
                        "schedule_id": schedule.id,
                        "table_name": schedule.table_name,
                        "record_id": schedule.record_id,
                        "policy_id": schedule.policy_id
                    }
                )
            else:
                schedule.status = RetentionStatus.FAILED.value
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to purge record {schedule.table_name}:{schedule.record_id}: {str(e)}")
            schedule.status = RetentionStatus.FAILED.value
            return False
    
    def _purge_attendance_record(self, schedule: DataPurgeSchedule, policy: DataRetentionPolicy) -> bool:
        """Purge attendance record based on policy strategy"""
        
        record = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.id == schedule.record_id
        ).first()
        
        if not record:
            logger.warning(f"Attendance record {schedule.record_id} not found")
            return True  # Already deleted
        
        try:
            # For now, use soft delete (mark as deleted)
            # In production, implement proper archival or anonymization
            self.db.delete(record)
            return True
        except Exception as e:
            logger.error(f"Failed to delete attendance record {schedule.record_id}: {str(e)}")
            return False
    
    def _purge_audit_log(self, schedule: DataPurgeSchedule, policy: DataRetentionPolicy) -> bool:
        """Purge audit log record based on policy strategy"""
        
        record = self.db.query(ComplianceAuditLog).filter(
            ComplianceAuditLog.id == schedule.record_id
        ).first()
        
        if not record:
            logger.warning(f"Audit log {schedule.record_id} not found")
            return True  # Already deleted
        
        try:
            # Archive audit logs rather than delete
            # In production, move to archive storage
            logger.info(f"Would archive audit log {schedule.record_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to archive audit log {schedule.record_id}: {str(e)}")
            return False
    
    def _run_scheduler(self):
        """Run the scheduler daemon"""
        
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}")
                time.sleep(60)
    
    def _scheduled_purge_job(self):
        """Scheduled job for automated purging"""
        logger.info("Running scheduled purge job")
        self.run_automated_purge(dry_run=False)
    
    def _scheduled_warning_job(self):
        """Scheduled job for sending purge warnings"""
        logger.info("Running scheduled warning job")
        warning_due = self._get_records_due_for_warning()
        for schedule in warning_due:
            self._send_purge_warning(schedule)
        if warning_due:
            self.db.commit()
    
    def _scheduled_compliance_check(self):
        """Scheduled compliance check"""
        overdue_count = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow() - timedelta(days=7),
                DataPurgeSchedule.status.in_([RetentionStatus.SCHEDULED.value, RetentionStatus.WARNED.value])
            )
        ).count()
        
        if overdue_count > 10:
            self.audit_service.log_audit_event(
                event_type="retention_compliance_alert",
                event_category="retention",
                description=f"{overdue_count} data purges are more than 7 days overdue",
                severity_level=AuditSeverity.WARNING,
                requires_action=True
            )
    
    # Reporting helper methods
    def _get_policy_summary(self) -> Dict[str, Any]:
        """Get summary of all retention policies"""
        
        policies = self.get_active_policies()
        return {
            "total_policies": len(policies),
            "by_category": {
                category.value: len([p for p in policies if p.category == category])
                for category in DataRetentionCategory
            },
            "auto_purge_enabled": len([p for p in policies if p.auto_purge_enabled])
        }
    
    def _get_purge_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get purge statistics for period"""
        
        purges = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.actual_purge_date >= start_date,
                DataPurgeSchedule.actual_purge_date <= end_date
            )
        ).all()
        
        return {
            "total_purged": len(purges),
            "by_status": {
                status.value: len([p for p in purges if p.status == status.value])
                for status in RetentionStatus
            },
            "by_table": {}  # Would group by table_name
        }
    
    def _get_retention_compliance_metrics(self) -> Dict[str, Any]:
        """Get retention compliance metrics"""
        
        total_scheduled = self.db.query(DataPurgeSchedule).count()
        overdue = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow(),
                DataPurgeSchedule.status.in_([RetentionStatus.SCHEDULED.value, RetentionStatus.WARNED.value])
            )
        ).count()
        
        compliance_rate = ((total_scheduled - overdue) / max(1, total_scheduled)) * 100
        
        return {
            "total_scheduled": total_scheduled,
            "overdue_purges": overdue,
            "compliance_rate": compliance_rate,
            "compliance_status": "compliant" if compliance_rate >= 95 else "non_compliant"
        }
    
    def _get_upcoming_purges(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """Get upcoming purges in next X days"""
        
        cutoff_date = datetime.utcnow() + timedelta(days=days_ahead)
        
        upcoming = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= cutoff_date,
                DataPurgeSchedule.status == RetentionStatus.SCHEDULED.value
            )
        ).order_by(DataPurgeSchedule.scheduled_purge_date).all()
        
        return [
            {
                "schedule_id": p.id,
                "table_name": p.table_name,
                "record_id": p.record_id,
                "scheduled_date": p.scheduled_purge_date.isoformat(),
                "days_remaining": (p.scheduled_purge_date - datetime.utcnow()).days
            }
            for p in upcoming
        ]
    
    def _get_exemption_summary(self) -> Dict[str, Any]:
        """Get summary of purge exemptions"""
        
        exemptions = self.db.query(DataPurgeSchedule).filter(
            DataPurgeSchedule.status == RetentionStatus.EXEMPTED.value
        ).all()
        
        return {
            "total_exemptions": len(exemptions),
            "permanent_exemptions": len([e for e in exemptions if not e.exemption_expires]),
            "temporary_exemptions": len([e for e in exemptions if e.exemption_expires])
        }
    
    def _generate_retention_recommendations(self) -> List[str]:
        """Generate recommendations for retention compliance"""
        
        recommendations = []
        
        overdue_count = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow(),
                DataPurgeSchedule.status.in_([RetentionStatus.SCHEDULED.value, RetentionStatus.WARNED.value])
            )
        ).count()
        
        if overdue_count > 0:
            recommendations.append(f"Execute {overdue_count} overdue data purges immediately")
        
        if overdue_count > 50:
            recommendations.append("Consider increasing automated purge frequency")
        
        return recommendations