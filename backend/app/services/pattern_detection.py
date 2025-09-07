"""
Advanced pattern detection service for sophisticated attendance analytics.
Implements machine learning algorithms and statistical analysis for 
early intervention and attendance prediction.
"""
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_, distinct
from sqlalchemy.orm import joinedload

from app.models.attendance import AttendanceRecord, AttendanceStatus, AttendanceAuditLog
from app.models.class_session import ClassSession
from app.models.user import User, UserRole
from app.schemas.attendance import (
    StudentAttendancePattern, AttendanceAlert, AttendanceStats
)


@dataclass
class AttendanceTrend:
    """Represents attendance trend over time."""
    period: str  # "week", "month", "semester"
    trend_direction: str  # "improving", "declining", "stable"
    trend_strength: float  # 0.0 to 1.0
    confidence_level: float  # Statistical confidence
    data_points: List[Tuple[datetime, float]]


@dataclass 
class SeasonalPattern:
    """Represents seasonal attendance patterns."""
    season: str  # "day_of_week", "time_of_day", "month"
    pattern_type: str  # "recurring", "anomaly", "seasonal"
    pattern_strength: float
    best_periods: List[str]
    worst_periods: List[str]


@dataclass
class PredictionResult:
    """Attendance prediction result."""
    student_id: int
    predicted_status: AttendanceStatus
    confidence: float
    risk_factors: List[str]
    recommended_actions: List[str]


