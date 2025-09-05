"""SMS notification service with multiple provider support."""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.notifications import NotificationDelivery, NotificationStatus, DevicePlatform
from app.core.config import settings

logger = logging.getLogger(__name__)


class SMSProvider(str, Enum):
    """Supported SMS providers."""
    TWILIO = "twilio"
    AWS_SNS = "aws_sns"


@dataclass
class SMSMessage:
    """SMS message data structure."""
    phone_number: str
    message: str
    notification_id: Optional[int] = None
    priority: str = "normal"
    scheduled_at: Optional[datetime] = None
    callback_url: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class SMSDeliveryResult:
    """Result of SMS delivery attempt."""
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    provider_response: Dict[str, Any] = None
    cost: Optional[float] = None
    phone_number: str = ""


class BaseSMSProvider(ABC):
    """Abstract base class for SMS providers."""
    
    @abstractmethod
    async def send_sms(self, message: SMSMessage) -> SMSDeliveryResult:
        """Send a single SMS message."""
        pass
    
    @abstractmethod
    async def send_bulk_sms(self, messages: List[SMSMessage]) -> List[SMSDeliveryResult]:
        """Send multiple SMS messages in bulk."""
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


class SMSService:
    """Main SMS service that coordinates multiple providers."""
    
    def __init__(self):
        self.providers = {}
        self.primary_provider = None
        self.fallback_provider = None
        self._initialize_providers()
        logger.info("SMS Service initialized")
    
    def _initialize_providers(self):
        """Initialize configured SMS providers."""
        try:
            # Initialize Twilio provider
            if hasattr(settings, 'TWILIO_ACCOUNT_SID') and settings.TWILIO_ACCOUNT_SID:
                from .twilio_provider import TwilioSMSProvider
                self.providers[SMSProvider.TWILIO] = TwilioSMSProvider()
                if self.primary_provider is None:
                    self.primary_provider = SMSProvider.TWILIO
                    
            # Initialize AWS SNS provider
            if hasattr(settings, 'AWS_SNS_REGION') and settings.AWS_SNS_REGION:
                from .aws_sns_provider import AWSSNSProvider
                self.providers[SMSProvider.AWS_SNS] = AWSSNSProvider()
                if self.primary_provider is None:
                    self.primary_provider = SMSProvider.AWS_SNS
                elif self.fallback_provider is None:
                    self.fallback_provider = SMSProvider.AWS_SNS
                    
        except Exception as e:
            logger.error(f"Error initializing SMS providers: {e}")
    
    async def send_sms(
        self, 
        phone_number: str,
        message: str,
        notification_id: Optional[int] = None,
        priority: str = "normal",
        provider: Optional[SMSProvider] = None,
        db: Optional[AsyncSession] = None
    ) -> SMSDeliveryResult:
        """
        Send a single SMS message.
        
        Args:
            phone_number: Target phone number in E.164 format
            message: SMS message content
            notification_id: Associated notification ID for tracking
            priority: Message priority (normal, high, urgent)
            provider: Specific provider to use (optional)
            db: Database session for logging
            
        Returns:
            Delivery result with success status and details
        """
        sms_message = SMSMessage(
            phone_number=phone_number,
            message=message,
            notification_id=notification_id,
            priority=priority
        )
        
        # Determine which provider to use
        target_provider = provider or self.primary_provider
        if not target_provider or target_provider not in self.providers:
            return SMSDeliveryResult(
                success=False,
                error_code="NO_PROVIDER",
                error_message="No SMS provider configured",
                phone_number=phone_number
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
                    return SMSDeliveryResult(
                        success=False,
                        error_code="PROVIDER_UNAVAILABLE",
                        error_message=f"Provider {target_provider.value} is not available",
                        phone_number=phone_number
                    )
            
            # Send the message
            result = await provider_instance.send_sms(sms_message)
            
            # Log delivery attempt if database session provided
            if db and notification_id:
                await self._log_delivery_attempt(
                    notification_id, phone_number, target_provider, result, db
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending SMS via {target_provider.value}: {e}")
            result = SMSDeliveryResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
                phone_number=phone_number
            )
            
            # Log failed delivery attempt
            if db and notification_id:
                await self._log_delivery_attempt(
                    notification_id, phone_number, target_provider, result, db
                )
            
            return result
    
    async def send_bulk_sms(
        self,
        messages: List[SMSMessage],
        provider: Optional[SMSProvider] = None,
        db: Optional[AsyncSession] = None
    ) -> List[SMSDeliveryResult]:
        """
        Send multiple SMS messages in bulk.
        
        Args:
            messages: List of SMS messages to send
            provider: Specific provider to use (optional)
            db: Database session for logging
            
        Returns:
            List of delivery results for each message
        """
        if not messages:
            return []
        
        # Determine which provider to use
        target_provider = provider or self.primary_provider
        if not target_provider or target_provider not in self.providers:
            return [
                SMSDeliveryResult(
                    success=False,
                    error_code="NO_PROVIDER",
                    error_message="No SMS provider configured",
                    phone_number=msg.phone_number
                ) for msg in messages
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
                        SMSDeliveryResult(
                            success=False,
                            error_code="PROVIDER_UNAVAILABLE",
                            error_message=f"Provider {target_provider.value} is not available",
                            phone_number=msg.phone_number
                        ) for msg in messages
                    ]
            
            # Send bulk messages
            results = await provider_instance.send_bulk_sms(messages)
            
            # Log delivery attempts if database session provided
            if db:
                for i, result in enumerate(results):
                    if i < len(messages) and messages[i].notification_id:
                        await self._log_delivery_attempt(
                            messages[i].notification_id,
                            messages[i].phone_number,
                            target_provider,
                            result,
                            db
                        )
            
            return results
            
        except Exception as e:
            logger.error(f"Error sending bulk SMS via {target_provider.value}: {e}")
            error_results = [
                SMSDeliveryResult(
                    success=False,
                    error_code="BULK_SEND_ERROR",
                    error_message=str(e),
                    phone_number=msg.phone_number
                ) for msg in messages
            ]
            
            # Log failed delivery attempts
            if db:
                for i, result in enumerate(error_results):
                    if i < len(messages) and messages[i].notification_id:
                        await self._log_delivery_attempt(
                            messages[i].notification_id,
                            messages[i].phone_number,
                            target_provider,
                            result,
                            db
                        )
            
            return error_results
    
    async def get_delivery_status(
        self,
        message_id: str,
        provider: Optional[SMSProvider] = None
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
        phone_number: str,
        provider: SMSProvider,
        result: SMSDeliveryResult,
        db: AsyncSession
    ):
        """Log SMS delivery attempt to database."""
        try:
            # Create delivery record
            delivery = NotificationDelivery(
                notification_id=notification_id,
                device_token_id=None,  # SMS doesn't use device tokens
                platform=DevicePlatform.WEB,  # Use WEB as placeholder for SMS
                status=NotificationStatus.SENT if result.success else NotificationStatus.FAILED,
                platform_message_id=result.message_id,
                platform_response={
                    "provider": provider.value,
                    "phone_number": phone_number,
                    "cost": result.cost,
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
            logger.error(f"Error logging SMS delivery attempt: {e}")
    
    def is_available(self) -> bool:
        """Check if any SMS provider is available."""
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
    
    def get_supported_providers(self) -> List[SMSProvider]:
        """Get list of configured and available providers."""
        return [
            provider_name for provider_name, provider in self.providers.items()
            if provider.is_available()
        ]