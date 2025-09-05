"""
Sync Schedule Manager

Manages configurable sync schedules for real-time, hourly, daily,
and custom synchronization operations between local and SIS systems.
"""

import logging
from datetime import datetime, timedelta, time
from typing import Dict, Any, List, Optional, Union
from enum import Enum
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc, func
from sqlalchemy.orm import selectinload
try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    # Mock croniter for when it's not available
    class croniter:
        def __init__(self, *args, **kwargs):
            pass
        def get_next(self, cls):
            from datetime import datetime, timedelta
            return datetime.utcnow() + timedelta(hours=1)
        def get_prev(self, cls):
            from datetime import datetime, timedelta
            return datetime.utcnow() - timedelta(hours=1)

from app.models.sync_metadata import (
    SyncSchedule, SyncOperation, SyncDirection, DataType,
    SyncStatus, SyncType
)
from app.models.sis_integration import SISIntegration
from app.services.sync.bidirectional_sync import BidirectionalSyncService
from app.services.sync.gradebook_integration import GradebookIntegrationService

logger = logging.getLogger(__name__)


class ScheduleFrequency(str, Enum):
    """Available schedule frequencies."""
    REAL_TIME = "real_time"
    EVERY_5_MINUTES = "every_5_minutes"
    EVERY_15_MINUTES = "every_15_minutes"
    EVERY_30_MINUTES = "every_30_minutes"
    HOURLY = "hourly"
    EVERY_2_HOURS = "every_2_hours"
    EVERY_6_HOURS = "every_6_hours"
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class SyncScheduleManager:
    """
    Manages sync schedules and their execution.
    
    Provides configuration and management of different sync schedules
    including real-time, periodic, and custom schedules.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.bidirectional_sync = BidirectionalSyncService(db)
        self.gradebook_integration = GradebookIntegrationService(db)
        
        # Predefined schedule templates
        self.schedule_templates = {
            ScheduleFrequency.REAL_TIME: {
                'schedule_type': 'real_time',
                'real_time_enabled': True,
                'cron_expression': None
            },
            ScheduleFrequency.EVERY_5_MINUTES: {
                'schedule_type': 'custom',
                'real_time_enabled': False,
                'cron_expression': '*/5 * * * *'
            },
            ScheduleFrequency.EVERY_15_MINUTES: {
                'schedule_type': 'custom',
                'real_time_enabled': False,
                'cron_expression': '*/15 * * * *'
            },
            ScheduleFrequency.EVERY_30_MINUTES: {
                'schedule_type': 'custom',
                'real_time_enabled': False,
                'cron_expression': '*/30 * * * *'
            },
            ScheduleFrequency.HOURLY: {
                'schedule_type': 'hourly',
                'real_time_enabled': False,
                'hourly_at_minute': 0,
                'cron_expression': '0 * * * *'
            },
            ScheduleFrequency.EVERY_2_HOURS: {
                'schedule_type': 'custom',
                'real_time_enabled': False,
                'cron_expression': '0 */2 * * *'
            },
            ScheduleFrequency.EVERY_6_HOURS: {
                'schedule_type': 'custom',
                'real_time_enabled': False,
                'cron_expression': '0 */6 * * *'
            },
            ScheduleFrequency.DAILY: {
                'schedule_type': 'daily',
                'real_time_enabled': False,
                'daily_at_time': '02:00',
                'cron_expression': '0 2 * * *'
            },
            ScheduleFrequency.WEEKLY: {
                'schedule_type': 'weekly',
                'real_time_enabled': False,
                'daily_at_time': '02:00',
                'weekly_days': [0],  # Monday
                'cron_expression': '0 2 * * 1'
            }
        }
    
    async def create_sync_schedule(
        self,
        integration_id: int,
        name: str,
        data_types: List[str],
        sync_direction: SyncDirection,
        frequency: Union[ScheduleFrequency, str],
        description: Optional[str] = None,
        custom_config: Optional[Dict[str, Any]] = None
    ) -> SyncSchedule:
        """
        Create a new sync schedule.
        
        Args:
            integration_id: SIS integration ID
            name: Schedule name
            data_types: List of data types to sync
            sync_direction: Direction of synchronization
            frequency: Schedule frequency
            description: Optional description
            custom_config: Custom configuration overrides
            
        Returns:
            Created sync schedule
        """
        logger.info(f"Creating sync schedule '{name}' for integration {integration_id}")
        
        # Validate integration exists
        integration = await self._get_integration(integration_id)
        if not integration:
            raise ValueError(f"Integration {integration_id} not found")
        
        # Validate data types
        for data_type in data_types:
            try:
                DataType(data_type)
            except ValueError:
                raise ValueError(f"Invalid data type: {data_type}")
        
        # Get schedule template
        template = self.schedule_templates.get(frequency, {})
        if isinstance(frequency, str) and frequency not in [f.value for f in ScheduleFrequency]:
            raise ValueError(f"Invalid frequency: {frequency}")
        
        # Create schedule configuration
        schedule_config = {
            'name': name,
            'description': description,
            'data_types': data_types,
            'sync_direction': sync_direction,
            'is_enabled': True,
            'batch_size': 100,
            'timeout_minutes': 30,
            'retry_attempts': 3,
            'retry_delay_minutes': 5
        }
        
        # Apply template
        schedule_config.update(template)
        
        # Apply custom config overrides
        if custom_config:
            schedule_config.update(custom_config)
        
        # Create the schedule
        schedule = SyncSchedule(
            integration_id=integration_id,
            **schedule_config
        )
        
        # Calculate next run time
        schedule.next_run_at = self._calculate_next_run_time(schedule, datetime.utcnow())
        
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        
        logger.info(f"Created sync schedule {schedule.id} with frequency {frequency}")
        return schedule
    
    async def update_sync_schedule(
        self,
        schedule_id: int,
        updates: Dict[str, Any]
    ) -> Optional[SyncSchedule]:
        """
        Update an existing sync schedule.
        
        Args:
            schedule_id: Schedule ID to update
            updates: Fields to update
            
        Returns:
            Updated schedule or None if not found
        """
        result = await self.db.execute(
            select(SyncSchedule).where(SyncSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        
        if not schedule:
            return None
        
        # Update fields
        for field, value in updates.items():
            if hasattr(schedule, field):
                setattr(schedule, field, value)
        
        # Recalculate next run time if schedule changed
        if any(field in updates for field in [
            'schedule_type', 'cron_expression', 'daily_at_time',
            'hourly_at_minute', 'weekly_days', 'real_time_enabled'
        ]):
            schedule.next_run_at = self._calculate_next_run_time(schedule, datetime.utcnow())
        
        await self.db.commit()
        await self.db.refresh(schedule)
        
        logger.info(f"Updated sync schedule {schedule_id}")
        return schedule
    
    async def delete_sync_schedule(self, schedule_id: int) -> bool:
        """
        Delete a sync schedule and cancel any running operations.
        
        Args:
            schedule_id: Schedule ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        result = await self.db.execute(
            select(SyncSchedule).where(SyncSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        
        if not schedule:
            return False
        
        # Cancel any running operations for this schedule
        await self.db.execute(
            update(SyncOperation)
            .where(
                and_(
                    SyncOperation.schedule_id == schedule_id,
                    SyncOperation.status == SyncStatus.RUNNING
                )
            )
            .values(
                status=SyncStatus.CANCELLED,
                completed_at=datetime.utcnow(),
                error_message="Schedule deleted"
            )
        )
        
        # Delete the schedule
        await self.db.delete(schedule)
        await self.db.commit()
        
        logger.info(f"Deleted sync schedule {schedule_id}")
        return True
    
    async def enable_schedule(self, schedule_id: int) -> bool:
        """Enable a sync schedule."""
        return await self._update_schedule_status(schedule_id, True)
    
    async def disable_schedule(self, schedule_id: int) -> bool:
        """Disable a sync schedule."""
        return await self._update_schedule_status(schedule_id, False)
    
    async def _update_schedule_status(self, schedule_id: int, enabled: bool) -> bool:
        """Update schedule enabled status."""
        result = await self.db.execute(
            update(SyncSchedule)
            .where(SyncSchedule.id == schedule_id)
            .values(is_enabled=enabled)
        )
        
        if result.rowcount > 0:
            await self.db.commit()
            status_text = "enabled" if enabled else "disabled"
            logger.info(f"Schedule {schedule_id} {status_text}")
            return True
        
        return False
    
    async def get_schedule(self, schedule_id: int) -> Optional[SyncSchedule]:
        """Get a sync schedule by ID."""
        result = await self.db.execute(
            select(SyncSchedule)
            .options(selectinload(SyncSchedule.integration))
            .where(SyncSchedule.id == schedule_id)
        )
        return result.scalar_one_or_none()
    
    async def list_schedules(
        self,
        integration_id: Optional[int] = None,
        enabled_only: bool = False
    ) -> List[SyncSchedule]:
        """List sync schedules with optional filtering."""
        query = select(SyncSchedule).options(selectinload(SyncSchedule.integration))
        
        if integration_id:
            query = query.where(SyncSchedule.integration_id == integration_id)
        
        if enabled_only:
            query = query.where(SyncSchedule.is_enabled == True)
        
        query = query.order_by(SyncSchedule.created_at.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def trigger_manual_sync(
        self,
        schedule_id: int,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Manually trigger a sync operation for a schedule.
        
        Args:
            schedule_id: Schedule ID to trigger
            force: Force sync even if schedule is disabled
            
        Returns:
            Sync operation results
        """
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")
        
        if not schedule.is_enabled and not force:
            raise ValueError(f"Schedule {schedule_id} is disabled")
        
        logger.info(f"Manually triggering sync for schedule {schedule_id}")
        
        # Check if there's already a running sync for this schedule
        result = await self.db.execute(
            select(SyncOperation).where(
                and_(
                    SyncOperation.schedule_id == schedule_id,
                    SyncOperation.status == SyncStatus.RUNNING
                )
            )
        )
        
        if result.scalar_one_or_none():
            raise ValueError(f"Sync operation already running for schedule {schedule_id}")
        
        # Execute the sync based on data types
        results = {'total_results': []}
        
        for data_type_str in schedule.data_types:
            try:
                data_type = DataType(data_type_str)
                
                if data_type == DataType.STUDENT_DEMOGRAPHICS:
                    sync_result = await self.bidirectional_sync.sync_student_demographics(
                        schedule.integration_id, schedule.sync_direction
                    )
                elif data_type == DataType.ENROLLMENT:
                    sync_result = await self.bidirectional_sync.sync_enrollment_data(
                        schedule.integration_id, schedule.sync_direction
                    )
                elif data_type == DataType.PARTICIPATION:
                    sync_result = await self.gradebook_integration.sync_participation_grades(
                        schedule.integration_id
                    )
                else:
                    logger.warning(f"Manual sync not supported for data type: {data_type}")
                    continue
                
                results['total_results'].append({
                    'data_type': data_type_str,
                    'result': sync_result
                })
            
            except Exception as e:
                logger.error(f"Error in manual sync for {data_type_str}: {e}")
                results['total_results'].append({
                    'data_type': data_type_str,
                    'error': str(e)
                })
        
        # Update schedule's last run time
        schedule.last_run_at = datetime.utcnow()
        schedule.next_run_at = self._calculate_next_run_time(schedule, datetime.utcnow())
        await self.db.commit()
        
        return results
    
    async def get_schedule_statistics(
        self,
        schedule_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get statistics for a sync schedule.
        
        Args:
            schedule_id: Schedule ID
            days: Number of days to look back
            
        Returns:
            Schedule statistics
        """
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            return {}
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get sync operations for this schedule
        result = await self.db.execute(
            select(SyncOperation).where(
                and_(
                    SyncOperation.schedule_id == schedule_id,
                    SyncOperation.created_at >= cutoff_date
                )
            ).order_by(SyncOperation.created_at.desc())
        )
        operations = list(result.scalars().all())
        
        # Calculate statistics
        total_operations = len(operations)
        successful_operations = len([op for op in operations if op.status == SyncStatus.COMPLETED])
        failed_operations = len([op for op in operations if op.status == SyncStatus.FAILED])
        
        # Calculate average duration for completed operations
        completed_ops = [op for op in operations if op.duration_seconds is not None]
        avg_duration = sum(op.duration_seconds for op in completed_ops) / len(completed_ops) if completed_ops else 0
        
        # Calculate success rate
        success_rate = (successful_operations / total_operations * 100) if total_operations > 0 else 0
        
        return {
            'schedule_id': schedule_id,
            'schedule_name': schedule.name,
            'is_enabled': schedule.is_enabled,
            'data_types': schedule.data_types,
            'sync_direction': schedule.sync_direction.value,
            'last_run_at': schedule.last_run_at,
            'next_run_at': schedule.next_run_at,
            'consecutive_failures': schedule.consecutive_failures,
            'period_days': days,
            'statistics': {
                'total_operations': total_operations,
                'successful_operations': successful_operations,
                'failed_operations': failed_operations,
                'success_rate': round(success_rate, 2),
                'average_duration_seconds': round(avg_duration, 2)
            },
            'recent_operations': [
                {
                    'id': op.id,
                    'operation_id': op.operation_id,
                    'status': op.status.value,
                    'started_at': op.started_at,
                    'completed_at': op.completed_at,
                    'duration_seconds': op.duration_seconds,
                    'successful_records': op.successful_records,
                    'failed_records': op.failed_records,
                    'error_message': op.error_message
                }
                for op in operations[:10]  # Last 10 operations
            ]
        }
    
    def _calculate_next_run_time(self, schedule: SyncSchedule, current_time: datetime) -> datetime:
        """Calculate the next run time for a schedule."""
        if schedule.real_time_enabled:
            # Real-time schedules check frequently
            return current_time + timedelta(minutes=1)
        
        if schedule.cron_expression:
            try:
                cron = croniter(schedule.cron_expression, current_time)
                return cron.get_next(datetime)
            except Exception as e:
                logger.error(f"Invalid cron expression {schedule.cron_expression}: {e}")
                return current_time + timedelta(hours=1)  # Fallback
        
        # Handle other schedule types
        if schedule.schedule_type == 'hourly':
            minute = schedule.hourly_at_minute or 0
            next_hour = current_time.replace(second=0, microsecond=0) + timedelta(hours=1)
            return next_hour.replace(minute=minute)
        
        elif schedule.schedule_type == 'daily' and schedule.daily_at_time:
            try:
                target_time = datetime.strptime(schedule.daily_at_time, "%H:%M").time()
                next_date = current_time.date() + timedelta(days=1)
                return datetime.combine(next_date, target_time)
            except ValueError:
                return current_time + timedelta(days=1)
        
        elif schedule.schedule_type == 'weekly' and schedule.weekly_days and schedule.daily_at_time:
            try:
                target_time = datetime.strptime(schedule.daily_at_time, "%H:%M").time()
                current_weekday = current_time.weekday()
                
                # Find next scheduled day
                days_ahead = []
                for day in schedule.weekly_days:
                    if day > current_weekday:
                        days_ahead.append(day - current_weekday)
                    elif day < current_weekday:
                        days_ahead.append(7 + day - current_weekday)
                    elif current_time.time() < target_time:
                        days_ahead.append(0)  # Today but time hasn't passed
                    else:
                        days_ahead.append(7)  # Next week
                
                next_days = min(days_ahead) if days_ahead else 7
                next_date = current_time.date() + timedelta(days=next_days)
                return datetime.combine(next_date, target_time)
            except ValueError:
                return current_time + timedelta(weeks=1)
        
        # Default fallback
        return current_time + timedelta(hours=1)
    
    async def _get_integration(self, integration_id: int) -> Optional[SISIntegration]:
        """Get SIS integration by ID."""
        result = await self.db.execute(
            select(SISIntegration).where(SISIntegration.id == integration_id)
        )
        return result.scalar_one_or_none()