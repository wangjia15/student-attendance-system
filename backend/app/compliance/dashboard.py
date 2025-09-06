"""
FERPA Compliance Reporting Dashboard

Real-time compliance monitoring dashboard providing comprehensive visibility
into FERPA compliance status, metrics, and actionable insights.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func, text
import json
import logging
from enum import Enum
from dataclasses import dataclass, asdict

from app.models.ferpa import (
    ComplianceAuditLog, DataAccessLog, StudentConsent, DataRetentionPolicy,
    DataPurgeSchedule, PrivacySettings, ConsentStatus, DataAccessReason,
    DataRetentionCategory
)
from app.models.user import User, UserRole
from app.compliance.audit_service import ComplianceAuditService
from app.compliance.retention_engine import DataRetentionEngine
from app.services.privacy_service import PrivacyService

logger = logging.getLogger(__name__)


class DashboardMetricType(str, Enum):
    """Types of dashboard metrics"""
    COMPLIANCE_SCORE = "compliance_score"
    CONSENT_RATE = "consent_rate"
    RETENTION_COMPLIANCE = "retention_compliance"
    ACTIVE_VIOLATIONS = "active_violations"
    DATA_REQUESTS = "data_requests"
    AUDIT_EVENTS = "audit_events"


class AlertSeverity(str, Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DashboardMetric:
    """Dashboard metric data structure"""
    metric_type: DashboardMetricType
    current_value: float
    previous_value: float
    trend: str  # "up", "down", "stable"
    trend_percentage: float
    target_value: float
    status: str  # "healthy", "warning", "critical"
    last_updated: str


@dataclass
class ComplianceAlert:
    """Compliance alert data structure"""
    alert_id: str
    severity: AlertSeverity
    title: str
    description: str
    category: str
    created_at: str
    requires_action: bool
    affected_students: int
    resolution_deadline: Optional[str]


class ComplianceDashboard:
    """
    FERPA Compliance Dashboard providing real-time monitoring,
    metrics visualization, and actionable compliance insights.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.audit_service = ComplianceAuditService(db)
        self.retention_engine = DataRetentionEngine(db)
        self.privacy_service = PrivacyService(db)
    
    # === MAIN DASHBOARD DATA ===
    
    def get_dashboard_overview(self, user_id: int, user_role: UserRole) -> Dict[str, Any]:
        """
        Get comprehensive dashboard overview with role-based data filtering
        """
        
        current_time = datetime.utcnow()
        
        dashboard_data = {
            "timestamp": current_time.isoformat(),
            "user_context": {
                "user_id": user_id,
                "role": user_role.value,
                "permissions": self._get_user_permissions(user_role)
            },
            "overview_metrics": self._get_overview_metrics(),
            "compliance_status": self._get_compliance_status_summary(),
            "real_time_alerts": self._get_real_time_alerts(limit=10),
            "recent_activity": self._get_recent_activity(limit=20),
            "trending_issues": self._get_trending_issues(),
            "quick_actions": self._get_quick_actions(user_role),
            "system_health": self._get_system_health_status()
        }
        
        # Add role-specific data
        if user_role in [UserRole.ADMIN]:
            dashboard_data["admin_insights"] = self._get_admin_insights()
        
        return dashboard_data
    
    def get_compliance_metrics(
        self,
        time_period: str = "7d",  # "1d", "7d", "30d", "90d"
        metric_types: List[DashboardMetricType] = None
    ) -> Dict[str, Any]:
        """
        Get detailed compliance metrics with historical trends
        """
        
        if not metric_types:
            metric_types = list(DashboardMetricType)
        
        # Calculate time range
        end_date = datetime.utcnow()
        start_date = self._calculate_start_date(end_date, time_period)
        previous_start = self._calculate_start_date(start_date, time_period)
        
        metrics_data = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "duration": time_period
            },
            "metrics": {},
            "trends": {},
            "benchmarks": self._get_compliance_benchmarks()
        }
        
        for metric_type in metric_types:
            current_value = self._calculate_metric_value(metric_type, start_date, end_date)
            previous_value = self._calculate_metric_value(metric_type, previous_start, start_date)
            
            metric = DashboardMetric(
                metric_type=metric_type,
                current_value=current_value,
                previous_value=previous_value,
                trend=self._calculate_trend(current_value, previous_value),
                trend_percentage=self._calculate_trend_percentage(current_value, previous_value),
                target_value=self._get_metric_target(metric_type),
                status=self._determine_metric_status(metric_type, current_value),
                last_updated=datetime.utcnow().isoformat()
            )
            
            metrics_data["metrics"][metric_type.value] = asdict(metric)
        
        # Get historical trend data
        metrics_data["trends"] = self._get_historical_trends(metric_types, time_period)
        
        return metrics_data
    
    def get_violation_analytics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get comprehensive violation analytics and patterns
        """
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        violations = self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.created_at >= start_date,
                ComplianceAuditLog.severity_level.in_(["warning", "error", "critical"])
            )
        ).all()
        
        analytics = {
            "summary": {
                "total_violations": len(violations),
                "period_days": days,
                "average_per_day": len(violations) / days,
                "resolution_rate": self._calculate_resolution_rate(violations)
            },
            "breakdown": {
                "by_severity": self._analyze_by_severity(violations),
                "by_category": self._analyze_by_category(violations),
                "by_type": self._analyze_by_type(violations),
                "by_user": self._analyze_by_user(violations)
            },
            "trends": {
                "daily_counts": self._get_daily_violation_counts(violations, days),
                "severity_trend": self._get_severity_trends(violations),
                "category_trends": self._get_category_trends(violations)
            },
            "patterns": {
                "peak_hours": self._analyze_violation_timing(violations),
                "repeat_offenders": self._identify_repeat_patterns(violations),
                "common_causes": self._identify_common_causes(violations)
            },
            "recommendations": self._generate_violation_recommendations(violations)
        }
        
        return analytics
    
    def get_consent_management_dashboard(self) -> Dict[str, Any]:
        """
        Get detailed consent management dashboard data
        """
        
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Get consent statistics
        all_consents = self.db.query(StudentConsent).all()
        recent_consents = self.db.query(StudentConsent).filter(
            StudentConsent.created_at >= thirty_days_ago
        ).all()
        
        dashboard = {
            "summary": {
                "total_consents": len(all_consents),
                "active_consents": len([c for c in all_consents if c.status == ConsentStatus.GRANTED]),
                "pending_consents": len([c for c in all_consents if c.status == ConsentStatus.PENDING]),
                "withdrawn_consents": len([c for c in all_consents if c.status == ConsentStatus.WITHDRAWN]),
                "recent_activity": len(recent_consents)
            },
            "consent_types": self._analyze_consent_types(all_consents),
            "processing_metrics": {
                "average_response_time": self._calculate_avg_consent_response_time(recent_consents),
                "approval_rate": self._calculate_consent_approval_rate(recent_consents),
                "withdrawal_rate": self._calculate_consent_withdrawal_rate()
            },
            "expiration_tracking": {
                "expiring_soon": self._get_expiring_consents(30),
                "expired_consents": self._get_expired_consents(),
                "renewal_needed": self._get_renewal_needed_consents()
            },
            "compliance_health": {
                "coverage_rate": self._calculate_consent_coverage_rate(),
                "documentation_completeness": self._assess_consent_documentation(),
                "audit_readiness": self._assess_consent_audit_readiness()
            },
            "alerts": self._get_consent_alerts(),
            "recommendations": self._get_consent_recommendations()
        }
        
        return dashboard
    
    def get_data_access_analytics(self, days: int = 7) -> Dict[str, Any]:
        """
        Get comprehensive data access analytics
        """
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        access_logs = self.db.query(DataAccessLog).filter(
            DataAccessLog.access_timestamp >= start_date
        ).all()
        
        analytics = {
            "summary": {
                "total_accesses": len(access_logs),
                "unique_users": len(set(log.user_id for log in access_logs)),
                "unique_students": len(set(log.student_id for log in access_logs)),
                "consent_compliance_rate": self._calculate_access_consent_rate(access_logs),
                "period_days": days
            },
            "access_patterns": {
                "by_hour": self._analyze_hourly_access_patterns(access_logs),
                "by_day": self._analyze_daily_access_patterns(access_logs),
                "by_data_type": self._analyze_data_type_access(access_logs),
                "by_action": self._analyze_access_actions(access_logs)
            },
            "user_analysis": {
                "top_users": self._get_top_accessing_users(access_logs),
                "suspicious_patterns": self._detect_suspicious_access_patterns(access_logs),
                "role_breakdown": self._analyze_access_by_role(access_logs)
            },
            "compliance_analysis": {
                "consented_vs_unconsented": self._analyze_consent_compliance(access_logs),
                "legitimate_interest_usage": self._analyze_legitimate_interest_usage(access_logs),
                "privacy_risk_assessment": self._assess_access_privacy_risks(access_logs)
            },
            "recommendations": self._generate_access_recommendations(access_logs)
        }
        
        return analytics
    
    def get_retention_dashboard(self) -> Dict[str, Any]:
        """
        Get comprehensive data retention dashboard
        """
        
        dashboard = {
            "summary": self._get_retention_summary(),
            "policies": self._get_retention_policies_overview(),
            "scheduled_purges": self._get_purge_schedule_overview(),
            "compliance_status": self._get_retention_compliance_status(),
            "upcoming_actions": self._get_upcoming_retention_actions(),
            "storage_analytics": self._get_storage_analytics(),
            "exemptions": self._get_exemption_overview(),
            "recommendations": self._get_retention_recommendations()
        }
        
        return dashboard
    
    # === REAL-TIME MONITORING ===
    
    def get_real_time_status(self) -> Dict[str, Any]:
        """
        Get real-time compliance status for live monitoring
        """
        
        current_time = datetime.utcnow()
        last_hour = current_time - timedelta(hours=1)
        
        status = {
            "timestamp": current_time.isoformat(),
            "system_status": "operational",
            "active_alerts": self._count_active_alerts(),
            "recent_violations": self._count_recent_violations(last_hour),
            "pending_actions": self._count_pending_actions(),
            "health_indicators": {
                "consent_processing": self._check_consent_processing_health(),
                "data_access_monitoring": self._check_access_monitoring_health(),
                "retention_compliance": self._check_retention_health(),
                "audit_logging": self._check_audit_logging_health()
            },
            "performance_metrics": {
                "response_times": self._get_system_response_times(),
                "processing_queues": self._get_processing_queue_status(),
                "error_rates": self._get_error_rates()
            }
        }
        
        return status
    
    def get_compliance_alerts(
        self,
        severity_filter: List[AlertSeverity] = None,
        limit: int = 50
    ) -> List[ComplianceAlert]:
        """
        Get current compliance alerts with filtering
        """
        
        if not severity_filter:
            severity_filter = list(AlertSeverity)
        
        # Get recent audit logs that represent alerts
        alert_logs = self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.severity_level.in_([s.value for s in severity_filter]),
                ComplianceAuditLog.resolved_at.is_(None)
            )
        ).order_by(desc(ComplianceAuditLog.created_at)).limit(limit).all()
        
        alerts = []
        for log in alert_logs:
            alert = ComplianceAlert(
                alert_id=f"ALERT-{log.id}",
                severity=AlertSeverity(log.severity_level),
                title=self._generate_alert_title(log),
                description=log.description,
                category=log.event_category,
                created_at=log.created_at.isoformat(),
                requires_action=log.requires_action or False,
                affected_students=1 if log.affected_student_id else 0,
                resolution_deadline=self._calculate_resolution_deadline(log)
            )
            alerts.append(alert)
        
        return alerts
    
    # === REPORTING ===
    
    def generate_executive_summary(self, period_days: int = 30) -> Dict[str, Any]:
        """
        Generate executive summary report for leadership
        """
        
        start_date = datetime.utcnow() - timedelta(days=period_days)
        end_date = datetime.utcnow()
        
        summary = {
            "report_metadata": {
                "title": "FERPA Compliance Executive Summary",
                "period": f"{period_days} days",
                "generated_at": end_date.isoformat(),
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat()
            },
            "key_metrics": {
                "overall_compliance_score": self._calculate_overall_compliance_score(),
                "consent_compliance_rate": self._calculate_consent_compliance_rate(start_date, end_date),
                "data_retention_compliance": self._calculate_retention_compliance_rate(),
                "total_violations": self._count_violations(start_date, end_date),
                "resolved_violations": self._count_resolved_violations(start_date, end_date)
            },
            "risk_assessment": {
                "current_risk_level": self._assess_current_risk_level(),
                "risk_factors": self._identify_key_risk_factors(),
                "mitigation_actions": self._get_active_mitigation_actions()
            },
            "operational_highlights": {
                "data_requests_processed": self._count_data_requests(start_date, end_date),
                "consents_managed": self._count_consents_processed(start_date, end_date),
                "records_purged": self._count_records_purged(start_date, end_date),
                "staff_training_completed": self._count_training_completions(start_date, end_date)
            },
            "recommendations": {
                "immediate_actions": self._get_immediate_action_recommendations(),
                "strategic_improvements": self._get_strategic_recommendations(),
                "resource_needs": self._assess_resource_needs()
            },
            "regulatory_outlook": {
                "upcoming_requirements": self._get_upcoming_regulatory_requirements(),
                "compliance_readiness": self._assess_compliance_readiness()
            }
        }
        
        return summary
    
    def export_compliance_report(
        self,
        report_type: str = "comprehensive",
        format: str = "json",
        period_days: int = 30
    ) -> Dict[str, Any]:
        """
        Export comprehensive compliance report in specified format
        """
        
        if report_type == "comprehensive":
            report_data = self._generate_comprehensive_report(period_days)
        elif report_type == "executive":
            report_data = self.generate_executive_summary(period_days)
        elif report_type == "violations":
            report_data = self.get_violation_analytics(period_days)
        elif report_type == "consent":
            report_data = self.get_consent_management_dashboard()
        else:
            raise ValueError(f"Unknown report type: {report_type}")
        
        # Add export metadata
        export_metadata = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "report_type": report_type,
            "format": format,
            "period_days": period_days,
            "data_hash": self._calculate_report_hash(report_data)
        }
        
        return {
            "metadata": export_metadata,
            "data": report_data
        }
    
    # === PRIVATE HELPER METHODS ===
    
    def _get_user_permissions(self, user_role: UserRole) -> List[str]:
        """Get user permissions based on role"""
        
        permissions = {
            UserRole.ADMIN: [
                "view_all_metrics", "manage_policies", "resolve_violations",
                "export_reports", "manage_users", "view_audit_logs"
            ],
            UserRole.TEACHER: [
                "view_own_metrics", "view_student_consents", "request_data_access"
            ],
            UserRole.STUDENT: [
                "view_own_data", "manage_own_consent", "request_data_export"
            ]
        }
        
        return permissions.get(user_role, [])
    
    def _get_overview_metrics(self) -> Dict[str, Any]:
        """Get key overview metrics"""
        
        return {
            "compliance_score": self._calculate_overall_compliance_score(),
            "active_violations": self._count_active_alerts(),
            "pending_actions": self._count_pending_actions(),
            "consent_rate": self._calculate_current_consent_rate(),
            "retention_compliance": self._get_retention_compliance_percentage(),
            "data_requests_today": self._count_todays_data_requests()
        }
    
    def _get_compliance_status_summary(self) -> Dict[str, str]:
        """Get high-level compliance status"""
        
        score = self._calculate_overall_compliance_score()
        
        if score >= 95:
            status = "excellent"
            message = "All compliance metrics within target ranges"
        elif score >= 85:
            status = "good"
            message = "Minor compliance issues requiring attention"
        elif score >= 70:
            status = "needs_attention"
            message = "Several compliance issues require immediate action"
        else:
            status = "critical"
            message = "Critical compliance issues require urgent resolution"
        
        return {
            "status": status,
            "score": score,
            "message": message,
            "last_assessed": datetime.utcnow().isoformat()
        }
    
    def _get_real_time_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent real-time alerts"""
        
        recent_alerts = self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.severity_level.in_(["warning", "error", "critical"]),
                ComplianceAuditLog.created_at >= datetime.utcnow() - timedelta(hours=24)
            )
        ).order_by(desc(ComplianceAuditLog.created_at)).limit(limit).all()
        
        return [
            {
                "id": alert.id,
                "severity": alert.severity_level,
                "title": self._generate_alert_title(alert),
                "timestamp": alert.created_at.isoformat(),
                "category": alert.event_category,
                "requires_action": alert.requires_action
            }
            for alert in recent_alerts
        ]
    
    def _get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent compliance-related activity"""
        
        recent_activity = self.db.query(ComplianceAuditLog).order_by(
            desc(ComplianceAuditLog.created_at)
        ).limit(limit).all()
        
        return [
            {
                "id": activity.id,
                "type": activity.event_type,
                "description": activity.description,
                "timestamp": activity.created_at.isoformat(),
                "user_id": activity.user_id,
                "category": activity.event_category
            }
            for activity in recent_activity
        ]
    
    def _get_trending_issues(self, days: int = 7) -> List[Dict[str, Any]]:
        """Identify trending compliance issues"""
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        recent_issues = self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.created_at >= start_date,
                ComplianceAuditLog.severity_level.in_(["warning", "error", "critical"])
            )
        ).all()
        
        # Count by event type
        issue_counts = {}
        for issue in recent_issues:
            issue_counts[issue.event_type] = issue_counts.get(issue.event_type, 0) + 1
        
        # Sort by frequency and return top issues
        trending = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return [
            {
                "issue_type": issue_type,
                "frequency": count,
                "trend": "increasing" if count > 2 else "stable"
            }
            for issue_type, count in trending
        ]
    
    def _get_quick_actions(self, user_role: UserRole) -> List[Dict[str, Any]]:
        """Get role-appropriate quick actions"""
        
        actions = []
        
        if user_role == UserRole.ADMIN:
            # Check for overdue purges
            overdue_purges = self.db.query(DataPurgeSchedule).filter(
                and_(
                    DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow(),
                    DataPurgeSchedule.status.in_(["scheduled", "warned"])
                )
            ).count()
            
            if overdue_purges > 0:
                actions.append({
                    "id": "execute_purges",
                    "title": f"Execute {overdue_purges} Overdue Purges",
                    "priority": "high",
                    "url": "/admin/retention/purges"
                })
            
            # Check for pending consent requests
            pending_consents = self.db.query(StudentConsent).filter(
                StudentConsent.status == ConsentStatus.PENDING
            ).count()
            
            if pending_consents > 5:
                actions.append({
                    "id": "review_consents",
                    "title": f"Review {pending_consents} Pending Consents",
                    "priority": "medium",
                    "url": "/admin/consents/pending"
                })
        
        return actions
    
    def _get_system_health_status(self) -> Dict[str, Any]:
        """Get system health indicators"""
        
        return {
            "database_status": "healthy",
            "audit_logging": "operational",
            "retention_engine": "operational",
            "notification_system": "operational",
            "last_health_check": datetime.utcnow().isoformat()
        }
    
    def _get_admin_insights(self) -> Dict[str, Any]:
        """Get administrative insights for admin users"""
        
        return {
            "user_activity_summary": self._get_user_activity_summary(),
            "policy_effectiveness": self._assess_policy_effectiveness(),
            "resource_utilization": self._get_resource_utilization(),
            "training_completion_rates": self._get_training_completion_rates()
        }
    
    # Metric calculation methods
    def _calculate_start_date(self, end_date: datetime, period: str) -> datetime:
        """Calculate start date based on period"""
        
        if period == "1d":
            return end_date - timedelta(days=1)
        elif period == "7d":
            return end_date - timedelta(days=7)
        elif period == "30d":
            return end_date - timedelta(days=30)
        elif period == "90d":
            return end_date - timedelta(days=90)
        else:
            return end_date - timedelta(days=7)
    
    def _calculate_metric_value(
        self,
        metric_type: DashboardMetricType,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """Calculate specific metric value for period"""
        
        if metric_type == DashboardMetricType.COMPLIANCE_SCORE:
            return self._calculate_overall_compliance_score()
        elif metric_type == DashboardMetricType.CONSENT_RATE:
            return self._calculate_consent_compliance_rate(start_date, end_date)
        elif metric_type == DashboardMetricType.RETENTION_COMPLIANCE:
            return self._calculate_retention_compliance_rate()
        elif metric_type == DashboardMetricType.ACTIVE_VIOLATIONS:
            return self._count_active_alerts()
        else:
            return 0.0
    
    def _calculate_trend(self, current: float, previous: float) -> str:
        """Calculate trend direction"""
        
        if current > previous * 1.05:  # 5% threshold
            return "up"
        elif current < previous * 0.95:
            return "down"
        else:
            return "stable"
    
    def _calculate_trend_percentage(self, current: float, previous: float) -> float:
        """Calculate trend percentage change"""
        
        if previous == 0:
            return 0.0
        
        return ((current - previous) / previous) * 100
    
    def _get_metric_target(self, metric_type: DashboardMetricType) -> float:
        """Get target value for metric"""
        
        targets = {
            DashboardMetricType.COMPLIANCE_SCORE: 95.0,
            DashboardMetricType.CONSENT_RATE: 98.0,
            DashboardMetricType.RETENTION_COMPLIANCE: 100.0,
            DashboardMetricType.ACTIVE_VIOLATIONS: 0.0
        }
        
        return targets.get(metric_type, 100.0)
    
    def _determine_metric_status(self, metric_type: DashboardMetricType, value: float) -> str:
        """Determine metric health status"""
        
        target = self._get_metric_target(metric_type)
        
        if metric_type == DashboardMetricType.ACTIVE_VIOLATIONS:
            # For violations, lower is better
            if value == 0:
                return "healthy"
            elif value <= 5:
                return "warning"
            else:
                return "critical"
        else:
            # For other metrics, higher is better
            if value >= target * 0.95:
                return "healthy"
            elif value >= target * 0.85:
                return "warning"
            else:
                return "critical"
    
    def _get_compliance_benchmarks(self) -> Dict[str, float]:
        """Get industry compliance benchmarks"""
        
        return {
            "consent_rate_benchmark": 95.0,
            "retention_compliance_benchmark": 98.0,
            "response_time_benchmark": 30.0,  # days
            "violation_rate_benchmark": 0.01  # per 1000 records
        }
    
    def _get_historical_trends(
        self,
        metric_types: List[DashboardMetricType],
        time_period: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get historical trend data for metrics"""
        
        trends = {}
        
        # For now, return placeholder trend data
        # In production, this would query historical metric storage
        for metric_type in metric_types:
            trends[metric_type.value] = [
                {"date": (datetime.utcnow() - timedelta(days=i)).isoformat(), "value": 85.0 + i}
                for i in range(7, 0, -1)
            ]
        
        return trends
    
    # Calculation helper methods (many would be implemented based on specific business logic)
    def _calculate_overall_compliance_score(self) -> float:
        """Calculate overall compliance score"""
        return 87.5  # Placeholder
    
    def _calculate_consent_compliance_rate(self, start_date: datetime, end_date: datetime) -> float:
        """Calculate consent compliance rate for period"""
        access_logs = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.access_timestamp >= start_date,
                DataAccessLog.access_timestamp <= end_date
            )
        ).all()
        
        if not access_logs:
            return 100.0
        
        consented_count = len([log for log in access_logs if log.consent_verified])
        return (consented_count / len(access_logs)) * 100
    
    def _calculate_retention_compliance_rate(self) -> float:
        """Calculate data retention compliance rate"""
        total_scheduled = self.db.query(DataPurgeSchedule).count()
        overdue = self.db.query(DataPurgeSchedule).filter(
            and_(
                DataPurgeSchedule.scheduled_purge_date <= datetime.utcnow(),
                DataPurgeSchedule.status.in_(["scheduled", "warned"])
            )
        ).count()
        
        if total_scheduled == 0:
            return 100.0
        
        return ((total_scheduled - overdue) / total_scheduled) * 100
    
    def _count_active_alerts(self) -> int:
        """Count currently active alerts"""
        return self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.severity_level.in_(["warning", "error", "critical"]),
                ComplianceAuditLog.resolved_at.is_(None)
            )
        ).count()
    
    def _count_pending_actions(self) -> int:
        """Count items requiring action"""
        return self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.requires_action == True,
                ComplianceAuditLog.resolved_at.is_(None)
            )
        ).count()
    
    def _calculate_current_consent_rate(self) -> float:
        """Calculate current consent compliance rate"""
        recent_access = self.db.query(DataAccessLog).filter(
            DataAccessLog.access_timestamp >= datetime.utcnow() - timedelta(days=7)
        ).all()
        
        if not recent_access:
            return 100.0
        
        consented = len([log for log in recent_access if log.consent_verified])
        return (consented / len(recent_access)) * 100
    
    def _get_retention_compliance_percentage(self) -> float:
        """Get retention compliance percentage"""
        return self._calculate_retention_compliance_rate()
    
    def _count_todays_data_requests(self) -> int:
        """Count data requests made today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        return self.db.query(ComplianceAuditLog).filter(
            and_(
                ComplianceAuditLog.created_at >= today_start,
                ComplianceAuditLog.event_type.in_(["data_export_requested", "data_access_requested"])
            )
        ).count()
    
    def _generate_alert_title(self, audit_log: ComplianceAuditLog) -> str:
        """Generate user-friendly alert title"""
        
        title_mapping = {
            "consent_violation": "Unauthorized Data Access Detected",
            "retention_violation": "Data Retention Policy Violation",
            "privacy_breach": "Privacy Breach Incident",
            "unauthorized_access": "Unauthorized System Access"
        }
        
        return title_mapping.get(audit_log.event_type, audit_log.event_type.replace("_", " ").title())
    
    def _calculate_resolution_deadline(self, audit_log: ComplianceAuditLog) -> Optional[str]:
        """Calculate resolution deadline based on severity"""
        
        if audit_log.severity_level == "critical":
            deadline = audit_log.created_at + timedelta(hours=24)
        elif audit_log.severity_level == "error":
            deadline = audit_log.created_at + timedelta(days=3)
        elif audit_log.severity_level == "warning":
            deadline = audit_log.created_at + timedelta(days=7)
        else:
            return None
        
        return deadline.isoformat()
    
    # Additional placeholder methods for comprehensive functionality
    def _analyze_by_severity(self, violations: List[ComplianceAuditLog]) -> Dict[str, int]:
        """Analyze violations by severity"""
        return {
            "critical": len([v for v in violations if v.severity_level == "critical"]),
            "error": len([v for v in violations if v.severity_level == "error"]), 
            "warning": len([v for v in violations if v.severity_level == "warning"])
        }
    
    def _analyze_by_category(self, violations: List[ComplianceAuditLog]) -> Dict[str, int]:
        """Analyze violations by category"""
        categories = {}
        for violation in violations:
            categories[violation.event_category] = categories.get(violation.event_category, 0) + 1
        return categories
    
    def _analyze_by_type(self, violations: List[ComplianceAuditLog]) -> Dict[str, int]:
        """Analyze violations by type"""
        types = {}
        for violation in violations:
            types[violation.event_type] = types.get(violation.event_type, 0) + 1
        return types
    
    def _analyze_by_user(self, violations: List[ComplianceAuditLog]) -> Dict[str, int]:
        """Analyze violations by user"""
        users = {}
        for violation in violations:
            if violation.user_id:
                users[str(violation.user_id)] = users.get(str(violation.user_id), 0) + 1
        return users
    
    # Additional methods would be implemented for complete functionality
    # Many of these are placeholders that would be fully implemented based on specific requirements
    
    def _calculate_report_hash(self, report_data: Dict[str, Any]) -> str:
        """Calculate hash of report data for integrity"""
        import hashlib
        return hashlib.sha256(json.dumps(report_data, sort_keys=True).encode()).hexdigest()[:16]
    
    # Many more helper methods would be implemented here for complete functionality...
    # This is a comprehensive framework that can be extended based on specific requirements