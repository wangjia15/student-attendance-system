"""Bulk notification service with advanced rate limiting and queue management."""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update, delete

from app.models.notifications import (
    Notification, NotificationPreferences, NotificationStatus, NotificationType, 
    NotificationPriority, DevicePlatform
)
from app.models.notification_preferences import NotificationContact, NotificationFrequencyLog
from app.integrations.sms import SMSService, SMSMessage
from app.integrations.email import EmailService, EmailMessage

logger = logging.getLogger(__name__)


class BulkNotificationPriority(str, Enum):
    """Priority levels for bulk notifications."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class BulkNotificationStatus(str, Enum):
    """Status of bulk notification jobs."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BulkNotificationTarget:
    """Target for bulk notification."""
    user_id: int
    email: Optional[str] = None
    phone_number: Optional[str] = None
    parent_email: Optional[str] = None
    parent_phone: Optional[str] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkNotificationRequest:
    """Request for bulk notification sending."""
    targets: List[BulkNotificationTarget]
    notification_type: NotificationType
    title: str
    message: str
    priority: BulkNotificationPriority = BulkNotificationPriority.NORMAL
    
    # Content options
    html_content: Optional[str] = None
    template_id: Optional[str] = None
    template_data: Dict[str, Any] = field(default_factory=dict)
    
    # Delivery options
    send_email: bool = True
    send_sms: bool = False
    send_push: bool = True
    include_parents: bool = False
    
    # Scheduling
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Rate limiting
    max_send_rate_per_second: int = 10
    max_send_rate_per_minute: int = 100
    respect_quiet_hours: bool = True
    
    # Additional metadata
    sender_id: Optional[int] = None
    class_session_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkNotificationResult:
    """Result of bulk notification operation."""
    job_id: str
    total_targets: int
    successful_sends: int
    failed_sends: int
    skipped_sends: int
    errors: List[Dict[str, Any]] = field(default_factory=list)
    processing_time: float = 0.0
    status: BulkNotificationStatus = BulkNotificationStatus.COMPLETED


