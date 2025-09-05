"""Email notification service with template management and multiple provider support."""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.notifications import NotificationDelivery, NotificationStatus, DevicePlatform
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailProvider(str, Enum):
    """Supported email providers."""
    SMTP = "smtp"
    SENDGRID = "sendgrid"
    AWS_SES = "aws_ses"


@dataclass
class EmailAttachment:
    """Email attachment data structure."""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Email message data structure."""
    to_email: str
    subject: str
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    attachments: List[EmailAttachment] = field(default_factory=list)
    template_id: Optional[str] = None
    template_data: Dict[str, Any] = field(default_factory=dict)
    notification_id: Optional[int] = None
    priority: str = "normal"
    scheduled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmailDeliveryResult:
    """Result of email delivery attempt."""
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    provider_response: Dict[str, Any] = field(default_factory=dict)
    to_email: str = ""


class BaseEmailProvider(ABC):
    """Abstract base class for email providers."""
    
    @abstractmethod
    async def send_email(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send a single email message."""
        pass
    
    @abstractmethod
    async def send_bulk_email(self, messages: List[EmailMessage]) -> List[EmailDeliveryResult]:
        """Send multiple email messages in bulk."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available."""
        pass
    
    @abstractmethod
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Get delivery status for a message."""
        pass
    
    @abstractmethod
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get current rate limiting information."""
        pass


