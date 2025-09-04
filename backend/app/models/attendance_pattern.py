"""
Attendance pattern models for storing analysis results, alerts, and insights.
These models persist pattern detection results for historical tracking and reporting.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
import json
from datetime import datetime
from typing import Dict, Any, Optional

from app.core.database import Base


class PatternType(str, enum.Enum):
    """Types of attendance patterns."""
    CONSECUTIVE_ABSENCE = "consecutive_absence"
    LOW_ATTENDANCE = "low_attendance"
    FREQUENT_LATENESS = "frequent_lateness"
    DECLINING_TREND = "declining_trend"
    IMPROVING_TREND = "improving_trend"
    SEASONAL_PATTERN = "seasonal_pattern"
    IRREGULAR_PATTERN = "irregular_pattern"


class AlertSeverity(str, enum.Enum):
    """Severity levels for attendance alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, enum.Enum):
    """Risk assessment levels."""
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AttendancePatternAnalysis(Base):
    """
    Stores comprehensive pattern analysis results for students.
    This enables historical tracking of attendance patterns and trends.
    """
    __tablename__ = "attendance_pattern_analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Target information
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    analysis_period_days = Column(Integer, nullable=False)
    data_points_analyzed = Column(Integer, nullable=False)
    
    # Basic statistics (JSON)
    basic_statistics = Column(Text, nullable=False)  # JSON string
    
    # Trend analysis results
    trend_direction = Column(String(50), nullable=True)  # "improving", "declining", "stable"
    trend_strength = Column(Float, nullable=True)  # 0.0 to 1.0
    trend_confidence = Column(Float, nullable=True)  # Statistical confidence
    
    # Seasonal patterns (JSON)
    seasonal_patterns = Column(Text, nullable=True)  # JSON string
    
    # Behavioral patterns (JSON)
    behavioral_patterns = Column(Text, nullable=True)  # JSON string
    
    # Risk assessment
    risk_score = Column(Float, nullable=False, default=0.0)
    risk_level = Column(SQLEnum(RiskLevel), nullable=False, default=RiskLevel.MINIMAL)
    risk_factors = Column(Text, nullable=True)  # JSON array of risk factor strings
    
    # Recommendations and actions (JSON)
    recommended_actions = Column(Text, nullable=True)  # JSON array
    
    # Metadata
    analysis_version = Column(String(20), nullable=False, default="1.0")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    student = relationship("User", back_populates="pattern_analyses")
    alerts = relationship("AttendanceAlert", back_populates="pattern_analysis")
    
    def set_basic_statistics(self, stats: Dict[str, Any]):
        """Set basic statistics as JSON."""
        self.basic_statistics = json.dumps(stats)
    
    def get_basic_statistics(self) -> Dict[str, Any]:
        """Get basic statistics from JSON."""
        if self.basic_statistics:
            return json.loads(self.basic_statistics)
        return {}
    
    def set_seasonal_patterns(self, patterns: Dict[str, Any]):
        """Set seasonal patterns as JSON."""
        self.seasonal_patterns = json.dumps(patterns)
    
    def get_seasonal_patterns(self) -> Dict[str, Any]:
        """Get seasonal patterns from JSON."""
        if self.seasonal_patterns:
            return json.loads(self.seasonal_patterns)
        return {}
    
    def set_behavioral_patterns(self, patterns: Dict[str, Any]):
        """Set behavioral patterns as JSON."""
        self.behavioral_patterns = json.dumps(patterns)
    
    def get_behavioral_patterns(self) -> Dict[str, Any]:
        """Get behavioral patterns from JSON."""
        if self.behavioral_patterns:
            return json.loads(self.behavioral_patterns)
        return {}
    
    def set_risk_factors(self, factors: list):
        """Set risk factors as JSON array."""
        self.risk_factors = json.dumps(factors)
    
    def get_risk_factors(self) -> list:
        """Get risk factors from JSON."""
        if self.risk_factors:
            return json.loads(self.risk_factors)
        return []
    
    def set_recommended_actions(self, actions: list):
        """Set recommended actions as JSON array."""
        self.recommended_actions = json.dumps(actions)
    
    def get_recommended_actions(self) -> list:
        """Get recommended actions from JSON."""
        if self.recommended_actions:
            return json.loads(self.recommended_actions)
        return []


