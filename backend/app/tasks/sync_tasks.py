"""
Background tasks for synchronization operations.

Handles scheduled sync operations, cleanup tasks, and background processing
for the Data Synchronization Engine.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
import uuid
try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    class croniter:
        def __init__(self, *args, **kwargs):
            pass
        def get_next(self, cls):
            from datetime import datetime, timedelta
            return datetime.utcnow() + timedelta(hours=1)
        def get_prev(self, cls):
            from datetime import datetime, timedelta
            return datetime.utcnow() - timedelta(hours=1)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, or_, desc, func
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.sync_metadata import (
    SyncSchedule, SyncOperation, SyncStatus, SyncType, DataType, 
    SyncDirection, HistoricalData
)
from app.models.sis_integration import SISIntegration, SISIntegrationStatus
from app.services.sis_service import SISService

logger = logging.getLogger(__name__)


class SyncTaskManager:
    """
    Manages background sync tasks and scheduling.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.sis_service = SISService(db)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
    
    async def start(self) -> None:
        """Start the task manager and background processes."""
        logger.info("Starting sync task manager")
        
        # Start the main scheduler loop
        self._running_tasks['scheduler'] = asyncio.create_task(
            self._scheduler_loop()
        )
        
        # Start cleanup task
        self._running_tasks['cleanup'] = asyncio.create_task(
            self._cleanup_loop()
        )
        
        logger.info("Sync task manager started")
    
    async def stop(self) -> None:
        """Stop the task manager and all running tasks."""
        logger.info("Stopping sync task manager")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel all running tasks
        for task_name, task in self._running_tasks.items():
            if not task.done():
                logger.info(f"Cancelling task: {task_name}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._running_tasks.clear()
        logger.info("Sync task manager stopped")
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that checks for due sync operations."""
        logger.info("Started sync scheduler loop")
        
        while not self._shutdown_event.is_set():
            try:
                await self._check_scheduled_syncs()
                
                # Wait for next check (1 minute intervals)
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=60
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    pass  # Continue with next check
                    
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Sync scheduler loop stopped")
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup loop for expired data."""
        logger.info("Started cleanup loop")
        
        while not self._shutdown_event.is_set():
            try:
                await self._cleanup_expired_data()
                
                # Run cleanup every 6 hours
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=21600  # 6 hours
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    pass  # Continue with next cleanup
                    
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour on error
        
        logger.info("Cleanup loop stopped")
    
    async def _check_scheduled_syncs(self) -> None:
        """Check for and execute scheduled sync operations."""
        current_time = datetime.utcnow()
        
        # Get all enabled schedules
        result = await self.db.execute(
            select(SyncSchedule)
            .options(selectinload(SyncSchedule.integration))
            .where(
                and_(
                    SyncSchedule.is_enabled == True,
                    or_(
                        SyncSchedule.next_run_at <= current_time,
                        SyncSchedule.next_run_at.is_(None)
                    )
                )
            )
        )
        schedules = result.scalars().all()
        
        for schedule in schedules:
            try:
                if await self._should_run_schedule(schedule, current_time):
                    # Create sync operation task
                    task_name = f"sync_{schedule.id}_{uuid.uuid4().hex[:8]}"
                    self._running_tasks[task_name] = asyncio.create_task(
                        self._execute_scheduled_sync(schedule)
                    )
                    
                    # Update next run time
                    schedule.next_run_at = self._calculate_next_run_time(schedule, current_time)
                    schedule.last_run_at = current_time
                    
            except Exception as e:
                logger.error(f"Error scheduling sync for schedule {schedule.id}: {e}")
                schedule.consecutive_failures += 1
                
                # Disable schedule after too many failures
                if schedule.consecutive_failures >= 5:
                    schedule.is_enabled = False
                    logger.warning(f"Disabled schedule {schedule.id} due to consecutive failures")
        
        await self.db.commit()
        
        # Clean up completed tasks
        completed_tasks = [
            name for name, task in self._running_tasks.items() 
            if task.done() and name != 'scheduler' and name != 'cleanup'
        ]
        for task_name in completed_tasks:
            del self._running_tasks[task_name]
    
    async def _should_run_schedule(self, schedule: SyncSchedule, current_time: datetime) -> bool:
        """Check if a schedule should run now."""
        # Check if integration is healthy
        if not schedule.integration.is_healthy:
            logger.debug(f"Skipping schedule {schedule.id} - integration not healthy")
            return False
        
        # Check if there's already a running sync for this schedule
        result = await self.db.execute(
            select(SyncOperation).where(
                and_(
                    SyncOperation.schedule_id == schedule.id,
                    SyncOperation.status == SyncStatus.RUNNING
                )
            )
        )
        if result.scalar_one_or_none():
            logger.debug(f"Skipping schedule {schedule.id} - sync already running")
            return False
        
        # Real-time schedules don't use timing
        if schedule.real_time_enabled:
            return True
        
        # Check timing based on schedule type
        if schedule.schedule_type == "hourly":
            return self._check_hourly_schedule(schedule, current_time)
        elif schedule.schedule_type == "daily":
            return self._check_daily_schedule(schedule, current_time)
        elif schedule.schedule_type == "weekly":
            return self._check_weekly_schedule(schedule, current_time)
        elif schedule.cron_expression:
            return self._check_cron_schedule(schedule, current_time)
        
        return False
    
    def _check_hourly_schedule(self, schedule: SyncSchedule, current_time: datetime) -> bool:
        """Check if hourly schedule should run."""
        if schedule.hourly_at_minute is None:
            return True  # Run every hour
        
        return current_time.minute == schedule.hourly_at_minute
    
    def _check_daily_schedule(self, schedule: SyncSchedule, current_time: datetime) -> bool:
        """Check if daily schedule should run."""
        if not schedule.daily_at_time:
            return False
        
        try:
            target_time = datetime.strptime(schedule.daily_at_time, "%H:%M").time()
            current_time_only = current_time.time()
            
            # Check if we're within 1 minute of the target time
            target_minutes = target_time.hour * 60 + target_time.minute
            current_minutes = current_time_only.hour * 60 + current_time_only.minute
            
            return abs(target_minutes - current_minutes) <= 1
        except ValueError:
            logger.error(f"Invalid daily_at_time format for schedule {schedule.id}: {schedule.daily_at_time}")
            return False
    
    def _check_weekly_schedule(self, schedule: SyncSchedule, current_time: datetime) -> bool:
        """Check if weekly schedule should run."""
        if not schedule.weekly_days or not schedule.daily_at_time:
            return False
        
        # Check if today is in the list of weekly days
        weekday = current_time.weekday()  # 0 = Monday
        if weekday not in schedule.weekly_days:
            return False
        
        # Check the time
        return self._check_daily_schedule(schedule, current_time)
    
    def _check_cron_schedule(self, schedule: SyncSchedule, current_time: datetime) -> bool:
        """Check if cron schedule should run."""
        try:
            cron = croniter(schedule.cron_expression, current_time)
            next_run = cron.get_prev(datetime)
            
            # Check if we should have run in the last minute
            return (current_time - next_run).total_seconds() < 60
        except Exception as e:
            logger.error(f"Invalid cron expression for schedule {schedule.id}: {e}")
            return False
    
    def _calculate_next_run_time(self, schedule: SyncSchedule, current_time: datetime) -> datetime:
        """Calculate the next run time for a schedule."""
        if schedule.real_time_enabled:
            return current_time + timedelta(minutes=1)  # Check again in a minute
        
        if schedule.schedule_type == "hourly":
            if schedule.hourly_at_minute is not None:
                next_hour = current_time.replace(second=0, microsecond=0) + timedelta(hours=1)
                return next_hour.replace(minute=schedule.hourly_at_minute)
            else:
                return current_time + timedelta(hours=1)
        
        elif schedule.schedule_type == "daily" and schedule.daily_at_time:
            try:
                target_time = datetime.strptime(schedule.daily_at_time, "%H:%M").time()
                next_day = current_time.date() + timedelta(days=1)
                return datetime.combine(next_day, target_time)
            except ValueError:
                return current_time + timedelta(days=1)
        
        elif schedule.schedule_type == "weekly" and schedule.weekly_days and schedule.daily_at_time:
            try:
                target_time = datetime.strptime(schedule.daily_at_time, "%H:%M").time()
                days_ahead = []
                current_weekday = current_time.weekday()
                
                for day in schedule.weekly_days:
                    if day > current_weekday:
                        days_ahead.append(day - current_weekday)
                    elif day < current_weekday:
                        days_ahead.append(7 + day - current_weekday)
                    # Same day - check if time has passed
                    elif current_time.time() < target_time:
                        days_ahead.append(0)
                    else:
                        days_ahead.append(7)
                
                next_days = min(days_ahead) if days_ahead else 7
                next_date = current_time.date() + timedelta(days=next_days)
                return datetime.combine(next_date, target_time)
            except ValueError:
                return current_time + timedelta(weeks=1)
        
        elif schedule.cron_expression:
            try:
                cron = croniter(schedule.cron_expression, current_time)
                return cron.get_next(datetime)
            except Exception:
                return current_time + timedelta(hours=1)  # Fallback
        
        return current_time + timedelta(hours=1)  # Default fallback
    
    async def _execute_scheduled_sync(self, schedule: SyncSchedule) -> None:
        """Execute a scheduled sync operation."""
        operation_id = str(uuid.uuid4())
        
        try:
            logger.info(f"Starting scheduled sync for schedule {schedule.id}")
            
            # Create sync operation record
            sync_operation = SyncOperation(
                integration_id=schedule.integration_id,
                schedule_id=schedule.id,
                operation_id=operation_id,
                data_type=DataType(schedule.data_types[0]) if schedule.data_types else DataType.STUDENT_DEMOGRAPHICS,
                sync_direction=schedule.sync_direction,
                sync_type=SyncType.SCHEDULED,
                status=SyncStatus.RUNNING,
                started_at=datetime.utcnow()
            )
            
            self.db.add(sync_operation)
            await self.db.commit()
            await self.db.refresh(sync_operation)
            
            # Execute the sync based on data types
            total_success = 0
            total_failed = 0
            
            for data_type_str in schedule.data_types:
                try:
                    data_type = DataType(data_type_str)
                    
                    if data_type == DataType.STUDENT_DEMOGRAPHICS:
                        result = await self._sync_student_demographics(schedule, sync_operation)
                    elif data_type == DataType.ENROLLMENT:
                        result = await self._sync_enrollments(schedule, sync_operation)
                    elif data_type == DataType.GRADES:
                        result = await self._sync_grades(schedule, sync_operation)
                    elif data_type == DataType.PARTICIPATION:
                        result = await self._sync_participation_grades(schedule, sync_operation)
                    else:
                        logger.warning(f"Unsupported data type for sync: {data_type}")
                        continue
                    
                    total_success += result.get('successful', 0)
                    total_failed += result.get('failed', 0)
                    
                except Exception as e:
                    logger.error(f"Error syncing {data_type_str}: {e}")
                    total_failed += 1
            
            # Update operation status
            sync_operation.update_progress(
                processed=total_success + total_failed,
                successful=total_success,
                failed=total_failed
            )
            sync_operation.mark_completed(success=total_failed == 0)
            
            # Reset consecutive failures on success
            if total_failed == 0:
                schedule.consecutive_failures = 0
            else:
                schedule.consecutive_failures += 1
            
            await self.db.commit()
            
            logger.info(f"Completed scheduled sync for schedule {schedule.id}: "
                       f"{total_success} success, {total_failed} failed")
        
        except Exception as e:
            logger.error(f"Scheduled sync failed for schedule {schedule.id}: {e}")
            
            # Update operation as failed if it exists
            try:
                result = await self.db.execute(
                    select(SyncOperation).where(SyncOperation.operation_id == operation_id)
                )
                sync_operation = result.scalar_one_or_none()
                if sync_operation:
                    sync_operation.status = SyncStatus.FAILED
                    sync_operation.error_message = str(e)
                    sync_operation.completed_at = datetime.utcnow()
                    await self.db.commit()
            except Exception as update_error:
                logger.error(f"Error updating failed sync operation: {update_error}")
            
            schedule.consecutive_failures += 1
            await self.db.commit()
    
    async def _sync_student_demographics(self, schedule: SyncSchedule, sync_operation: SyncOperation) -> Dict[str, Any]:
        """Sync student demographic data."""
        logger.info(f"Syncing student demographics for integration {schedule.integration_id}")
        
        # Use SIS service to sync student data
        if schedule.sync_direction in [SyncDirection.FROM_SIS, SyncDirection.BIDIRECTIONAL]:
            # Sync from SIS to local system
            result = await self.sis_service.sync_integration_roster(
                schedule.integration_id
            )
            return result
        
        return {"successful": 0, "failed": 0}
    
    async def _sync_enrollments(self, schedule: SyncSchedule, sync_operation: SyncOperation) -> Dict[str, Any]:
        """Sync enrollment data."""
        logger.info(f"Syncing enrollments for integration {schedule.integration_id}")
        
        if schedule.sync_direction in [SyncDirection.FROM_SIS, SyncDirection.BIDIRECTIONAL]:
            result = await self.sis_service.sync_enrollments(schedule.integration_id)
            return result
        
        return {"successful": 0, "failed": 0}
    
    async def _sync_grades(self, schedule: SyncSchedule, sync_operation: SyncOperation) -> Dict[str, Any]:
        """Sync grade data."""
        logger.info(f"Syncing grades for integration {schedule.integration_id}")
        
        # This would be implemented to sync grade data
        # For now, return placeholder
        return {"successful": 0, "failed": 0}
    
    async def _sync_participation_grades(self, schedule: SyncSchedule, sync_operation: SyncOperation) -> Dict[str, Any]:
        """Sync participation grades based on attendance."""
        logger.info(f"Syncing participation grades for integration {schedule.integration_id}")
        
        # This will be implemented as part of grade book integration
        # For now, return placeholder
        return {"successful": 0, "failed": 0}
    
    async def _cleanup_expired_data(self) -> None:
        """Clean up expired historical data and old sync operations."""
        logger.info("Starting data cleanup")
        current_time = datetime.utcnow()
        
        try:
            # Clean up expired historical data
            result = await self.db.execute(
                delete(HistoricalData).where(
                    HistoricalData.expires_at <= current_time
                )
            )
            expired_historical = result.rowcount
            
            # Clean up old sync operations (keep for 90 days)
            cutoff_date = current_time - timedelta(days=90)
            result = await self.db.execute(
                delete(SyncOperation).where(
                    and_(
                        SyncOperation.created_at <= cutoff_date,
                        SyncOperation.status.in_([SyncStatus.COMPLETED, SyncStatus.FAILED])
                    )
                )
            )
            old_operations = result.rowcount
            
            await self.db.commit()
            
            if expired_historical > 0 or old_operations > 0:
                logger.info(f"Cleanup completed: {expired_historical} historical records, "
                           f"{old_operations} old sync operations")
        
        except Exception as e:
            logger.error(f"Error during data cleanup: {e}")
            await self.db.rollback()


# Standalone task functions for use with task queue systems

async def schedule_sync_operation(
    integration_id: int,
    data_types: List[str],
    sync_direction: str,
    sync_type: str = "manual"
) -> str:
    """
    Schedule a sync operation.
    
    Returns:
        operation_id of the created sync operation
    """
    async with get_db() as db:
        operation_id = str(uuid.uuid4())
        
        sync_operation = SyncOperation(
            integration_id=integration_id,
            operation_id=operation_id,
            data_type=DataType(data_types[0]) if data_types else DataType.STUDENT_DEMOGRAPHICS,
            sync_direction=SyncDirection(sync_direction),
            sync_type=SyncType(sync_type),
            status=SyncStatus.PENDING
        )
        
        db.add(sync_operation)
        await db.commit()
        
        logger.info(f"Scheduled sync operation {operation_id}")
        return operation_id


async def execute_scheduled_sync(operation_id: str) -> Dict[str, Any]:
    """
    Execute a scheduled sync operation.
    
    Args:
        operation_id: ID of the sync operation to execute
        
    Returns:
        Dictionary with sync results
    """
    async with get_db() as db:
        # Get the sync operation
        result = await db.execute(
            select(SyncOperation)
            .options(selectinload(SyncOperation.integration))
            .where(SyncOperation.operation_id == operation_id)
        )
        sync_operation = result.scalar_one_or_none()
        
        if not sync_operation:
            raise ValueError(f"Sync operation {operation_id} not found")
        
        if sync_operation.status != SyncStatus.PENDING:
            raise ValueError(f"Sync operation {operation_id} is not in pending status")
        
        try:
            # Update status to running
            sync_operation.status = SyncStatus.RUNNING
            sync_operation.started_at = datetime.utcnow()
            await db.commit()
            
            # Execute the sync using SIS service
            sis_service = SISService(db)
            
            if sync_operation.data_type == DataType.STUDENT_DEMOGRAPHICS:
                result = await sis_service.sync_integration_roster(
                    sync_operation.integration_id
                )
            elif sync_operation.data_type == DataType.ENROLLMENT:
                result = await sis_service.sync_enrollments(
                    sync_operation.integration_id
                )
            else:
                result = {"successful": 0, "failed": 0, "message": "Data type not yet implemented"}
            
            # Update operation with results
            sync_operation.update_progress(
                processed=result.get('successful', 0) + result.get('failed', 0),
                successful=result.get('successful', 0),
                failed=result.get('failed', 0)
            )
            sync_operation.mark_completed(success=result.get('failed', 0) == 0)
            
            await db.commit()
            
            return {
                'operation_id': operation_id,
                'status': sync_operation.status.value,
                'results': result
            }
        
        except Exception as e:
            sync_operation.status = SyncStatus.FAILED
            sync_operation.error_message = str(e)
            sync_operation.completed_at = datetime.utcnow()
            await db.commit()
            
            logger.error(f"Sync operation {operation_id} failed: {e}")
            raise


async def cleanup_expired_data() -> Dict[str, int]:
    """
    Clean up expired historical data.
    
    Returns:
        Dictionary with cleanup statistics
    """
    async with get_db() as db:
        current_time = datetime.utcnow()
        
        # Clean up expired historical data
        result = await db.execute(
            delete(HistoricalData).where(
                HistoricalData.expires_at <= current_time
            )
        )
        expired_historical = result.rowcount
        
        # Clean up old sync operations (keep for 90 days)
        cutoff_date = current_time - timedelta(days=90)
        result = await db.execute(
            delete(SyncOperation).where(
                and_(
                    SyncOperation.created_at <= cutoff_date,
                    SyncOperation.status.in_([SyncStatus.COMPLETED, SyncStatus.FAILED])
                )
            )
        )
        old_operations = result.rowcount
        
        await db.commit()
        
        return {
            'expired_historical_records': expired_historical,
            'old_sync_operations': old_operations
        }