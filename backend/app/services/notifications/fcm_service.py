"""Firebase Cloud Messaging (FCM) service for Android and iOS push notifications."""

import json
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, messaging
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notifications import (
    DeviceToken, Notification, NotificationDelivery, 
    NotificationStatus, DevicePlatform
)

logger = logging.getLogger(__name__)


@dataclass
class FCMNotificationData:
    """Structured data for FCM notifications."""
    title: str
    message: str
    data: Dict[str, Any] = None
    actions: List[Dict[str, str]] = None
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    click_action: Optional[str] = None


class FCMService:
    """Service for sending Firebase Cloud Messaging notifications."""
    
    def __init__(self):
        self._initialized = False
        self._app = None
        self._initialize_firebase()
    
    def _initialize_firebase(self) -> None:
        """Initialize Firebase Admin SDK."""
        try:
            if not settings.FCM_SERVICE_ACCOUNT_PATH:
                logger.warning("FCM_SERVICE_ACCOUNT_PATH not configured. FCM notifications will be disabled.")
                return
            
            # Check if Firebase app is already initialized
            try:
                self._app = firebase_admin.get_app()
                logger.info("Firebase app already initialized")
            except ValueError:
                # Initialize Firebase app with service account
                cred = credentials.Certificate(settings.FCM_SERVICE_ACCOUNT_PATH)
                self._app = firebase_admin.initialize_app(cred)
                logger.info("Firebase app initialized successfully")
            
            self._initialized = True
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            self._initialized = False
    
    def is_available(self) -> bool:
        """Check if FCM service is available and configured."""
        return self._initialized
    
    async def send_notification(
        self,
        device_tokens: List[str],
        notification_data: FCMNotificationData,
        notification_id: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Send FCM notification to multiple devices.
        
        Args:
            device_tokens: List of FCM device tokens
            notification_data: Notification content and metadata
            notification_id: Database notification ID for tracking
            db: Database session for logging delivery attempts
            
        Returns:
            Dictionary with delivery results and statistics
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "FCM service not initialized",
                "sent_count": 0,
                "failed_count": len(device_tokens),
                "results": []
            }
        
        if not device_tokens:
            return {
                "success": True,
                "sent_count": 0,
                "failed_count": 0,
                "results": []
            }
        
        try:
            # Build FCM message
            message = self._build_fcm_message(notification_data)
            
            # Send to multiple tokens
            if len(device_tokens) == 1:
                response = await self._send_single_message(device_tokens[0], message)
                results = [response]
            else:
                response = await self._send_multicast_message(device_tokens, message)
                results = response.responses if hasattr(response, 'responses') else []
            
            # Process results
            success_count = 0
            failed_count = 0
            delivery_results = []
            
            for i, result in enumerate(results):
                token = device_tokens[i] if i < len(device_tokens) else "unknown"
                
                if hasattr(result, 'success') and result.success:
                    success_count += 1
                    delivery_results.append({
                        "token": token,
                        "status": "sent",
                        "message_id": getattr(result, 'message_id', None)
                    })
                    
                    # Log successful delivery if database session provided
                    if db and notification_id:
                        await self._log_delivery_success(
                            db, notification_id, token, 
                            getattr(result, 'message_id', None)
                        )
                else:
                    failed_count += 1
                    error_message = getattr(result, 'exception', 'Unknown error')
                    delivery_results.append({
                        "token": token,
                        "status": "failed",
                        "error": str(error_message)
                    })
                    
                    # Log failed delivery if database session provided
                    if db and notification_id:
                        await self._log_delivery_failure(
                            db, notification_id, token, str(error_message)
                        )
            
            return {
                "success": success_count > 0,
                "sent_count": success_count,
                "failed_count": failed_count,
                "results": delivery_results
            }
            
        except Exception as e:
            logger.error(f"FCM send error: {e}")
            
            # Log error for all tokens if database session provided
            if db and notification_id:
                for token in device_tokens:
                    await self._log_delivery_failure(db, notification_id, token, str(e))
            
            return {
                "success": False,
                "error": str(e),
                "sent_count": 0,
                "failed_count": len(device_tokens),
                "results": []
            }
    
    def _build_fcm_message(self, notification_data: FCMNotificationData) -> messaging.Message:
        """Build FCM message from notification data."""
        
        # Build notification payload
        notification = messaging.Notification(
            title=notification_data.title,
            body=notification_data.message,
            image=notification_data.image_url
        )
        
        # Build data payload
        data_payload = notification_data.data or {}
        
        # Add action data if present
        if notification_data.actions:
            data_payload["actions"] = json.dumps(notification_data.actions)
        
        # Add click action
        if notification_data.click_action:
            data_payload["click_action"] = notification_data.click_action
        
        # Add timestamp
        data_payload["timestamp"] = str(int(datetime.utcnow().timestamp()))
        
        # Build Android config for rich notifications
        android_config = messaging.AndroidConfig(
            ttl=86400,  # 24 hours TTL
            priority='high',
            notification=messaging.AndroidNotification(
                title=notification_data.title,
                body=notification_data.message,
                icon=notification_data.icon_url,
                image=notification_data.image_url,
                click_action=notification_data.click_action,
                tag="attendance_notification"
            )
        )
        
        # Build iOS config for rich notifications
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        title=notification_data.title,
                        body=notification_data.message
                    ),
                    badge=1,
                    sound="default",
                    mutable_content=True
                )
            )
        )
        
        return messaging.Message(
            notification=notification,
            data=data_payload,
            android=android_config,
            apns=apns_config
        )
    
    async def _send_single_message(self, token: str, message: messaging.Message) -> Any:
        """Send message to a single device token."""
        message.token = token
        return messaging.send(message)
    
    async def _send_multicast_message(
        self, 
        tokens: List[str], 
        message: messaging.Message
    ) -> messaging.BatchResponse:
        """Send message to multiple device tokens."""
        multicast_message = messaging.MulticastMessage(
            tokens=tokens,
            notification=message.notification,
            data=message.data,
            android=message.android,
            apns=message.apns
        )
        return messaging.send_multicast(multicast_message)
    
    async def _log_delivery_success(
        self,
        db: AsyncSession,
        notification_id: int,
        token: str,
        message_id: Optional[str]
    ) -> None:
        """Log successful delivery to database."""
        try:
            # Find device token record
            device_token_record = await db.execute(
                f"SELECT * FROM device_tokens WHERE token = '{token}'"
            )
            device_token = device_token_record.scalar_one_or_none()
            
            if device_token:
                delivery = NotificationDelivery(
                    notification_id=notification_id,
                    device_token_id=device_token.id,
                    platform=DevicePlatform.ANDROID if device_token.platform == DevicePlatform.ANDROID else DevicePlatform.IOS,
                    status=NotificationStatus.SENT,
                    platform_message_id=message_id,
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
        token: str,
        error_message: str
    ) -> None:
        """Log failed delivery to database."""
        try:
            # Find device token record
            device_token_record = await db.execute(
                f"SELECT * FROM device_tokens WHERE token = '{token}'"
            )
            device_token = device_token_record.scalar_one_or_none()
            
            if device_token:
                delivery = NotificationDelivery(
                    notification_id=notification_id,
                    device_token_id=device_token.id,
                    platform=DevicePlatform.ANDROID if device_token.platform == DevicePlatform.ANDROID else DevicePlatform.IOS,
                    status=NotificationStatus.FAILED,
                    error_message=error_message,
                    failed_at=datetime.utcnow()
                )
                db.add(delivery)
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to log delivery failure: {e}")
    
    async def validate_token(self, token: str) -> bool:
        """Validate if a device token is still valid."""
        if not self._initialized:
            return False
        
        try:
            # Try to send a test message (dry run)
            test_message = messaging.Message(
                data={"test": "validation"},
                token=token
            )
            messaging.send(test_message, dry_run=True)
            return True
        except Exception as e:
            logger.warning(f"Token validation failed: {e}")
            return False
    
    async def subscribe_to_topic(self, tokens: List[str], topic: str) -> Dict[str, Any]:
        """Subscribe device tokens to a topic for broadcast notifications."""
        if not self._initialized:
            return {"success": False, "error": "FCM service not initialized"}
        
        try:
            response = messaging.subscribe_to_topic(tokens, topic)
            return {
                "success": response.success_count > 0,
                "success_count": response.success_count,
                "failure_count": response.failure_count,
                "errors": [str(error) for error in response.errors] if response.errors else []
            }
        except Exception as e:
            logger.error(f"Topic subscription failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def unsubscribe_from_topic(self, tokens: List[str], topic: str) -> Dict[str, Any]:
        """Unsubscribe device tokens from a topic."""
        if not self._initialized:
            return {"success": False, "error": "FCM service not initialized"}
        
        try:
            response = messaging.unsubscribe_from_topic(tokens, topic)
            return {
                "success": response.success_count > 0,
                "success_count": response.success_count,
                "failure_count": response.failure_count,
                "errors": [str(error) for error in response.errors] if response.errors else []
            }
        except Exception as e:
            logger.error(f"Topic unsubscription failed: {e}")
            return {"success": False, "error": str(e)}