class EmailService:
    """Main email service that coordinates multiple providers and templates."""
    
    def __init__(self):
        self.providers = {}
        self.primary_provider = None
        self.fallback_provider = None
        self.template_manager = None
        self._initialize_providers()
        self._initialize_template_manager()
        logger.info("Email Service initialized")
    
    def _initialize_providers(self):
        """Initialize configured email providers."""
        try:
            # Initialize SMTP provider
            if hasattr(settings, 'SMTP_HOST') and settings.SMTP_HOST:
                from .smtp_provider import SMTPProvider
                self.providers[EmailProvider.SMTP] = SMTPProvider()
                if self.primary_provider is None:
                    self.primary_provider = EmailProvider.SMTP
                    
            # Initialize SendGrid provider
            if hasattr(settings, 'SENDGRID_API_KEY') and settings.SENDGRID_API_KEY:
                from .sendgrid_provider import SendGridProvider
                self.providers[EmailProvider.SENDGRID] = SendGridProvider()
                if self.primary_provider is None:
                    self.primary_provider = EmailProvider.SENDGRID
                elif self.fallback_provider is None:
                    self.fallback_provider = EmailProvider.SENDGRID
                    
        except Exception as e:
            logger.error(f"Error initializing email providers: {e}")
    
    def _initialize_template_manager(self):
        """Initialize email template manager."""
        try:
            from .template_manager import EmailTemplateManager
            self.template_manager = EmailTemplateManager()
        except Exception as e:
            logger.error(f"Error initializing template manager: {e}")
    
    async def send_email(
        self, 
        to_email: str,
        subject: str,
        html_content: Optional[str] = None,
        text_content: Optional[str] = None,
        template_id: Optional[str] = None,
        template_data: Dict[str, Any] = None,
        notification_id: Optional[int] = None,
        priority: str = "normal",
        provider: Optional[EmailProvider] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        attachments: List[EmailAttachment] = None,
        db: Optional[AsyncSession] = None
    ) -> EmailDeliveryResult:
        """
        Send a single email message.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text email content
            template_id: Email template ID to use
            template_data: Data for template rendering
            notification_id: Associated notification ID for tracking
            priority: Message priority (normal, high, urgent)
            provider: Specific provider to use (optional)
            from_email: Sender email address (optional)
            from_name: Sender display name (optional)
            attachments: Email attachments (optional)
            db: Database session for logging
            
        Returns:
            Delivery result with success status and details
        """
        email_message = EmailMessage(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            template_id=template_id,
            template_data=template_data or {},
            notification_id=notification_id,
            priority=priority,
            from_email=from_email,
            from_name=from_name,
            attachments=attachments or []
        )
        
        # Process template if specified
        if template_id and self.template_manager:
            try:
                rendered = await self.template_manager.render_template(
                    template_id, template_data or {}
                )
                if rendered["success"]:
                    email_message.subject = rendered["subject"] or email_message.subject
                    email_message.html_content = rendered["html_content"]
                    email_message.text_content = rendered["text_content"]
                else:
                    logger.error(f"Template rendering failed: {rendered.get('error')}")
                    return EmailDeliveryResult(
                        success=False,
                        error_code="TEMPLATE_ERROR",
                        error_message=f"Template rendering failed: {rendered.get('error')}",
                        to_email=to_email
                    )
            except Exception as e:
                logger.error(f"Template processing error: {e}")
                return EmailDeliveryResult(
                    success=False,
                    error_code="TEMPLATE_ERROR",
                    error_message=str(e),
                    to_email=to_email
                )
        
        # Determine which provider to use
        target_provider = provider or self.primary_provider
        if not target_provider or target_provider not in self.providers:
            return EmailDeliveryResult(
                success=False,
                error_code="NO_PROVIDER",
                error_message="No email provider configured",
                to_email=to_email
            )
        
        provider_instance = self.providers[target_provider]
        
        try:
            # Check provider availability
            if not provider_instance.is_available():
                # Try fallback provider if available
                if self.fallback_provider and self.fallback_provider in self.providers:
                    logger.warning(f"Primary provider {target_provider.value} unavailable, trying fallback")
                    provider_instance = self.providers[self.fallback_provider]
                    target_provider = self.fallback_provider
                else:
                    return EmailDeliveryResult(
                        success=False,
                        error_code="PROVIDER_UNAVAILABLE",
                        error_message=f"Provider {target_provider.value} is not available",
                        to_email=to_email
                    )
            
            # Send the email
            result = await provider_instance.send_email(email_message)
            
            # Log delivery attempt if database session provided
            if db and notification_id:
                await self._log_delivery_attempt(
                    notification_id, to_email, target_provider, result, db
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending email via {target_provider.value}: {e}")
            result = EmailDeliveryResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
                to_email=to_email
            )
            
            # Log failed delivery attempt
            if db and notification_id:
                await self._log_delivery_attempt(
                    notification_id, to_email, target_provider, result, db
                )
            
            return result
    
    async def send_bulk_email(
        self,
        messages: List[EmailMessage],
        provider: Optional[EmailProvider] = None,
        db: Optional[AsyncSession] = None
    ) -> List[EmailDeliveryResult]:
        """
        Send multiple email messages in bulk.
        
        Args:
            messages: List of email messages to send
            provider: Specific provider to use (optional)
            db: Database session for logging
            
        Returns:
            List of delivery results for each message
        """
        if not messages:
            return []
        
        # Process templates for all messages
        processed_messages = []
        for message in messages:
            if message.template_id and self.template_manager:
                try:
                    rendered = await self.template_manager.render_template(
                        message.template_id, message.template_data
                    )
                    if rendered["success"]:
                        message.subject = rendered["subject"] or message.subject
                        message.html_content = rendered["html_content"]
                        message.text_content = rendered["text_content"]
                    else:
                        logger.error(f"Template rendering failed for message to {message.to_email}")
                        # Skip this message or use fallback content
                        continue
                except Exception as e:
                    logger.error(f"Template processing error for {message.to_email}: {e}")
                    continue
            processed_messages.append(message)
        
        # Determine which provider to use
        target_provider = provider or self.primary_provider
        if not target_provider or target_provider not in self.providers:
            return [
                EmailDeliveryResult(
                    success=False,
                    error_code="NO_PROVIDER",
                    error_message="No email provider configured",
                    to_email=msg.to_email
                ) for msg in processed_messages
            ]
        
        provider_instance = self.providers[target_provider]
        
        try:
            # Check provider availability
            if not provider_instance.is_available():
                if self.fallback_provider and self.fallback_provider in self.providers:
                    logger.warning(f"Primary provider {target_provider.value} unavailable, trying fallback")
                    provider_instance = self.providers[self.fallback_provider]
                    target_provider = self.fallback_provider
                else:
                    return [
                        EmailDeliveryResult(
                            success=False,
                            error_code="PROVIDER_UNAVAILABLE",
                            error_message=f"Provider {target_provider.value} is not available",
                            to_email=msg.to_email
                        ) for msg in processed_messages
                    ]
            
            # Send bulk emails
            results = await provider_instance.send_bulk_email(processed_messages)
            
            # Log delivery attempts if database session provided
            if db:
                for i, result in enumerate(results):
                    if i < len(processed_messages) and processed_messages[i].notification_id:
                        await self._log_delivery_attempt(
                            processed_messages[i].notification_id,
                            processed_messages[i].to_email,
                            target_provider,
                            result,
                            db
                        )
            
            return results
            
        except Exception as e:
            logger.error(f"Error sending bulk email via {target_provider.value}: {e}")
            error_results = [
                EmailDeliveryResult(
                    success=False,
                    error_code="BULK_SEND_ERROR",
                    error_message=str(e),
                    to_email=msg.to_email
                ) for msg in processed_messages
            ]
            
            # Log failed delivery attempts
            if db:
                for i, result in enumerate(error_results):
                    if i < len(processed_messages) and processed_messages[i].notification_id:
                        await self._log_delivery_attempt(
                            processed_messages[i].notification_id,
                            processed_messages[i].to_email,
                            target_provider,
                            result,
                            db
                        )
            
            return error_results
    
    async def get_delivery_status(
        self,
        message_id: str,
        provider: Optional[EmailProvider] = None
    ) -> Dict[str, Any]:
        """Get delivery status for a message."""
        target_provider = provider or self.primary_provider
        if not target_provider or target_provider not in self.providers:
            return {
                "success": False,
                "error": "Provider not available"
            }
        
        provider_instance = self.providers[target_provider]
        return await provider_instance.get_delivery_status(message_id)
    
    async def _log_delivery_attempt(
        self,
        notification_id: int,
        to_email: str,
        provider: EmailProvider,
        result: EmailDeliveryResult,
        db: AsyncSession
    ):
        """Log email delivery attempt to database."""
        try:
            # Create delivery record
            delivery = NotificationDelivery(
                notification_id=notification_id,
                device_token_id=None,  # Email doesn't use device tokens
                platform=DevicePlatform.WEB,  # Use WEB as placeholder for email
                status=NotificationStatus.SENT if result.success else NotificationStatus.FAILED,
                platform_message_id=result.message_id,
                platform_response={
                    "provider": provider.value,
                    "to_email": to_email,
                    "provider_response": result.provider_response
                },
                sent_at=datetime.utcnow() if result.success else None,
                failed_at=datetime.utcnow() if not result.success else None,
                error_code=result.error_code,
                error_message=result.error_message
            )
            
            db.add(delivery)
            await db.flush()
            
        except Exception as e:
            logger.error(f"Error logging email delivery attempt: {e}")
    
    def is_available(self) -> bool:
        """Check if any email provider is available."""
        return any(
            provider.is_available() 
            for provider in self.providers.values()
        )
    
    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all configured providers."""
        status = {}
        for provider_name, provider in self.providers.items():
            status[provider_name.value] = {
                "available": provider.is_available(),
                "rate_limit_info": provider.get_rate_limit_info()
            }
        return status
    
    def get_supported_providers(self) -> List[EmailProvider]:
        """Get list of configured and available providers."""
        return [
            provider_name for provider_name, provider in self.providers.items()
            if provider.is_available()
        ]
    
    def get_template_manager(self):
        """Get the template manager instance."""
        return self.template_manager