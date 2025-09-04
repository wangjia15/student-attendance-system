"""Notification batching service to prevent spam and optimize delivery."""

import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.notifications import (
    Notification, NotificationBatch, NotificationPreferences,
    NotificationType, NotificationStatus, NotificationPriority
)

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Configuration for notification batching."""
    enabled: bool = True
    interval_minutes: int = 30
    max_batch_size: int = 5
    priority_threshold: NotificationPriority = NotificationPriority.HIGH
    immediate_types: List[NotificationType] = None
    
    def __post_init__(self):
        if self.immediate_types is None:
            self.immediate_types = [
                NotificationType.CLASS_STARTED,
                NotificationType.SYSTEM_ANNOUNCEMENT
            ]


class NotificationBatchingService:
    """Service for intelligent notification batching and queuing."""
    
    def __init__(self):
        self.default_config = BatchConfig()
        logger.info("Notification batching service initialized")
    
    async def should_batch_notification(
        self,
        notification: Notification,
        user_preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Tuple[bool, str]:
        """
        Determine if a notification should be batched or sent immediately.
        
        Args:
            notification: The notification to evaluate
            user_preferences: User's notification preferences
            db: Database session
            
        Returns:
            Tuple of (should_batch, reason)
        """
        # Check if batching is enabled for user
        if not user_preferences.batch_enabled:
            return False, "User disabled batching"
        
        # High priority or urgent notifications bypass batching
        if notification.priority in [NotificationPriority.HIGH, NotificationPriority.URGENT]:
            return False, "High/urgent priority"
        
        # Certain notification types should be sent immediately
        if notification.type in self.default_config.immediate_types:
            return False, f"Immediate type: {notification.type.value}"
        
        # Check if we're in user's quiet hours
        if await self._is_quiet_hours(user_preferences):
            return True, "Quiet hours - will batch"
        
        # Check recent notification frequency
        recent_count = await self._get_recent_notification_count(
            notification.user_id, timedelta(minutes=user_preferences.batch_interval_minutes), db
        )
        
        if recent_count >= 3:  # If more than 3 notifications in the interval
            return True, "High frequency - batching to prevent spam"
        
        # Check if there's already a pending batch
        pending_batch = await self._get_pending_batch(notification.user_id, db)
        if pending_batch and pending_batch.notification_count < user_preferences.max_batch_size:
            return True, "Adding to existing batch"
        
        return False, "No batching criteria met"
    
    async def add_to_batch(
        self,
        notification: Notification,
        user_preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Optional[str]:
        """
        Add notification to a batch. Creates new batch if needed.
        
        Args:
            notification: Notification to batch
            user_preferences: User's batching preferences
            db: Database session
            
        Returns:
            Batch ID if successful, None if failed
        """
        try:
            # Find or create pending batch
            batch = await self._find_or_create_batch(
                notification.user_id, user_preferences, db
            )
            
            if not batch:
                logger.error("Failed to create/find batch")
                return None
            
            # Add notification to batch
            notification.batch_id = batch.batch_id
            notification.is_batched = True
            notification.status = NotificationStatus.PENDING
            
            # Update batch metadata
            batch.notification_count += 1
            await self._update_batch_content(batch, notification, db)
            
            # Schedule batch for sending if it's full or time-based
            await self._schedule_batch_if_ready(batch, user_preferences, db)
            
            await db.commit()
            logger.info(f"Added notification {notification.id} to batch {batch.batch_id}")
            
            return batch.batch_id
            
        except Exception as e:
            logger.error(f"Failed to add notification to batch: {e}")
            await db.rollback()
            return None
    
    async def process_ready_batches(self, db: AsyncSession) -> List[str]:
        """
        Process all batches that are ready to be sent.
        
        Args:
            db: Database session
            
        Returns:
            List of processed batch IDs
        """
        try:
            # Find batches ready for processing
            ready_batches = await self._find_ready_batches(db)
            processed_batch_ids = []
            
            for batch in ready_batches:
                try:
                    success = await self._process_batch(batch, db)
                    if success:
                        processed_batch_ids.append(batch.batch_id)
                        logger.info(f"Successfully processed batch {batch.batch_id}")
                    else:
                        logger.warning(f"Failed to process batch {batch.batch_id}")
                        
                except Exception as e:
                    logger.error(f"Error processing batch {batch.batch_id}: {e}")
            
            return processed_batch_ids
            
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            return []
    
    async def _find_or_create_batch(
        self,
        user_id: int,
        user_preferences: NotificationPreferences,
        db: AsyncSession
    ) -> Optional[NotificationBatch]:
        """Find existing pending batch or create new one."""
        try:
            # Look for existing pending batch
            result = await db.execute(
                select(NotificationBatch).where(
                    and_(
                        NotificationBatch.user_id == user_id,
                        NotificationBatch.status == NotificationStatus.PENDING,
                        NotificationBatch.notification_count < user_preferences.max_batch_size
                    )
                )
            )
            
            existing_batch = result.scalar_one_or_none()
            if existing_batch:
                return existing_batch
            
            # Create new batch
            batch_id = str(uuid.uuid4())
            new_batch = NotificationBatch(
                batch_id=batch_id,
                user_id=user_id,
                title="Attendance Updates",
                message="You have new attendance notifications",
                scheduled_at=datetime.utcnow() + timedelta(minutes=user_preferences.batch_interval_minutes),
                notification_count=0,
                status=NotificationStatus.PENDING
            )
            
            db.add(new_batch)
            await db.flush()  # Get the ID without committing
            
            return new_batch
            
        except Exception as e:
            logger.error(f"Failed to find/create batch: {e}")
            return None
    
    async def _update_batch_content(
        self,
        batch: NotificationBatch,
        notification: Notification,
        db: AsyncSession
    ) -> None:
        """Update batch title and message based on contained notifications."""
        try:
            # Get all notifications in this batch
            result = await db.execute(
                select(Notification).where(
                    Notification.batch_id == batch.batch_id
                )
            )
            batch_notifications = result.scalars().all()
            
            # Count notification types
            type_counts = defaultdict(int)
            for notif in batch_notifications:
                type_counts[notif.type] += 1
            type_counts[notification.type] += 1  # Include the current one
            
            # Generate batch summary
            total_count = sum(type_counts.values())
            
            if total_count == 1:
                # Single notification
                batch.title = notification.title
                batch.message = notification.message
            else:
                # Multiple notifications
                batch.title = f"You have {total_count} attendance updates"
                
                # Create summary message
                summary_parts = []
                for notif_type, count in type_counts.items():
                    type_name = self._get_friendly_type_name(notif_type)
                    if count == 1:
                        summary_parts.append(f"1 {type_name}")
                    else:
                        summary_parts.append(f"{count} {type_name}s")
                
                batch.message = "Including: " + ", ".join(summary_parts)
                
        except Exception as e:
            logger.error(f"Failed to update batch content: {e}")
    
    def _get_friendly_type_name(self, notification_type: NotificationType) -> str:
        """Convert notification type enum to friendly name."""
        type_names = {
            NotificationType.ATTENDANCE_REMINDER: "attendance reminder",
            NotificationType.LATE_ARRIVAL: "late arrival alert",
            NotificationType.ABSENT_ALERT: "absence alert",
            NotificationType.CLASS_STARTED: "class started notification",
            NotificationType.CLASS_ENDED: "class ended notification",
            NotificationType.PATTERN_ALERT: "pattern alert",
            NotificationType.SYSTEM_ANNOUNCEMENT: "system announcement",
            NotificationType.ACHIEVEMENT_BADGE: "achievement notification"
        }
        return type_names.get(notification_type, "notification")
    
    async def _schedule_batch_if_ready(
        self,
        batch: NotificationBatch,
        user_preferences: NotificationPreferences,
        db: AsyncSession
    ) -> None:
        """Schedule batch for immediate sending if conditions are met."""
        try:
            # Send immediately if batch is full
            if batch.notification_count >= user_preferences.max_batch_size:
                batch.scheduled_at = datetime.utcnow()
                logger.info(f"Batch {batch.batch_id} scheduled immediately (full)")
                return
            
            # Check if we have high-priority notifications that push the batch
            result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.batch_id == batch.batch_id,
                        Notification.priority == NotificationPriority.HIGH
                    )
                )
            )
            high_priority_notifs = result.scalars().all()
            
            if high_priority_notifs:
                # Schedule sooner for high priority content
                batch.scheduled_at = datetime.utcnow() + timedelta(minutes=5)
                logger.info(f"Batch {batch.batch_id} scheduled sooner (high priority content)")
                
        except Exception as e:
            logger.error(f"Failed to schedule batch: {e}")
    
    async def _find_ready_batches(self, db: AsyncSession) -> List[NotificationBatch]:
        """Find batches that are ready to be processed."""
        try:
            result = await db.execute(
                select(NotificationBatch).where(
                    and_(
                        NotificationBatch.status == NotificationStatus.PENDING,
                        NotificationBatch.scheduled_at <= datetime.utcnow(),
                        NotificationBatch.notification_count > 0
                    )
                )
            )
            return result.scalars().all()
            
        except Exception as e:
            logger.error(f"Failed to find ready batches: {e}")
            return []
    
    async def _process_batch(self, batch: NotificationBatch, db: AsyncSession) -> bool:
        """Process a single batch - create combined notification and mark as sent."""
        try:
            # Get all notifications in this batch
            result = await db.execute(
                select(Notification).where(
                    Notification.batch_id == batch.batch_id
                )
            )
            batch_notifications = result.scalars().all()
            
            if not batch_notifications:
                logger.warning(f"No notifications found for batch {batch.batch_id}")
                return False
            
            # Create a combined notification
            combined_notification = Notification(
                user_id=batch.user_id,
                type=NotificationType.SYSTEM_ANNOUNCEMENT,  # Generic type for batched
                priority=NotificationPriority.NORMAL,
                title=batch.title,
                message=batch.message,
                data={
                    "batch_id": batch.batch_id,
                    "notification_count": batch.notification_count,
                    "notification_ids": [n.id for n in batch_notifications],
                    "types": [n.type.value for n in batch_notifications]
                },
                status=NotificationStatus.PENDING,
                is_batched=False,  # This is the actual notification to send
                batch_id=None      # Not part of another batch
            )
            
            db.add(combined_notification)
            await db.flush()  # Get ID
            
            # Mark batch as sent
            batch.status = NotificationStatus.SENT
            batch.sent_at = datetime.utcnow()
            
            # Mark individual notifications as batched/sent
            for notification in batch_notifications:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
            
            await db.commit()
            
            logger.info(f"Processed batch {batch.batch_id} into notification {combined_notification.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to process batch {batch.batch_id}: {e}")
            await db.rollback()
            return False
    
    async def _is_quiet_hours(self, user_preferences: NotificationPreferences) -> bool:
        """Check if current time is within user's quiet hours."""
        if not user_preferences.quiet_hours_start or not user_preferences.quiet_hours_end:
            return False
        
        try:
            now = datetime.now().time()
            start_time = datetime.strptime(user_preferences.quiet_hours_start, "%H:%M").time()
            end_time = datetime.strptime(user_preferences.quiet_hours_end, "%H:%M").time()
            
            if start_time <= end_time:
                # Same day range (e.g., 09:00 to 17:00)
                return start_time <= now <= end_time
            else:
                # Overnight range (e.g., 22:00 to 08:00)
                return now >= start_time or now <= end_time
                
        except Exception as e:
            logger.error(f"Error checking quiet hours: {e}")
            return False
    
    async def _get_recent_notification_count(
        self,
        user_id: int,
        time_window: timedelta,
        db: AsyncSession
    ) -> int:
        """Get count of notifications sent to user in the time window."""
        try:
            cutoff_time = datetime.utcnow() - time_window
            
            result = await db.execute(
                select(Notification).where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.sent_at >= cutoff_time,
                        Notification.status == NotificationStatus.SENT
                    )
                )
            )
            
            return len(result.scalars().all())
            
        except Exception as e:
            logger.error(f"Error getting recent notification count: {e}")
            return 0
    
    async def _get_pending_batch(self, user_id: int, db: AsyncSession) -> Optional[NotificationBatch]:
        """Get user's current pending batch."""
        try:
            result = await db.execute(
                select(NotificationBatch).where(
                    and_(
                        NotificationBatch.user_id == user_id,
                        NotificationBatch.status == NotificationStatus.PENDING
                    )
                )
            )
            
            return result.scalar_one_or_none()
            
        except Exception as e:
            logger.error(f"Error getting pending batch: {e}")
            return None
    
    async def force_send_batch(self, batch_id: str, db: AsyncSession) -> bool:
        """Force immediate sending of a specific batch."""
        try:
            result = await db.execute(
                select(NotificationBatch).where(
                    NotificationBatch.batch_id == batch_id
                )
            )
            
            batch = result.scalar_one_or_none()
            if not batch:
                logger.error(f"Batch {batch_id} not found")
                return False
            
            if batch.status != NotificationStatus.PENDING:
                logger.warning(f"Batch {batch_id} is not pending (status: {batch.status})")
                return False
            
            return await self._process_batch(batch, db)
            
        except Exception as e:
            logger.error(f"Error force sending batch {batch_id}: {e}")
            return False
    
    async def get_batch_statistics(self, db: AsyncSession) -> Dict[str, Any]:
        """Get statistics about notification batching."""
        try:
            # Count batches by status
            batch_stats = {}
            for status in NotificationStatus:
                result = await db.execute(
                    select(NotificationBatch).where(
                        NotificationBatch.status == status
                    )
                )
                batch_stats[status.value] = len(result.scalars().all())
            
            # Count notifications that are batched vs individual
            batched_result = await db.execute(
                select(Notification).where(Notification.is_batched == True)
            )
            batched_count = len(batched_result.scalars().all())
            
            individual_result = await db.execute(
                select(Notification).where(Notification.is_batched == False)
            )
            individual_count = len(individual_result.scalars().all())
            
            return {
                "batch_counts": batch_stats,
                "notification_counts": {
                    "batched": batched_count,
                    "individual": individual_count,
                    "total": batched_count + individual_count
                },
                "batching_efficiency": (
                    (batched_count / (batched_count + individual_count) * 100) 
                    if (batched_count + individual_count) > 0 else 0
                )
            }
            
        except Exception as e:
            logger.error(f"Error getting batch statistics: {e}")
            return {"error": str(e)}