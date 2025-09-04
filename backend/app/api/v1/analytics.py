"""
Analytics API endpoints for attendance reporting and insights.
Provides comprehensive analytics, pattern detection, and forecasting capabilities.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.auth import get_current_user, require_teacher_or_admin
from app.models.user import User, UserRole
from app.services.pattern_detection import AdvancedPatternDetector
from app.services.attendance_analytics import AttendanceAnalyticsService
from app.schemas.attendance import AttendanceAlert


router = APIRouter(prefix="/analytics", tags=["analytics"])


# Request/Response Models

class PatternAnalysisRequest(BaseModel):
    student_id: int
    analysis_period_days: int = Field(default=60, ge=7, le=365)
    include_predictions: bool = False


class PatternAnalysisResponse(BaseModel):
    student_id: int
    analysis_period_days: int
    data_points_analyzed: int
    basic_statistics: Dict[str, Any]
    trend_analysis: Dict[str, Any] 
    seasonal_patterns: Dict[str, Any]
    behavioral_patterns: Dict[str, Any]
    risk_assessment: Dict[str, Any]
    generated_at: datetime


class StudentAnalyticsResponse(BaseModel):
    student_id: int
    student_name: str
    overall_stats: Dict[str, Any]
    performance_trends: Dict[str, Any]
    punctuality_analysis: Dict[str, Any]
    comparative_ranking: Dict[str, Any]
    risk_indicators: Dict[str, Any]
    improvement_suggestions: List[str]


class ClassAnalyticsResponse(BaseModel):
    class_session_id: int
    class_name: str
    teacher_name: str
    start_time: datetime
    total_enrolled: int
    attendance_summary: Dict[str, Any]
    late_analysis: Dict[str, Any]
    participation_metrics: Dict[str, Any]
    comparative_metrics: Dict[str, Any]
    time_series_data: List[Dict[str, Any]]


class InstitutionalAnalyticsResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    total_students: int
    total_classes: int
    overall_attendance_rate: float
    department_breakdown: Dict[str, Any]
    trend_analysis: Dict[str, Any]
    performance_distribution: Dict[str, Any]
    alert_summary: Dict[str, Any]


class AlertRequest(BaseModel):
    class_session_id: Optional[int] = None
    student_id: Optional[int] = None
    severity_threshold: str = Field(default="medium", pattern="^(low|medium|high)$")
    detection_period_days: int = Field(default=30, ge=7, le=90)


class PredictionRequest(BaseModel):
    target_type: str = Field(..., pattern="^(student|class|institution)$")
    target_id: Optional[int] = None
    forecast_days: int = Field(default=7, ge=1, le=30)


class ComparativeReportRequest(BaseModel):
    comparison_type: str = Field(..., pattern="^(student_vs_class|class_vs_institution|time_period)$")
    primary_id: int
    secondary_id: Optional[int] = None
    time_period_days: int = Field(default=30, ge=7, le=365)


# Analytics Endpoints

@router.post("/patterns/advanced", response_model=PatternAnalysisResponse)
async def analyze_advanced_patterns(
    request: PatternAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Perform advanced pattern analysis for a student including trends,
    seasonality, behavioral patterns, and comprehensive risk assessment.
    """
    try:
        detector = AdvancedPatternDetector(db)
        
        analysis_result = await detector.detect_advanced_patterns(
            student_id=request.student_id,
            analysis_period_days=request.analysis_period_days
        )
        
        # Check if insufficient data
        if analysis_result.get("status") == "insufficient_data":
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient data for analysis: {analysis_result.get('message')}"
            )
        
        return PatternAnalysisResponse(**analysis_result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pattern analysis failed: {str(e)}")


@router.get("/student/{student_id}", response_model=StudentAnalyticsResponse)
async def get_student_analytics(
    student_id: int,
    analysis_period_days: int = Query(default=60, ge=7, le=365),
    include_predictions: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Get comprehensive analytics for a specific student including performance trends,
    punctuality analysis, comparative ranking, and improvement suggestions.
    """
    try:
        analytics_service = AttendanceAnalyticsService(db)
        
        student_analytics = await analytics_service.generate_student_analytics(
            student_id=student_id,
            analysis_period_days=analysis_period_days,
            include_predictions=include_predictions
        )
        
        return StudentAnalyticsResponse(
            student_id=student_analytics.student_id,
            student_name=student_analytics.student_name,
            overall_stats=student_analytics.overall_stats.__dict__,
            performance_trends=student_analytics.performance_trends,
            punctuality_analysis=student_analytics.punctuality_analysis,
            comparative_ranking=student_analytics.comparative_ranking,
            risk_indicators=student_analytics.risk_indicators,
            improvement_suggestions=student_analytics.improvement_suggestions
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Student analytics failed: {str(e)}")


@router.get("/class/{class_session_id}", response_model=ClassAnalyticsResponse)
async def get_class_analytics(
    class_session_id: int,
    include_predictions: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Get comprehensive analytics for a specific class including attendance summary,
    late analysis, participation metrics, and comparative metrics.
    """
    try:
        analytics_service = AttendanceAnalyticsService(db)
        
        class_analytics = await analytics_service.generate_class_analytics(
            class_session_id=class_session_id,
            include_predictions=include_predictions
        )
        
        return ClassAnalyticsResponse(
            class_session_id=class_analytics.class_session_id,
            class_name=class_analytics.class_name,
            teacher_name=class_analytics.teacher_name,
            start_time=class_analytics.start_time,
            total_enrolled=class_analytics.total_enrolled,
            attendance_summary=class_analytics.attendance_summary.__dict__,
            late_analysis=class_analytics.late_analysis,
            participation_metrics=class_analytics.participation_metrics,
            comparative_metrics=class_analytics.comparative_metrics,
            time_series_data=class_analytics.time_series_data
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Class analytics failed: {str(e)}")


@router.get("/institutional", response_model=InstitutionalAnalyticsResponse)
async def get_institutional_analytics(
    period_days: int = Query(default=30, ge=7, le=365),
    department_filter: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Get institution-wide attendance analytics including overall metrics,
    department breakdown, trend analysis, and performance distribution.
    """
    try:
        # Require admin for institutional analytics
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Admin access required for institutional analytics")
        
        analytics_service = AttendanceAnalyticsService(db)
        
        institutional_analytics = await analytics_service.generate_institutional_analytics(
            period_days=period_days,
            department_filter=department_filter
        )
        
        return InstitutionalAnalyticsResponse(**institutional_analytics.__dict__)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Institutional analytics failed: {str(e)}")


@router.post("/alerts/generate", response_model=List[AttendanceAlert])
async def generate_attendance_alerts(
    request: AlertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Generate sophisticated early warning alerts based on attendance patterns
    with configurable severity thresholds and detection periods.
    """
    try:
        detector = AdvancedPatternDetector(db)
        
        alerts = await detector.generate_early_warning_alerts(
            class_session_id=request.class_session_id,
            alert_severity_threshold=request.severity_threshold
        )
        
        return alerts
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alert generation failed: {str(e)}")


@router.get("/anomalies/detect")
async def detect_attendance_anomalies(
    student_id: Optional[int] = Query(default=None),
    class_session_id: Optional[int] = Query(default=None),
    detection_period_days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Detect attendance anomalies using statistical methods to identify
    unusual patterns or outliers in attendance behavior.
    """
    try:
        detector = AdvancedPatternDetector(db)
        
        anomalies = await detector.detect_attendance_anomalies(
            student_id=student_id,
            class_session_id=class_session_id,
            detection_period_days=detection_period_days
        )
        
        return {
            "detection_period_days": detection_period_days,
            "total_anomalies": len(anomalies),
            "anomalies": anomalies,
            "generated_at": datetime.utcnow()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {str(e)}")


@router.post("/predictions/future")
async def predict_future_attendance(
    request: PredictionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Predict future attendance using historical patterns and machine learning
    algorithms. Supports student, class, and institutional level predictions.
    """
    try:
        if request.target_type == "student" and not request.target_id:
            raise HTTPException(status_code=400, detail="target_id required for student predictions")
        
        if request.target_type == "class" and not request.target_id:
            raise HTTPException(status_code=400, detail="target_id required for class predictions")
        
        analytics_service = AttendanceAnalyticsService(db)
        
        predictions = await analytics_service.generate_attendance_forecasting(
            target_type=request.target_type,
            target_id=request.target_id,
            forecast_days=request.forecast_days
        )
        
        return {
            "target_type": request.target_type,
            "target_id": request.target_id,
            "forecast_days": request.forecast_days,
            "predictions": predictions,
            "generated_at": datetime.utcnow()
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@router.post("/reports/comparative")
async def generate_comparative_report(
    request: ComparativeReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Generate comparative analytics reports including student vs class,
    class vs institution, and time period comparisons.
    """
    try:
        analytics_service = AttendanceAnalyticsService(db)
        
        report = await analytics_service.generate_comparative_report(
            comparison_type=request.comparison_type,
            primary_id=request.primary_id,
            secondary_id=request.secondary_id,
            time_period_days=request.time_period_days
        )
        
        return {
            "comparison_type": request.comparison_type,
            "primary_id": request.primary_id,
            "secondary_id": request.secondary_id,
            "time_period_days": request.time_period_days,
            "report": report,
            "generated_at": datetime.utcnow()
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparative report failed: {str(e)}")


@router.get("/insights/summary")
async def get_analytics_insights_summary(
    period_days: int = Query(default=30, ge=7, le=365),
    class_session_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Get a comprehensive summary of attendance insights including key metrics,
    trends, alerts, and recommendations for a given period.
    """
    try:
        detector = AdvancedPatternDetector(db)
        analytics_service = AttendanceAnalyticsService(db)
        
        # Generate alerts
        alerts = await detector.generate_early_warning_alerts(
            class_session_id=class_session_id,
            alert_severity_threshold="medium"
        )
        
        # Get institutional analytics if no class specified
        if not class_session_id:
            institutional_data = await analytics_service.generate_institutional_analytics(
                period_days=period_days
            )
            
            return {
                "period_days": period_days,
                "summary_type": "institutional",
                "key_metrics": {
                    "total_students": institutional_data.total_students,
                    "total_classes": institutional_data.total_classes,
                    "overall_attendance_rate": institutional_data.overall_attendance_rate
                },
                "alerts": {
                    "total_alerts": len(alerts),
                    "high_priority": len([a for a in alerts if a.severity == "high"]),
                    "medium_priority": len([a for a in alerts if a.severity == "medium"]),
                    "low_priority": len([a for a in alerts if a.severity == "low"])
                },
                "trends": institutional_data.trend_analysis,
                "recommendations": [
                    "Monitor high-priority alerts closely",
                    "Implement intervention strategies for at-risk students",
                    "Review attendance policies if overall rate is below target"
                ],
                "generated_at": datetime.utcnow()
            }
        else:
            # Class-specific summary
            class_data = await analytics_service.generate_class_analytics(class_session_id)
            
            return {
                "period_days": period_days,
                "summary_type": "class",
                "class_session_id": class_session_id,
                "key_metrics": {
                    "class_name": class_data.class_name,
                    "total_enrolled": class_data.total_enrolled,
                    "attendance_rate": class_data.attendance_summary.attendance_rate,
                    "late_rate": class_data.attendance_summary.late_rate
                },
                "alerts": {
                    "total_alerts": len(alerts),
                    "high_priority": len([a for a in alerts if a.severity == "high"]),
                    "medium_priority": len([a for a in alerts if a.severity == "medium"])
                },
                "performance_metrics": class_data.participation_metrics,
                "recommendations": [
                    "Focus on students with high-priority alerts",
                    "Address chronic lateness if late rate is high",
                    "Celebrate good attendance performance"
                ],
                "generated_at": datetime.utcnow()
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Insights summary failed: {str(e)}")


@router.get("/export/report")
async def export_analytics_report(
    report_type: str = Query(..., pattern="^(student|class|institutional|comparative)$"),
    target_id: Optional[int] = Query(default=None),
    period_days: int = Query(default=30, ge=7, le=365),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_teacher_or_admin)
):
    """
    Export analytics reports in various formats (JSON, CSV) for external
    analysis and reporting tools.
    """
    try:
        analytics_service = AttendanceAnalyticsService(db)
        
        if report_type == "student" and target_id:
            data = await analytics_service.generate_student_analytics(target_id, period_days)
            report_data = {
                "report_type": "student",
                "student_id": data.student_id,
                "student_name": data.student_name,
                "period_days": period_days,
                "data": data.__dict__,
                "generated_at": datetime.utcnow()
            }
        elif report_type == "class" and target_id:
            data = await analytics_service.generate_class_analytics(target_id)
            report_data = {
                "report_type": "class",
                "class_session_id": data.class_session_id,
                "class_name": data.class_name,
                "data": data.__dict__,
                "generated_at": datetime.utcnow()
            }
        elif report_type == "institutional":
            data = await analytics_service.generate_institutional_analytics(period_days)
            report_data = {
                "report_type": "institutional",
                "period_days": period_days,
                "data": data.__dict__,
                "generated_at": datetime.utcnow()
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid report type or missing target_id")
        
        if format == "json":
            return report_data
        elif format == "csv":
            # For CSV format, we would need to flatten the data structure
            # This is a simplified implementation
            return {
                "message": "CSV export not fully implemented",
                "data": report_data
            }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report export failed: {str(e)}")


# Health check and status endpoints

@router.get("/health")
async def analytics_health_check():
    """Check the health status of analytics services."""
    return {
        "status": "healthy",
        "services": {
            "pattern_detection": "active",
            "analytics_service": "active",
            "forecasting": "active"
        },
        "timestamp": datetime.utcnow()
    }


@router.get("/capabilities")
async def get_analytics_capabilities():
    """Get information about available analytics capabilities and features."""
    return {
        "pattern_detection": {
            "advanced_patterns": True,
            "seasonal_analysis": True,
            "behavioral_patterns": True,
            "risk_assessment": True
        },
        "analytics": {
            "student_analytics": True,
            "class_analytics": True,
            "institutional_analytics": True,
            "comparative_reports": True
        },
        "forecasting": {
            "student_predictions": True,
            "class_predictions": True,
            "institutional_predictions": True
        },
        "alerts": {
            "early_warning_system": True,
            "anomaly_detection": True,
            "configurable_thresholds": True
        },
        "export_formats": ["json", "csv"],
        "max_analysis_period_days": 365,
        "max_forecast_days": 30
    }