"""Delivery status tracking and retry mechanism service."""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update, func

from app.models.notifications import (
    Notification, NotificationDelivery, NotificationStatus, 
    DevicePlatform, NotificationPriority
)
from app.integrations.sms import SMSService
from app.integrations.email import EmailService
from app.core.config import settings

logger = logging.getLogger(__name__)


class RetryStrategy(str, Enum):
    """Retry strategies for failed notifications."""
    IMMEDIATE = "immediate"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"


class DeliveryTrackingStatus(str, Enum):
    """Extended delivery tracking statuses."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"
    CLICKED = "clicked"
    OPENED = "opened"
    EXPIRED = "expired"


@dataclass
class RetryConfiguration:
    """Configuration for retry attempts."""
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_retries: int = 3
    initial_delay_seconds: int = 30
    max_delay_seconds: int = 3600
    backoff_multiplier: float = 2.0
    retry_on_statuses: List[NotificationStatus] = None
    
    def __post_init__(self):
        if self.retry_on_statuses is None:
            self.retry_on_statuses = [NotificationStatus.FAILED]


@dataclass
class DeliveryStatusUpdate:
    """Status update for a notification delivery."""
    delivery_id: int
    platform_message_id: str
    new_status: DeliveryTrackingStatus
    status_timestamp: datetime
    provider_response: Dict[str, Any] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None


class DeliveryTrackingService:
    """Service for tracking notification delivery status and handling retries."""
    
    def __init__(self):
        self.sms_service = SMSService()
        self.email_service = EmailService()
        
        # Retry configurations by priority
        self.retry_configs = {
            NotificationPriority.URGENT: RetryConfiguration(
                strategy=RetryStrategy.EXPONENTIAL,
                max_retries=5,
                initial_delay_seconds=10,
                max_delay_seconds=300,
                backoff_multiplier=1.5
            ),
            NotificationPriority.HIGH: RetryConfiguration(
                strategy=RetryStrategy.EXPONENTIAL,
                max_retries=4,
                initial_delay_seconds=30,
                max_delay_seconds=1800,
                backoff_multiplier=2.0
            ),
            NotificationPriority.NORMAL: RetryConfiguration(
                strategy=RetryStrategy.EXPONENTIAL,
                max_retries=3,
                initial_delay_seconds=60,
                max_delay_seconds=3600,
                backoff_multiplier=2.0
            ),
            NotificationPriority.LOW: RetryConfiguration(
                strategy=RetryStrategy.LINEAR,
                max_retries=2,
                initial_delay_seconds=300,
                max_delay_seconds=7200,
                backoff_multiplier=1.0
            )
        }
        
        logger.info("Delivery Tracking Service initialized")
    
    async def update_delivery_status(
        self,
        update: DeliveryStatusUpdate,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Update delivery status for a notification.
        
        Args:
            update: Status update information
            db: Database session
            
        Returns:
            Dictionary with update result
        """
        try:
            # Get delivery record
            result = await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == update.delivery_id
                )
            )
            
            delivery = result.scalar_one_or_none()
            if not delivery:
                return {
                    "success": False,
                    "error": f"Delivery record {update.delivery_id} not found"
                }
            
            # Update delivery record
            delivery.status = NotificationStatus(update.new_status.value)
            delivery.platform_response = update.provider_response or {}
            delivery.error_code = update.error_code
            delivery.error_message = update.error_message
            delivery.updated_at = datetime.utcnow()
            
            # Set appropriate timestamp based on status
            if update.new_status == DeliveryTrackingStatus.DELIVERED:
                delivery.delivered_at = update.status_timestamp
            elif update.new_status in [DeliveryTrackingStatus.FAILED, DeliveryTrackingStatus.BOUNCED]:
                delivery.failed_at = update.status_timestamp
            
            # Update parent notification status
            notification = await self._get_notification(delivery.notification_id, db)
            if notification:
                await self._update_notification_status(notification, update.new_status, db)
            
            await db.commit()
            
            # Schedule retry if needed
            if update.new_status == DeliveryTrackingStatus.FAILED and notification:
                await self._schedule_retry(notification, delivery, db)
            
            return {
                "success": True,
                "delivery_id": update.delivery_id,
                "new_status": update.new_status.value
            }
            
        except Exception as e:
            logger.error(f"Error updating delivery status: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def process_delivery_webhooks(
        self,
        provider: str,
        webhook_data: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Process delivery status webhooks from external providers.
        
        Args:
            provider: Provider name (twilio, sendgrid, etc.)
            webhook_data: Webhook payload data
            db: Database session
            
        Returns:
            Processing result
        """
        try:
            if provider.lower() == "twilio":
                return await self._process_twilio_webhook(webhook_data, db)
            elif provider.lower() == "sendgrid":
                return await self._process_sendgrid_webhook(webhook_data, db)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported provider: {provider}"
                }
                
        except Exception as e:
            logger.error(f"Error processing {provider} webhook: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _process_twilio_webhook(
        self,
        webhook_data: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Process Twilio SMS status webhook."""
        try:
            message_sid = webhook_data.get("MessageSid")
            message_status = webhook_data.get("MessageStatus")
            
            if not message_sid or not message_status:
                return {
                    "success": False,
                    "error": "Missing required webhook fields"
                }
            
            # Find delivery record by platform message ID
            result = await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.platform_message_id == message_sid
                )
            )
            
            delivery = result.scalar_one_or_none()
            if not delivery:
                return {
                    "success": False,
                    "error": f"Delivery record not found for message {message_sid}"
                }
            
            # Map Twilio status to our status
            status_mapping = {
                "queued": DeliveryTrackingStatus.PENDING,
                "sent": DeliveryTrackingStatus.SENT,
                "delivered": DeliveryTrackingStatus.DELIVERED,
                "failed": DeliveryTrackingStatus.FAILED,
                "undelivered": DeliveryTrackingStatus.FAILED
            }
            
            new_status = status_mapping.get(message_status, DeliveryTrackingStatus.FAILED)
            
            # Create status update
            update = DeliveryStatusUpdate(
                delivery_id=delivery.id,
                platform_message_id=message_sid,
                new_status=new_status,
                status_timestamp=datetime.utcnow(),
                provider_response=webhook_data,
                error_code=webhook_data.get("ErrorCode"),
                error_message=webhook_data.get("ErrorMessage")
            )
            
            return await self.update_delivery_status(update, db)
            
        except Exception as e:
            logger.error(f"Error processing Twilio webhook: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _process_sendgrid_webhook(
        self,
        webhook_data: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Process SendGrid email status webhook."""
        try:
            # SendGrid sends array of events
            events = webhook_data if isinstance(webhook_data, list) else [webhook_data]
            processed_count = 0
            errors = []
            
            for event in events:
                try:
                    sg_message_id = event.get("sg_message_id")
                    event_type = event.get("event")
                    timestamp = event.get("timestamp")
                    
                    if not sg_message_id or not event_type:
                        continue
                    
                    # Find delivery record
                    result = await db.execute(
                        select(NotificationDelivery).where(
                            NotificationDelivery.platform_message_id == sg_message_id
                        )
                    )
                    
                    delivery = result.scalar_one_or_none()
                    if not delivery:
                        continue
                    
                    # Map SendGrid event to our status
                    status_mapping = {
                        "processed": DeliveryTrackingStatus.SENT,
                        "delivered": DeliveryTrackingStatus.DELIVERED,
                        "open": DeliveryTrackingStatus.OPENED,
                        "click": DeliveryTrackingStatus.CLICKED,
                        "bounce": DeliveryTrackingStatus.BOUNCED,
                        "dropped": DeliveryTrackingStatus.FAILED,
                        "deferred": DeliveryTrackingStatus.PENDING,
                        "spamreport": DeliveryTrackingStatus.COMPLAINED,
                        "unsubscribe": DeliveryTrackingStatus.UNSUBSCRIBED
                    }
                    
                    new_status = status_mapping.get(event_type, DeliveryTrackingStatus.FAILED)
                    
                    # Create status update
                    update = DeliveryStatusUpdate(
                        delivery_id=delivery.id,
                        platform_message_id=sg_message_id,
                        new_status=new_status,
                        status_timestamp=datetime.fromtimestamp(timestamp) if timestamp else datetime.utcnow(),
                        provider_response=event,
                        error_code=event.get("reason"),
                        error_message=event.get("reason")
                    )
                    
                    result = await self.update_delivery_status(update, db)
                    if result["success"]:
                        processed_count += 1
                    else:
                        errors.append(result["error"])
                        
                except Exception as e:
                    errors.append(str(e))
            
            return {
                "success": processed_count > 0,
                "processed_events": processed_count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error processing SendGrid webhook: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def process_retry_queue(self, db: AsyncSession) -> Dict[str, Any]:
        """Process notifications that need to be retried."""
        try:
            # Find notifications ready for retry
            current_time = datetime.utcnow()
            
            # Look for failed notifications that haven't exceeded max retries
            # and are scheduled for retry
            result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.status == NotificationStatus.FAILED,
                        Notification.retry_count < Notification.max_retries,
                        or_(
                            Notification.scheduled_at.is_(None),
                            Notification.scheduled_at <= current_time
                        )
                    )
                ).limit(100)  # Process in batches
            )
            
            notifications = result.scalars().all()
            
            processed_count = 0
            failed_count = 0
            
            for notification in notifications:
                try:
                    retry_result = await self._retry_notification(notification, db)
                    if retry_result["success"]:
                        processed_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Error retrying notification {notification.id}: {e}")
                    failed_count += 1
            
            await db.commit()
            
            return {
                "success": True,
                "processed": processed_count,
                "failed": failed_count,
                "total_found": len(notifications)
            }
            
        except Exception as e:
            logger.error(f"Error processing retry queue: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _retry_notification(
        self,
        notification: Notification,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Retry a failed notification."""
        try:
            # Get retry configuration for notification priority
            config = self.retry_configs.get(
                notification.priority,
                self.retry_configs[NotificationPriority.NORMAL]
            )
            
            # Calculate next retry delay
            retry_delay = self._calculate_retry_delay(
                notification.retry_count,
                config
            )
            
            # Update retry information
            notification.retry_count += 1
            notification.scheduled_at = datetime.utcnow() + timedelta(seconds=retry_delay)
            notification.status = NotificationStatus.PENDING
            notification.error_message = None
            
            # Find delivery records for this notification
            result = await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id
                )
            )
            
            deliveries = result.scalars().all()
            
            # Reset failed deliveries for retry
            for delivery in deliveries:
                if delivery.status == NotificationStatus.FAILED:
                    delivery.status = NotificationStatus.PENDING
                    delivery.retry_count += 1
                    delivery.error_code = None
                    delivery.error_message = None
                    delivery.failed_at = None
            
            await db.flush()
            
            logger.info(
                f"Scheduled notification {notification.id} for retry #{notification.retry_count} "
                f"in {retry_delay} seconds"
            )
            
            return {
                "success": True,
                "notification_id": notification.id,
                "retry_count": notification.retry_count,
                "retry_delay_seconds": retry_delay
            }
            
        except Exception as e:
            logger.error(f"Error scheduling retry for notification {notification.id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _calculate_retry_delay(
        self,
        retry_count: int,
        config: RetryConfiguration
    ) -> int:
        """Calculate delay before next retry attempt."""
        if config.strategy == RetryStrategy.IMMEDIATE:
            return 0
        
        elif config.strategy == RetryStrategy.LINEAR:
            delay = config.initial_delay_seconds * (retry_count + 1)
        
        elif config.strategy == RetryStrategy.EXPONENTIAL:
            delay = config.initial_delay_seconds * (config.backoff_multiplier ** retry_count)
        
        elif config.strategy == RetryStrategy.FIBONACCI:
            # Fibonacci sequence for delays
            fib_sequence = [1, 1]
            for i in range(2, retry_count + 2):
                fib_sequence.append(fib_sequence[i-1] + fib_sequence[i-2])
            delay = config.initial_delay_seconds * fib_sequence[retry_count]
        
        else:
            delay = config.initial_delay_seconds
        
        # Cap the delay at maximum
        return min(int(delay), config.max_delay_seconds)
    
    async def _get_notification(
        self,
        notification_id: int,
        db: AsyncSession
    ) -> Optional[Notification]:
        """Get notification by ID."""
        try:
            result = await db.execute(
                select(Notification).where(Notification.id == notification_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting notification {notification_id}: {e}")
            return None
    
    async def _update_notification_status(
        self,
        notification: Notification,
        delivery_status: DeliveryTrackingStatus,
        db: AsyncSession
    ):
        """Update notification status based on delivery status."""
        try:
            # Get all delivery records for this notification
            result = await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id
                )
            )
            
            deliveries = result.scalars().all()
            
            if not deliveries:
                return
            
            # Determine overall notification status
            delivered_count = sum(1 for d in deliveries if d.status == NotificationStatus.DELIVERED)
            failed_count = sum(1 for d in deliveries if d.status == NotificationStatus.FAILED)
            pending_count = sum(1 for d in deliveries if d.status == NotificationStatus.PENDING)
            sent_count = sum(1 for d in deliveries if d.status == NotificationStatus.SENT)
            
            if delivered_count > 0:
                # At least one delivery succeeded
                notification.status = NotificationStatus.DELIVERED
                if not notification.delivered_at:
                    notification.delivered_at = datetime.utcnow()
            elif sent_count > 0 or pending_count > 0:
                # Some deliveries are still in progress
                notification.status = NotificationStatus.SENT
                if not notification.sent_at:
                    notification.sent_at = datetime.utcnow()
            elif failed_count == len(deliveries):
                # All deliveries failed
                notification.status = NotificationStatus.FAILED
            
            await db.flush()
            
        except Exception as e:
            logger.error(f"Error updating notification status: {e}")
    
    async def _schedule_retry(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
        db: AsyncSession
    ):
        """Schedule retry for failed delivery."""
        try:
            config = self.retry_configs.get(
                notification.priority,
                self.retry_configs[NotificationPriority.NORMAL]
            )
            
            # Check if we should retry
            if delivery.retry_count >= config.max_retries:
                logger.info(f"Delivery {delivery.id} exceeded max retries ({config.max_retries})")
                return
            
            # Calculate retry delay
            retry_delay = self._calculate_retry_delay(delivery.retry_count, config)
            
            # We don't schedule individual delivery retries here
            # Instead, the notification will be processed by the retry queue
            logger.info(
                f"Delivery {delivery.id} will be retried with notification {notification.id} "
                f"after {retry_delay} seconds"
            )
            
        except Exception as e:
            logger.error(f"Error scheduling retry: {e}")
    
    async def get_delivery_statistics(self, db: AsyncSession) -> Dict[str, Any]:
        """Get delivery statistics and metrics."""
        try:
            # Overall delivery stats
            result = await db.execute(
                select(
                    NotificationDelivery.status,
                    func.count(NotificationDelivery.id).label('count')
                ).group_by(NotificationDelivery.status)
            )
            
            status_counts = {status: count for status, count in result.fetchall()}
            
            # Platform-specific stats
            result = await db.execute(
                select(
                    NotificationDelivery.platform,
                    NotificationDelivery.status,
                    func.count(NotificationDelivery.id).label('count')
                ).group_by(NotificationDelivery.platform, NotificationDelivery.status)
            )
            
            platform_stats = {}
            for platform, status, count in result.fetchall():
                if platform.value not in platform_stats:
                    platform_stats[platform.value] = {}
                platform_stats[platform.value][status.value] = count
            
            # Retry statistics
            result = await db.execute(
                select(
                    func.avg(Notification.retry_count).label('avg_retries'),
                    func.max(Notification.retry_count).label('max_retries'),
                    func.count(Notification.id).filter(Notification.retry_count > 0).label('retried_notifications')
                )
            )
            
            retry_stats = result.fetchone()
            
            return {
                "status_counts": status_counts,
                "platform_stats": platform_stats,
                "retry_stats": {
                    "average_retries": float(retry_stats.avg_retries) if retry_stats.avg_retries else 0,
                    "max_retries": retry_stats.max_retries or 0,
                    "retried_notifications": retry_stats.retried_notifications or 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting delivery statistics: {e}")
            return {"error": str(e)}