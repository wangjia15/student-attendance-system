"""
Attendance engine service for managing core business logic.
This service handles attendance state management, pattern detection,
and automated business rule enforcement.
"""
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_
from sqlalchemy.orm import joinedload

from app.models.attendance import AttendanceRecord, AttendanceStatus, AttendanceAuditLog
from app.models.class_session import ClassSession
from app.models.user import User, UserRole
from app.models.attendance_pattern import (
    AttendancePatternAnalysis, AttendanceAlert as AlertModel, 
    AttendanceInsight, PatternType, AlertSeverity, RiskLevel
)
from app.schemas.attendance import (
    StudentAttendancePattern, AttendanceAlert, AttendanceStats,
    BulkAttendanceOperation, AttendanceStatusUpdate
)


class AttendanceEngine:
    """Core attendance management engine."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.default_grace_period_minutes = 5
        self.default_late_threshold_minutes = 15
        self.at_risk_consecutive_absence_threshold = 3
        self.at_risk_attendance_rate_threshold = 0.75
    
    async def calculate_late_status(
        self,
        class_session: ClassSession,
        check_in_time: datetime,
        grace_period_minutes: Optional[int] = None
    ) -> Tuple[bool, int, bool]:
        """
        Calculate if student is late and by how many minutes.
        
        Returns:
            (is_late, late_minutes, grace_period_used)
        """
        if grace_period_minutes is None:
            grace_period_minutes = self.default_grace_period_minutes
        
        # Calculate time difference from class start
        time_diff = check_in_time - class_session.start_time
        late_minutes = int(time_diff.total_seconds() / 60)
        
        if late_minutes <= grace_period_minutes:
            return False, 0, late_minutes > 0
        
        return True, late_minutes, False
    
    async def determine_attendance_status(
        self,
        class_session: ClassSession,
        check_in_time: Optional[datetime] = None
    ) -> AttendanceStatus:
        """
        Determine appropriate attendance status based on timing.
        """
        if check_in_time is None:
            return AttendanceStatus.ABSENT
        
        is_late, late_minutes, _ = await self.calculate_late_status(
            class_session, check_in_time
        )
        
        if is_late and late_minutes > self.default_late_threshold_minutes:
            return AttendanceStatus.LATE
        
        return AttendanceStatus.PRESENT
    
    async def create_attendance_record(
        self,
        student_id: int,
        class_session_id: int,
        status: AttendanceStatus,
        verification_method: str,
        user_id: int,  # Who is creating the record
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        notes: Optional[str] = None,
        check_in_time: Optional[datetime] = None,
        override_reason: Optional[str] = None
    ) -> AttendanceRecord:
        """
        Create a new attendance record with proper audit logging.
        """
        # Get class session for late detection
        result = await self.db.execute(
            select(ClassSession).where(ClassSession.id == class_session_id)
        )
        class_session = result.scalar_one()
        
        # Set default check-in time if not provided and status is not ABSENT
        if check_in_time is None and status != AttendanceStatus.ABSENT:
            check_in_time = datetime.utcnow()
        
        # Calculate late status if check-in time is provided
        is_late, late_minutes, grace_period_used = False, 0, False
        if check_in_time:
            is_late, late_minutes, grace_period_used = await self.calculate_late_status(
                class_session, check_in_time
            )
        
        # Create attendance record
        attendance_record = AttendanceRecord(
            student_id=student_id,
            class_session_id=class_session_id,
            status=status,
            check_in_time=check_in_time,
            verification_method=verification_method,
            ip_address=ip_address,
            user_agent=user_agent,
            notes=notes,
            is_late=is_late,
            late_minutes=late_minutes,
            grace_period_used=grace_period_used,
            is_manual_override=verification_method == "teacher_override",
            override_reason=override_reason,
            override_by_teacher_id=user_id if verification_method == "teacher_override" else None
        )
        
        self.db.add(attendance_record)
        await self.db.flush()
        
        # Create audit log
        await self._create_audit_log(
            attendance_record.id,
            user_id,
            "create",
            None,
            status,
            override_reason or "Initial attendance record",
            ip_address,
            user_agent
        )
        
        return attendance_record
    
    async def update_attendance_status(
        self,
        attendance_record: AttendanceRecord,
        new_status: AttendanceStatus,
        user_id: int,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        notes: Optional[str] = None
    ) -> AttendanceRecord:
        """
        Update attendance status with audit logging.
        """
        old_status = attendance_record.status
        
        # Update record
        attendance_record.status = new_status
        attendance_record.updated_at = datetime.utcnow()
        
        if notes:
            attendance_record.notes = notes
        
        # Mark as manual override if changed by teacher
        if user_id != attendance_record.student_id:
            attendance_record.is_manual_override = True
            attendance_record.override_by_teacher_id = user_id
            attendance_record.override_reason = reason
            attendance_record.verification_method = "teacher_override"
        
        # Create audit log
        await self._create_audit_log(
            attendance_record.id,
            user_id,
            "update_status",
            old_status,
            new_status,
            reason,
            ip_address,
            user_agent
        )
        
        return attendance_record
    
    async def bulk_update_attendance(
        self,
        class_session_id: int,
        operation: BulkAttendanceOperation,
        student_ids: Optional[List[int]],
        teacher_id: int,
        reason: str,
        notes: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Perform bulk attendance operations.
        """
        # Map operations to status
        operation_to_status = {
            BulkAttendanceOperation.MARK_PRESENT: AttendanceStatus.PRESENT,
            BulkAttendanceOperation.MARK_ABSENT: AttendanceStatus.ABSENT,
            BulkAttendanceOperation.MARK_LATE: AttendanceStatus.LATE,
            BulkAttendanceOperation.MARK_EXCUSED: AttendanceStatus.EXCUSED
        }
        
        new_status = operation_to_status[operation]
        processed_count = 0
        failed_count = 0
        failed_students = []
        
        # Get target students
        if student_ids is None:
            # Get all enrolled students for the class session
            result = await self.db.execute(
                select(ClassSession).where(ClassSession.id == class_session_id)
                .options(joinedload(ClassSession.enrolled_students))
            )
            session = result.scalar_one()
            target_student_ids = [student.id for student in session.enrolled_students]
        else:
            target_student_ids = student_ids
        
        # Process each student
        for student_id in target_student_ids:
            try:
                # Check if attendance record exists
                result = await self.db.execute(
                    select(AttendanceRecord).where(
                        and_(
                            AttendanceRecord.student_id == student_id,
                            AttendanceRecord.class_session_id == class_session_id
                        )
                    )
                )
                attendance_record = result.scalar_one_or_none()
                
                if attendance_record:
                    # Update existing record
                    await self.update_attendance_status(
                        attendance_record,
                        new_status,
                        teacher_id,
                        reason,
                        ip_address,
                        user_agent,
                        notes
                    )
                else:
                    # Create new record
                    check_in_time = datetime.utcnow() if new_status != AttendanceStatus.ABSENT else None
                    await self.create_attendance_record(
                        student_id,
                        class_session_id,
                        new_status,
                        "teacher_override",
                        teacher_id,
                        ip_address,
                        user_agent,
                        notes,
                        check_in_time,
                        reason
                    )
                
                processed_count += 1
                
                # Create bulk audit log
                await self._create_audit_log(
                    attendance_record.id if attendance_record else None,
                    teacher_id,
                    "bulk_update",
                    attendance_record.status if attendance_record else None,
                    new_status,
                    f"Bulk operation: {operation.value} - {reason}",
                    ip_address,
                    user_agent,
                    {"operation": operation.value, "bulk_reason": reason}
                )
                
            except Exception as e:
                failed_count += 1
                failed_students.append({
                    "student_id": student_id,
                    "error": str(e)
                })
        
        return {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "failed_students": failed_students
        }
    
    async def calculate_attendance_stats(self, class_session_id: int) -> AttendanceStats:
        """
        Calculate attendance statistics for a class session.
        """
        result = await self.db.execute(
            select(
                func.count(AttendanceRecord.id).label('total'),
                func.count().filter(AttendanceRecord.status == AttendanceStatus.PRESENT).label('present'),
                func.count().filter(AttendanceRecord.status == AttendanceStatus.LATE).label('late'),
                func.count().filter(AttendanceRecord.status == AttendanceStatus.ABSENT).label('absent'),
                func.count().filter(AttendanceRecord.status == AttendanceStatus.EXCUSED).label('excused')
            )
            .where(AttendanceRecord.class_session_id == class_session_id)
        )
        
        stats = result.first()
        
        if stats.total == 0:
            return AttendanceStats(
                total_students=0,
                present_count=0,
                late_count=0,
                absent_count=0,
                excused_count=0,
                attendance_rate=0.0,
                late_rate=0.0
            )
        
        attendance_rate = (stats.present + stats.late + stats.excused) / stats.total
        late_rate = stats.late / stats.total if stats.total > 0 else 0.0
        
        return AttendanceStats(
            total_students=stats.total,
            present_count=stats.present,
            late_count=stats.late,
            absent_count=stats.absent,
            excused_count=stats.excused,
            attendance_rate=round(attendance_rate, 3),
            late_rate=round(late_rate, 3)
        )
    
    async def analyze_student_attendance_pattern(
        self,
        student_id: int,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        min_sessions: int = 5
    ) -> StudentAttendancePattern:
        """
        Analyze attendance patterns for a specific student.
        """
        # Default to last 30 days if no dates provided
        if date_to is None:
            date_to = datetime.utcnow()
        if date_from is None:
            date_from = date_to - timedelta(days=30)
        
        # Get attendance records
        result = await self.db.execute(
            select(AttendanceRecord, User.full_name)
            .join(User, AttendanceRecord.student_id == User.id)
            .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
            .where(
                and_(
                    AttendanceRecord.student_id == student_id,
                    ClassSession.start_time.between(date_from, date_to)
                )
            )
            .order_by(ClassSession.start_time.desc())
        )
        
        records = result.all()
        
        if len(records) < min_sessions:
            # Not enough data
            return StudentAttendancePattern(
                student_id=student_id,
                student_name=records[0].full_name if records else "Unknown",
                total_sessions=len(records),
                present_count=0,
                late_count=0,
                absent_count=0,
                excused_count=0,
                consecutive_absences=0,
                attendance_rate=0.0,
                is_at_risk=len(records) > 0,
                risk_factors=["insufficient_data"] if len(records) > 0 else []
            )
        
        # Calculate statistics
        present_count = sum(1 for r, _ in records if r.status == AttendanceStatus.PRESENT)
        late_count = sum(1 for r, _ in records if r.status == AttendanceStatus.LATE)
        absent_count = sum(1 for r, _ in records if r.status == AttendanceStatus.ABSENT)
        excused_count = sum(1 for r, _ in records if r.status == AttendanceStatus.EXCUSED)
        
        # Calculate consecutive absences
        consecutive_absences = 0
        for record, _ in records:
            if record.status == AttendanceStatus.ABSENT:
                consecutive_absences += 1
            else:
                break
        
        # Calculate attendance rate (present + late + excused)
        attendance_rate = (present_count + late_count + excused_count) / len(records)
        
        # Determine risk factors
        risk_factors = []
        is_at_risk = False
        
        if consecutive_absences >= self.at_risk_consecutive_absence_threshold:
            risk_factors.append("consecutive_absences")
            is_at_risk = True
        
        if attendance_rate < self.at_risk_attendance_rate_threshold:
            risk_factors.append("low_attendance_rate")
            is_at_risk = True
        
        if late_count / len(records) > 0.3:  # More than 30% late
            risk_factors.append("frequent_lateness")
            is_at_risk = True
        
        return StudentAttendancePattern(
            student_id=student_id,
            student_name=records[0][1] if records else "Unknown",
            total_sessions=len(records),
            present_count=present_count,
            late_count=late_count,
            absent_count=absent_count,
            excused_count=excused_count,
            consecutive_absences=consecutive_absences,
            attendance_rate=round(attendance_rate, 3),
            is_at_risk=is_at_risk,
            risk_factors=risk_factors
        )
    
    async def generate_attendance_alerts(
        self,
        class_session_id: Optional[int] = None,
        student_id: Optional[int] = None
    ) -> List[AttendanceAlert]:
        """
        Generate attendance alerts based on patterns.
        """
        alerts = []
        
        # Base query for students to analyze
        if student_id:
            student_ids = [student_id]
        elif class_session_id:
            # Get all students in the class
            result = await self.db.execute(
                select(User.id).distinct()
                .join(AttendanceRecord, User.id == AttendanceRecord.student_id)
                .where(AttendanceRecord.class_session_id == class_session_id)
            )
            student_ids = [row[0] for row in result.all()]
        else:
            # Get all students with recent attendance
            result = await self.db.execute(
                select(User.id).distinct()
                .join(AttendanceRecord, User.id == AttendanceRecord.student_id)
                .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
                .where(ClassSession.start_time >= datetime.utcnow() - timedelta(days=7))
            )
            student_ids = [row[0] for row in result.all()]
        
        # Analyze each student
        for sid in student_ids:
            pattern = await self.analyze_student_attendance_pattern(sid)
            
            if pattern.is_at_risk:
                severity = "high" if pattern.consecutive_absences >= 5 else "medium"
                
                alert_message = f"{pattern.student_name} may need attention"
                alert_data = {
                    "attendance_rate": pattern.attendance_rate,
                    "consecutive_absences": pattern.consecutive_absences,
                    "total_sessions": pattern.total_sessions,
                    "risk_factors": pattern.risk_factors
                }
                
                if "consecutive_absences" in pattern.risk_factors:
                    alerts.append(AttendanceAlert(
                        type="consecutive_absence",
                        severity=severity,
                        student_id=pattern.student_id,
                        student_name=pattern.student_name,
                        message=f"{pattern.student_name} has {pattern.consecutive_absences} consecutive absences",
                        data=alert_data,
                        created_at=datetime.utcnow()
                    ))
                
                if "low_attendance_rate" in pattern.risk_factors:
                    alerts.append(AttendanceAlert(
                        type="low_attendance",
                        severity="medium",
                        student_id=pattern.student_id,
                        student_name=pattern.student_name,
                        message=f"{pattern.student_name} has low attendance rate: {pattern.attendance_rate:.1%}",
                        data=alert_data,
                        created_at=datetime.utcnow()
                    ))
        
        return alerts
    
    async def _create_audit_log(
        self,
        attendance_record_id: Optional[int],
        user_id: int,
        action: str,
        old_status: Optional[AttendanceStatus],
        new_status: AttendanceStatus,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Create an audit log entry.
        """
        audit_log = AttendanceAuditLog(
            attendance_record_id=attendance_record_id,
            user_id=user_id,
            action=action,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
            audit_metadata=json.dumps(metadata) if metadata else None
        )
        
        self.db.add(audit_log)
        await self.db.flush()
    
    async def get_audit_trail(
        self,
        attendance_record_id: int
    ) -> List[AttendanceAuditLog]:
        """
        Get audit trail for an attendance record.
        """
        result = await self.db.execute(
            select(AttendanceAuditLog)
            .where(AttendanceAuditLog.attendance_record_id == attendance_record_id)
            .order_by(AttendanceAuditLog.created_at.desc())
        )
        
        return result.scalars().all()
    
    async def save_pattern_analysis(
        self,
        student_id: int,
        analysis_result: Dict[str, Any]
    ) -> AttendancePatternAnalysis:
        """
        Save pattern analysis results to the database for historical tracking.
        """
        analysis = AttendancePatternAnalysis(
            student_id=student_id,
            analysis_period_days=analysis_result.get("analysis_period_days", 30),
            data_points_analyzed=analysis_result.get("data_points_analyzed", 0)
        )
        
        # Set basic statistics
        basic_stats = analysis_result.get("basic_statistics", {})
        analysis.set_basic_statistics(basic_stats)
        
        # Set trend analysis
        trend = analysis_result.get("trend_analysis", {})
        if isinstance(trend, dict) and trend.get("trend_direction"):
            analysis.trend_direction = trend.get("trend_direction")
            analysis.trend_strength = trend.get("trend_strength", 0.0)
            analysis.trend_confidence = trend.get("confidence_level", 0.0)
        
        # Set seasonal patterns
        seasonal = analysis_result.get("seasonal_patterns", {})
        analysis.set_seasonal_patterns(seasonal)
        
        # Set behavioral patterns
        behavioral = analysis_result.get("behavioral_patterns", {})
        analysis.set_behavioral_patterns(behavioral)
        
        # Set risk assessment
        risk = analysis_result.get("risk_assessment", {})
        if risk:
            analysis.risk_score = risk.get("risk_score", 0.0)
            risk_level = risk.get("risk_level", "minimal")
            try:
                analysis.risk_level = RiskLevel(risk_level.upper())
            except ValueError:
                analysis.risk_level = RiskLevel.MINIMAL
            
            risk_factors = risk.get("risk_factors", [])
            analysis.set_risk_factors(risk_factors)
            
            recommended_actions = risk.get("recommended_actions", [])
            analysis.set_recommended_actions(recommended_actions)
        
        self.db.add(analysis)
        await self.db.flush()
        
        return analysis
    
    async def save_attendance_alert(
        self,
        alert_data: AttendanceAlert,
        pattern_analysis_id: Optional[int] = None,
        class_session_id: Optional[int] = None
    ) -> AlertModel:
        """
        Save attendance alert to the database for tracking and management.
        """
        # Map alert type to PatternType
        type_mapping = {
            "consecutive_absence": PatternType.CONSECUTIVE_ABSENCE,
            "low_attendance": PatternType.LOW_ATTENDANCE,
            "frequent_lateness": PatternType.FREQUENT_LATENESS,
            "declining_trend": PatternType.DECLINING_TREND,
            "comprehensive_risk": PatternType.IRREGULAR_PATTERN  # Default for complex patterns
        }
        
        alert_type = type_mapping.get(alert_data.type, PatternType.IRREGULAR_PATTERN)
        
        # Map severity
        severity_mapping = {
            "low": AlertSeverity.LOW,
            "medium": AlertSeverity.MEDIUM,
            "high": AlertSeverity.HIGH,
            "critical": AlertSeverity.CRITICAL
        }
        
        severity = severity_mapping.get(alert_data.severity, AlertSeverity.MEDIUM)
        
        # Create alert record
        alert_record = AlertModel(
            alert_type=alert_type,
            severity=severity,
            student_id=alert_data.student_id,
            class_session_id=class_session_id,
            pattern_analysis_id=pattern_analysis_id,
            title=f"{alert_data.type.replace('_', ' ').title()} Alert",
            message=alert_data.message
        )
        
        # Set alert data
        alert_record.set_alert_data(alert_data.data)
        
        # Set follow-up requirements for high-severity alerts
        if severity in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]:
            alert_record.requires_followup = True
            # Set deadline to 3 days from now for high priority
            alert_record.followup_deadline = datetime.utcnow() + timedelta(days=3)
        
        self.db.add(alert_record)
        await self.db.flush()
        
        return alert_record
    
    async def create_attendance_insight(
        self,
        scope: str,
        target_id: Optional[int],
        category: str,
        title: str,
        description: str,
        priority: str = "medium",
        supporting_metrics: Optional[Dict[str, Any]] = None,
        recommended_actions: Optional[List[str]] = None,
        analysis_period_days: int = 30
    ) -> AttendanceInsight:
        """
        Create an attendance insight for actionable recommendations.
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=analysis_period_days)
        
        # Map priority
        priority_mapping = {
            "low": AlertSeverity.LOW,
            "medium": AlertSeverity.MEDIUM,
            "high": AlertSeverity.HIGH,
            "critical": AlertSeverity.CRITICAL
        }
        
        insight = AttendanceInsight(
            insight_scope=scope,
            target_id=target_id,
            category=category,
            priority=priority_mapping.get(priority, AlertSeverity.MEDIUM),
            title=title,
            description=description,
            analysis_period_start=start_date,
            analysis_period_end=end_date
        )
        
        if supporting_metrics:
            insight.set_supporting_metrics(supporting_metrics)
        
        if recommended_actions:
            insight.set_recommended_actions(recommended_actions)
        
        self.db.add(insight)
        await self.db.flush()
        
        return insight
    
    async def get_pattern_analysis_history(
        self,
        student_id: int,
        limit: int = 10
    ) -> List[AttendancePatternAnalysis]:
        """
        Get historical pattern analysis records for a student.
        """
        result = await self.db.execute(
            select(AttendancePatternAnalysis)
            .where(AttendancePatternAnalysis.student_id == student_id)
            .order_by(AttendancePatternAnalysis.created_at.desc())
            .limit(limit)
        )
        
        return result.scalars().all()
    
    async def get_active_alerts(
        self,
        student_id: Optional[int] = None,
        class_session_id: Optional[int] = None,
        severity_filter: Optional[str] = None
    ) -> List[AlertModel]:
        """
        Get active (unresolved) alerts with optional filtering.
        """
        query = select(AlertModel).where(AlertModel.is_resolved == False)
        
        if student_id:
            query = query.where(AlertModel.student_id == student_id)
        
        if class_session_id:
            query = query.where(AlertModel.class_session_id == class_session_id)
        
        if severity_filter:
            try:
                severity = AlertSeverity(severity_filter.upper())
                query = query.where(AlertModel.severity == severity)
            except ValueError:
                pass  # Invalid severity, ignore filter
        
        query = query.order_by(AlertModel.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def acknowledge_alert(
        self,
        alert_id: int,
        user_id: int,
        note: Optional[str] = None
    ) -> AlertModel:
        """
        Acknowledge an alert and optionally add a note.
        """
        result = await self.db.execute(
            select(AlertModel).where(AlertModel.id == alert_id)
        )
        alert = result.scalar_one()
        
        alert.acknowledge(user_id, note)
        await self.db.flush()
        
        return alert
    
    async def resolve_alert(
        self,
        alert_id: int,
        user_id: int,
        note: Optional[str] = None
    ) -> AlertModel:
        """
        Resolve an alert and optionally add a resolution note.
        """
        result = await self.db.execute(
            select(AlertModel).where(AlertModel.id == alert_id)
        )
        alert = result.scalar_one()
        
        alert.resolve(user_id, note)
        await self.db.flush()
        
        return alert