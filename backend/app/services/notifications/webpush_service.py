"""Web Push service for browser push notifications."""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

from pywebpush import webpush, WebPushException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notifications import (
    DeviceToken, Notification, NotificationDelivery,
    NotificationStatus, DevicePlatform
)

logger = logging.getLogger(__name__)


@dataclass
class WebPushNotificationData:
    """Structured data for Web Push notifications."""
    title: str
    message: str
    data: Dict[str, Any] = None
    actions: List[Dict[str, str]] = None
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    badge_url: Optional[str] = None
    click_action: Optional[str] = None
    require_interaction: bool = False
    silent: bool = False
    tag: Optional[str] = None
    timestamp: Optional[int] = None
    ttl: int = 86400  # 24 hours default


class WebPushService:
    """Service for sending Web Push notifications to browsers."""
    
    def __init__(self):
        self._initialized = False
        self._vapid_claims = {}
        self._initialize_vapid()
    
    def _initialize_vapid(self) -> None:
        """Initialize VAPID configuration for Web Push."""
        try:
            if not settings.WEB_PUSH_VAPID_PUBLIC_KEY or not settings.WEB_PUSH_VAPID_PRIVATE_KEY:
                logger.warning("VAPID keys not configured. Web Push notifications will be disabled.")
                return
            
            if not settings.WEB_PUSH_VAPID_SUBJECT:
                logger.warning("VAPID subject not configured. Web Push notifications may fail.")
                return
            
            self._vapid_claims = {
                "sub": settings.WEB_PUSH_VAPID_SUBJECT
            }
            
            self._initialized = True
            logger.info("Web Push service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Web Push service: {e}")
            self._initialized = False
    
    def is_available(self) -> bool:
        """Check if Web Push service is available and configured."""
        return self._initialized
    
    async def send_notification(
        self,
        subscriptions: List[Dict[str, Any]],
        notification_data: WebPushNotificationData,
        notification_id: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Send Web Push notification to multiple browser subscriptions.
        
        Args:
            subscriptions: List of Web Push subscription objects
            notification_data: Notification content and metadata
            notification_id: Database notification ID for tracking
            db: Database session for logging delivery attempts
            
        Returns:
            Dictionary with delivery results and statistics
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "Web Push service not initialized",
                "sent_count": 0,
                "failed_count": len(subscriptions),
                "results": []
            }
        
        if not subscriptions:
            return {
                "success": True,
                "sent_count": 0,
                "failed_count": 0,
                "results": []
            }
        
        success_count = 0
        failed_count = 0
        delivery_results = []
        
        for subscription in subscriptions:
            try:
                result = await self._send_single_notification(
                    subscription, notification_data, notification_id, db
                )
                
                if result["success"]:
                    success_count += 1
                    delivery_results.append({
                        "subscription_endpoint": subscription.get("endpoint", "unknown"),
                        "status": "sent"
                    })
                else:
                    failed_count += 1
                    delivery_results.append({
                        "subscription_endpoint": subscription.get("endpoint", "unknown"),
                        "status": "failed",
                        "error": result.get("error", "Unknown error")
                    })
                    
            except Exception as e:
                failed_count += 1
                endpoint = subscription.get("endpoint", "unknown")
                logger.error(f"Web Push send error for {endpoint}: {e}")
                
                delivery_results.append({
                    "subscription_endpoint": endpoint,
                    "status": "failed",
                    "error": str(e)
                })
                
                # Log failed delivery if database session provided
                if db and notification_id:
                    await self._log_delivery_failure(
                        db, notification_id, endpoint, str(e)
                    )
        
        return {
            "success": success_count > 0,
            "sent_count": success_count,
            "failed_count": failed_count,
            "results": delivery_results
        }
    
    async def _send_single_notification(
        self,
        subscription: Dict[str, Any],
        notification_data: WebPushNotificationData,
        notification_id: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Send Web Push notification to a single subscription."""
        try:
            # Build notification payload
            payload = self._build_notification_payload(notification_data)
            
            # Send the notification
            response = webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": subscription["keys"]
                },
                data=json.dumps(payload),
                vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
                vapid_claims=self._vapid_claims,
                ttl=notification_data.ttl
            )
            
            # Log successful delivery if database session provided
            if db and notification_id:
                await self._log_delivery_success(
                    db, notification_id, subscription["endpoint"], 
                    response.status_code if hasattr(response, 'status_code') else None
                )
            
            return {
                "success": True,
                "status_code": response.status_code if hasattr(response, 'status_code') else 200
            }
            
        except WebPushException as e:
            error_message = f"Web Push error: {e}"
            logger.error(error_message)
            
            # Handle specific error codes
            if hasattr(e, 'response') and e.response:
                status_code = e.response.status_code
                if status_code == 410:
                    # Subscription expired or invalid - should be removed
                    error_message = "Subscription expired or invalid"
                elif status_code == 413:
                    # Payload too large
                    error_message = "Notification payload too large"
                elif status_code == 429:
                    # Rate limited
                    error_message = "Rate limited by push service"
            
            # Log failed delivery if database session provided
            if db and notification_id:
                await self._log_delivery_failure(
                    db, notification_id, subscription["endpoint"], error_message
                )
            
            return {
                "success": False,
                "error": error_message,
                "should_retry": status_code not in [400, 410, 413] if 'status_code' in locals() else True
            }
        
        except Exception as e:
            error_message = f"Unexpected error: {e}"
            logger.error(error_message)
            
            # Log failed delivery if database session provided
            if db and notification_id:
                await self._log_delivery_failure(
                    db, notification_id, subscription["endpoint"], error_message
                )
            
            return {
                "success": False,
                "error": error_message,
                "should_retry": True
            }
    
    def _build_notification_payload(self, notification_data: WebPushNotificationData) -> Dict[str, Any]:
        """Build Web Push notification payload."""
        payload = {
            "title": notification_data.title,
            "body": notification_data.message,
            "tag": notification_data.tag or "attendance-notification",
            "timestamp": notification_data.timestamp or int(datetime.utcnow().timestamp() * 1000),
            "requireInteraction": notification_data.require_interaction,
            "silent": notification_data.silent,
            "data": notification_data.data or {}
        }
        
        # Add optional visual elements
        if notification_data.icon_url:
            payload["icon"] = notification_data.icon_url
        
        if notification_data.image_url:
            payload["image"] = notification_data.image_url
        
        if notification_data.badge_url:
            payload["badge"] = notification_data.badge_url
        
        # Add actions for rich notifications
        if notification_data.actions:
            payload["actions"] = notification_data.actions
        
        # Add click action URL
        if notification_data.click_action:
            payload["data"]["clickAction"] = notification_data.click_action
        
        return payload
    
    async def _log_delivery_success(
        self,
        db: AsyncSession,
        notification_id: int,
        endpoint: str,
        status_code: Optional[int]
    ) -> None:
        """Log successful delivery to database."""
        try:
            # Find device token record by endpoint
            device_token_record = await db.execute(
                f"SELECT * FROM device_tokens WHERE token LIKE '%{endpoint[-50:]}%' AND platform = 'web'"
            )
            device_token = device_token_record.scalar_one_or_none()
            
            if device_token:
                delivery = NotificationDelivery(
                    notification_id=notification_id,
                    device_token_id=device_token.id,
                    platform=DevicePlatform.WEB,
                    status=NotificationStatus.SENT,
                    platform_response={"status_code": status_code} if status_code else None,
                    sent_at=datetime.utcnow()
                )
                db.add(delivery)
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to log delivery success: {e}")
    
    async def _log_delivery_failure(
        self,
        db: AsyncSession,
        notification_id: int,
        endpoint: str,
        error_message: str
    ) -> None:
        """Log failed delivery to database."""
        try:
            # Find device token record by endpoint
            device_token_record = await db.execute(
                f"SELECT * FROM device_tokens WHERE token LIKE '%{endpoint[-50:]}%' AND platform = 'web'"
            )
            device_token = device_token_record.scalar_one_or_none()
            
            if device_token:
                delivery = NotificationDelivery(
                    notification_id=notification_id,
                    device_token_id=device_token.id,
                    platform=DevicePlatform.WEB,
                    status=NotificationStatus.FAILED,
                    error_message=error_message,
                    failed_at=datetime.utcnow()
                )
                db.add(delivery)
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to log delivery failure: {e}")
    
    async def validate_subscription(self, subscription: Dict[str, Any]) -> bool:
        """Validate if a Web Push subscription is still valid."""
        if not self._initialized:
            return False
        
        try:
            # Try to send a test notification (empty payload for validation)
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": subscription["keys"]
                },
                data="",
                vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
                vapid_claims=self._vapid_claims,
                ttl=0  # Minimal TTL for validation
            )
            return True
        except WebPushException as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 410:
                # Subscription expired/invalid
                return False
            # Other errors might be temporary, so consider valid for now
            logger.warning(f"Subscription validation warning: {e}")
            return True
        except Exception as e:
            logger.warning(f"Subscription validation failed: {e}")
            return False
    
    def get_vapid_public_key(self) -> Optional[str]:
        """Get the VAPID public key for client-side subscription."""
        return settings.WEB_PUSH_VAPID_PUBLIC_KEY if self._initialized else None
    
    async def cleanup_expired_subscriptions(self, db: AsyncSession) -> int:
        """Remove expired or invalid Web Push subscriptions from database."""
        if not self._initialized:
            return 0
        
        try:
            # Get all web device tokens
            web_tokens = await db.execute(
                "SELECT * FROM device_tokens WHERE platform = 'web' AND is_active = true"
            )
            tokens = web_tokens.scalars().all()
            
            removed_count = 0
            for token in tokens:
                try:
                    # Parse subscription from token
                    subscription = json.loads(token.token)
                    
                    # Validate subscription
                    if not await self.validate_subscription(subscription):
                        # Mark as inactive
                        token.is_active = False
                        removed_count += 1
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Invalid subscription format for token {token.id}: {e}")
                    token.is_active = False
                    removed_count += 1
            
            await db.commit()
            logger.info(f"Cleaned up {removed_count} expired Web Push subscriptions")
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired subscriptions: {e}")
            return 0