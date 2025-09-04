from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from typing import Dict, Any, Optional

from app.core.database import Base


class NotificationType(str, enum.Enum):
    """Types of notifications that can be sent."""
    ATTENDANCE_REMINDER = "attendance_reminder"
    LATE_ARRIVAL = "late_arrival"
    ABSENT_ALERT = "absent_alert"
    CLASS_STARTED = "class_started"
    CLASS_ENDED = "class_ended"
    PATTERN_ALERT = "pattern_alert"
    SYSTEM_ANNOUNCEMENT = "system_announcement"
    ACHIEVEMENT_BADGE = "achievement_badge"


class NotificationStatus(str, enum.Enum):
    """Status of notification delivery."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    EXPIRED = "expired"


class NotificationPriority(str, enum.Enum):
    """Priority levels for notifications."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DevicePlatform(str, enum.Enum):
    """Supported device platforms."""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class NotificationPreferences(Base):
    """User notification preferences and settings."""
    __tablename__ = "notification_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    
    # General preferences
    enabled = Column(Boolean, default=True)
    quiet_hours_start = Column(String(5), nullable=True)  # Format: "22:00"
    quiet_hours_end = Column(String(5), nullable=True)    # Format: "08:00"
    
    # Notification type preferences
    attendance_reminders = Column(Boolean, default=True)
    late_arrival_alerts = Column(Boolean, default=True)
    absent_alerts = Column(Boolean, default=True)
    class_notifications = Column(Boolean, default=True)
    pattern_alerts = Column(Boolean, default=True)
    system_announcements = Column(Boolean, default=True)
    achievement_notifications = Column(Boolean, default=True)
    
    # Delivery method preferences
    push_notifications = Column(Boolean, default=True)
    email_notifications = Column(Boolean, default=False)
    sms_notifications = Column(Boolean, default=False)
    
    # Batching preferences
    batch_enabled = Column(Boolean, default=True)
    batch_interval_minutes = Column(Integer, default=30)  # Minutes to wait before sending batch
    max_batch_size = Column(Integer, default=5)           # Maximum notifications per batch
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notification_preferences")


class DeviceToken(Base):
    """Device tokens for push notifications."""
    __tablename__ = "device_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Device information
    platform = Column(SQLEnum(DevicePlatform), nullable=False)
    token = Column(Text, nullable=False, unique=True)
    device_id = Column(String(255), nullable=True)  # Unique device identifier
    device_name = Column(String(255), nullable=True)  # User-friendly device name
    
    # Token metadata
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    app_version = Column(String(50), nullable=True)
    os_version = Column(String(50), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="device_tokens")


class Notification(Base):
    """Individual notification records."""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Target user
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Notification metadata
    type = Column(SQLEnum(NotificationType), nullable=False, index=True)
    priority = Column(SQLEnum(NotificationPriority), default=NotificationPriority.NORMAL)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING, index=True)
    
    # Content
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)  # Additional structured data
    
    # Rich notification features
    actions = Column(JSON, nullable=True)  # Action buttons for rich notifications
    image_url = Column(String(500), nullable=True)
    icon_url = Column(String(500), nullable=True)
    click_action = Column(String(500), nullable=True)  # URL or action to perform on click
    
    # Scheduling
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Batching
    batch_id = Column(String(100), nullable=True, index=True)
    is_batched = Column(Boolean, default=False)
    
    # Related entities (optional foreign keys for context)
    class_session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=True)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id"), nullable=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notifications")
    class_session = relationship("ClassSession", back_populates="notifications")
    attendance_record = relationship("AttendanceRecord", back_populates="notifications")


class NotificationDelivery(Base):
    """Tracking notification delivery attempts across platforms."""
    __tablename__ = "notification_deliveries"
    
    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=False, index=True)
    device_token_id = Column(Integer, ForeignKey("device_tokens.id"), nullable=False, index=True)
    
    # Delivery information
    platform = Column(SQLEnum(DevicePlatform), nullable=False)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING)
    
    # Platform-specific data
    platform_message_id = Column(String(255), nullable=True)  # FCM message ID, etc.
    platform_response = Column(JSON, nullable=True)  # Full platform response
    
    # Timing
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Error tracking
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    notification = relationship("Notification", back_populates="deliveries")
    device_token = relationship("DeviceToken", back_populates="deliveries")


class NotificationBatch(Base):
    """Batched notification groups to prevent spam."""
    __tablename__ = "notification_batches"
    
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(100), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Batch metadata
    notification_count = Column(Integer, default=0)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING)
    
    # Content summary
    title = Column(String(255), nullable=False)  # Combined title for batch
    message = Column(Text, nullable=False)       # Summary message
    
    # Scheduling
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notification_batches")


# Add relationships to existing models
def setup_relationships():
    """Setup reverse relationships with existing models."""
    from app.models.user import User
    from app.models.class_session import ClassSession
    from app.models.attendance import AttendanceRecord
    
    # User relationships
    User.notification_preferences = relationship("NotificationPreferences", 
                                               back_populates="user", uselist=False)
    User.device_tokens = relationship("DeviceToken", back_populates="user")
    User.notifications = relationship("Notification", back_populates="user")
    User.notification_batches = relationship("NotificationBatch", back_populates="user")
    
    # ClassSession relationships (if exists)
    try:
        ClassSession.notifications = relationship("Notification", back_populates="class_session")
    except (AttributeError, ImportError):
        pass
    
    # AttendanceRecord relationships (if exists)
    try:
        AttendanceRecord.notifications = relationship("Notification", back_populates="attendance_record")
    except (AttributeError, ImportError):
        pass
    
    # DeviceToken relationships
    DeviceToken.deliveries = relationship("NotificationDelivery", back_populates="device_token")
    
    # Notification relationships
    Notification.deliveries = relationship("NotificationDelivery", back_populates="notification")