"""Tests for bulk notification service."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.services.notifications.bulk_notification_service import (
    BulkNotificationService,
    BulkNotificationRequest,
    BulkNotificationTarget,
    BulkNotificationPriority,
    BulkNotificationStatus,
    BulkNotificationResult
)
from app.models.notifications import NotificationType, NotificationPriority


@pytest.fixture
def bulk_targets():
    """Create test bulk notification targets."""
    return [
        BulkNotificationTarget(
            user_id=1,
            email="user1@example.com",
            phone_number="+1234567890",
            custom_data={"name": "User 1"}
        ),
        BulkNotificationTarget(
            user_id=2,
            email="user2@example.com",
            custom_data={"name": "User 2"}
        ),
        BulkNotificationTarget(
            user_id=3,
            phone_number="+1234567891",
            custom_data={"name": "User 3"}
        )
    ]


@pytest.fixture
def bulk_request(bulk_targets):
    """Create test bulk notification request."""
    return BulkNotificationRequest(
        targets=bulk_targets,
        notification_type=NotificationType.ABSENT_ALERT,
        title="Bulk Absence Alert",
        message="Multiple students are absent today",
        priority=BulkNotificationPriority.HIGH,
        send_email=True,
        send_sms=True,
        send_push=True,
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
    return mock_prefs


class TestBulkNotificationService:
    """Test cases for BulkNotificationService."""
    
    def test_initialization(self):
        """Test bulk notification service initialization."""
        service = BulkNotificationService()
        
        assert service.sms_service is not None
        assert service.email_service is not None
        assert service.global_rate_limit_per_second == 50
        assert service.global_rate_limit_per_minute == 1000
        assert service._active_jobs == {}
    
    @pytest.mark.asyncio
    async def test_send_bulk_notification_success(self, bulk_request, mock_db_session):
        """Test successful bulk notification sending."""
        service = BulkNotificationService()
        
        # Mock dependencies
        with patch.object(service, '_process_batch') as mock_process_batch:
            mock_process_batch.return_value = [
                {"success": True, "sent_count": 2, "failed_count": 0},
                {"success": True, "sent_count": 1, "failed_count": 1},
                {"success": False, "skipped": True, "reason": "User disabled"}
            ]
            
            with patch.object(service, '_check_global_rate_limit') as mock_rate_limit:
                mock_rate_limit.return_value = True
                
                result = await service.send_bulk_notification(bulk_request, mock_db_session)
                
                assert isinstance(result, BulkNotificationResult)
                assert result.status == BulkNotificationStatus.COMPLETED
                assert result.total_targets == 3
                assert result.successful_sends == 2
                assert result.failed_sends == 1
                assert result.skipped_sends == 1
                assert result.processing_time > 0
                
                # Verify job was tracked
                assert result.job_id in service._active_jobs
                assert service._active_jobs[result.job_id]['status'] == BulkNotificationStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_send_bulk_notification_empty_targets(self, mock_db_session):
        """Test bulk notification with empty target list."""
        empty_request = BulkNotificationRequest(
            targets=[],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Empty Test",
            message="This should not send to anyone"
        )
        
        service = BulkNotificationService()
        result = await service.send_bulk_notification(empty_request, mock_db_session)
        
        assert result.status == BulkNotificationStatus.COMPLETED
        assert result.total_targets == 0
        assert result.successful_sends == 0
        assert result.failed_sends == 0
    
    @pytest.mark.asyncio
    async def test_send_bulk_notification_error(self, bulk_request, mock_db_session):
        """Test bulk notification with processing error."""
        service = BulkNotificationService()
        
        # Force an exception in batch processing
        with patch.object(service, '_process_batch') as mock_process_batch:
            mock_process_batch.side_effect = Exception("Database connection failed")
            
            result = await service.send_bulk_notification(bulk_request, mock_db_session)
            
            assert result.status == BulkNotificationStatus.FAILED
            assert result.successful_sends == 0
            assert result.failed_sends == 3
            assert len(result.errors) == 1
            assert "Database connection failed" in result.errors[0]["error"]
    
    @pytest.mark.asyncio
    async def test_process_single_target_all_channels_success(self, mock_db_session):
        """Test processing single target with all delivery channels successful."""
        service = BulkNotificationService()
        
        target = BulkNotificationTarget(
            user_id=1,
            email="test@example.com",
            phone_number="+1234567890"
        )
        
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.ABSENT_ALERT,
            title="Test Alert",
            message="Test message",
            send_push=True,
            send_email=True,
            send_sms=True,
            include_parents=True
        )
        
        # Mock dependencies
        with patch.object(service, '_get_user_preferences') as mock_get_prefs, \
             patch.object(service, '_check_frequency_limits') as mock_freq_check, \
             patch.object(service, '_is_in_quiet_hours') as mock_quiet_hours, \
             patch.object(service, '_create_notification_record') as mock_create_notif, \
             patch.object(service, '_send_email_notification') as mock_send_email, \
             patch.object(service, '_send_sms_notification') as mock_send_sms, \
             patch.object(service, '_send_parent_notifications') as mock_send_parents, \
             patch.object(service, '_update_frequency_tracking') as mock_update_freq:
            
            mock_get_prefs.return_value = mock_preferences
            mock_freq_check.return_value = {"exceeded": False}
            mock_quiet_hours.return_value = False
            
            mock_notif = Mock()
            mock_notif.id = 123
            mock_create_notif.return_value = mock_notif
            
            mock_send_email.return_value = {"success": True}
            mock_send_sms.return_value = {"success": True}
            mock_send_parents.return_value = {"sent_count": 2, "failed_count": 0}
            
            result = await service._process_single_target(target, request, "test_job", mock_db_session)
            
            assert result["success"] is True
            assert result["sent_count"] == 4  # push + email + sms + 2 parents
            assert result["failed_count"] == 0
            
            # Verify all methods were called
            mock_send_email.assert_called_once()
            mock_send_sms.assert_called_once()
            mock_send_parents.assert_called_once()
            mock_update_freq.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_single_target_user_disabled(self, mock_db_session):
        """Test processing target with disabled notifications."""
        service = BulkNotificationService()
        
        target = BulkNotificationTarget(user_id=1)
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Test",
            message="Test"
        )
        
        # Mock disabled preferences
        disabled_prefs = Mock()
        disabled_prefs.enabled = False
        
        with patch.object(service, '_get_user_preferences') as mock_get_prefs:
            mock_get_prefs.return_value = disabled_prefs
            
            result = await service._process_single_target(target, request, "test_job", mock_db_session)
            
            assert result["success"] is False
            assert result["skipped"] is True
            assert result["reason"] == "Notifications disabled for user"
    
    @pytest.mark.asyncio
    async def test_process_single_target_frequency_limit_exceeded(self, mock_db_session, mock_preferences):
        """Test processing target with frequency limit exceeded."""
        service = BulkNotificationService()
        
        target = BulkNotificationTarget(user_id=1)
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Test",
            message="Test"
        )
        
        with patch.object(service, '_get_user_preferences') as mock_get_prefs, \
             patch.object(service, '_check_frequency_limits') as mock_freq_check:
            
            mock_get_prefs.return_value = mock_preferences
            mock_freq_check.return_value = {"exceeded": True}
            
            result = await service._process_single_target(target, request, "test_job", mock_db_session)
            
            assert result["success"] is False
            assert result["skipped"] is True
            assert result["reason"] == "Frequency limit exceeded"
    
    @pytest.mark.asyncio
    async def test_process_single_target_quiet_hours(self, mock_db_session, mock_preferences):
        """Test processing target during quiet hours."""
        service = BulkNotificationService()
        
        target = BulkNotificationTarget(user_id=1)
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Test",
            message="Test",
            respect_quiet_hours=True
        )
        
        with patch.object(service, '_get_user_preferences') as mock_get_prefs, \
             patch.object(service, '_check_frequency_limits') as mock_freq_check, \
             patch.object(service, '_is_in_quiet_hours') as mock_quiet_hours:
            
            mock_get_prefs.return_value = mock_preferences
            mock_freq_check.return_value = {"exceeded": False}
            mock_quiet_hours.return_value = True
            
            result = await service._process_single_target(target, request, "test_job", mock_db_session)
            
            assert result["success"] is False
            assert result["skipped"] is True
            assert result["reason"] == "In quiet hours"
    
    @pytest.mark.asyncio
    async def test_send_email_notification_success(self, mock_db_session):
        """Test successful email notification in bulk service."""
        service = BulkNotificationService()
        
        # Mock email service
        service.email_service = AsyncMock()
        service.email_service.send_email = AsyncMock()
        service.email_service.send_email.return_value.success = True
        
        target = BulkNotificationTarget(user_id=1, email="test@example.com")
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Test Email",
            message="Test message"
        )
        
        result = await service._send_email_notification(target, request, 123, mock_db_session)
        
        assert result["success"] is True
        service.email_service.send_email.assert_called_once()
        
        # Verify email was sent with correct parameters
        call_args = service.email_service.send_email.call_args
        assert call_args[1]["to_email"] == "test@example.com"
        assert call_args[1]["subject"] == "Test Email"
    
    @pytest.mark.asyncio
    async def test_send_sms_notification_success(self, mock_db_session):
        """Test successful SMS notification in bulk service."""
        service = BulkNotificationService()
        
        # Mock SMS service
        service.sms_service = AsyncMock()
        service.sms_service.send_sms = AsyncMock()
        service.sms_service.send_sms.return_value.success = True
        
        target = BulkNotificationTarget(user_id=1, phone_number="+1234567890")
        request = BulkNotificationRequest(
            targets=[target],
            notification_type=NotificationType.SYSTEM_ANNOUNCEMENT,
            title="Test SMS",
            message="Test message"
        )
        
        result = await service._send_sms_notification(target, request, 123, mock_db_session)
        
        assert result["success"] is True
        service.sms_service.send_sms.assert_called_once()
        
        # Verify SMS was sent with correct parameters
        call_args = service.sms_service.send_sms.call_args
        assert call_args[1]["phone_number"] == "+1234567890"
        assert call_args[1]["message"] == "Test message"
    
    @pytest.mark.asyncio
    async def test_check_global_rate_limit(self):
        """Test global rate limiting functionality."""
        service = BulkNotificationService()
        
        # Clear any existing requests
        service._rate_limit_tracker = {
            'requests_this_second': [],
            'requests_this_minute': []
        }
        
        # Should be under limit initially
        assert await service._check_global_rate_limit() is True
        
        # Fill up the per-second limit
        current_time = datetime.now()
        service._rate_limit_tracker['requests_this_second'] = [current_time] * 50
        
        # Should now be over limit
        assert await service._check_global_rate_limit() is False
    
    @pytest.mark.asyncio
    async def test_frequency_limits_checking(self, mock_db_session):
        """Test frequency limit checking functionality."""
        service = BulkNotificationService()
        
        # Mock database results for frequency logs
        mock_log = Mock()
        mock_log.hour_key = "2024-01-01-12"
        mock_log.day_key = "2024-01-01"
        mock_log.notification_count = 5
        
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [mock_log, mock_log]  # Two logs
        mock_db_session.execute.return_value = mock_result
        
        result = await service._check_frequency_limits(1, mock_db_session)
        
        assert "exceeded" in result
        assert "hour_count" in result
        assert "day_count" in result
        assert result["hour_count"] == 5  # From matching hour key
        assert result["day_count"] == 10  # From both logs (5 + 5)
    
    @pytest.mark.asyncio
    async def test_update_frequency_tracking(self, mock_db_session):
        """Test frequency tracking update functionality."""
        service = BulkNotificationService()
        
        # Mock existing frequency log
        existing_log = Mock()
        existing_log.notification_count = 3
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = existing_log
        mock_db_session.execute.return_value = mock_result
        
        await service._update_frequency_tracking(1, mock_db_session)
        
        # Verify log was updated
        assert existing_log.notification_count == 4
        mock_db_session.flush.assert_called_once()
    
    def test_job_status_tracking(self, bulk_request, mock_db_session):
        """Test job status tracking functionality."""
        service = BulkNotificationService()
        
        # Create a job ID
        job_id = "test_job_123"
        service._active_jobs[job_id] = {
            'status': BulkNotificationStatus.PROCESSING,
            'total_targets': 5,
            'processed': 3,
            'successful': 2,
            'failed': 1
        }
        
        # Test getting job status
        status = service.get_job_status(job_id)
        assert status['status'] == BulkNotificationStatus.PROCESSING
        assert status['total_targets'] == 5
        assert status['successful'] == 2
        
        # Test getting all active jobs
        active_jobs = service.get_active_jobs()
        assert job_id in active_jobs
        assert active_jobs[job_id]['processed'] == 3
    
    @pytest.mark.asyncio
    async def test_cancel_job(self):
        """Test job cancellation functionality."""
        service = BulkNotificationService()
        
        # Create an active job
        job_id = "test_job_123"
        service._active_jobs[job_id] = {
            'status': BulkNotificationStatus.PROCESSING
        }
        
        # Cancel the job
        result = await service.cancel_job(job_id)
        
        assert result is True
        assert service._active_jobs[job_id]['status'] == BulkNotificationStatus.CANCELLED
        
        # Try to cancel non-existent job
        result = await service.cancel_job("non_existent")
        assert result is False
    
    def test_notification_type_enabled_checking(self):
        """Test notification type enabled checking."""
        service = BulkNotificationService()
        
        # Mock preferences
        prefs = Mock()
        prefs.absent_alerts = True
        prefs.attendance_reminders = False
        prefs.system_announcements = True
        
        # Test enabled types
        assert service._is_notification_type_enabled(
            NotificationType.ABSENT_ALERT, prefs
        ) is True
        
        assert service._is_notification_type_enabled(
            NotificationType.SYSTEM_ANNOUNCEMENT, prefs
        ) is True
        
        # Test disabled type
        assert service._is_notification_type_enabled(
            NotificationType.ATTENDANCE_REMINDER, prefs
        ) is False


class TestBulkNotificationDataClasses:
    """Test cases for bulk notification data classes."""
    
    def test_bulk_notification_target_creation(self):
        """Test BulkNotificationTarget creation."""
        target = BulkNotificationTarget(
            user_id=123,
            email="test@example.com",
            phone_number="+1234567890",
            parent_email="parent@example.com",
            parent_phone="+1234567891",
            custom_data={"name": "John Doe", "class": "Math 101"}
        )
        
        assert target.user_id == 123
        assert target.email == "test@example.com"
        assert target.phone_number == "+1234567890"
        assert target.parent_email == "parent@example.com"
        assert target.parent_phone == "+1234567891"
        assert target.custom_data == {"name": "John Doe", "class": "Math 101"}
    
    def test_bulk_notification_request_creation(self, bulk_targets):
        """Test BulkNotificationRequest creation."""
        request = BulkNotificationRequest(
            targets=bulk_targets,
            notification_type=NotificationType.LATE_ARRIVAL,
            title="Bulk Late Arrival Alert",
            message="Multiple students arrived late",
            priority=BulkNotificationPriority.URGENT,
            html_content="<h1>Alert</h1>",
            template_id="late_arrival_template",
            template_data={"date": "2024-01-01"},
            send_email=True,
            send_sms=True,
            send_push=False,
            include_parents=True,
            scheduled_at=datetime.now(),
            expires_at=datetime.now(),
            max_send_rate_per_second=5,
            max_send_rate_per_minute=50,
            respect_quiet_hours=False,
            sender_id=100,
            class_session_id=456,
            metadata={"source": "test"}
        )
        
        assert request.targets == bulk_targets
        assert request.notification_type == NotificationType.LATE_ARRIVAL
        assert request.title == "Bulk Late Arrival Alert"
        assert request.message == "Multiple students arrived late"
        assert request.priority == BulkNotificationPriority.URGENT
        assert request.html_content == "<h1>Alert</h1>"
        assert request.template_id == "late_arrival_template"
        assert request.template_data == {"date": "2024-01-01"}
        assert request.send_email is True
        assert request.send_sms is True
        assert request.send_push is False
        assert request.include_parents is True
        assert request.max_send_rate_per_second == 5
        assert request.respect_quiet_hours is False
        assert request.sender_id == 100
        assert request.metadata == {"source": "test"}
    
    def test_bulk_notification_result_creation(self):
        """Test BulkNotificationResult creation."""
        result = BulkNotificationResult(
            job_id="bulk_job_123",
            total_targets=100,
            successful_sends=85,
            failed_sends=10,
            skipped_sends=5,
            errors=[
                {"user_id": 1, "error": "Invalid email"},
                {"user_id": 2, "error": "Rate limited"}
            ],
            processing_time=45.67,
            status=BulkNotificationStatus.COMPLETED
        )
        
        assert result.job_id == "bulk_job_123"
        assert result.total_targets == 100
        assert result.successful_sends == 85
        assert result.failed_sends == 10
        assert result.skipped_sends == 5
        assert len(result.errors) == 2
        assert result.processing_time == 45.67
        assert result.status == BulkNotificationStatus.COMPLETED