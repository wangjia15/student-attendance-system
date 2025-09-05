"""
Access Logger

Comprehensive logging system for all student data access in compliance
with FERPA requirements for maintaining educational record access logs.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func, text
import json
import logging
from contextlib import contextmanager
import hashlib
import secrets

from app.models.ferpa import DataAccessLog, DataAccessReason
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


class AccessLogger:
    """
    FERPA-compliant access logging system for tracking all interactions
    with student educational records.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    # === ACCESS LOGGING ===
    
    def log_access(
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
        request_headers: Dict[str, str] = None,
        response_status: int = None,
        data_anonymized: bool = False,
        consent_verified: bool = False,
        legitimate_interest_basis: str = None,
        additional_metadata: Dict[str, Any] = None
    ) -> DataAccessLog:
        """
        Log comprehensive access to student educational records
        """
        
        # Create access log entry
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
            consent_verified=consent_verified,
            legitimate_interest_basis=legitimate_interest_basis
        )
        
        self.db.add(access_log)
        self.db.commit()
        self.db.refresh(access_log)
        
        # Store additional metadata if provided
        if additional_metadata or request_headers or response_status:
            self._store_access_metadata(
                access_log.id,
                request_headers,
                response_status,
                additional_metadata
            )
        
        # Check for suspicious access patterns
        self._check_access_patterns(access_log)
        
        return access_log
    
    def bulk_log_access(self, access_records: List[Dict[str, Any]]) -> List[DataAccessLog]:
        """
        Efficiently log multiple access records in batch
        """
        
        logged_records = []
        
        try:
            for record_data in access_records:
                access_log = DataAccessLog(**record_data)
                self.db.add(access_log)
                logged_records.append(access_log)
            
            self.db.commit()
            
            # Refresh all records to get IDs
            for record in logged_records:
                self.db.refresh(record)
            
            return logged_records
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to bulk log access records: {str(e)}")
            raise
    
    @contextmanager
    def log_session_access(
        self,
        user_id: int,
        session_id: str,
        ip_address: str,
        user_agent: str
    ):
        """
        Context manager for logging all access within a session
        """
        
        session_start = datetime.utcnow()
        session_accesses = []
        
        # Store session context
        original_log_access = self.log_access
        
        def session_aware_log_access(*args, **kwargs):
            kwargs['session_id'] = session_id
            kwargs['ip_address'] = kwargs.get('ip_address', ip_address)
            kwargs['user_agent'] = kwargs.get('user_agent', user_agent)
            
            access_log = original_log_access(*args, **kwargs)
            session_accesses.append(access_log)
            return access_log
        
        self.log_access = session_aware_log_access
        
        try:
            yield self
        finally:
            # Restore original method
            self.log_access = original_log_access
            
            # Log session summary
            session_end = datetime.utcnow()
            session_duration = (session_end - session_start).total_seconds()
            
            self._log_session_summary(
                user_id=user_id,
                session_id=session_id,
                session_start=session_start,
                session_end=session_end,
                duration_seconds=session_duration,
                total_accesses=len(session_accesses),
                unique_students=len(set(log.student_id for log in session_accesses))
            )
    
    # === ACCESS PATTERN ANALYSIS ===
    
    def detect_suspicious_access(
        self,
        user_id: int = None,
        student_id: int = None,
        time_window_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Detect suspicious access patterns that may indicate privacy violations
        """
        
        suspicious_patterns = []
        cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        # Base query
        query = self.db.query(DataAccessLog).filter(
            DataAccessLog.access_timestamp >= cutoff_time
        )
        
        if user_id:
            query = query.filter(DataAccessLog.user_id == user_id)
        
        if student_id:
            query = query.filter(DataAccessLog.student_id == student_id)
        
        access_logs = query.all()
        
        # Pattern 1: Unusual volume of access
        suspicious_patterns.extend(self._detect_volume_anomalies(access_logs))
        
        # Pattern 2: Access outside normal hours
        suspicious_patterns.extend(self._detect_time_anomalies(access_logs))
        
        # Pattern 3: Access without proper consent
        suspicious_patterns.extend(self._detect_consent_violations(access_logs))
        
        # Pattern 4: Unusual data type access patterns
        suspicious_patterns.extend(self._detect_data_type_anomalies(access_logs))
        
        # Pattern 5: Geographic anomalies
        suspicious_patterns.extend(self._detect_geographic_anomalies(access_logs))
        
        return suspicious_patterns
    
    def get_access_statistics(
        self,
        start_date: datetime,
        end_date: datetime,
        breakdown_by: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive access statistics for reporting
        """
        
        if not breakdown_by:
            breakdown_by = ["user", "data_type", "action", "access_reason"]
        
        access_logs = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.access_timestamp >= start_date,
                DataAccessLog.access_timestamp <= end_date
            )
        ).all()
        
        stats = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "total_accesses": len(access_logs)
            },
            "breakdown": {},
            "compliance_metrics": self._calculate_compliance_metrics(access_logs),
            "risk_indicators": self._calculate_risk_indicators(access_logs)
        }
        
        # Generate requested breakdowns
        for breakdown_type in breakdown_by:
            stats["breakdown"][breakdown_type] = self._generate_breakdown(
                access_logs, breakdown_type
            )
        
        return stats
    
    # === ACCESS HISTORY QUERIES ===
    
    def get_student_access_history(
        self,
        student_id: int,
        limit: int = 100,
        offset: int = 0,
        start_date: datetime = None,
        end_date: datetime = None,
        data_type: str = None,
        user_id: int = None,
        include_metadata: bool = False
    ) -> Dict[str, Any]:
        """
        Get comprehensive access history for a specific student
        """
        
        query = self.db.query(DataAccessLog).filter(DataAccessLog.student_id == student_id)
        
        # Apply filters
        if start_date:
            query = query.filter(DataAccessLog.access_timestamp >= start_date)
        if end_date:
            query = query.filter(DataAccessLog.access_timestamp <= end_date)
        if data_type:
            query = query.filter(DataAccessLog.data_type == data_type)
        if user_id:
            query = query.filter(DataAccessLog.user_id == user_id)
        
        # Get total count
        total_count = query.count()
        
        # Get paginated results
        access_logs = query.order_by(
            desc(DataAccessLog.access_timestamp)
        ).offset(offset).limit(limit).all()
        
        # Format results
        formatted_logs = []
        for log in access_logs:
            formatted_log = {
                "id": log.id,
                "user_id": log.user_id,
                "data_type": log.data_type,
                "action": log.action,
                "access_reason": log.access_reason.value,
                "purpose_description": log.purpose_description,
                "access_timestamp": log.access_timestamp.isoformat(),
                "consent_verified": log.consent_verified,
                "data_anonymized": log.data_anonymized,
                "ip_address": log.ip_address,
                "endpoint": log.endpoint
            }
            
            if include_metadata:
                # Add additional metadata if requested
                formatted_log["metadata"] = self._get_access_metadata(log.id)
            
            formatted_logs.append(formatted_log)
        
        return {
            "student_id": student_id,
            "total_count": total_count,
            "returned_count": len(formatted_logs),
            "offset": offset,
            "limit": limit,
            "access_logs": formatted_logs,
            "summary": {
                "unique_users": len(set(log.user_id for log in access_logs)),
                "data_types_accessed": list(set(log.data_type for log in access_logs)),
                "most_recent_access": access_logs[0].access_timestamp.isoformat() if access_logs else None,
                "consent_compliance_rate": self._calculate_consent_compliance_rate(access_logs)
            }
        }
    
    def get_user_access_history(
        self,
        user_id: int,
        limit: int = 100,
        include_student_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Get access history for a specific user (what they've accessed)
        """
        
        access_logs = self.db.query(DataAccessLog).filter(
            DataAccessLog.user_id == user_id
        ).order_by(desc(DataAccessLog.access_timestamp)).limit(limit).all()
        
        result = {
            "user_id": user_id,
            "total_accesses": len(access_logs),
            "access_logs": [
                {
                    "id": log.id,
                    "student_id": log.student_id,
                    "data_type": log.data_type,
                    "action": log.action,
                    "access_reason": log.access_reason.value,
                    "access_timestamp": log.access_timestamp.isoformat(),
                    "consent_verified": log.consent_verified
                }
                for log in access_logs
            ]
        }
        
        if include_student_summary:
            # Group by student
            students_accessed = {}
            for log in access_logs:
                if log.student_id not in students_accessed:
                    students_accessed[log.student_id] = {
                        "student_id": log.student_id,
                        "access_count": 0,
                        "first_access": log.access_timestamp,
                        "last_access": log.access_timestamp,
                        "data_types": set()
                    }
                
                student_summary = students_accessed[log.student_id]
                student_summary["access_count"] += 1
                student_summary["data_types"].add(log.data_type)
                
                if log.access_timestamp < student_summary["first_access"]:
                    student_summary["first_access"] = log.access_timestamp
                if log.access_timestamp > student_summary["last_access"]:
                    student_summary["last_access"] = log.access_timestamp
            
            # Convert to list and format
            result["students_accessed"] = [
                {
                    "student_id": summary["student_id"],
                    "access_count": summary["access_count"],
                    "first_access": summary["first_access"].isoformat(),
                    "last_access": summary["last_access"].isoformat(),
                    "data_types": list(summary["data_types"])
                }
                for summary in students_accessed.values()
            ]
        
        return result
    
    # === AUDIT AND COMPLIANCE ===
    
    def generate_audit_report(
        self,
        start_date: datetime,
        end_date: datetime,
        report_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Generate comprehensive audit report for FERPA compliance
        """
        
        access_logs = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.access_timestamp >= start_date,
                DataAccessLog.access_timestamp <= end_date
            )
        ).all()
        
        report = {
            "report_metadata": {
                "type": report_type,
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "generated_at": datetime.utcnow().isoformat(),
                "total_access_events": len(access_logs)
            },
            "compliance_summary": {
                "consent_compliance_rate": self._calculate_consent_compliance_rate(access_logs),
                "legitimate_interest_basis_documented": self._count_documented_basis(access_logs),
                "privacy_violations_detected": len(self.detect_suspicious_access()),
                "data_anonymization_rate": self._calculate_anonymization_rate(access_logs)
            },
            "access_patterns": {
                "by_hour": self._analyze_hourly_patterns(access_logs),
                "by_day_of_week": self._analyze_daily_patterns(access_logs),
                "by_user_role": self._analyze_role_patterns(access_logs)
            },
            "risk_assessment": {
                "high_risk_accesses": self._identify_high_risk_accesses(access_logs),
                "unusual_patterns": self.detect_suspicious_access(),
                "recommendations": self._generate_compliance_recommendations(access_logs)
            }
        }
        
        return report
    
    # === PRIVATE HELPER METHODS ===
    
    def _store_access_metadata(
        self,
        access_log_id: int,
        request_headers: Dict[str, str] = None,
        response_status: int = None,
        additional_metadata: Dict[str, Any] = None
    ):
        """Store additional metadata for access log"""
        
        metadata = {}
        
        if request_headers:
            # Store relevant headers (excluding sensitive ones)
            safe_headers = {
                k: v for k, v in request_headers.items()
                if k.lower() not in ['authorization', 'cookie', 'x-api-key']
            }
            metadata["request_headers"] = safe_headers
        
        if response_status:
            metadata["response_status"] = response_status
        
        if additional_metadata:
            metadata.update(additional_metadata)
        
        if metadata:
            # Store as JSON in database or separate metadata table
            # For now, we'll assume there's a way to store this
            logger.debug(f"Storing metadata for access log {access_log_id}: {metadata}")
    
    def _check_access_patterns(self, access_log: DataAccessLog):
        """Check for suspicious access patterns in real-time"""
        
        # Check for rapid-fire access (potential bulk download)
        recent_access = self.db.query(DataAccessLog).filter(
            and_(
                DataAccessLog.user_id == access_log.user_id,
                DataAccessLog.access_timestamp >= datetime.utcnow() - timedelta(minutes=5)
            )
        ).count()
        
        if recent_access > 50:  # More than 50 accesses in 5 minutes
            logger.warning(f"Rapid access pattern detected for user {access_log.user_id}")
    
    def _detect_volume_anomalies(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Detect unusual volume of access"""
        
        anomalies = []
        
        # Group by user
        user_access_counts = {}
        for log in access_logs:
            user_access_counts[log.user_id] = user_access_counts.get(log.user_id, 0) + 1
        
        # Flag users with unusually high access
        for user_id, count in user_access_counts.items():
            if count > 100:  # Threshold for unusual volume
                anomalies.append({
                    "type": "high_volume_access",
                    "user_id": user_id,
                    "access_count": count,
                    "severity": "medium",
                    "description": f"User {user_id} accessed data {count} times"
                })
        
        return anomalies
    
    def _detect_time_anomalies(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Detect access outside normal business hours"""
        
        anomalies = []
        
        after_hours_access = [
            log for log in access_logs
            if log.access_timestamp.hour < 7 or log.access_timestamp.hour > 19
        ]
        
        if len(after_hours_access) > 10:  # Threshold for concern
            anomalies.append({
                "type": "after_hours_access",
                "access_count": len(after_hours_access),
                "severity": "low",
                "description": f"{len(after_hours_access)} accesses outside business hours"
            })
        
        return anomalies
    
    def _detect_consent_violations(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Detect access without proper consent"""
        
        violations = []
        
        non_consented_access = [
            log for log in access_logs
            if not log.consent_verified and log.access_reason not in [
                DataAccessReason.SAFETY_EMERGENCY,
                DataAccessReason.COURT_ORDER
            ]
        ]
        
        if non_consented_access:
            violations.append({
                "type": "consent_violation",
                "access_count": len(non_consented_access),
                "severity": "high",
                "description": f"{len(non_consented_access)} accesses without proper consent"
            })
        
        return violations
    
    def _detect_data_type_anomalies(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Detect unusual data type access patterns"""
        
        anomalies = []
        
        # Check for access to sensitive data types
        sensitive_types = ["health_records", "disciplinary_records", "financial_records"]
        sensitive_access = [
            log for log in access_logs
            if log.data_type in sensitive_types
        ]
        
        if sensitive_access:
            anomalies.append({
                "type": "sensitive_data_access",
                "access_count": len(sensitive_access),
                "severity": "medium",
                "description": f"{len(sensitive_access)} accesses to sensitive data types"
            })
        
        return anomalies
    
    def _detect_geographic_anomalies(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Detect unusual geographic access patterns"""
        
        # This would analyze IP addresses for geographic anomalies
        # For now, return empty list
        return []
    
    def _calculate_consent_compliance_rate(self, access_logs: List[DataAccessLog]) -> float:
        """Calculate percentage of accesses with proper consent"""
        
        if not access_logs:
            return 100.0
        
        consented_access = len([log for log in access_logs if log.consent_verified])
        return (consented_access / len(access_logs)) * 100
    
    def _calculate_compliance_metrics(self, access_logs: List[DataAccessLog]) -> Dict[str, Any]:
        """Calculate various compliance metrics"""
        
        return {
            "consent_compliance_rate": self._calculate_consent_compliance_rate(access_logs),
            "anonymization_rate": self._calculate_anonymization_rate(access_logs),
            "documented_purpose_rate": self._calculate_documented_purpose_rate(access_logs)
        }
    
    def _calculate_risk_indicators(self, access_logs: List[DataAccessLog]) -> Dict[str, Any]:
        """Calculate risk indicators from access patterns"""
        
        return {
            "high_risk_access_count": len([log for log in access_logs if self._is_high_risk_access(log)]),
            "after_hours_access_rate": self._calculate_after_hours_rate(access_logs),
            "bulk_access_indicators": self._count_bulk_access_patterns(access_logs)
        }
    
    def _is_high_risk_access(self, access_log: DataAccessLog) -> bool:
        """Determine if access is high risk"""
        
        return (
            not access_log.consent_verified or
            access_log.data_type in ["health_records", "disciplinary_records"] or
            access_log.action == "export"
        )
    
    def _calculate_anonymization_rate(self, access_logs: List[DataAccessLog]) -> float:
        """Calculate rate of data anonymization"""
        
        if not access_logs:
            return 100.0
        
        anonymized_count = len([log for log in access_logs if log.data_anonymized])
        return (anonymized_count / len(access_logs)) * 100
    
    def _calculate_documented_purpose_rate(self, access_logs: List[DataAccessLog]) -> float:
        """Calculate rate of documented access purpose"""
        
        if not access_logs:
            return 100.0
        
        documented_count = len([
            log for log in access_logs 
            if log.purpose_description and len(log.purpose_description.strip()) > 0
        ])
        return (documented_count / len(access_logs)) * 100
    
    def _calculate_after_hours_rate(self, access_logs: List[DataAccessLog]) -> float:
        """Calculate percentage of after-hours access"""
        
        if not access_logs:
            return 0.0
        
        after_hours_count = len([
            log for log in access_logs
            if log.access_timestamp.hour < 7 or log.access_timestamp.hour > 19
        ])
        return (after_hours_count / len(access_logs)) * 100
    
    def _count_bulk_access_patterns(self, access_logs: List[DataAccessLog]) -> int:
        """Count potential bulk access patterns"""
        
        # Group by user and 5-minute time windows
        time_windows = {}
        
        for log in access_logs:
            window_key = (
                log.user_id,
                log.access_timestamp.replace(minute=(log.access_timestamp.minute // 5) * 5, second=0, microsecond=0)
            )
            
            if window_key not in time_windows:
                time_windows[window_key] = 0
            time_windows[window_key] += 1
        
        # Count windows with high activity
        return len([count for count in time_windows.values() if count > 20])
    
    def _generate_breakdown(self, access_logs: List[DataAccessLog], breakdown_type: str) -> Dict[str, int]:
        """Generate breakdown statistics by specified type"""
        
        breakdown = {}
        
        for log in access_logs:
            if breakdown_type == "user":
                key = str(log.user_id)
            elif breakdown_type == "data_type":
                key = log.data_type
            elif breakdown_type == "action":
                key = log.action
            elif breakdown_type == "access_reason":
                key = log.access_reason.value
            else:
                continue
            
            breakdown[key] = breakdown.get(key, 0) + 1
        
        return breakdown
    
    def _get_access_metadata(self, access_log_id: int) -> Dict[str, Any]:
        """Get additional metadata for access log"""
        # This would retrieve stored metadata
        return {}
    
    def _log_session_summary(
        self,
        user_id: int,
        session_id: str,
        session_start: datetime,
        session_end: datetime,
        duration_seconds: float,
        total_accesses: int,
        unique_students: int
    ):
        """Log session summary for audit purposes"""
        
        logger.info(
            f"Session summary - User: {user_id}, Session: {session_id}, "
            f"Duration: {duration_seconds:.1f}s, Accesses: {total_accesses}, "
            f"Students: {unique_students}"
        )
    
    def _analyze_hourly_patterns(self, access_logs: List[DataAccessLog]) -> Dict[str, int]:
        """Analyze access patterns by hour of day"""
        
        hourly_counts = {}
        for hour in range(24):
            hourly_counts[str(hour)] = 0
        
        for log in access_logs:
            hour_key = str(log.access_timestamp.hour)
            hourly_counts[hour_key] += 1
        
        return hourly_counts
    
    def _analyze_daily_patterns(self, access_logs: List[DataAccessLog]) -> Dict[str, int]:
        """Analyze access patterns by day of week"""
        
        daily_counts = {}
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        for day in days:
            daily_counts[day] = 0
        
        for log in access_logs:
            day_name = days[log.access_timestamp.weekday()]
            daily_counts[day_name] += 1
        
        return daily_counts
    
    def _analyze_role_patterns(self, access_logs: List[DataAccessLog]) -> Dict[str, int]:
        """Analyze access patterns by user role"""
        
        role_counts = {}
        
        # Get user roles for all accessing users
        user_ids = list(set(log.user_id for log in access_logs))
        users = self.db.query(User).filter(User.id.in_(user_ids)).all()
        user_roles = {user.id: user.role.value for user in users}
        
        for log in access_logs:
            role = user_roles.get(log.user_id, "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
        
        return role_counts
    
    def _count_documented_basis(self, access_logs: List[DataAccessLog]) -> int:
        """Count accesses with documented legitimate interest basis"""
        
        return len([
            log for log in access_logs
            if log.legitimate_interest_basis and len(log.legitimate_interest_basis.strip()) > 0
        ])
    
    def _identify_high_risk_accesses(self, access_logs: List[DataAccessLog]) -> List[Dict[str, Any]]:
        """Identify high-risk access events"""
        
        high_risk_accesses = []
        
        for log in access_logs:
            if self._is_high_risk_access(log):
                high_risk_accesses.append({
                    "id": log.id,
                    "user_id": log.user_id,
                    "student_id": log.student_id,
                    "data_type": log.data_type,
                    "action": log.action,
                    "timestamp": log.access_timestamp.isoformat(),
                    "risk_factors": self._get_risk_factors(log)
                })
        
        return high_risk_accesses
    
    def _get_risk_factors(self, access_log: DataAccessLog) -> List[str]:
        """Get risk factors for an access event"""
        
        risk_factors = []
        
        if not access_log.consent_verified:
            risk_factors.append("no_consent_verification")
        
        if access_log.data_type in ["health_records", "disciplinary_records"]:
            risk_factors.append("sensitive_data_type")
        
        if access_log.action == "export":
            risk_factors.append("data_export")
        
        if access_log.access_timestamp.hour < 7 or access_log.access_timestamp.hour > 19:
            risk_factors.append("after_hours_access")
        
        return risk_factors
    
    def _generate_compliance_recommendations(self, access_logs: List[DataAccessLog]) -> List[str]:
        """Generate compliance recommendations based on access patterns"""
        
        recommendations = []
        
        consent_rate = self._calculate_consent_compliance_rate(access_logs)
        if consent_rate < 95:
            recommendations.append("Improve consent verification processes")
        
        after_hours_rate = self._calculate_after_hours_rate(access_logs)
        if after_hours_rate > 10:
            recommendations.append("Review after-hours access policies")
        
        anonymization_rate = self._calculate_anonymization_rate(access_logs)
        if anonymization_rate < 80:
            recommendations.append("Increase data anonymization for reporting")
        
        if self._count_bulk_access_patterns(access_logs) > 5:
            recommendations.append("Review bulk data access procedures")
        
        return recommendations