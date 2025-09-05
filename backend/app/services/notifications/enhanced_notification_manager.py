"""Enhanced notification manager integrating SMS, email, bulk operations, and audit trails."""

import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import (
    Notification, NotificationPreferences, NotificationType, 
    NotificationStatus, NotificationPriority
)

# Import existing notification services
from .fcm_service import FCMService
from .webpush_service import WebPushService
from .batching_service import NotificationBatchingService

# Import new external notification services
from app.integrations.sms import SMSService
from app.integrations.email import EmailService

# Import new enhanced services
from .bulk_notification_service import BulkNotificationService, BulkNotificationRequest, BulkNotificationTarget
from .delivery_tracking_service import DeliveryTrackingService
from .audit_service import NotificationAuditService, AuditEvent, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)


@dataclass
class EnhancedNotificationRequest:
    """Enhanced notification request supporting all delivery methods."""
    user_ids: List[int]
    type: NotificationType
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    
    # Content options
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    template_id: Optional[str] = None
    template_data: Dict[str, Any] = None
    
    # Rich notification features
    data: Dict[str, Any] = None
    actions: List[Dict[str, str]] = None
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    click_action: Optional[str] = None
    
    # Delivery method control
    send_push: bool = True
    send_email: bool = False
    send_sms: bool = False
    include_parents: bool = False
    
    # Scheduling
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Context
    class_session_id: Optional[int] = None
    attendance_record_id: Optional[int] = None
    sender_id: Optional[int] = None
    
    # Audit context
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None