class AdvancedPatternDetector:
    """
    Advanced pattern detection with machine learning algorithms,
    statistical analysis, and early warning system.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
        # Configuration parameters
        self.min_data_points = 10
        self.prediction_confidence_threshold = 0.7
        self.trend_analysis_window_days = 30
        self.seasonal_analysis_min_weeks = 4
        
        # Risk thresholds
        self.high_risk_consecutive_absences = 5
        self.medium_risk_consecutive_absences = 3
        self.critical_attendance_rate = 0.5
        self.low_attendance_rate = 0.75
        self.high_lateness_rate = 0.3
        
        # Pattern detection weights
        self.pattern_weights = {
            "consecutive_absences": 0.4,
            "attendance_rate": 0.3,
            "lateness_pattern": 0.15,
            "trend_direction": 0.15
        }

    async def detect_advanced_patterns(
        self,
        student_id: int,
        analysis_period_days: int = 60
    ) -> Dict[str, Any]:
        """
        Comprehensive pattern analysis including trends, seasonality,
        and behavioral patterns.
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=analysis_period_days)
        
        # Get comprehensive attendance data
        attendance_data = await self._get_attendance_history(
            student_id, start_date, end_date
        )
        
        if len(attendance_data) < self.min_data_points:
            return self._insufficient_data_response(student_id, len(attendance_data))
        
        # Perform various analyses
        basic_stats = await self._calculate_advanced_statistics(attendance_data)
        trend_analysis = await self._analyze_attendance_trends(attendance_data)
        seasonal_patterns = await self._detect_seasonal_patterns(attendance_data)
        behavioral_patterns = await self._analyze_behavioral_patterns(attendance_data)
        risk_assessment = await self._assess_comprehensive_risk(
            basic_stats, trend_analysis, behavioral_patterns
        )
        
        return {
            "student_id": student_id,
            "analysis_period_days": analysis_period_days,
            "data_points_analyzed": len(attendance_data),
            "basic_statistics": basic_stats,
            "trend_analysis": trend_analysis,
            "seasonal_patterns": seasonal_patterns,
            "behavioral_patterns": behavioral_patterns,
            "risk_assessment": risk_assessment,
            "generated_at": datetime.utcnow()
        }

    async def predict_future_attendance(
        self,
        student_id: int,
        prediction_days: int = 7
    ) -> List[PredictionResult]:
        """
        Predict future attendance using historical patterns and trends.
        """
        # Get historical data for prediction model
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=90)  # 3 months for prediction
        
        attendance_data = await self._get_attendance_history(
            student_id, start_date, end_date
        )
        
        if len(attendance_data) < self.min_data_points:
            return []
        
        # Analyze patterns for prediction
        trend_analysis = await self._analyze_attendance_trends(attendance_data)
        behavioral_patterns = await self._analyze_behavioral_patterns(attendance_data)
        seasonal_patterns = await self._detect_seasonal_patterns(attendance_data)
        
        predictions = []
        
        # Get upcoming class sessions for prediction
        upcoming_sessions = await self._get_upcoming_sessions(student_id, prediction_days)
        
        for session in upcoming_sessions:
            prediction = await self._generate_session_prediction(
                student_id, session, trend_analysis, 
                behavioral_patterns, seasonal_patterns
            )
            predictions.append(prediction)
        
        return predictions

    async def detect_attendance_anomalies(
        self,
        student_id: Optional[int] = None,
        class_session_id: Optional[int] = None,
        detection_period_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Detect attendance anomalies using statistical methods.
        """
        anomalies = []
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=detection_period_days)
        
        if student_id:
            student_ids = [student_id]
        else:
            # Get all active students
            student_ids = await self._get_active_students(start_date)
        
        for sid in student_ids:
            student_anomalies = await self._detect_student_anomalies(
                sid, start_date, end_date
            )
            anomalies.extend(student_anomalies)
        
        return anomalies

    async def generate_early_warning_alerts(
        self,
        class_session_id: Optional[int] = None,
        alert_severity_threshold: str = "medium"
    ) -> List[AttendanceAlert]:
        """
        Generate sophisticated early warning alerts with multiple criteria.
        """
        alerts = []
        
        # Get students to analyze
        if class_session_id:
            student_ids = await self._get_class_students(class_session_id)
        else:
            student_ids = await self._get_active_students()
        
        for student_id in student_ids:
            student_alerts = await self._generate_student_alerts(
                student_id, alert_severity_threshold
            )
            alerts.extend(student_alerts)
        
        # Sort alerts by severity and confidence
        alerts.sort(key=lambda x: (
            {"high": 3, "medium": 2, "low": 1}[x.severity],
            x.data.get("confidence", 0)
        ), reverse=True)
        
        return alerts

    async def _get_attendance_history(
        self,
        student_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Tuple[AttendanceRecord, ClassSession, User]]:
        """Get comprehensive attendance history with session and user data."""
        result = await self.db.execute(
            select(AttendanceRecord, ClassSession, User)
            .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
            .join(User, AttendanceRecord.student_id == User.id)
            .where(
                and_(
                    AttendanceRecord.student_id == student_id,
                    ClassSession.start_time.between(start_date, end_date)
                )
            )
            .order_by(ClassSession.start_time.asc())
        )
        
        return result.all()

    async def _calculate_advanced_statistics(
        self,
        attendance_data: List[Tuple[AttendanceRecord, ClassSession, User]]
    ) -> Dict[str, Any]:
        """Calculate comprehensive statistical metrics."""
        if not attendance_data:
            return {}
        
        statuses = [record.status for record, _, _ in attendance_data]
        late_minutes = [record.late_minutes for record, _, _ in attendance_data if record.late_minutes]
        
        # Basic counts
        status_counts = {status.value: statuses.count(status) for status in AttendanceStatus}
        total_sessions = len(attendance_data)
        
        # Advanced metrics
        attendance_rate = (status_counts["present"] + status_counts["late"] + status_counts["excused"]) / total_sessions
        punctuality_rate = status_counts["present"] / total_sessions if total_sessions > 0 else 0
        absence_rate = status_counts["absent"] / total_sessions if total_sessions > 0 else 0
        
        # Late analysis
        avg_late_minutes = statistics.mean(late_minutes) if late_minutes else 0
        max_late_minutes = max(late_minutes) if late_minutes else 0
        late_consistency = statistics.stdev(late_minutes) if len(late_minutes) > 1 else 0
        
        # Consecutive patterns
        consecutive_absences = self._calculate_max_consecutive(statuses, AttendanceStatus.ABSENT)
        consecutive_late = self._calculate_max_consecutive(statuses, AttendanceStatus.LATE)
        consecutive_present = self._calculate_max_consecutive(statuses, AttendanceStatus.PRESENT)
        
        return {
            "total_sessions": total_sessions,
            "status_distribution": status_counts,
            "attendance_rate": round(attendance_rate, 3),
            "punctuality_rate": round(punctuality_rate, 3),
            "absence_rate": round(absence_rate, 3),
            "average_late_minutes": round(avg_late_minutes, 1),
            "max_late_minutes": max_late_minutes,
            "late_consistency_score": round(late_consistency, 2),
            "consecutive_patterns": {
                "max_absences": consecutive_absences,
                "max_late": consecutive_late,
                "max_present": consecutive_present
            }
        }

    async def _analyze_attendance_trends(
        self,
        attendance_data: List[Tuple[AttendanceRecord, ClassSession, User]]
    ) -> AttendanceTrend:
        """Analyze attendance trends over time using statistical methods."""
        if len(attendance_data) < 5:
            return AttendanceTrend(
                period="insufficient_data",
                trend_direction="unknown",
                trend_strength=0.0,
                confidence_level=0.0,
                data_points=[]
            )
        
        # Group by weekly periods
        weekly_rates = defaultdict(list)
        for record, session, _ in attendance_data:
            week_key = session.start_time.strftime("%Y-%W")
            # Score: present=1, late=0.8, excused=0.6, absent=0
            score = {
                AttendanceStatus.PRESENT: 1.0,
                AttendanceStatus.LATE: 0.8,
                AttendanceStatus.EXCUSED: 0.6,
                AttendanceStatus.ABSENT: 0.0
            }[record.status]
            weekly_rates[week_key].append(score)
        
        # Calculate weekly averages
        weekly_averages = []
        for week, scores in weekly_rates.items():
            avg_score = statistics.mean(scores)
            weekly_averages.append(avg_score)
        
        if len(weekly_averages) < 3:
            return AttendanceTrend(
                period="insufficient_weeks",
                trend_direction="unknown", 
                trend_strength=0.0,
                confidence_level=0.0,
                data_points=[]
            )
        
        # Calculate linear trend
        n = len(weekly_averages)
        x_values = list(range(n))
        y_values = weekly_averages
        
        # Linear regression for trend detection
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)
        
        slope_numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        slope_denominator = sum((x - x_mean) ** 2 for x in x_values)
        
        if slope_denominator == 0:
            slope = 0
        else:
            slope = slope_numerator / slope_denominator
        
        # Determine trend direction and strength
        trend_strength = abs(slope)
        if abs(slope) < 0.01:
            trend_direction = "stable"
        elif slope > 0:
            trend_direction = "improving"
        else:
            trend_direction = "declining"
        
        # Calculate confidence based on R-squared
        y_pred = [y_mean + slope * (x - x_mean) for x in x_values]
        ss_tot = sum((y - y_mean) ** 2 for y in y_values)
        ss_res = sum((y - y_pred) ** 2 for y, y_pred in zip(y_values, y_pred))
        
        confidence_level = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        
        return AttendanceTrend(
            period="weekly",
            trend_direction=trend_direction,
            trend_strength=min(trend_strength * 10, 1.0),  # Scale to 0-1
            confidence_level=max(0.0, min(confidence_level, 1.0)),
            data_points=list(zip(x_values, y_values))
        )

    async def _detect_seasonal_patterns(
        self,
        attendance_data: List[Tuple[AttendanceRecord, ClassSession, User]]
    ) -> Dict[str, SeasonalPattern]:
        """Detect seasonal and recurring patterns."""
        patterns = {}
        
        if len(attendance_data) < self.seasonal_analysis_min_weeks * 7:
            return patterns
        
        # Day of week patterns
        dow_scores = defaultdict(list)
        for record, session, _ in attendance_data:
            dow = session.start_time.weekday()  # 0=Monday, 6=Sunday
            score = self._status_to_score(record.status)
            dow_scores[dow].append(score)
        
        # Calculate average scores per day
        dow_averages = {dow: statistics.mean(scores) for dow, scores in dow_scores.items() if scores}
        
        if len(dow_averages) >= 3:
            best_days = sorted(dow_averages.items(), key=lambda x: x[1], reverse=True)[:2]
            worst_days = sorted(dow_averages.items(), key=lambda x: x[1])[:2]
            
            # Calculate pattern strength
            max_score = max(dow_averages.values())
            min_score = min(dow_averages.values())
            pattern_strength = max_score - min_score
            
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            
            patterns["day_of_week"] = SeasonalPattern(
                season="day_of_week",
                pattern_type="recurring",
                pattern_strength=pattern_strength,
                best_periods=[day_names[day] for day, _ in best_days],
                worst_periods=[day_names[day] for day, _ in worst_days]
            )
        
        # Time of day patterns
        hour_scores = defaultdict(list)
        for record, session, _ in attendance_data:
            hour = session.start_time.hour
            score = self._status_to_score(record.status)
            hour_scores[hour].append(score)
        
        hour_averages = {hour: statistics.mean(scores) for hour, scores in hour_scores.items() if scores}
        
        if len(hour_averages) >= 3:
            best_hours = sorted(hour_averages.items(), key=lambda x: x[1], reverse=True)[:2]
            worst_hours = sorted(hour_averages.items(), key=lambda x: x[1])[:2]
            
            max_score = max(hour_averages.values())
            min_score = min(hour_averages.values())
            pattern_strength = max_score - min_score
            
            patterns["time_of_day"] = SeasonalPattern(
                season="time_of_day",
                pattern_type="recurring",
                pattern_strength=pattern_strength,
                best_periods=[f"{hour:02d}:00" for hour, _ in best_hours],
                worst_periods=[f"{hour:02d}:00" for hour, _ in worst_hours]
            )
        
        return patterns

    async def _analyze_behavioral_patterns(
        self,
        attendance_data: List[Tuple[AttendanceRecord, ClassSession, User]]
    ) -> Dict[str, Any]:
        """Analyze behavioral patterns and habits."""
        if len(attendance_data) < 10:
            return {}
        
        # Check-in timing patterns
        check_in_delays = []
        grace_period_usage = 0
        late_arrivals = 0
        
        for record, session, _ in attendance_data:
            if record.check_in_time and record.status != AttendanceStatus.ABSENT:
                delay = (record.check_in_time - session.start_time).total_seconds() / 60
                check_in_delays.append(delay)
                
                if record.grace_period_used:
                    grace_period_usage += 1
                if record.is_late:
                    late_arrivals += 1
        
        # Override patterns
        manual_overrides = sum(1 for record, _, _ in attendance_data if record.is_manual_override)
        override_rate = manual_overrides / len(attendance_data)
        
        # Consistency patterns
        status_changes = 0
        prev_status = None
        for record, _, _ in attendance_data:
            if prev_status and prev_status != record.status:
                status_changes += 1
            prev_status = record.status
        
        consistency_score = 1 - (status_changes / max(len(attendance_data) - 1, 1))
        
        return {
            "check_in_patterns": {
                "average_delay_minutes": round(statistics.mean(check_in_delays), 1) if check_in_delays else 0,
                "delay_consistency": round(statistics.stdev(check_in_delays), 2) if len(check_in_delays) > 1 else 0,
                "grace_period_usage_rate": round(grace_period_usage / len(attendance_data), 3),
                "late_arrival_rate": round(late_arrivals / len(attendance_data), 3)
            },
            "intervention_patterns": {
                "manual_override_rate": round(override_rate, 3),
                "needs_intervention": override_rate > 0.1
            },
            "consistency_metrics": {
                "status_consistency_score": round(consistency_score, 3),
                "behavior_predictability": "high" if consistency_score > 0.8 else "medium" if consistency_score > 0.6 else "low"
            }
        }

    async def _assess_comprehensive_risk(
        self,
        basic_stats: Dict[str, Any],
        trend_analysis: AttendanceTrend,
        behavioral_patterns: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Comprehensive risk assessment using multiple factors."""
        risk_factors = []
        risk_score = 0.0
        
        # Attendance rate risk
        attendance_rate = basic_stats.get("attendance_rate", 0)
        if attendance_rate < self.critical_attendance_rate:
            risk_factors.append("critical_attendance_rate")
            risk_score += 0.4
        elif attendance_rate < self.low_attendance_rate:
            risk_factors.append("low_attendance_rate")
            risk_score += 0.25
        
        # Consecutive absence risk
        max_absences = basic_stats.get("consecutive_patterns", {}).get("max_absences", 0)
        if max_absences >= self.high_risk_consecutive_absences:
            risk_factors.append("high_consecutive_absences")
            risk_score += 0.35
        elif max_absences >= self.medium_risk_consecutive_absences:
            risk_factors.append("medium_consecutive_absences")
            risk_score += 0.2
        
        # Trend analysis risk
        if trend_analysis.trend_direction == "declining" and trend_analysis.confidence_level > 0.6:
            risk_factors.append("declining_trend")
            risk_score += 0.15 * trend_analysis.trend_strength
        
        # Behavioral risk
        if behavioral_patterns and behavioral_patterns.get("intervention_patterns", {}).get("needs_intervention", False):
            risk_factors.append("frequent_interventions")
            risk_score += 0.1
        
        # Determine risk level
        if risk_score >= 0.7:
            risk_level = "high"
        elif risk_score >= 0.4:
            risk_level = "medium"
        elif risk_score > 0.1:
            risk_level = "low"
        else:
            risk_level = "minimal"
        
        return {
            "risk_score": round(risk_score, 3),
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "requires_immediate_attention": risk_score >= 0.7,
            "recommended_actions": self._generate_recommended_actions(risk_factors, risk_level)
        }

    def _generate_recommended_actions(self, risk_factors: List[str], risk_level: str) -> List[str]:
        """Generate recommended actions based on risk factors."""
        actions = []
        
        if "critical_attendance_rate" in risk_factors:
            actions.append("Schedule immediate meeting with student and parents")
            actions.append("Develop personalized attendance improvement plan")
        
        if "high_consecutive_absences" in risk_factors:
            actions.append("Initiate early intervention protocol")
            actions.append("Check for underlying issues (health, personal, academic)")
        
        if "declining_trend" in risk_factors:
            actions.append("Monitor weekly attendance closely")
            actions.append("Provide additional academic support if needed")
        
        if "frequent_interventions" in risk_factors:
            actions.append("Review attendance policies with student")
            actions.append("Establish clearer expectations and consequences")
        
        if risk_level == "high":
            actions.append("Consider formal attendance contract")
            actions.append("Involve school counselor or social worker")
        elif risk_level == "medium":
            actions.append("Increase monitoring frequency")
            actions.append("Schedule check-in meeting within 1 week")
        
        return actions

    def _status_to_score(self, status: AttendanceStatus) -> float:
        """Convert attendance status to numerical score for analysis."""
        return {
            AttendanceStatus.PRESENT: 1.0,
            AttendanceStatus.LATE: 0.8,
            AttendanceStatus.EXCUSED: 0.6,
            AttendanceStatus.ABSENT: 0.0
        }[status]

    def _calculate_max_consecutive(self, statuses: List[AttendanceStatus], target_status: AttendanceStatus) -> int:
        """Calculate maximum consecutive occurrences of a status."""
        max_consecutive = 0
        current_consecutive = 0
        
        for status in statuses:
            if status == target_status:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        
        return max_consecutive

    def _insufficient_data_response(self, student_id: int, data_points: int) -> Dict[str, Any]:
        """Return response for insufficient data cases."""
        return {
            "student_id": student_id,
            "status": "insufficient_data",
            "data_points_found": data_points,
            "minimum_required": self.min_data_points,
            "message": f"Not enough attendance data for comprehensive analysis. Found {data_points}, need at least {self.min_data_points}."
        }

    async def _get_upcoming_sessions(self, student_id: int, days: int) -> List[ClassSession]:
        """Get upcoming class sessions for a student."""
        end_date = datetime.utcnow() + timedelta(days=days)
        
        # This would need to be implemented based on student enrollment system
        # For now, return empty list as this requires enrollment relationship
        return []

    async def _generate_session_prediction(
        self,
        student_id: int,
        session: ClassSession,
        trend_analysis: AttendanceTrend,
        behavioral_patterns: Dict[str, Any],
        seasonal_patterns: Dict[str, SeasonalPattern]
    ) -> PredictionResult:
        """Generate attendance prediction for a specific session."""
        # This is a simplified prediction model
        # In a real implementation, this would use more sophisticated ML algorithms
        
        base_probability = 0.8  # Base attendance probability
        
        # Adjust based on trend
        if trend_analysis.trend_direction == "improving":
            base_probability += 0.1 * trend_analysis.trend_strength
        elif trend_analysis.trend_direction == "declining":
            base_probability -= 0.15 * trend_analysis.trend_strength
        
        # Adjust based on day of week patterns
        if "day_of_week" in seasonal_patterns:
            # This would need more sophisticated logic
            pass
        
        # Determine predicted status
        if base_probability > 0.9:
            predicted_status = AttendanceStatus.PRESENT
            confidence = base_probability
        elif base_probability > 0.7:
            predicted_status = AttendanceStatus.PRESENT
            confidence = base_probability * 0.9
        elif base_probability > 0.5:
            predicted_status = AttendanceStatus.LATE
            confidence = base_probability * 0.8
        else:
            predicted_status = AttendanceStatus.ABSENT
            confidence = (1 - base_probability) * 0.9
        
        return PredictionResult(
            student_id=student_id,
            predicted_status=predicted_status,
            confidence=confidence,
            risk_factors=[],
            recommended_actions=[]
        )

    async def _get_active_students(self, since_date: Optional[datetime] = None) -> List[int]:
        """Get list of active student IDs."""
        if since_date is None:
            since_date = datetime.utcnow() - timedelta(days=30)
        
        result = await self.db.execute(
            select(distinct(AttendanceRecord.student_id))
            .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
            .where(ClassSession.start_time >= since_date)
        )
        
        return [row[0] for row in result.all()]

    async def _get_class_students(self, class_session_id: int) -> List[int]:
        """Get student IDs for a specific class session."""
        result = await self.db.execute(
            select(distinct(AttendanceRecord.student_id))
            .where(AttendanceRecord.class_session_id == class_session_id)
        )
        
        return [row[0] for row in result.all()]

    async def _detect_student_anomalies(
        self,
        student_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Detect anomalies for a specific student."""
        anomalies = []
        
        # Get student's attendance pattern
        attendance_data = await self._get_attendance_history(student_id, start_date, end_date)
        
        if len(attendance_data) < 5:
            return anomalies
        
        # Calculate baseline metrics
        statuses = [record.status for record, _, _ in attendance_data]
        baseline_absence_rate = statuses.count(AttendanceStatus.ABSENT) / len(statuses)
        
        # Detect unusual absence spikes (simple anomaly detection)
        # Group by weeks and check for unusual patterns
        weekly_data = defaultdict(list)
        for record, session, _ in attendance_data:
            week_key = session.start_time.strftime("%Y-%W")
            weekly_data[week_key].append(record.status)
        
        for week, week_statuses in weekly_data.items():
            week_absence_rate = week_statuses.count(AttendanceStatus.ABSENT) / len(week_statuses)
            
            # Flag if absence rate is significantly higher than baseline
            if week_absence_rate > baseline_absence_rate + 0.3:  # 30% threshold
                anomalies.append({
                    "student_id": student_id,
                    "type": "unusual_absence_spike",
                    "period": week,
                    "severity": "medium",
                    "description": f"Unusually high absence rate: {week_absence_rate:.1%} vs baseline {baseline_absence_rate:.1%}",
                    "detected_at": datetime.utcnow()
                })
        
        return anomalies

    async def _generate_student_alerts(
        self,
        student_id: int,
        severity_threshold: str
    ) -> List[AttendanceAlert]:
        """Generate alerts for a specific student."""
        alerts = []
        
        # Get recent pattern analysis
        pattern_data = await self.detect_advanced_patterns(student_id, analysis_period_days=30)
        
        if pattern_data.get("status") == "insufficient_data":
            return alerts
        
        risk_assessment = pattern_data.get("risk_assessment", {})
        
        # Generate alerts based on risk level
        risk_level = risk_assessment.get("risk_level", "minimal")
        risk_factors = risk_assessment.get("risk_factors", [])
        
        severity_order = {"low": 1, "medium": 2, "high": 3}
        threshold_level = severity_order.get(severity_threshold, 2)
        
        if severity_order.get(risk_level, 0) >= threshold_level:
            # Get student name
            result = await self.db.execute(
                select(User.full_name).where(User.id == student_id)
            )
            student_name = result.scalar_one_or_none() or "Unknown Student"
            
            alert_message = self._generate_alert_message(risk_factors, risk_level)
            
            alerts.append(AttendanceAlert(
                type="comprehensive_risk",
                severity=risk_level,
                student_id=student_id,
                student_name=student_name,
                message=alert_message,
                data={
                    "risk_score": risk_assessment.get("risk_score", 0),
                    "risk_factors": risk_factors,
                    "recommended_actions": risk_assessment.get("recommended_actions", []),
                    "confidence": 0.85
                },
                created_at=datetime.utcnow()
            ))
        
        return alerts

    def _generate_alert_message(self, risk_factors: List[str], risk_level: str) -> str:
        """Generate human-readable alert message."""
        if "critical_attendance_rate" in risk_factors:
            return "Student has critically low attendance rate requiring immediate intervention"
        elif "high_consecutive_absences" in risk_factors:
            return "Student has excessive consecutive absences indicating potential issues"
        elif "declining_trend" in risk_factors and "low_attendance_rate" in risk_factors:
            return "Student shows declining attendance trend with below-average rate"
        elif "declining_trend" in risk_factors:
            return "Student attendance is showing a concerning declining trend"
        elif risk_level == "high":
            return "Student requires immediate attention due to attendance concerns"
        elif risk_level == "medium":
            return "Student shows patterns that may require monitoring and support"
        else:
            return "Student attendance patterns suggest potential for improvement"