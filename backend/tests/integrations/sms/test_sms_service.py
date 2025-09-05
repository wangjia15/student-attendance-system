"""Tests for SMS notification service."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.integrations.sms import SMSService, SMSMessage, SMSProvider
from app.integrations.sms.sms_service import SMSDeliveryResult


@pytest.fixture
def sms_message():
    """Create a test SMS message."""
    return SMSMessage(
        phone_number="+1234567890",
        message="Test SMS message",
        notification_id=123,
        priority="normal"
    )


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    mock_db = AsyncMock()
    mock_db.add = Mock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


class TestSMSService:
    """Test cases for SMSService."""
    
    def test_sms_service_initialization(self):
        """Test SMS service initializes correctly."""
        with patch('app.integrations.sms.sms_service.settings') as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "test_sid"
            mock_settings.TWILIO_AUTH_TOKEN = "test_token"
            
            service = SMSService()
            
            assert service.providers is not None
            assert isinstance(service.providers, dict)
    
    @pytest.mark.asyncio
    async def test_send_sms_success(self, sms_message, mock_db_session):
        """Test successful SMS sending."""
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_sms.return_value = SMSDeliveryResult(
            success=True,
            message_id="test_msg_123",
            phone_number=sms_message.phone_number
        )
        
        service = SMSService()
        service.providers = {SMSProvider.TWILIO: mock_provider}
        service.primary_provider = SMSProvider.TWILIO
        
        result = await service.send_sms(
            phone_number=sms_message.phone_number,
            message=sms_message.message,
            notification_id=sms_message.notification_id,
            db=mock_db_session
        )
        
        assert result.success is True
        assert result.message_id == "test_msg_123"
        assert result.phone_number == sms_message.phone_number
        mock_provider.send_sms.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_sms_no_provider(self, sms_message, mock_db_session):
        """Test SMS sending with no provider configured."""
        service = SMSService()
        service.providers = {}
        service.primary_provider = None
        
        result = await service.send_sms(
            phone_number=sms_message.phone_number,
            message=sms_message.message,
            db=mock_db_session
        )
        
        assert result.success is False
        assert result.error_code == "NO_PROVIDER"
        assert result.phone_number == sms_message.phone_number
    
    @pytest.mark.asyncio
    async def test_send_sms_provider_unavailable_with_fallback(self, sms_message, mock_db_session):
        """Test SMS sending with unavailable primary provider but available fallback."""
        # Mock primary provider (unavailable)
        mock_primary = AsyncMock()
        mock_primary.is_available.return_value = False
        
        # Mock fallback provider (available)
        mock_fallback = AsyncMock()
        mock_fallback.is_available.return_value = True
        mock_fallback.send_sms.return_value = SMSDeliveryResult(
            success=True,
            message_id="fallback_msg_123",
            phone_number=sms_message.phone_number
        )
        
        service = SMSService()
        service.providers = {
            SMSProvider.TWILIO: mock_primary,
            SMSProvider.AWS_SNS: mock_fallback
        }
        service.primary_provider = SMSProvider.TWILIO
        service.fallback_provider = SMSProvider.AWS_SNS
        
        result = await service.send_sms(
            phone_number=sms_message.phone_number,
            message=sms_message.message,
            db=mock_db_session
        )
        
        assert result.success is True
        assert result.message_id == "fallback_msg_123"
        mock_primary.is_available.assert_called_once()
        mock_fallback.send_sms.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_sms_all_providers_unavailable(self, sms_message, mock_db_session):
        """Test SMS sending with all providers unavailable."""
        # Mock providers (all unavailable)
        mock_primary = AsyncMock()
        mock_primary.is_available.return_value = False
        
        mock_fallback = AsyncMock()
        mock_fallback.is_available.return_value = False
        
        service = SMSService()
        service.providers = {
            SMSProvider.TWILIO: mock_primary,
            SMSProvider.AWS_SNS: mock_fallback
        }
        service.primary_provider = SMSProvider.TWILIO
        service.fallback_provider = SMSProvider.AWS_SNS
        
        result = await service.send_sms(
            phone_number=sms_message.phone_number,
            message=sms_message.message,
            db=mock_db_session
        )
        
        assert result.success is False
        assert result.error_code == "PROVIDER_UNAVAILABLE"
    
    @pytest.mark.asyncio
    async def test_send_bulk_sms_success(self, mock_db_session):
        """Test successful bulk SMS sending."""
        messages = [
            SMSMessage(phone_number="+1234567890", message="Message 1", notification_id=1),
            SMSMessage(phone_number="+1234567891", message="Message 2", notification_id=2),
            SMSMessage(phone_number="+1234567892", message="Message 3", notification_id=3)
        ]
        
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_bulk_sms.return_value = [
            SMSDeliveryResult(success=True, message_id="msg_1", phone_number="+1234567890"),
            SMSDeliveryResult(success=True, message_id="msg_2", phone_number="+1234567891"),
            SMSDeliveryResult(success=False, error_code="INVALID", phone_number="+1234567892")
        ]
        
        service = SMSService()
        service.providers = {SMSProvider.TWILIO: mock_provider}
        service.primary_provider = SMSProvider.TWILIO
        
        results = await service.send_bulk_sms(messages, db=mock_db_session)
        
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is True
        assert results[2].success is False
        assert results[2].error_code == "INVALID"
        mock_provider.send_bulk_sms.assert_called_once_with(messages)
    
    @pytest.mark.asyncio
    async def test_send_bulk_sms_empty_list(self, mock_db_session):
        """Test bulk SMS sending with empty message list."""
        service = SMSService()
        
        results = await service.send_bulk_sms([], db=mock_db_session)
        
        assert results == []
    
    @pytest.mark.asyncio
    async def test_get_delivery_status(self):
        """Test getting delivery status."""
        message_id = "test_msg_123"
        
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.get_delivery_status.return_value = {
            "success": True,
            "status": "delivered",
            "message_id": message_id
        }
        
        service = SMSService()
        service.providers = {SMSProvider.TWILIO: mock_provider}
        service.primary_provider = SMSProvider.TWILIO
        
        status = await service.get_delivery_status(message_id)
        
        assert status["success"] is True
        assert status["status"] == "delivered"
        mock_provider.get_delivery_status.assert_called_once_with(message_id)
    
    def test_is_available(self):
        """Test service availability check."""
        # Mock provider
        mock_provider = Mock()
        mock_provider.is_available.return_value = True
        
        service = SMSService()
        service.providers = {SMSProvider.TWILIO: mock_provider}
        
        assert service.is_available() is True
        mock_provider.is_available.assert_called_once()
    
    def test_is_available_no_providers(self):
        """Test service availability with no providers."""
        service = SMSService()
        service.providers = {}
        
        assert service.is_available() is False
    
    def test_get_provider_status(self):
        """Test getting provider status."""
        # Mock providers
        mock_twilio = Mock()
        mock_twilio.is_available.return_value = True
        mock_twilio.get_rate_limit_info.return_value = {"requests_this_second": 5}
        
        mock_sns = Mock()
        mock_sns.is_available.return_value = False
        mock_sns.get_rate_limit_info.return_value = {"requests_this_second": 0}
        
        service = SMSService()
        service.providers = {
            SMSProvider.TWILIO: mock_twilio,
            SMSProvider.AWS_SNS: mock_sns
        }
        
        status = service.get_provider_status()
        
        assert status["twilio"]["available"] is True
        assert status["aws_sns"]["available"] is False
        assert "rate_limit_info" in status["twilio"]
        assert "rate_limit_info" in status["aws_sns"]
    
    def test_get_supported_providers(self):
        """Test getting list of supported providers."""
        # Mock providers
        mock_twilio = Mock()
        mock_twilio.is_available.return_value = True
        
        mock_sns = Mock()
        mock_sns.is_available.return_value = False
        
        service = SMSService()
        service.providers = {
            SMSProvider.TWILIO: mock_twilio,
            SMSProvider.AWS_SNS: mock_sns
        }
        
        supported = service.get_supported_providers()
        
        assert SMSProvider.TWILIO in supported
        assert SMSProvider.AWS_SNS not in supported
        assert len(supported) == 1


@pytest.mark.asyncio
async def test_log_delivery_attempt(mock_db_session):
    """Test logging delivery attempt to database."""
    from app.models.notifications import NotificationDelivery
    
    service = SMSService()
    
    # Mock provider with logging
    mock_provider = AsyncMock()
    mock_provider.is_available.return_value = True
    mock_provider.send_sms.return_value = SMSDeliveryResult(
        success=True,
        message_id="test_msg_123",
        phone_number="+1234567890",
        cost=0.05
    )
    
    service.providers = {SMSProvider.TWILIO: mock_provider}
    service.primary_provider = SMSProvider.TWILIO
    
    result = await service.send_sms(
        phone_number="+1234567890",
        message="Test message",
        notification_id=123,
        db=mock_db_session
    )
    
    assert result.success is True
    
    # Verify database logging was called
    mock_db_session.add.assert_called()
    mock_db_session.flush.assert_called()


class TestSMSMessage:
    """Test cases for SMSMessage data class."""
    
    def test_sms_message_creation(self):
        """Test SMS message creation with all fields."""
        message = SMSMessage(
            phone_number="+1234567890",
            message="Test message",
            notification_id=123,
            priority="urgent",
            scheduled_at=datetime.now(),
            callback_url="https://example.com/callback",
            metadata={"key": "value"}
        )
        
        assert message.phone_number == "+1234567890"
        assert message.message == "Test message"
        assert message.notification_id == 123
        assert message.priority == "urgent"
        assert message.callback_url == "https://example.com/callback"
        assert message.metadata == {"key": "value"}
    
    def test_sms_message_minimal(self):
        """Test SMS message creation with minimal fields."""
        message = SMSMessage(
            phone_number="+1234567890",
            message="Test message"
        )
        
        assert message.phone_number == "+1234567890"
        assert message.message == "Test message"
        assert message.notification_id is None
        assert message.priority == "normal"
        assert message.scheduled_at is None
        assert message.callback_url is None
        assert message.metadata is None


class TestSMSDeliveryResult:
    """Test cases for SMSDeliveryResult data class."""
    
    def test_delivery_result_success(self):
        """Test successful delivery result."""
        result = SMSDeliveryResult(
            success=True,
            message_id="msg_123",
            phone_number="+1234567890",
            cost=0.05,
            provider_response={"status": "sent"}
        )
        
        assert result.success is True
        assert result.message_id == "msg_123"
        assert result.phone_number == "+1234567890"
        assert result.cost == 0.05
        assert result.provider_response == {"status": "sent"}
        assert result.error_code is None
        assert result.error_message is None
    
    def test_delivery_result_failure(self):
        """Test failed delivery result."""
        result = SMSDeliveryResult(
            success=False,
            error_code="INVALID_NUMBER",
            error_message="Invalid phone number format",
            phone_number="+invalid"
        )
        
        assert result.success is False
        assert result.error_code == "INVALID_NUMBER"
        assert result.error_message == "Invalid phone number format"
        assert result.phone_number == "+invalid"
        assert result.message_id is None
        assert result.cost is None


# Integration tests would go here for testing with actual providers
# These would be marked with @pytest.mark.integration and require
# actual API credentials for testing

@pytest.mark.integration
@pytest.mark.skip(reason="Requires actual API credentials")
class TestSMSServiceIntegration:
    """Integration tests for SMS service with real providers."""
    
    @pytest.mark.asyncio
    async def test_twilio_integration(self):
        """Test integration with actual Twilio API."""
        # This would test with real Twilio credentials
        # Only run in integration test environment
        pass
    
    @pytest.mark.asyncio
    async def test_aws_sns_integration(self):
        """Test integration with actual AWS SNS."""
        # This would test with real AWS credentials
        # Only run in integration test environment
        pass