class EnhancedNotificationManager:
    """Enhanced notification manager with SMS, email, bulk operations, and audit trails."""
    
    def __init__(self):
        # Existing services
        self.fcm_service = FCMService()
        self.webpush_service = WebPushService()
        self.batching_service = NotificationBatchingService()
        
        # New external notification services
        self.sms_service = SMSService()
        self.email_service = EmailService()
        
        # New enhanced services
        self.bulk_service = BulkNotificationService()
        self.delivery_tracking = DeliveryTrackingService()
        self.audit_service = NotificationAuditService()
        
        logger.info("Enhanced Notification Manager initialized")
    
    async def send_notification(
        self,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Send enhanced notification with full feature support.
        
        Args:
            request: Enhanced notification request
            db: Database session
            
        Returns:
            Summary of delivery results with audit trail
        """
        try:
            # Log audit event for notification creation
            await self._log_notification_creation(request, db)
            
            # Check if this should be a bulk operation
            if len(request.user_ids) > 10:  # Threshold for bulk processing
                return await self._send_bulk_notification(request, db)
            else:
                return await self._send_individual_notifications(request, db)
                
        except Exception as e:
            logger.error(f"Error in enhanced notification send: {e}")
            
            # Log error event
            await self._log_error_event(
                action="send_notification_error",
                description=f"Failed to send notification: {str(e)}",
                actor_id=request.sender_id,
                additional_data={"error": str(e), "user_count": len(request.user_ids)},
                db=db
            )
            
            return {
                "success": False,
                "error": str(e),
                "total_sent": 0,
                "total_failed": len(request.user_ids)
            }
    
    async def _send_bulk_notification(
        self,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notification using bulk processing."""
        try:
            # Convert to bulk notification targets
            targets = []
            for user_id in request.user_ids:
                target = BulkNotificationTarget(
                    user_id=user_id,
                    custom_data=request.template_data or {}
                )
                targets.append(target)
            
            # Create bulk request
            bulk_request = BulkNotificationRequest(
                targets=targets,
                notification_type=request.type,
                title=request.title,
                message=request.message,
                priority=request.priority,
                html_content=request.html_content,
                template_id=request.template_id,
                template_data=request.template_data or {},
                send_email=request.send_email,
                send_sms=request.send_sms,
                send_push=request.send_push,
                include_parents=request.include_parents,
                scheduled_at=request.scheduled_at,
                expires_at=request.expires_at,
                sender_id=request.sender_id,
                class_session_id=request.class_session_id,
                metadata={
                    "request_id": request.request_id,
                    "source": "enhanced_notification_manager"
                }
            )
            
            # Send bulk notification
            result = await self.bulk_service.send_bulk_notification(bulk_request, db)
            
            # Log bulk completion event
            await self._log_bulk_completion(bulk_request, result, db)
            
            return {
                "success": result.status.value == "completed",
                "bulk_job_id": result.job_id,
                "total_targets": result.total_targets,
                "total_sent": result.successful_sends,
                "total_failed": result.failed_sends,
                "total_skipped": result.skipped_sends,
                "processing_time": result.processing_time,
                "errors": result.errors
            }
            
        except Exception as e:
            logger.error(f"Error in bulk notification send: {e}")
            raise
    
    async def _send_individual_notifications(
        self,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notifications individually with enhanced features."""
        total_sent = 0
        total_failed = 0
        user_results = {}
        
        for user_id in request.user_ids:
            try:
                result = await self._send_to_single_user(user_id, request, db)
                user_results[user_id] = result
                
                if result.get("success"):
                    total_sent += result.get("sent_count", 0)
                else:
                    total_failed += 1
                    
            except Exception as e:
                logger.error(f"Failed to send notification to user {user_id}: {e}")
                user_results[user_id] = {
                    "success": False,
                    "error": str(e)
                }
                total_failed += 1
        
        return {
            "success": total_sent > 0,
            "total_sent": total_sent,
            "total_failed": total_failed,
            "user_results": user_results
        }
    
    async def _send_to_single_user(
        self,
        user_id: int,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notification to a single user with all delivery methods."""
        try:
            # Get user preferences
            preferences = await self._get_user_preferences(user_id, db)
            if not preferences or not preferences.enabled:
                return {"success": False, "reason": "Notifications disabled"}
            
            # Check notification type preferences
            if not self._is_notification_type_enabled(request.type, preferences):
                return {"success": False, "reason": "Notification type disabled"}
            
            # Create notification record
            notification = await self._create_notification_record(user_id, request, db)
            
            # Log notification creation
            await self.audit_service.log_notification_event(
                notification=notification,
                event_type=AuditEventType.NOTIFICATION_CREATED,
                action="notification_created",
                description=f"Notification created: {request.title[:100]}",
                actor_id=request.sender_id,
                db=db
            )
            
            sent_count = 0
            failed_count = 0
            delivery_results = {}
            
            # Send push notifications (existing FCM/WebPush)
            if request.send_push and preferences.push_notifications:
                push_result = await self._send_push_notification(
                    notification, preferences, request, db
                )
                delivery_results["push"] = push_result
                if push_result.get("success"):
                    sent_count += push_result.get("sent_count", 0)
                else:
                    failed_count += 1
            
            # Send email notification
            if request.send_email and preferences.email_notifications:
                email_result = await self._send_email_notification(
                    user_id, notification, request, preferences, db
                )
                delivery_results["email"] = email_result
                if email_result.get("success"):
                    sent_count += 1
                else:
                    failed_count += 1
            
            # Send SMS notification
            if request.send_sms and preferences.sms_notifications:
                sms_result = await self._send_sms_notification(
                    user_id, notification, request, preferences, db
                )
                delivery_results["sms"] = sms_result
                if sms_result.get("success"):
                    sent_count += 1
                else:
                    failed_count += 1
            
            # Send to parents/guardians if requested
            if request.include_parents:
                parent_result = await self._send_parent_notifications(
                    user_id, notification, request, db
                )
                delivery_results["parents"] = parent_result
                sent_count += parent_result.get("sent_count", 0)
                failed_count += parent_result.get("failed_count", 0)
            
            # Update notification status
            if sent_count > 0:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
                
                # Log successful send
                await self.audit_service.log_notification_event(
                    notification=notification,
                    event_type=AuditEventType.NOTIFICATION_SENT,
                    action="notification_sent",
                    description=f"Notification sent successfully via {sent_count} channels",
                    actor_id=request.sender_id,
                    additional_data={"channels_sent": sent_count, "channels_failed": failed_count},
                    db=db
                )
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "All delivery channels failed"
                
                # Log failure
                await self.audit_service.log_notification_event(
                    notification=notification,
                    event_type=AuditEventType.NOTIFICATION_FAILED,
                    action="notification_failed",
                    description="All notification delivery channels failed",
                    actor_id=request.sender_id,
                    additional_data={"channels_failed": failed_count},
                    db=db
                )
            
            await db.commit()
            
            return {
                "success": sent_count > 0,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "delivery_results": delivery_results,
                "notification_id": notification.id
            }
            
        except Exception as e:
            logger.error(f"Error sending to user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_push_notification(
        self,
        notification: Notification,
        preferences: NotificationPreferences,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send push notification using existing FCM/WebPush services."""
        try:
            # This delegates to the existing notification manager logic
            # Import here to avoid circular imports
            from .notification_manager import NotificationManager
            legacy_manager = NotificationManager()
            
            # Use existing push notification logic
            result = await legacy_manager._send_immediate_notification(
                notification, preferences, db
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending push notification: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_email_notification(
        self,
        user_id: int,
        notification: Notification,
        request: EnhancedNotificationRequest,
        preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send email notification."""
        try:
            # Get email address
            email_address = preferences.email_address
            if not email_address:
                # Try to get from user table (would need user service)
                return {"success": False, "error": "No email address configured"}
            
            # Send email
            result = await self.email_service.send_email(
                to_email=email_address,
                subject=request.title,
                html_content=request.html_content,
                text_content=request.text_content or request.message,
                template_id=request.template_id,
                template_data=request.template_data,
                notification_id=notification.id,
                priority=request.priority.value,
                db=db
            )
            
            return {"success": result.success, "error": result.error_message}
            
        except Exception as e:
            logger.error(f"Error sending email notification: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_sms_notification(
        self,
        user_id: int,
        notification: Notification,
        request: EnhancedNotificationRequest,
        preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send SMS notification."""
        try:
            # Get phone number
            phone_number = preferences.phone_number
            if not phone_number:
                return {"success": False, "error": "No phone number configured"}
            
            # Check if this is urgent-only SMS preference
            if preferences.sms_urgent_only and request.priority not in [
                NotificationPriority.HIGH, NotificationPriority.URGENT
            ]:
                return {"success": False, "reason": "SMS limited to urgent notifications"}
            
            # Send SMS
            result = await self.sms_service.send_sms(
                phone_number=phone_number,
                message=request.message,
                notification_id=notification.id,
                priority=request.priority.value,
                db=db
            )
            
            return {"success": result.success, "error": result.error_message}
            
        except Exception as e:
            logger.error(f"Error sending SMS notification: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_parent_notifications(
        self,
        user_id: int,
        notification: Notification,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notifications to parents/guardians."""
        try:
            # Import here to avoid circular imports
            from app.models.notification_preferences import NotificationContact
            from sqlalchemy import select, and_
            
            # Get parent contacts
            result = await db.execute(
                select(NotificationContact).where(
                    and_(
                        NotificationContact.user_id == user_id,
                        NotificationContact.enabled == True,
                        NotificationContact.contact_type.in_(['parent', 'guardian'])
                    )
                )
            )
            
            contacts = result.scalars().all()
            sent_count = 0
            failed_count = 0
            
            for contact in contacts:
                # Send email to parent
                if contact.email and contact.email_notifications:
                    email_result = await self.email_service.send_email(
                        to_email=contact.email,
                        subject=f"[Parent Alert] {request.title}",
                        text_content=request.message,
                        html_content=request.html_content,
                        template_id=request.template_id,
                        template_data=request.template_data,
                        notification_id=notification.id,
                        priority=request.priority.value,
                        db=db
                    )
                    
                    if email_result.success:
                        sent_count += 1
                    else:
                        failed_count += 1
                
                # Send SMS to parent
                if contact.phone_number and contact.sms_notifications:
                    sms_result = await self.sms_service.send_sms(
                        phone_number=contact.phone_number,
                        message=f"Parent Alert: {request.message}",
                        notification_id=notification.id,
                        priority=request.priority.value,
                        db=db
                    )
                    
                    if sms_result.success:
                        sent_count += 1
                    else:
                        failed_count += 1
            
            return {"sent_count": sent_count, "failed_count": failed_count}
            
        except Exception as e:
            logger.error(f"Error sending parent notifications: {e}")
            return {"sent_count": 0, "failed_count": 1}
    
    async def _log_notification_creation(
        self,
        request: EnhancedNotificationRequest,
        db: AsyncSession
    ):
        """Log notification creation audit event."""
        try:
            event = AuditEvent(
                event_type=AuditEventType.NOTIFICATION_CREATED,
                action="enhanced_notification_request",
                description=f"Enhanced notification request: {request.title[:100]}",
                actor_type="user" if request.sender_id else "system",
                actor_id=request.sender_id,
                target_type="notification_request",
                event_data={
                    "notification_type": request.type.value,
                    "priority": request.priority.value,
                    "target_count": len(request.user_ids),
                    "delivery_methods": {
                        "push": request.send_push,
                        "email": request.send_email,
                        "sms": request.send_sms,
                        "parents": request.include_parents
                    },
                    "has_template": request.template_id is not None,
                    "scheduled": request.scheduled_at is not None
                },
                source_ip=request.source_ip,
                user_agent=request.user_agent,
                session_id=request.session_id,
                request_id=request.request_id,
                is_sensitive=True
            )
            
            await self.audit_service.log_event(event, db)
            
        except Exception as e:
            logger.error(f"Error logging notification creation: {e}")
    
    async def _log_bulk_completion(
        self,
        bulk_request,
        result,
        db: AsyncSession
    ):
        """Log bulk operation completion."""
        try:
            event = AuditEvent(
                event_type=AuditEventType.BULK_OPERATION_COMPLETED,
                action="bulk_notification_completed",
                description=f"Bulk notification completed: {result.successful_sends}/{result.total_targets} sent",
                actor_type="system",
                target_type="bulk_operation",
                target_identifier=result.job_id,
                event_data={
                    "job_id": result.job_id,
                    "total_targets": result.total_targets,
                    "successful_sends": result.successful_sends,
                    "failed_sends": result.failed_sends,
                    "skipped_sends": result.skipped_sends,
                    "processing_time": result.processing_time,
                    "status": result.status.value
                }
            )
            
            await self.audit_service.log_event(event, db)
            
        except Exception as e:
            logger.error(f"Error logging bulk completion: {e}")
    
    async def _log_error_event(
        self,
        action: str,
        description: str,
        actor_id: Optional[int] = None,
        additional_data: Dict[str, Any] = None,
        db: AsyncSession = None
    ):
        """Log error events for audit trail."""
        try:
            event = AuditEvent(
                event_type=AuditEventType.NOTIFICATION_FAILED,
                action=action,
                description=description,
                severity=AuditSeverity.ERROR,
                actor_type="user" if actor_id else "system",
                actor_id=actor_id,
                event_data=additional_data or {}
            )
            
            await self.audit_service.log_event(event, db)
            
        except Exception as e:
            logger.error(f"Error logging error event: {e}")
    
    async def _get_user_preferences(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Optional[NotificationPreferences]:
        """Get user's notification preferences."""
        try:
            from sqlalchemy import select
            result = await db.execute(
                select(NotificationPreferences).where(
                    NotificationPreferences.user_id == user_id
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user preferences: {e}")
            return None
    
    def _is_notification_type_enabled(
        self,
        notification_type: NotificationType,
        preferences: NotificationPreferences
    ) -> bool:
        """Check if notification type is enabled for user."""
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
    
    async def _create_notification_record(
        self,
        user_id: int,
        request: EnhancedNotificationRequest,
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
        await db.flush()
        return notification
    
    # Expose service capabilities
    def get_sms_service(self) -> SMSService:
        """Get SMS service instance."""
        return self.sms_service
    
    def get_email_service(self) -> EmailService:
        """Get email service instance."""
        return self.email_service
    
    def get_bulk_service(self) -> BulkNotificationService:
        """Get bulk notification service instance."""
        return self.bulk_service
    
    def get_delivery_tracking(self) -> DeliveryTrackingService:
        """Get delivery tracking service instance."""
        return self.delivery_tracking
    
    def get_audit_service(self) -> NotificationAuditService:
        """Get audit service instance."""
        return self.audit_service
    
    async def get_comprehensive_statistics(self, db: AsyncSession) -> Dict[str, Any]:
        """Get comprehensive statistics from all services."""
        try:
            # Get statistics from all services
            legacy_stats = await super().get_notification_statistics(db) if hasattr(super(), 'get_notification_statistics') else {}
            delivery_stats = await self.delivery_tracking.get_delivery_statistics(db)
            
            # Get service status
            service_status = {
                "sms_available": self.sms_service.is_available(),
                "email_available": self.email_service.is_available(),
                "fcm_available": self.fcm_service.is_available(),
                "webpush_available": self.webpush_service.is_available(),
                "sms_providers": self.sms_service.get_provider_status(),
                "email_providers": self.email_service.get_provider_status()
            }
            
            return {
                "legacy_stats": legacy_stats,
                "delivery_stats": delivery_stats,
                "service_status": service_status,
                "audit_available": True,
                "bulk_operations_supported": True
            }
            
        except Exception as e:
            logger.error(f"Error getting comprehensive statistics: {e}")
            return {"error": str(e)}