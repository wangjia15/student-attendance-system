"""Extended notification preferences model with parent/guardian support."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from typing import Dict, Any, Optional, List

from app.core.database import Base


class NotificationPreferences(Base):
    """User notification preferences with parent/guardian support."""
    __tablename__ = "notification_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    
    # General preferences
    enabled = Column(Boolean, default=True)
    quiet_hours_start = Column(String(5), nullable=True)  # Format: "22:00"
    quiet_hours_end = Column(String(5), nullable=True)    # Format: "08:00"
    timezone = Column(String(50), default="UTC")
    
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
    
    # Email-specific settings
    email_address = Column(String(255), nullable=True)  # Override email for notifications
    email_digest_enabled = Column(Boolean, default=False)  # Daily digest emails
    email_digest_time = Column(String(5), default="08:00")  # Time for daily digest
    
    # SMS-specific settings
    phone_number = Column(String(20), nullable=True)  # E.164 format phone number
    sms_urgent_only = Column(Boolean, default=True)  # Only urgent notifications via SMS
    
    # Parent/Guardian notification settings
    parent_notifications_enabled = Column(Boolean, default=False)
    parent_email = Column(String(255), nullable=True)
    parent_phone = Column(String(20), nullable=True)
    parent_name = Column(String(255), nullable=True)
    
    # Secondary guardian settings
    secondary_guardian_enabled = Column(Boolean, default=False)
    secondary_guardian_email = Column(String(255), nullable=True)
    secondary_guardian_phone = Column(String(20), nullable=True)
    secondary_guardian_name = Column(String(255), nullable=True)
    
    # Emergency contact settings
    emergency_contact_enabled = Column(Boolean, default=False)
    emergency_contact_email = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_relation = Column(String(100), nullable=True)
    
    # Parent notification preferences by type
    parent_attendance_reminders = Column(Boolean, default=False)
    parent_late_arrival_alerts = Column(Boolean, default=True)
    parent_absent_alerts = Column(Boolean, default=True)
    parent_class_notifications = Column(Boolean, default=False)
    parent_pattern_alerts = Column(Boolean, default=True)
    parent_system_announcements = Column(Boolean, default=False)
    parent_achievement_notifications = Column(Boolean, default=True)
    
    # Parent delivery method preferences
    parent_email_notifications = Column(Boolean, default=True)
    parent_sms_notifications = Column(Boolean, default=False)
    
    # Escalation settings
    escalation_enabled = Column(Boolean, default=False)
    escalation_delay_minutes = Column(Integer, default=30)  # Minutes before escalating to parents
    escalation_triggers = Column(JSON, nullable=True)  # Which events trigger escalation
    
    # Batching preferences
    batch_enabled = Column(Boolean, default=True)
    batch_interval_minutes = Column(Integer, default=30)  # Minutes to wait before sending batch
    max_batch_size = Column(Integer, default=5)           # Maximum notifications per batch
    
    # Advanced preferences
    language_code = Column(String(10), default="en")  # Language for notifications
    frequency_cap_enabled = Column(Boolean, default=True)  # Enable frequency capping
    max_notifications_per_hour = Column(Integer, default=10)
    max_notifications_per_day = Column(Integer, default=50)
    
    # Cost management for SMS
    sms_cost_limit_daily = Column(Float, nullable=True)  # Daily SMS cost limit in USD
    sms_cost_warning_threshold = Column(Float, default=5.0)  # Warning threshold
    
    # Custom notification rules (JSON format)
    custom_rules = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notification_preferences")


class NotificationContact(Base):
    """Additional notification contacts for a user (parents, guardians, emergency contacts)."""
    __tablename__ = "notification_contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Contact information
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone_number = Column(String(20), nullable=True)  # E.164 format
    
    # Contact type and relationship
    contact_type = Column(String(50), nullable=False)  # parent, guardian, emergency, other
    relationship = Column(String(100), nullable=True)  # mother, father, guardian, etc.
    
    # Priority and preferences
    priority_order = Column(Integer, default=1)  # 1 = primary, 2 = secondary, etc.
    is_primary = Column(Boolean, default=False)
    
    # Notification preferences for this contact
    enabled = Column(Boolean, default=True)
    email_notifications = Column(Boolean, default=True)
    sms_notifications = Column(Boolean, default=False)
    
    # Notification type preferences
    attendance_reminders = Column(Boolean, default=False)
    late_arrival_alerts = Column(Boolean, default=True)
    absent_alerts = Column(Boolean, default=True)
    class_notifications = Column(Boolean, default=False)
    pattern_alerts = Column(Boolean, default=True)
    system_announcements = Column(Boolean, default=False)
    achievement_notifications = Column(Boolean, default=True)
    emergency_alerts = Column(Boolean, default=True)
    
    # Time-based preferences
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    timezone = Column(String(50), default="UTC")
    
    # Language preference
    language_code = Column(String(10), default="en")
    
    # Contact verification
    email_verified = Column(Boolean, default=False)
    phone_verified = Column(Boolean, default=False)
    verification_token = Column(String(255), nullable=True)
    
    # Additional metadata
    notes = Column(Text, nullable=True)
    emergency_only = Column(Boolean, default=False)  # Only contact for emergencies
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notification_contacts")


class NotificationFrequencyLog(Base):
    """Log of notification frequency for rate limiting and analytics."""
    __tablename__ = "notification_frequency_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("notification_contacts.id"), nullable=True, index=True)
    
    # Frequency tracking
    hour_key = Column(String(13), nullable=False, index=True)  # Format: YYYY-MM-DD-HH
    day_key = Column(String(10), nullable=False, index=True)   # Format: YYYY-MM-DD
    
    # Counters
    notification_count = Column(Integer, default=0)
    email_count = Column(Integer, default=0)
    sms_count = Column(Integer, default=0)
    push_count = Column(Integer, default=0)
    
    # Cost tracking
    sms_cost_total = Column(Float, default=0.0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    contact = relationship("NotificationContact")


def setup_relationships():
    """Setup reverse relationships with existing models."""
    from app.models.user import User
    
    # User relationships
    User.notification_preferences = relationship("NotificationPreferences", 
                                               back_populates="user", uselist=False)
    User.notification_contacts = relationship("NotificationContact", back_populates="user")


# Utility functions for working with preferences

def get_all_notification_recipients(user_id: int, notification_type: str) -> List[Dict[str, Any]]:
    """
    Get all recipients (user + contacts) who should receive a specific notification type.
    
    Args:
        user_id: ID of the user
        notification_type: Type of notification
        
    Returns:
        List of recipient dictionaries with contact info and preferences
    """
    # This would be implemented as a database query in practice
    # For now, return empty list as placeholder
    return []


def check_quiet_hours(preferences: NotificationPreferences, contact_timezone: str = "UTC") -> bool:
    """
    Check if current time falls within quiet hours for a user/contact.
    
    Args:
        preferences: User's notification preferences
        contact_timezone: Timezone for the contact
        
    Returns:
        True if in quiet hours, False otherwise
    """
    if not preferences.quiet_hours_start or not preferences.quiet_hours_end:
        return False
    
    # Implementation would check current time against quiet hours
    # considering timezone differences
    return False


def check_frequency_limits(user_id: int, contact_id: Optional[int] = None) -> Dict[str, bool]:
    """
    Check if user/contact has exceeded frequency limits.
    
    Args:
        user_id: ID of the user
        contact_id: ID of the contact (optional)
        
    Returns:
        Dictionary with limit status for different time periods
    """
    return {
        "hourly_limit_exceeded": False,
        "daily_limit_exceeded": False,
        "cost_limit_exceeded": False
    }