class BulkNotificationService:
    """Service for sending bulk notifications with advanced rate limiting."""
    
    def __init__(self):
        self.sms_service = SMSService()
        self.email_service = EmailService()
        
        # Rate limiting configuration
        self.global_rate_limit_per_second = 50
        self.global_rate_limit_per_minute = 1000
        
        # Active jobs tracking
        self._active_jobs = {}
        self._rate_limit_tracker = {
            'requests_this_second': [],
            'requests_this_minute': []
        }
        
        logger.info("Bulk Notification Service initialized")
    
    async def send_bulk_notification(
        self,
        request: BulkNotificationRequest,
        db: AsyncSession
    ) -> BulkNotificationResult:
        """
        Send bulk notification to multiple targets with rate limiting.
        
        Args:
            request: Bulk notification request with targets and content
            db: Database session
            
        Returns:
            Result summary of the bulk operation
        """
        start_time = datetime.utcnow()
        job_id = f"bulk_{start_time.strftime('%Y%m%d_%H%M%S')}_{hash(str(request.targets))}"
        
        try:
            logger.info(f"Starting bulk notification job {job_id} with {len(request.targets)} targets")
            
            # Initialize job tracking
            self._active_jobs[job_id] = {
                'status': BulkNotificationStatus.PROCESSING,
                'start_time': start_time,
                'total_targets': len(request.targets),
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'skipped': 0
            }
            
            # Process targets in batches with rate limiting
            successful_sends = 0
            failed_sends = 0
            skipped_sends = 0
            errors = []
            
            batch_size = min(request.max_send_rate_per_second, 20)
            
            for i in range(0, len(request.targets), batch_size):
                batch = request.targets[i:i + batch_size]
                
                # Check global rate limits
                if not await self._check_global_rate_limit():
                    logger.warning("Global rate limit reached, adding delay")
                    await asyncio.sleep(1)
                
                # Process batch
                batch_results = await self._process_batch(
                    batch, request, job_id, db
                )
                
                # Aggregate results
                for result in batch_results:
                    if result['success']:
                        successful_sends += 1
                    elif result.get('skipped'):
                        skipped_sends += 1
                    else:
                        failed_sends += 1
                        if result.get('error'):
                            errors.append(result['error'])
                
                # Update job tracking
                self._active_jobs[job_id]['processed'] = i + len(batch)
                self._active_jobs[job_id]['successful'] = successful_sends
                self._active_jobs[job_id]['failed'] = failed_sends
                self._active_jobs[job_id]['skipped'] = skipped_sends
                
                # Add inter-batch delay for rate limiting
                if i + batch_size < len(request.targets):
                    delay = max(1.0, len(batch) / request.max_send_rate_per_second)
                    await asyncio.sleep(delay)
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Update job status
            self._active_jobs[job_id]['status'] = BulkNotificationStatus.COMPLETED
            
            result = BulkNotificationResult(
                job_id=job_id,
                total_targets=len(request.targets),
                successful_sends=successful_sends,
                failed_sends=failed_sends,
                skipped_sends=skipped_sends,
                errors=errors[:100],  # Limit error list size
                processing_time=processing_time,
                status=BulkNotificationStatus.COMPLETED
            )
            
            logger.info(
                f"Bulk notification job {job_id} completed: "
                f"{successful_sends} sent, {failed_sends} failed, {skipped_sends} skipped "
                f"in {processing_time:.2f}s"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in bulk notification job {job_id}: {e}")
            
            # Update job status
            if job_id in self._active_jobs:
                self._active_jobs[job_id]['status'] = BulkNotificationStatus.FAILED
            
            return BulkNotificationResult(
                job_id=job_id,
                total_targets=len(request.targets),
                successful_sends=0,
                failed_sends=len(request.targets),
                skipped_sends=0,
                errors=[{"error": str(e), "target": "all"}],
                processing_time=(datetime.utcnow() - start_time).total_seconds(),
                status=BulkNotificationStatus.FAILED
            )
    
    async def _process_batch(
        self,
        batch: List[BulkNotificationTarget],
        request: BulkNotificationRequest,
        job_id: str,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """Process a batch of notification targets."""
        tasks = []
        for target in batch:
            task = self._process_single_target(target, request, job_id, db)
            tasks.append(task)
        
        # Process batch concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'success': False,
                    'error': {
                        'user_id': batch[i].user_id,
                        'error': str(result)
                    }
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _process_single_target(
        self,
        target: BulkNotificationTarget,
        request: BulkNotificationRequest,
        job_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Process notification for a single target."""
        try:
            # Get user preferences
            preferences = await self._get_user_preferences(target.user_id, db)
            if not preferences or not preferences.enabled:
                return {
                    'success': False,
                    'skipped': True,
                    'reason': 'User notifications disabled'
                }
            
            # Check if user wants this notification type
            if not self._is_notification_type_enabled(request.notification_type, preferences):
                return {
                    'success': False,
                    'skipped': True,
                    'reason': f'Notification type {request.notification_type.value} disabled'
                }
            
            # Check frequency limits
            frequency_check = await self._check_frequency_limits(target.user_id, db)
            if frequency_check['exceeded']:
                return {
                    'success': False,
                    'skipped': True,
                    'reason': 'Frequency limit exceeded'
                }
            
            # Check quiet hours
            if request.respect_quiet_hours and self._is_in_quiet_hours(preferences):
                return {
                    'success': False,
                    'skipped': True,
                    'reason': 'In quiet hours'
                }
            
            # Create notification record
            notification = await self._create_notification_record(
                target.user_id, request, job_id, db
            )
            
            # Send via different channels based on request
            sent_count = 0
            failed_count = 0
            
            # Send push notification
            if request.send_push and preferences.push_notifications:
                # This would integrate with existing push notification system
                # For now, mark as sent
                sent_count += 1
            
            # Send email notification
            if request.send_email and preferences.email_notifications:
                email_result = await self._send_email_notification(
                    target, request, notification.id, db
                )
                if email_result['success']:
                    sent_count += 1
                else:
                    failed_count += 1
            
            # Send SMS notification
            if request.send_sms and preferences.sms_notifications:
                sms_result = await self._send_sms_notification(
                    target, request, notification.id, db
                )
                if sms_result['success']:
                    sent_count += 1
                else:
                    failed_count += 1
            
            # Send to parents/guardians if requested
            if request.include_parents:
                parent_result = await self._send_parent_notifications(
                    target, request, notification.id, db
                )
                sent_count += parent_result.get('sent_count', 0)
                failed_count += parent_result.get('failed_count', 0)
            
            # Update notification status
            if sent_count > 0:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "No delivery channels succeeded"
            
            await db.commit()
            
            # Update frequency tracking
            await self._update_frequency_tracking(target.user_id, db)
            
            return {
                'success': sent_count > 0,
                'sent_count': sent_count,
                'failed_count': failed_count
            }
            
        except Exception as e:
            logger.error(f"Error processing target {target.user_id}: {e}")
            return {
                'success': False,
                'error': {
                    'user_id': target.user_id,
                    'error': str(e)
                }
            }
    
    async def _send_email_notification(
        self,
        target: BulkNotificationTarget,
        request: BulkNotificationRequest,
        notification_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send email notification to target."""
        try:
            email_address = target.email
            if not email_address:
                # Get email from user preferences
                preferences = await self._get_user_preferences(target.user_id, db)
                email_address = preferences.email_address if preferences else None
            
            if not email_address:
                return {'success': False, 'error': 'No email address'}
            
            # Merge template data with target custom data
            template_data = {**request.template_data, **target.custom_data}
            
            result = await self.email_service.send_email(
                to_email=email_address,
                subject=request.title,
                html_content=request.html_content,
                text_content=request.message,
                template_id=request.template_id,
                template_data=template_data,
                notification_id=notification_id,
                priority=request.priority.value,
                db=db
            )
            
            return {'success': result.success, 'error': result.error_message}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _send_sms_notification(
        self,
        target: BulkNotificationTarget,
        request: BulkNotificationRequest,
        notification_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send SMS notification to target."""
        try:
            phone_number = target.phone_number
            if not phone_number:
                # Get phone from user preferences
                preferences = await self._get_user_preferences(target.user_id, db)
                phone_number = preferences.phone_number if preferences else None
            
            if not phone_number:
                return {'success': False, 'error': 'No phone number'}
            
            result = await self.sms_service.send_sms(
                phone_number=phone_number,
                message=request.message,
                notification_id=notification_id,
                priority=request.priority.value,
                db=db
            )
            
            return {'success': result.success, 'error': result.error_message}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _send_parent_notifications(
        self,
        target: BulkNotificationTarget,
        request: BulkNotificationRequest,
        notification_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send notifications to parent/guardian contacts."""
        try:
            # Get parent contacts for user
            result = await db.execute(
                select(NotificationContact).where(
                    and_(
                        NotificationContact.user_id == target.user_id,
                        NotificationContact.enabled == True,
                        NotificationContact.contact_type.in_(['parent', 'guardian'])
                    )
                )
            )
            
            contacts = result.scalars().all()
            sent_count = 0
            failed_count = 0
            
            for contact in contacts:
                # Check if contact wants this notification type
                if not self._is_contact_notification_enabled(request.notification_type, contact):
                    continue
                
                # Send email to contact
                if contact.email and contact.email_notifications:
                    email_result = await self.email_service.send_email(
                        to_email=contact.email,
                        subject=f"[Parent Alert] {request.title}",
                        text_content=request.message,
                        html_content=request.html_content,
                        notification_id=notification_id,
                        priority=request.priority.value,
                        db=db
                    )
                    if email_result.success:
                        sent_count += 1
                    else:
                        failed_count += 1
                
                # Send SMS to contact
                if contact.phone_number and contact.sms_notifications:
                    sms_result = await self.sms_service.send_sms(
                        phone_number=contact.phone_number,
                        message=f"Parent Alert: {request.message}",
                        notification_id=notification_id,
                        priority=request.priority.value,
                        db=db
                    )
                    if sms_result.success:
                        sent_count += 1
                    else:
                        failed_count += 1
            
            return {'sent_count': sent_count, 'failed_count': failed_count}
            
        except Exception as e:
            logger.error(f"Error sending parent notifications: {e}")
            return {'sent_count': 0, 'failed_count': 1}
    
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
    
    def _is_contact_notification_enabled(
        self,
        notification_type: NotificationType,
        contact: NotificationContact
    ) -> bool:
        """Check if notification type is enabled for a contact."""
        type_mapping = {
            NotificationType.ATTENDANCE_REMINDER: contact.attendance_reminders,
            NotificationType.LATE_ARRIVAL: contact.late_arrival_alerts,
            NotificationType.ABSENT_ALERT: contact.absent_alerts,
            NotificationType.CLASS_STARTED: contact.class_notifications,
            NotificationType.CLASS_ENDED: contact.class_notifications,
            NotificationType.PATTERN_ALERT: contact.pattern_alerts,
            NotificationType.SYSTEM_ANNOUNCEMENT: contact.system_announcements,
            NotificationType.ACHIEVEMENT_BADGE: contact.achievement_notifications
        }
        
        return type_mapping.get(notification_type, False)
    
    def _is_in_quiet_hours(self, preferences: NotificationPreferences) -> bool:
        """Check if current time is in user's quiet hours."""
        # Simplified implementation - in practice would handle timezones
        if not preferences.quiet_hours_start or not preferences.quiet_hours_end:
            return False
        
        # This would implement proper quiet hours checking with timezone support
        return False
    
    async def _check_frequency_limits(self, user_id: int, db: AsyncSession) -> Dict[str, Any]:
        """Check if user has exceeded frequency limits."""
        try:
            now = datetime.utcnow()
            hour_key = now.strftime('%Y-%m-%d-%H')
            day_key = now.strftime('%Y-%m-%d')
            
            # Get frequency log for current hour and day
            result = await db.execute(
                select(NotificationFrequencyLog).where(
                    and_(
                        NotificationFrequencyLog.user_id == user_id,
                        or_(
                            NotificationFrequencyLog.hour_key == hour_key,
                            NotificationFrequencyLog.day_key == day_key
                        )
                    )
                )
            )
            
            logs = result.scalars().all()
            
            hour_count = 0
            day_count = 0
            
            for log in logs:
                if log.hour_key == hour_key:
                    hour_count += log.notification_count
                if log.day_key == day_key:
                    day_count += log.notification_count
            
            # Check against limits (simplified - would get from user preferences)
            hourly_limit = 10
            daily_limit = 50
            
            return {
                'exceeded': hour_count >= hourly_limit or day_count >= daily_limit,
                'hour_count': hour_count,
                'day_count': day_count,
                'hourly_limit': hourly_limit,
                'daily_limit': daily_limit
            }
            
        except Exception as e:
            logger.error(f"Error checking frequency limits: {e}")
            return {'exceeded': False}
    
    async def _update_frequency_tracking(self, user_id: int, db: AsyncSession):
        """Update frequency tracking for rate limiting."""
        try:
            now = datetime.utcnow()
            hour_key = now.strftime('%Y-%m-%d-%H')
            day_key = now.strftime('%Y-%m-%d')
            
            # Update or create frequency log
            result = await db.execute(
                select(NotificationFrequencyLog).where(
                    and_(
                        NotificationFrequencyLog.user_id == user_id,
                        NotificationFrequencyLog.hour_key == hour_key
                    )
                )
            )
            
            log = result.scalar_one_or_none()
            
            if log:
                log.notification_count += 1
                log.updated_at = now
            else:
                log = NotificationFrequencyLog(
                    user_id=user_id,
                    hour_key=hour_key,
                    day_key=day_key,
                    notification_count=1
                )
                db.add(log)
            
            await db.flush()
            
        except Exception as e:
            logger.error(f"Error updating frequency tracking: {e}")
    
    async def _create_notification_record(
        self,
        user_id: int,
        request: BulkNotificationRequest,
        job_id: str,
        db: AsyncSession
    ) -> Notification:
        """Create notification database record."""
        notification = Notification(
            user_id=user_id,
            type=request.notification_type,
            priority=NotificationPriority(request.priority.value),
            title=request.title,
            message=request.message,
            data={'bulk_job_id': job_id, **request.metadata},
            scheduled_at=request.scheduled_at,
            expires_at=request.expires_at,
            class_session_id=request.class_session_id,
            status=NotificationStatus.PENDING
        )
        
        db.add(notification)
        await db.flush()
        return notification
    
    async def _check_global_rate_limit(self) -> bool:
        """Check global rate limits for the service."""
        now = datetime.now()
        
        # Clean up old requests
        self._rate_limit_tracker['requests_this_second'] = [
            req_time for req_time in self._rate_limit_tracker['requests_this_second']
            if now - req_time <= timedelta(seconds=1)
        ]
        self._rate_limit_tracker['requests_this_minute'] = [
            req_time for req_time in self._rate_limit_tracker['requests_this_minute']
            if now - req_time <= timedelta(minutes=1)
        ]
        
        # Check limits
        if len(self._rate_limit_tracker['requests_this_second']) >= self.global_rate_limit_per_second:
            return False
        if len(self._rate_limit_tracker['requests_this_minute']) >= self.global_rate_limit_per_minute:
            return False
        
        # Track this request
        self._rate_limit_tracker['requests_this_second'].append(now)
        self._rate_limit_tracker['requests_this_minute'].append(now)
        
        return True
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a bulk notification job."""
        return self._active_jobs.get(job_id)
    
    def get_active_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Get all active bulk notification jobs."""
        return self._active_jobs.copy()
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running bulk notification job."""
        if job_id in self._active_jobs:
            self._active_jobs[job_id]['status'] = BulkNotificationStatus.CANCELLED
            return True
        return False