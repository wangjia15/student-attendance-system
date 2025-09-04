"""Main notification manager that coordinates all notification services."""

import logging
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.notifications import (
    Notification, NotificationPreferences, DeviceToken, NotificationDelivery,
    NotificationType, NotificationStatus, NotificationPriority, DevicePlatform
)
from app.models.user import User
from .fcm_service import FCMService, FCMNotificationData
from .webpush_service import WebPushService, WebPushNotificationData
from .batching_service import NotificationBatchingService

logger = logging.getLogger(__name__)


@dataclass
class NotificationRequest:
    """Request to send a notification."""
    user_ids: List[int]
    type: NotificationType
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    data: Dict[str, Any] = None
    actions: List[Dict[str, str]] = None
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    click_action: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    class_session_id: Optional[int] = None
    attendance_record_id: Optional[int] = None


class NotificationManager:
    """Main service for managing all types of push notifications."""
    
    def __init__(self):
        self.fcm_service = FCMService()
        self.webpush_service = WebPushService()
        self.batching_service = NotificationBatchingService()
        logger.info("Notification Manager initialized")
    
    async def send_notification(
        self,
        request: NotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Send notification to multiple users across all platforms.
        
        Args:
            request: Notification request with all details
            db: Database session
            
        Returns:
            Summary of delivery results
        """
        logger.info(f"Processing notification request for {len(request.user_ids)} users")
        
        total_sent = 0
        total_failed = 0
        user_results = {}
        
        # Process each user individually
        for user_id in request.user_ids:
            try:
                result = await self._send_to_user(user_id, request, db)
                user_results[user_id] = result
                total_sent += result.get("sent_count", 0)
                total_failed += result.get("failed_count", 0)
                
            except Exception as e:
                logger.error(f"Failed to send notification to user {user_id}: {e}")
                user_results[user_id] = {
                    "success": False,
                    "error": str(e),
                    "sent_count": 0,
                    "failed_count": 1
                }
                total_failed += 1
        
        return {
            "success": total_sent > 0,
            "total_sent": total_sent,
            "total_failed": total_failed,
            "user_results": user_results
        }
    
    async def _send_to_user(
        self,
        user_id: int,
        request: NotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notification to a single user across all their devices."""
        try:
            # Get user preferences
            preferences = await self._get_user_preferences(user_id, db)
            if not preferences or not preferences.enabled:
                return {
                    "success": False,
                    "reason": "Notifications disabled for user",
                    "sent_count": 0,
                    "failed_count": 0
                }
            
            # Check if user wants this type of notification
            if not self._is_notification_type_enabled(request.type, preferences):
                return {
                    "success": False,
                    "reason": f"Notification type {request.type.value} disabled for user",
                    "sent_count": 0,
                    "failed_count": 0
                }
            
            # Create notification record
            notification = await self._create_notification_record(user_id, request, db)
            
            # Check if notification should be batched
            should_batch, batch_reason = await self.batching_service.should_batch_notification(
                notification, preferences, db
            )
            
            if should_batch:
                batch_id = await self.batching_service.add_to_batch(notification, preferences, db)
                return {
                    "success": True,
                    "reason": f"Added to batch: {batch_reason}",
                    "batch_id": batch_id,
                    "sent_count": 0,
                    "failed_count": 0
                }
            
            # Send immediately
            return await self._send_immediate_notification(notification, preferences, db)
            
        except Exception as e:
            logger.error(f"Error sending notification to user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "sent_count": 0,
                "failed_count": 1
            }
    
    async def _send_immediate_notification(
        self,
        notification: Notification,
        preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notification immediately to all user's devices."""
        try:
            # Get user's device tokens
            device_tokens = await self._get_user_device_tokens(notification.user_id, db)
            
            if not device_tokens:
                return {
                    "success": False,
                    "reason": "No device tokens found for user",
                    "sent_count": 0,
                    "failed_count": 0
                }
            
            # Group tokens by platform
            ios_tokens = []
            android_tokens = []
            web_subscriptions = []
            
            for token in device_tokens:
                if not token.is_active:
                    continue
                    
                if token.platform == DevicePlatform.IOS:
                    ios_tokens.append(token.token)
                elif token.platform == DevicePlatform.ANDROID:
                    android_tokens.append(token.token)
                elif token.platform == DevicePlatform.WEB:
                    try:
                        subscription = json.loads(token.token)
                        web_subscriptions.append(subscription)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid web push subscription for token {token.id}")
            
            # Send to mobile platforms via FCM
            fcm_result = {"sent_count": 0, "failed_count": 0}
            if (ios_tokens or android_tokens) and self.fcm_service.is_available():
                all_fcm_tokens = ios_tokens + android_tokens
                fcm_data = FCMNotificationData(
                    title=notification.title,
                    message=notification.message,
                    data=notification.data,
                    actions=notification.actions,
                    image_url=notification.image_url,
                    icon_url=notification.icon_url,
                    click_action=notification.click_action
                )
                
                fcm_result = await self.fcm_service.send_notification(
                    all_fcm_tokens, fcm_data, notification.id, db
                )
            
            # Send to web browsers via Web Push
            web_result = {"sent_count": 0, "failed_count": 0}
            if web_subscriptions and self.webpush_service.is_available():
                web_data = WebPushNotificationData(
                    title=notification.title,
                    message=notification.message,
                    data=notification.data,
                    actions=notification.actions,
                    image_url=notification.image_url,
                    icon_url=notification.icon_url,
                    click_action=notification.click_action,
                    require_interaction=(notification.priority in [
                        NotificationPriority.HIGH, 
                        NotificationPriority.URGENT
                    ]),
                    tag=f"notification-{notification.id}"
                )
                
                web_result = await self.webpush_service.send_notification(
                    web_subscriptions, web_data, notification.id, db
                )
            
            # Update notification status
            total_sent = fcm_result["sent_count"] + web_result["sent_count"]
            total_failed = fcm_result["failed_count"] + web_result["failed_count"]
            
            if total_sent > 0:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "Failed to send to all platforms"
            
            await db.commit()
            
            return {
                "success": total_sent > 0,
                "sent_count": total_sent,
                "failed_count": total_failed,
                "fcm_result": fcm_result,
                "web_result": web_result
            }
            
        except Exception as e:
            logger.error(f"Error sending immediate notification: {e}")
            notification.status = NotificationStatus.FAILED
            notification.error_message = str(e)
            await db.commit()
            
            return {
                "success": False,
                "error": str(e),
                "sent_count": 0,
                "failed_count": 1
            }
    
    async def _create_notification_record(
        self,
        user_id: int,
        request: NotificationRequest,
        db: AsyncSession
    ) -> Notification:
        """Create notification database record."""
        notification = Notification(
            user_id=user_id,
            type=request.type,
            priority=request.priority,
            title=request.title,
            message=request.message,
            data=request.data,
            actions=request.actions,
            image_url=request.image_url,
            icon_url=request.icon_url,
            click_action=request.click_action,
            scheduled_at=request.scheduled_at,
            expires_at=request.expires_at,
            class_session_id=request.class_session_id,
            attendance_record_id=request.attendance_record_id,
            status=NotificationStatus.PENDING
        )
        
        db.add(notification)
        await db.flush()  # Get the ID
        return notification
    
    async def _get_user_preferences(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Optional[NotificationPreferences]:
        """Get user's notification preferences."""
        try:
            result = await db.execute(
                select(NotificationPreferences).where(
                    NotificationPreferences.user_id == user_id
                )
            )
            return result.scalar_one_or_none()
            
        except Exception as e:
            logger.error(f"Error getting user preferences: {e}")
            return None
    
    async def _get_user_device_tokens(
        self,
        user_id: int,
        db: AsyncSession
    ) -> List[DeviceToken]:
        """Get all active device tokens for a user."""
        try:
            result = await db.execute(
                select(DeviceToken).where(
                    and_(
                        DeviceToken.user_id == user_id,
                        DeviceToken.is_active == True
                    )
                )
            )
            return result.scalars().all()
            
        except Exception as e:
            logger.error(f"Error getting device tokens: {e}")
            return []
    
    def _is_notification_type_enabled(
        self,
        notification_type: NotificationType,
        preferences: NotificationPreferences
    ) -> bool:
        """Check if a specific notification type is enabled for the user."""
        type_mapping = {
            NotificationType.ATTENDANCE_REMINDER: preferences.attendance_reminders,
            NotificationType.LATE_ARRIVAL: preferences.late_arrival_alerts,
            NotificationType.ABSENT_ALERT: preferences.absent_alerts,
            NotificationType.CLASS_STARTED: preferences.class_notifications,
            NotificationType.CLASS_ENDED: preferences.class_notifications,
            NotificationType.PATTERN_ALERT: preferences.pattern_alerts,
            NotificationType.SYSTEM_ANNOUNCEMENT: preferences.system_announcements,
            NotificationType.ACHIEVEMENT_BADGE: preferences.achievement_notifications
        }
        
        return type_mapping.get(notification_type, True)
    
    async def process_scheduled_notifications(self, db: AsyncSession) -> Dict[str, Any]:
        """Process all scheduled notifications that are ready to send."""
        try:
            # Find scheduled notifications ready to send
            current_time = datetime.utcnow()
            result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.status == NotificationStatus.PENDING,
                        Notification.scheduled_at <= current_time,
                        Notification.is_batched == False,  # Not part of a batch
                        or_(
                            Notification.expires_at.is_(None),
                            Notification.expires_at > current_time
                        )
                    )
                )
            )
            
            scheduled_notifications = result.scalars().all()
            processed_count = 0
            failed_count = 0
            
            for notification in scheduled_notifications:
                try:
                    preferences = await self._get_user_preferences(notification.user_id, db)
                    if preferences and preferences.enabled:
                        result = await self._send_immediate_notification(notification, preferences, db)
                        if result["success"]:
                            processed_count += 1
                        else:
                            failed_count += 1
                    else:
                        # Mark as failed if user disabled notifications
                        notification.status = NotificationStatus.FAILED
                        notification.error_message = "User notifications disabled"
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Error processing scheduled notification {notification.id}: {e}")
                    notification.status = NotificationStatus.FAILED
                    notification.error_message = str(e)
                    failed_count += 1
            
            # Process ready batches
            processed_batches = await self.batching_service.process_ready_batches(db)
            
            await db.commit()
            
            return {
                "success": True,
                "processed_notifications": processed_count,
                "failed_notifications": failed_count,
                "processed_batches": len(processed_batches),
                "batch_ids": processed_batches
            }
            
        except Exception as e:
            logger.error(f"Error processing scheduled notifications: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def cleanup_expired_notifications(self, db: AsyncSession) -> Dict[str, Any]:
        """Clean up expired notifications and invalid device tokens."""
        try:
            # Mark expired notifications
            current_time = datetime.utcnow()
            result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.status == NotificationStatus.PENDING,
                        Notification.expires_at <= current_time
                    )
                )
            )
            
            expired_notifications = result.scalars().all()
            for notification in expired_notifications:
                notification.status = NotificationStatus.EXPIRED
            
            # Clean up old delivered notifications (older than 30 days)
            cutoff_date = current_time - timedelta(days=30)
            old_notifications_result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.status.in_([
                            NotificationStatus.DELIVERED,
                            NotificationStatus.READ
                        ]),
                        Notification.sent_at <= cutoff_date
                    )
                )
            )
            
            old_notifications = old_notifications_result.scalars().all()
            for notification in old_notifications:
                await db.delete(notification)
            
            # Clean up expired web push subscriptions
            web_cleanup_count = await self.webpush_service.cleanup_expired_subscriptions(db)
            
            await db.commit()
            
            return {
                "success": True,
                "expired_notifications": len(expired_notifications),
                "deleted_old_notifications": len(old_notifications),
                "cleaned_web_subscriptions": web_cleanup_count
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up notifications: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def register_device_token(
        self,
        user_id: int,
        platform: DevicePlatform,
        token: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        app_version: Optional[str] = None,
        os_version: Optional[str] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Register or update a device token for push notifications."""
        try:
            # Check if token already exists
            result = await db.execute(
                select(DeviceToken).where(
                    DeviceToken.token == token
                )
            )
            
            existing_token = result.scalar_one_or_none()
            
            if existing_token:
                # Update existing token
                existing_token.user_id = user_id
                existing_token.platform = platform
                existing_token.device_id = device_id
                existing_token.device_name = device_name
                existing_token.app_version = app_version
                existing_token.os_version = os_version
                existing_token.is_active = True
                existing_token.last_used_at = datetime.utcnow()
                existing_token.updated_at = datetime.utcnow()
                
                token_record = existing_token
            else:
                # Create new token
                token_record = DeviceToken(
                    user_id=user_id,
                    platform=platform,
                    token=token,
                    device_id=device_id,
                    device_name=device_name,
                    app_version=app_version,
                    os_version=os_version,
                    is_active=True,
                    last_used_at=datetime.utcnow()
                )
                
                db.add(token_record)
            
            await db.commit()
            
            return {
                "success": True,
                "token_id": token_record.id,
                "is_new": existing_token is None
            }
            
        except Exception as e:
            logger.error(f"Error registering device token: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_notification_statistics(self, db: AsyncSession) -> Dict[str, Any]:
        """Get comprehensive notification system statistics."""
        try:
            # Get basic notification counts
            notification_stats = {}
            for status in NotificationStatus:
                result = await db.execute(
                    select(Notification).where(Notification.status == status)
                )
                notification_stats[status.value] = len(result.scalars().all())
            
            # Get platform delivery stats
            platform_stats = {}
            for platform in DevicePlatform:
                result = await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.platform == platform
                    )
                )
                platform_stats[platform.value] = len(result.scalars().all())
            
            # Get batching statistics
            batch_stats = await self.batching_service.get_batch_statistics(db)
            
            # Get service availability
            service_status = {
                "fcm_available": self.fcm_service.is_available(),
                "webpush_available": self.webpush_service.is_available()
            }
            
            return {
                "notification_counts": notification_stats,
                "platform_deliveries": platform_stats,
                "batching_stats": batch_stats,
                "service_status": service_status
            }
            
        except Exception as e:
            logger.error(f"Error getting notification statistics: {e}")
            return {"error": str(e)}