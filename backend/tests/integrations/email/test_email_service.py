"""Tests for email notification service."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.integrations.email import EmailService, EmailMessage, EmailProvider
from app.integrations.email.email_service import EmailDeliveryResult, EmailAttachment


@pytest.fixture
def email_message():
    """Create a test email message."""
    return EmailMessage(
        to_email="test@example.com",
        subject="Test Email",
        html_content="<h1>Test HTML Content</h1>",
        text_content="Test text content",
        from_email="sender@example.com",
        from_name="Test Sender",
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


@pytest.fixture
def mock_template_manager():
    """Mock email template manager."""
    mock_tm = AsyncMock()
    mock_tm.render_template.return_value = {
        "success": True,
        "subject": "Rendered Subject",
        "html_content": "<h1>Rendered HTML</h1>",
        "text_content": "Rendered text"
    }
    return mock_tm


class TestEmailService:
    """Test cases for EmailService."""
    
    def test_email_service_initialization(self):
        """Test email service initializes correctly."""
        with patch('app.integrations.email.email_service.settings') as mock_settings:
            mock_settings.SMTP_HOST = "smtp.example.com"
            mock_settings.SMTP_USERNAME = "test@example.com"
            mock_settings.SMTP_PASSWORD = "password"
            
            service = EmailService()
            
            assert service.providers is not None
            assert isinstance(service.providers, dict)
    
    @pytest.mark.asyncio
    async def test_send_email_success(self, email_message, mock_db_session):
        """Test successful email sending."""
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_email.return_value = EmailDeliveryResult(
            success=True,
            message_id="email_123",
            to_email=email_message.to_email
        )
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        service.primary_provider = EmailProvider.SMTP
        
        result = await service.send_email(
            to_email=email_message.to_email,
            subject=email_message.subject,
            html_content=email_message.html_content,
            text_content=email_message.text_content,
            notification_id=email_message.notification_id,
            db=mock_db_session
        )
        
        assert result.success is True
        assert result.message_id == "email_123"
        assert result.to_email == email_message.to_email
        mock_provider.send_email.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_email_with_template(self, mock_db_session, mock_template_manager):
        """Test email sending with template rendering."""
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_email.return_value = EmailDeliveryResult(
            success=True,
            message_id="email_template_123",
            to_email="test@example.com"
        )
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        service.primary_provider = EmailProvider.SMTP
        service.template_manager = mock_template_manager
        
        result = await service.send_email(
            to_email="test@example.com",
            subject="Original Subject",
            template_id="test_template",
            template_data={"name": "John Doe"},
            db=mock_db_session
        )
        
        assert result.success is True
        mock_template_manager.render_template.assert_called_once_with(
            "test_template", {"name": "John Doe"}
        )
        
        # Verify the provider received rendered content
        call_args = mock_provider.send_email.call_args[0][0]
        assert call_args.subject == "Rendered Subject"
        assert call_args.html_content == "<h1>Rendered HTML</h1>"
        assert call_args.text_content == "Rendered text"
    
    @pytest.mark.asyncio
    async def test_send_email_template_error(self, mock_db_session):
        """Test email sending with template rendering error."""
        # Mock template manager with error
        mock_template_manager = AsyncMock()
        mock_template_manager.render_template.return_value = {
            "success": False,
            "error": "Template not found"
        }
        
        service = EmailService()
        service.template_manager = mock_template_manager
        
        result = await service.send_email(
            to_email="test@example.com",
            subject="Test",
            template_id="nonexistent_template",
            db=mock_db_session
        )
        
        assert result.success is False
        assert result.error_code == "TEMPLATE_ERROR"
        assert "Template rendering failed" in result.error_message
    
    @pytest.mark.asyncio
    async def test_send_email_no_provider(self, email_message, mock_db_session):
        """Test email sending with no provider configured."""
        service = EmailService()
        service.providers = {}
        service.primary_provider = None
        
        result = await service.send_email(
            to_email=email_message.to_email,
            subject=email_message.subject,
            html_content=email_message.html_content,
            db=mock_db_session
        )
        
        assert result.success is False
        assert result.error_code == "NO_PROVIDER"
        assert result.to_email == email_message.to_email
    
    @pytest.mark.asyncio
    async def test_send_email_provider_unavailable_with_fallback(self, email_message, mock_db_session):
        """Test email sending with unavailable primary provider but available fallback."""
        # Mock primary provider (unavailable)
        mock_primary = AsyncMock()
        mock_primary.is_available.return_value = False
        
        # Mock fallback provider (available)
        mock_fallback = AsyncMock()
        mock_fallback.is_available.return_value = True
        mock_fallback.send_email.return_value = EmailDeliveryResult(
            success=True,
            message_id="fallback_email_123",
            to_email=email_message.to_email
        )
        
        service = EmailService()
        service.providers = {
            EmailProvider.SMTP: mock_primary,
            EmailProvider.SENDGRID: mock_fallback
        }
        service.primary_provider = EmailProvider.SMTP
        service.fallback_provider = EmailProvider.SENDGRID
        
        result = await service.send_email(
            to_email=email_message.to_email,
            subject=email_message.subject,
            html_content=email_message.html_content,
            db=mock_db_session
        )
        
        assert result.success is True
        assert result.message_id == "fallback_email_123"
        mock_primary.is_available.assert_called_once()
        mock_fallback.send_email.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_bulk_email_success(self, mock_db_session):
        """Test successful bulk email sending."""
        messages = [
            EmailMessage(to_email="user1@example.com", subject="Test 1", text_content="Content 1"),
            EmailMessage(to_email="user2@example.com", subject="Test 2", text_content="Content 2"),
            EmailMessage(to_email="user3@example.com", subject="Test 3", text_content="Content 3")
        ]
        
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_bulk_email.return_value = [
            EmailDeliveryResult(success=True, message_id="email_1", to_email="user1@example.com"),
            EmailDeliveryResult(success=True, message_id="email_2", to_email="user2@example.com"),
            EmailDeliveryResult(success=False, error_code="INVALID", to_email="user3@example.com")
        ]
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        service.primary_provider = EmailProvider.SMTP
        
        results = await service.send_bulk_email(messages, db=mock_db_session)
        
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is True
        assert results[2].success is False
        assert results[2].error_code == "INVALID"
        mock_provider.send_bulk_email.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_bulk_email_with_templates(self, mock_db_session, mock_template_manager):
        """Test bulk email sending with template processing."""
        messages = [
            EmailMessage(
                to_email="user1@example.com",
                subject="Template Test",
                template_id="test_template",
                template_data={"name": "User 1"}
            ),
            EmailMessage(
                to_email="user2@example.com",
                subject="Template Test",
                template_id="test_template", 
                template_data={"name": "User 2"}
            )
        ]
        
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.is_available.return_value = True
        mock_provider.send_bulk_email.return_value = [
            EmailDeliveryResult(success=True, message_id="email_1", to_email="user1@example.com"),
            EmailDeliveryResult(success=True, message_id="email_2", to_email="user2@example.com")
        ]
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        service.primary_provider = EmailProvider.SMTP
        service.template_manager = mock_template_manager
        
        results = await service.send_bulk_email(messages, db=mock_db_session)
        
        assert len(results) == 2
        assert all(r.success for r in results)
        
        # Verify template rendering was called for each message
        assert mock_template_manager.render_template.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_delivery_status(self):
        """Test getting delivery status."""
        message_id = "email_123"
        
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.get_delivery_status.return_value = {
            "success": True,
            "status": "delivered",
            "message_id": message_id
        }
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        service.primary_provider = EmailProvider.SMTP
        
        status = await service.get_delivery_status(message_id)
        
        assert status["success"] is True
        assert status["status"] == "delivered"
        mock_provider.get_delivery_status.assert_called_once_with(message_id)
    
    def test_is_available(self):
        """Test service availability check."""
        # Mock provider
        mock_provider = Mock()
        mock_provider.is_available.return_value = True
        
        service = EmailService()
        service.providers = {EmailProvider.SMTP: mock_provider}
        
        assert service.is_available() is True
        mock_provider.is_available.assert_called_once()
    
    def test_get_template_manager(self):
        """Test getting template manager."""
        mock_template_manager = Mock()
        
        service = EmailService()
        service.template_manager = mock_template_manager
        
        assert service.get_template_manager() == mock_template_manager


class TestEmailMessage:
    """Test cases for EmailMessage data class."""
    
    def test_email_message_creation_full(self):
        """Test email message creation with all fields."""
        attachments = [
            EmailAttachment(filename="test.pdf", content=b"PDF content", content_type="application/pdf")
        ]
        
        message = EmailMessage(
            to_email="test@example.com",
            subject="Test Subject",
            html_content="<h1>HTML Content</h1>",
            text_content="Text content",
            from_email="sender@example.com",
            from_name="Test Sender",
            reply_to="noreply@example.com",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            attachments=attachments,
            template_id="test_template",
            template_data={"key": "value"},
            notification_id=123,
            priority="high",
            scheduled_at=datetime.now(),
            metadata={"source": "test"}
        )
        
        assert message.to_email == "test@example.com"
        assert message.subject == "Test Subject"
        assert message.html_content == "<h1>HTML Content</h1>"
        assert message.text_content == "Text content"
        assert message.from_email == "sender@example.com"
        assert message.from_name == "Test Sender"
        assert message.reply_to == "noreply@example.com"
        assert message.cc == ["cc@example.com"]
        assert message.bcc == ["bcc@example.com"]
        assert len(message.attachments) == 1
        assert message.template_id == "test_template"
        assert message.template_data == {"key": "value"}
        assert message.notification_id == 123
        assert message.priority == "high"
        assert message.metadata == {"source": "test"}
    
    def test_email_message_minimal(self):
        """Test email message creation with minimal fields."""
        message = EmailMessage(
            to_email="test@example.com",
            subject="Test Subject"
        )
        
        assert message.to_email == "test@example.com"
        assert message.subject == "Test Subject"
        assert message.html_content is None
        assert message.text_content is None
        assert message.cc == []
        assert message.bcc == []
        assert message.attachments == []
        assert message.template_data == {}
        assert message.metadata == {}


class TestEmailAttachment:
    """Test cases for EmailAttachment data class."""
    
    def test_email_attachment_creation(self):
        """Test email attachment creation."""
        attachment = EmailAttachment(
            filename="document.pdf",
            content=b"PDF binary content",
            content_type="application/pdf"
        )
        
        assert attachment.filename == "document.pdf"
        assert attachment.content == b"PDF binary content"
        assert attachment.content_type == "application/pdf"
    
    def test_email_attachment_default_content_type(self):
        """Test email attachment with default content type."""
        attachment = EmailAttachment(
            filename="file.bin",
            content=b"Binary content"
        )
        
        assert attachment.content_type == "application/octet-stream"


class TestEmailDeliveryResult:
    """Test cases for EmailDeliveryResult data class."""
    
    def test_delivery_result_success(self):
        """Test successful delivery result."""
        result = EmailDeliveryResult(
            success=True,
            message_id="email_123",
            to_email="test@example.com",
            provider_response={"status": "queued", "id": "email_123"}
        )
        
        assert result.success is True
        assert result.message_id == "email_123"
        assert result.to_email == "test@example.com"
        assert result.provider_response == {"status": "queued", "id": "email_123"}
        assert result.error_code is None
        assert result.error_message is None
    
    def test_delivery_result_failure(self):
        """Test failed delivery result."""
        result = EmailDeliveryResult(
            success=False,
            error_code="INVALID_EMAIL",
            error_message="Invalid email address format",
            to_email="invalid-email",
            provider_response={"error": "validation_failed"}
        )
        
        assert result.success is False
        assert result.error_code == "INVALID_EMAIL"
        assert result.error_message == "Invalid email address format"
        assert result.to_email == "invalid-email"
        assert result.message_id is None


# Integration tests for actual email providers
@pytest.mark.integration
@pytest.mark.skip(reason="Requires actual email provider credentials")
class TestEmailServiceIntegration:
    """Integration tests for email service with real providers."""
    
    @pytest.mark.asyncio
    async def test_smtp_integration(self):
        """Test integration with actual SMTP server."""
        # This would test with real SMTP credentials
        # Only run in integration test environment
        pass
    
    @pytest.mark.asyncio
    async def test_sendgrid_integration(self):
        """Test integration with actual SendGrid API."""
        # This would test with real SendGrid API key
        # Only run in integration test environment
        pass