class AttendanceAlert(Base):
    """
    Stores attendance alerts generated by the pattern detection system.
    Enables tracking and management of early warning notifications.
    """
    __tablename__ = "attendance_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Alert classification
    alert_type = Column(SQLEnum(PatternType), nullable=False)
    severity = Column(SQLEnum(AlertSeverity), nullable=False)
    
    # Target information
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    class_session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=True)
    pattern_analysis_id = Column(Integer, ForeignKey("attendance_pattern_analyses.id"), nullable=True)
    
    # Alert details
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    
    # Alert data (JSON)
    alert_data = Column(Text, nullable=True)  # JSON with specific alert data
    
    # Status tracking
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledgment_note = Column(Text, nullable=True)
    
    is_resolved = Column(Boolean, default=False)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(Text, nullable=True)
    
    # Follow-up tracking
    requires_followup = Column(Boolean, default=False)
    followup_deadline = Column(DateTime(timezone=True), nullable=True)
    followup_assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    student = relationship("User", foreign_keys=[student_id])
    class_session = relationship("ClassSession", back_populates="attendance_alerts")
    pattern_analysis = relationship("AttendancePatternAnalysis", back_populates="alerts")
    acknowledged_by_user = relationship("User", foreign_keys=[acknowledged_by])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by])
    followup_assigned_user = relationship("User", foreign_keys=[followup_assigned_to])
    
    def set_alert_data(self, data: Dict[str, Any]):
        """Set alert data as JSON."""
        self.alert_data = json.dumps(data)
    
    def get_alert_data(self) -> Dict[str, Any]:
        """Get alert data from JSON."""
        if self.alert_data:
            return json.loads(self.alert_data)
        return {}
    
    def acknowledge(self, user_id: int, note: Optional[str] = None):
        """Mark alert as acknowledged."""
        self.is_acknowledged = True
        self.acknowledged_by = user_id
        self.acknowledged_at = datetime.utcnow()
        if note:
            self.acknowledgment_note = note
    
    def resolve(self, user_id: int, note: Optional[str] = None):
        """Mark alert as resolved."""
        self.is_resolved = True
        self.resolved_by = user_id
        self.resolved_at = datetime.utcnow()
        if note:
            self.resolution_note = note
    
    def assign_followup(self, user_id: int, deadline: datetime):
        """Assign follow-up action to a user."""
        self.requires_followup = True
        self.followup_assigned_to = user_id
        self.followup_deadline = deadline


class AttendanceInsight(Base):
    """
    Stores actionable insights generated from attendance analytics.
    These are higher-level observations and recommendations for improvement.
    """
    __tablename__ = "attendance_insights"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Scope of insight
    insight_scope = Column(String(50), nullable=False)  # "student", "class", "institution"
    target_id = Column(Integer, nullable=True)  # ID of student, class, or null for institution
    
    # Insight classification
    category = Column(String(100), nullable=False)  # "performance", "engagement", "risk", "opportunity"
    priority = Column(SQLEnum(AlertSeverity), nullable=False, default=AlertSeverity.MEDIUM)
    
    # Insight content
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    
    # Supporting data
    supporting_metrics = Column(Text, nullable=True)  # JSON with relevant metrics
    confidence_score = Column(Float, nullable=True)  # 0.0 to 1.0
    
    # Recommendations
    recommended_actions = Column(Text, nullable=True)  # JSON array of actions
    expected_impact = Column(Text, nullable=True)  # Description of expected impact
    
    # Time context
    analysis_period_start = Column(DateTime(timezone=True), nullable=False)
    analysis_period_end = Column(DateTime(timezone=True), nullable=False)
    
    # Status tracking
    is_actionable = Column(Boolean, default=True)
    is_implemented = Column(Boolean, default=False)
    implemented_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    implemented_at = Column(DateTime(timezone=True), nullable=True)
    implementation_notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    implemented_by_user = relationship("User", foreign_keys=[implemented_by])
    
    def set_supporting_metrics(self, metrics: Dict[str, Any]):
        """Set supporting metrics as JSON."""
        self.supporting_metrics = json.dumps(metrics)
    
    def get_supporting_metrics(self) -> Dict[str, Any]:
        """Get supporting metrics from JSON."""
        if self.supporting_metrics:
            return json.loads(self.supporting_metrics)
        return {}
    
    def set_recommended_actions(self, actions: list):
        """Set recommended actions as JSON array."""
        self.recommended_actions = json.dumps(actions)
    
    def get_recommended_actions(self) -> list:
        """Get recommended actions from JSON."""
        if self.recommended_actions:
            return json.loads(self.recommended_actions)
        return []
    
    def mark_implemented(self, user_id: int, notes: Optional[str] = None):
        """Mark insight as implemented."""
        self.is_implemented = True
        self.implemented_by = user_id
        self.implemented_at = datetime.utcnow()
        if notes:
            self.implementation_notes = notes


