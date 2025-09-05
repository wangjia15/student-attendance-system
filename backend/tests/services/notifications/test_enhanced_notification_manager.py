"""Tests for enhanced notification manager."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.services.notifications import (
    EnhancedNotificationManager,
    EnhancedNotificationRequest
)
from app.models.notifications import NotificationType, NotificationPriority
from app.integrations.sms.sms_service import SMSDeliveryResult
from app.integrations.email.email_service import EmailDeliveryResult


@pytest.fixture
def enhanced_request():
    """Create a test enhanced notification request."""
    return EnhancedNotificationRequest(
        user_ids=[1, 2, 3],
        type=NotificationType.ABSENT_ALERT,
        title="Test Alert",
        message="This is a test alert message",
        priority=NotificationPriority.HIGH,
        send_push=True,
        send_email=True,
        send_sms=False,
        include_parents=True,
        sender_id=100
    )


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    mock_db = AsyncMock()
    mock_db.add = Mock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.execute = AsyncMock()
    return mock_db


@pytest.fixture
def mock_notification():
    """Mock notification object."""
    mock_notif = Mock()
    mock_notif.id = 123
    mock_notif.user_id = 1
    mock_notif.type = NotificationType.ABSENT_ALERT
    mock_notif.priority = NotificationPriority.HIGH
    mock_notif.title = "Test Alert"
    mock_notif.message = "Test message"
    mock_notif.status = None
    mock_notif.sent_at = None
    mock_notif.error_message = None
    return mock_notif


@pytest.fixture
def mock_preferences():
    """Mock notification preferences."""
    mock_prefs = Mock()
    mock_prefs.enabled = True
    mock_prefs.absent_alerts = True
    mock_prefs.push_notifications = True
    mock_prefs.email_notifications = True
    mock_prefs.sms_notifications = True
    mock_prefs.email_address = "test@example.com"
    mock_prefs.phone_number = "+1234567890"
    mock_prefs.sms_urgent_only = False
    return mock_prefs


class TestEnhancedNotificationManager:
    """Test cases for EnhancedNotificationManager."""
    
    def test_initialization(self):
        """Test enhanced notification manager initialization."""
        manager = EnhancedNotificationManager()
        
        assert manager.fcm_service is not None
        assert manager.webpush_service is not None
        assert manager.batching_service is not None
        assert manager.sms_service is not None
        assert manager.email_service is not None
        assert manager.bulk_service is not None
        assert manager.delivery_tracking is not None
        assert manager.audit_service is not None
    
    @pytest.mark.asyncio
    async def test_send_notification_small_list(self, enhanced_request, mock_db_session):
        """Test sending notification to small user list (individual processing)."""
        manager = EnhancedNotificationManager()
        
        # Mock audit service
        manager.audit_service = AsyncMock()
        manager.audit_service.log_event = AsyncMock()
        
        # Mock individual sending method
        with patch.object(manager, '_send_individual_notifications') as mock_individual:
            mock_individual.return_value = {
                "success": True,
                "total_sent": 3,
                "total_failed": 0
            }
            
            result = await manager.send_notification(enhanced_request, mock_db_session)
            
            assert result["success"] is True
            assert result["total_sent"] == 3
            mock_individual.assert_called_once_with(enhanced_request, mock_db_session)
    
    @pytest.mark.asyncio
    async def test_send_notification_large_list(self, mock_db_session):
        """Test sending notification to large user list (bulk processing)."""
        # Create request with many users
        large_request = EnhancedNotificationRequest(
            user_ids=list(range(1, 21)),  # 20 users
            type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="System Update",
            message="System will be down for maintenance"
        )
        
        manager = EnhancedNotificationManager()
        
        # Mock audit service
        manager.audit_service = AsyncMock()
        manager.audit_service.log_event = AsyncMock()
        
        # Mock bulk sending method
        with patch.object(manager, '_send_bulk_notification') as mock_bulk:
            mock_bulk.return_value = {
                "success": True,
                "bulk_job_id": "bulk_12345",
                "total_targets": 20,
                "total_sent": 18,
                "total_failed": 2
            }
            
            result = await manager.send_notification(large_request, mock_db_session)
            
            assert result["success"] is True
            assert result["bulk_job_id"] == "bulk_12345"
            assert result["total_targets"] == 20
            mock_bulk.assert_called_once_with(large_request, mock_db_session)
    
    @pytest.mark.asyncio
    async def test_send_to_single_user_all_channels(
        self, enhanced_request, mock_db_session, mock_notification, mock_preferences
    ):
        """Test sending notification to single user with all delivery channels."""
        manager = EnhancedNotificationManager()
        
        # Mock dependencies
        manager.audit_service = AsyncMock()
        manager.audit_service.log_notification_event = AsyncMock()
        
        # Mock getting user preferences
        with patch.object(manager, '_get_user_preferences') as mock_get_prefs:
            mock_get_prefs.return_value = mock_preferences
            
            # Mock creating notification record
            with patch.object(manager, '_create_notification_record') as mock_create_notif:
                mock_create_notif.return_value = mock_notification
                
                # Mock delivery methods
                with patch.object(manager, '_send_push_notification') as mock_push, \
                     patch.object(manager, '_send_email_notification') as mock_email, \
                     patch.object(manager, '_send_sms_notification') as mock_sms, \
                     patch.object(manager, '_send_parent_notifications') as mock_parents:
                    
                    mock_push.return_value = {"success": True, "sent_count": 2}
                    mock_email.return_value = {"success": True}
                    mock_sms.return_value = {"success": False, "error": "No SMS provider"}
                    mock_parents.return_value = {"sent_count": 1, "failed_count": 0}
                    
                    result = await manager._send_to_single_user(1, enhanced_request, mock_db_session)
                    
                    assert result["success"] is True
                    assert result["sent_count"] == 4  # 2 push + 1 email + 1 parent
                    assert result["failed_count"] == 1  # SMS failed
                    assert result["notification_id"] == 123
                    
                    # Verify all delivery methods were called
                    mock_push.assert_called_once()
                    mock_email.assert_called_once()
                    mock_sms.assert_called_once()
                    mock_parents.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_to_single_user_notifications_disabled(
        self, enhanced_request, mock_db_session
    ):
        """Test sending to user with notifications disabled."""
        manager = EnhancedNotificationManager()
        
        # Mock disabled preferences
        disabled_prefs = Mock()
        disabled_prefs.enabled = False
        
        with patch.object(manager, '_get_user_preferences') as mock_get_prefs:
            mock_get_prefs.return_value = disabled_prefs
            
            result = await manager._send_to_single_user(1, enhanced_request, mock_db_session)
            
            assert result["success"] is False
            assert result["reason"] == "Notifications disabled"
    
    @pytest.mark.asyncio
    async def test_send_email_notification_success(
        self, enhanced_request, mock_db_session, mock_notification, mock_preferences
    ):
        """Test successful email notification sending."""
        manager = EnhancedNotificationManager()
        
        # Mock email service
        manager.email_service = AsyncMock()
        manager.email_service.send_email = AsyncMock(return_value=EmailDeliveryResult(
            success=True,
            message_id="email_123",
            to_email="test@example.com"
        ))
        
        result = await manager._send_email_notification(
            user_id=1,
            notification=mock_notification,
            request=enhanced_request,
            preferences=mock_preferences,
            db=mock_db_session
        )
        
        assert result["success"] is True
        assert result["error"] is None
        manager.email_service.send_email.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_email_notification_no_email(
        self, enhanced_request, mock_db_session, mock_notification
    ):
        """Test email notification when no email address configured."""
        manager = EnhancedNotificationManager()
        
        # Mock preferences without email
        prefs_no_email = Mock()
        prefs_no_email.email_address = None
        
        result = await manager._send_email_notification(
            user_id=1,
            notification=mock_notification,
            request=enhanced_request,
            preferences=prefs_no_email,
            db=mock_db_session
        )
        
        assert result["success"] is False
        assert "No email address" in result["error"]
    
    @pytest.mark.asyncio
    async def test_send_sms_notification_success(
        self, enhanced_request, mock_db_session, mock_notification, mock_preferences
    ):
        """Test successful SMS notification sending."""
        manager = EnhancedNotificationManager()
        
        # Mock SMS service
        manager.sms_service = AsyncMock()
        manager.sms_service.send_sms = AsyncMock(return_value=SMSDeliveryResult(
            success=True,
            message_id="sms_123",
            phone_number="+1234567890"
        ))
        
        result = await manager._send_sms_notification(
            user_id=1,
            notification=mock_notification,
            request=enhanced_request,
            preferences=mock_preferences,
            db=mock_db_session
        )
        
        assert result["success"] is True
        assert result["error"] is None
        manager.sms_service.send_sms.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_sms_notification_urgent_only_restriction(
        self, mock_db_session, mock_notification
    ):
        """Test SMS notification with urgent-only restriction."""
        manager = EnhancedNotificationManager()
        
        # Normal priority request
        normal_request = EnhancedNotificationRequest(
            user_ids=[1],
            type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Normal Alert",
            message="This is a normal alert",
            priority=NotificationPriority.NORMAL,
            send_sms=True
        )
        
        # Mock preferences with urgent-only SMS
        urgent_only_prefs = Mock()
        urgent_only_prefs.phone_number = "+1234567890"
        urgent_only_prefs.sms_urgent_only = True
        
        result = await manager._send_sms_notification(
            user_id=1,
            notification=mock_notification,
            request=normal_request,
            preferences=urgent_only_prefs,
            db=mock_db_session
        )
        
        assert result["success"] is False
        assert "SMS limited to urgent notifications" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_send_parent_notifications(
        self, enhanced_request, mock_db_session, mock_notification
    ):
        """Test sending notifications to parents/guardians."""
        manager = EnhancedNotificationManager()
        
        # Mock parent contacts
        mock_contact1 = Mock()
        mock_contact1.email = "parent1@example.com"
        mock_contact1.phone_number = "+1234567891"
        mock_contact1.email_notifications = True
        mock_contact1.sms_notifications = True
        
        mock_contact2 = Mock()
        mock_contact2.email = "parent2@example.com"
        mock_contact2.phone_number = None
        mock_contact2.email_notifications = True
        mock_contact2.sms_notifications = False
        
        # Mock database query result
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [mock_contact1, mock_contact2]
        mock_db_session.execute.return_value = mock_result
        
        # Mock email and SMS services
        manager.email_service = AsyncMock()
        manager.email_service.send_email = AsyncMock(return_value=EmailDeliveryResult(
            success=True,
            message_id="parent_email_123"
        ))
        
        manager.sms_service = AsyncMock()
        manager.sms_service.send_sms = AsyncMock(return_value=SMSDeliveryResult(
            success=True,
            message_id="parent_sms_123",
            phone_number="+1234567891"
        ))
        
        result = await manager._send_parent_notifications(
            user_id=1,
            notification=mock_notification,
            request=enhanced_request,
            db=mock_db_session
        )
        
        assert result["sent_count"] == 3  # 2 emails + 1 SMS
        assert result["failed_count"] == 0
        
        # Verify services were called
        assert manager.email_service.send_email.call_count == 2
        assert manager.sms_service.send_sms.call_count == 1
    
    @pytest.mark.asyncio
    async def test_error_handling_and_audit_logging(self, enhanced_request, mock_db_session):
        """Test error handling and audit logging."""
        manager = EnhancedNotificationManager()
        
        # Mock audit service
        manager.audit_service = AsyncMock()
        manager.audit_service.log_event = AsyncMock()
        
        # Force an exception in individual notifications
        with patch.object(manager, '_send_individual_notifications') as mock_individual:
            mock_individual.side_effect = Exception("Database connection failed")
            
            result = await manager.send_notification(enhanced_request, mock_db_session)
            
            assert result["success"] is False
            assert "Database connection failed" in result["error"]
            assert result["total_sent"] == 0
            assert result["total_failed"] == 3
            
            # Verify error was logged to audit
            manager.audit_service.log_event.assert_called()
    
    def test_is_notification_type_enabled(self):
        """Test notification type preference checking."""
        manager = EnhancedNotificationManager()
        
        # Mock preferences
        prefs = Mock()
        prefs.absent_alerts = True
        prefs.attendance_reminders = False
        
        # Test enabled type
        assert manager._is_notification_type_enabled(
            NotificationType.ABSENT_ALERT, prefs
        ) is True
        
        # Test disabled type
        assert manager._is_notification_type_enabled(
            NotificationType.ATTENDANCE_REMINDER, prefs
        ) is False
    
    def test_service_getters(self):
        """Test service getter methods."""
        manager = EnhancedNotificationManager()
        
        assert manager.get_sms_service() is manager.sms_service
        assert manager.get_email_service() is manager.email_service
        assert manager.get_bulk_service() is manager.bulk_service
        assert manager.get_delivery_tracking() is manager.delivery_tracking
        assert manager.get_audit_service() is manager.audit_service
    
    @pytest.mark.asyncio
    async def test_get_comprehensive_statistics(self, mock_db_session):
        """Test getting comprehensive statistics from all services."""
        manager = EnhancedNotificationManager()
        
        # Mock delivery tracking service
        manager.delivery_tracking = AsyncMock()
        manager.delivery_tracking.get_delivery_statistics = AsyncMock(return_value={
            "status_counts": {"sent": 100, "delivered": 95, "failed": 5}
        })
        
        # Mock service availability
        manager.sms_service.is_available = Mock(return_value=True)
        manager.email_service.is_available = Mock(return_value=True)
        manager.fcm_service.is_available = Mock(return_value=True)
        manager.webpush_service.is_available = Mock(return_value=False)
        
        manager.sms_service.get_provider_status = Mock(return_value={"twilio": {"available": True}})
        manager.email_service.get_provider_status = Mock(return_value={"smtp": {"available": True}})
        
        stats = await manager.get_comprehensive_statistics(mock_db_session)
        
        assert stats["service_status"]["sms_available"] is True
        assert stats["service_status"]["email_available"] is True
        assert stats["service_status"]["fcm_available"] is True
        assert stats["service_status"]["webpush_available"] is False
        assert stats["audit_available"] is True
        assert stats["bulk_operations_supported"] is True
        
        # Verify delivery tracking was called
        manager.delivery_tracking.get_delivery_statistics.assert_called_once_with(mock_db_session)


class TestEnhancedNotificationRequest:
    """Test cases for EnhancedNotificationRequest data class."""
    
    def test_enhanced_request_creation_full(self):
        """Test enhanced notification request creation with all fields."""
        template_data = {"student_name": "John Doe", "class_name": "Math 101"}
        actions = [{"action": "view", "title": "View Details"}]
        
        request = EnhancedNotificationRequest(
            user_ids=[1, 2, 3, 4, 5],
            type=NotificationType.LATE_ARRIVAL,
            title="Late Arrival Alert",
            message="Student arrived late to class",
            priority=NotificationPriority.HIGH,
            html_content="<h1>Late Arrival Alert</h1>",
            text_content="Student arrived late to class",
            template_id="late_arrival_template",
            template_data=template_data,
            data={"attendance_id": 123},
            actions=actions,
            image_url="https://example.com/alert.png",
            icon_url="https://example.com/icon.png",
            click_action="https://example.com/attendance/123",
            send_push=True,
            send_email=True,
            send_sms=True,
            include_parents=True,
            scheduled_at=datetime.now(),
            expires_at=datetime.now(),
            class_session_id=456,
            attendance_record_id=789,
            sender_id=100,
            source_ip="192.168.1.1",
            user_agent="Mozilla/5.0",
            session_id="session_123",
            request_id="req_456"
        )
        
        assert request.user_ids == [1, 2, 3, 4, 5]
        assert request.type == NotificationType.LATE_ARRIVAL
        assert request.title == "Late Arrival Alert"
        assert request.message == "Student arrived late to class"
        assert request.priority == NotificationPriority.HIGH
        assert request.html_content == "<h1>Late Arrival Alert</h1>"
        assert request.template_id == "late_arrival_template"
        assert request.template_data == template_data
        assert request.data == {"attendance_id": 123}
        assert request.actions == actions
        assert request.send_push is True
        assert request.send_email is True
        assert request.send_sms is True
        assert request.include_parents is True
        assert request.class_session_id == 456
        assert request.sender_id == 100
        assert request.source_ip == "192.168.1.1"
    
    def test_enhanced_request_minimal(self):
        """Test enhanced notification request creation with minimal fields."""
        request = EnhancedNotificationRequest(
            user_ids=[1],
            type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="System Update",
            message="System will be updated tonight"
        )
        
        assert request.user_ids == [1]
        assert request.type == NotificationType.SYSTEM_ANNOUNCEMENT
        assert request.title == "System Update"
        assert request.message == "System will be updated tonight"
        assert request.priority == NotificationPriority.NORMAL
        assert request.send_push is True
        assert request.send_email is False
        assert request.send_sms is False
        assert request.include_parents is False
        assert request.template_data is None
        assert request.sender_id is None