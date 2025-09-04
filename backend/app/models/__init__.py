from .user import User, UserRole
from .class_session import ClassSession, SessionStatus
from .attendance import AttendanceRecord, AttendanceStatus, AttendanceAuditLog
from .attendance_pattern import (
    AttendancePatternAnalysis, AttendanceAlert, AttendanceInsight, 
    AttendancePrediction, PatternType, AlertSeverity, RiskLevel
)
from .notifications import (
    NotificationPreferences, DeviceToken, Notification, NotificationDelivery,
    NotificationBatch, NotificationType, NotificationStatus, NotificationPriority,
    DevicePlatform, setup_relationships
)

# Setup notification model relationships
setup_relationships()

__all__ = [
    "User",
    "UserRole", 
    "ClassSession",
    "SessionStatus",
    "AttendanceRecord",
    "AttendanceStatus",
    "AttendanceAuditLog",
    "AttendancePatternAnalysis",
    "AttendanceAlert", 
    "AttendanceInsight",
    "AttendancePrediction",
    "PatternType",
    "AlertSeverity",
    "RiskLevel",
    "NotificationPreferences",
    "DeviceToken",
    "Notification",
    "NotificationDelivery",
    "NotificationBatch",
    "NotificationType",
    "NotificationStatus",
    "NotificationPriority",
    "DevicePlatform",
]