class AttendancePrediction(Base):
    """
    Stores attendance predictions generated by forecasting algorithms.
    Enables tracking prediction accuracy and model performance.
    """
    __tablename__ = "attendance_predictions"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Prediction scope
    prediction_type = Column(String(50), nullable=False)  # "student", "class", "institution"
    target_id = Column(Integer, nullable=True)  # Student ID, Class Session ID, or null
    
    # Prediction details
    predicted_date = Column(DateTime(timezone=True), nullable=False)
    predicted_status = Column(String(50), nullable=True)  # For student predictions
    predicted_attendance_rate = Column(Float, nullable=True)  # For class/institution
    
    # Model information
    model_version = Column(String(50), nullable=False, default="1.0")
    confidence_score = Column(Float, nullable=False)  # 0.0 to 1.0
    
    # Supporting data
    input_features = Column(Text, nullable=True)  # JSON with features used
    prediction_factors = Column(Text, nullable=True)  # JSON with key factors
    
    # Validation tracking
    actual_status = Column(String(50), nullable=True)  # Actual outcome when known
    actual_attendance_rate = Column(Float, nullable=True)
    prediction_accuracy = Column(Float, nullable=True)  # Calculated accuracy score
    
    is_validated = Column(Boolean, default=False)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def set_input_features(self, features: Dict[str, Any]):
        """Set input features as JSON."""
        self.input_features = json.dumps(features)
    
    def get_input_features(self) -> Dict[str, Any]:
        """Get input features from JSON."""
        if self.input_features:
            return json.loads(self.input_features)
        return {}
    
    def set_prediction_factors(self, factors: Dict[str, Any]):
        """Set prediction factors as JSON."""
        self.prediction_factors = json.dumps(factors)
    
    def get_prediction_factors(self) -> Dict[str, Any]:
        """Get prediction factors from JSON."""
        if self.prediction_factors:
            return json.loads(self.prediction_factors)
        return {}
    
    def validate_prediction(self, actual_outcome: Any):
        """Validate prediction against actual outcome."""
        self.is_validated = True
        self.validated_at = datetime.utcnow()
        
        if isinstance(actual_outcome, str):
            self.actual_status = actual_outcome
            # Calculate accuracy for status prediction
            self.prediction_accuracy = 1.0 if self.predicted_status == actual_outcome else 0.0
        elif isinstance(actual_outcome, (int, float)):
            self.actual_attendance_rate = float(actual_outcome)
            # Calculate accuracy for rate prediction
            if self.predicted_attendance_rate:
                error = abs(self.predicted_attendance_rate - actual_outcome)
                # Accuracy decreases with error (1.0 for perfect, 0.0 for >50% error)
                self.prediction_accuracy = max(0.0, 1.0 - (error / 0.5))


# Add relationships to existing models
# These would be added to the existing User and ClassSession models

# In User model:
# pattern_analyses = relationship("AttendancePatternAnalysis", back_populates="student")
# alerts = relationship("AttendanceAlert", foreign_keys=[AttendanceAlert.student_id])

# In ClassSession model:
# attendance_alerts = relationship("AttendanceAlert", back_populates="class_session")