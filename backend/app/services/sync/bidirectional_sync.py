"""
Bidirectional Synchronization Service

Handles bidirectional sync of student demographics and enrollment data
between the local system and external SIS systems.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
import uuid
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.models.sync_metadata import (
    SyncOperation, SyncRecordChange, SyncConflict, HistoricalData,
    SyncStatus, SyncDirection, DataType, SyncType
)
from app.models.sis_integration import SISIntegration, SISStudentMapping
from app.models.user import User
from app.models.class_session import ClassSession
from app.services.sis_service import SISService
from app.utils.conflict_resolution import ConflictResolver, ConflictResolutionStrategy

logger = logging.getLogger(__name__)


class BidirectionalSyncService:
    """
    Service for handling bidirectional synchronization of student data.
    
    Coordinates data flow between local system and external SIS,
    handling conflicts, validation, and historical data preservation.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.sis_service = SISService(db)
        self.conflict_resolver = ConflictResolver(db)
        
        # Configuration for sync operations
        self.batch_size = 100
        self.max_retries = 3
        self.retry_delay = 5  # seconds
    
    async def sync_student_demographics(
        self,
        integration_id: int,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
        student_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """
        Sync student demographic data.
        
        Args:
            integration_id: SIS integration ID
            direction: Sync direction (to_sis, from_sis, bidirectional)
            student_ids: Specific students to sync (None for all)
            force_full_sync: Force full sync instead of incremental
            
        Returns:
            Sync operation results
        """
        logger.info(f"Starting student demographics sync for integration {integration_id}")
        
        # Create sync operation
        sync_operation = await self._create_sync_operation(
            integration_id=integration_id,
            data_type=DataType.STUDENT_DEMOGRAPHICS,
            sync_direction=direction
        )
        
        try:
            results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
            
            if direction in [SyncDirection.FROM_SIS, SyncDirection.BIDIRECTIONAL]:
                # Sync from SIS to local
                from_sis_result = await self._sync_demographics_from_sis(
                    sync_operation, student_ids, force_full_sync
                )
                results['successful'] += from_sis_result['successful']
                results['failed'] += from_sis_result['failed']
                results['conflicts'] += from_sis_result['conflicts']
                results['skipped'] += from_sis_result['skipped']
            
            if direction in [SyncDirection.TO_SIS, SyncDirection.BIDIRECTIONAL]:
                # Sync from local to SIS
                to_sis_result = await self._sync_demographics_to_sis(
                    sync_operation, student_ids, force_full_sync
                )
                results['successful'] += to_sis_result['successful']
                results['failed'] += to_sis_result['failed']
                results['conflicts'] += to_sis_result['conflicts']
                results['skipped'] += to_sis_result['skipped']
            
            # Update operation progress
            total_processed = sum(results.values())
            sync_operation.update_progress(
                processed=total_processed,
                successful=results['successful'],
                failed=results['failed'],
                skipped=results['skipped']
            )
            
            # Mark as completed
            sync_operation.mark_completed(success=results['failed'] == 0)
            await self.db.commit()
            
            logger.info(f"Completed demographics sync: {results}")
            return results
        
        except Exception as e:
            logger.error(f"Demographics sync failed: {e}")
            sync_operation.status = SyncStatus.FAILED
            sync_operation.error_message = str(e)
            sync_operation.completed_at = datetime.utcnow()
            await self.db.commit()
            raise
    
    async def sync_enrollment_data(
        self,
        integration_id: int,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
        class_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """
        Sync student enrollment data.
        
        Args:
            integration_id: SIS integration ID
            direction: Sync direction
            class_ids: Specific classes to sync (None for all)
            force_full_sync: Force full sync instead of incremental
            
        Returns:
            Sync operation results
        """
        logger.info(f"Starting enrollment sync for integration {integration_id}")
        
        # Create sync operation
        sync_operation = await self._create_sync_operation(
            integration_id=integration_id,
            data_type=DataType.ENROLLMENT,
            sync_direction=direction
        )
        
        try:
            results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
            
            if direction in [SyncDirection.FROM_SIS, SyncDirection.BIDIRECTIONAL]:
                # Sync from SIS to local
                from_sis_result = await self._sync_enrollment_from_sis(
                    sync_operation, class_ids, force_full_sync
                )
                results['successful'] += from_sis_result['successful']
                results['failed'] += from_sis_result['failed']
                results['conflicts'] += from_sis_result['conflicts']
                results['skipped'] += from_sis_result['skipped']
            
            if direction in [SyncDirection.TO_SIS, SyncDirection.BIDIRECTIONAL]:
                # Sync from local to SIS
                to_sis_result = await self._sync_enrollment_to_sis(
                    sync_operation, class_ids, force_full_sync
                )
                results['successful'] += to_sis_result['successful']
                results['failed'] += to_sis_result['failed']
                results['conflicts'] += to_sis_result['conflicts']
                results['skipped'] += to_sis_result['skipped']
            
            # Update operation progress
            total_processed = sum(results.values())
            sync_operation.update_progress(
                processed=total_processed,
                successful=results['successful'],
                failed=results['failed'],
                skipped=results['skipped']
            )
            
            # Mark as completed
            sync_operation.mark_completed(success=results['failed'] == 0)
            await self.db.commit()
            
            logger.info(f"Completed enrollment sync: {results}")
            return results
        
        except Exception as e:
            logger.error(f"Enrollment sync failed: {e}")
            sync_operation.status = SyncStatus.FAILED
            sync_operation.error_message = str(e)
            sync_operation.completed_at = datetime.utcnow()
            await self.db.commit()
            raise
    
    async def _sync_demographics_from_sis(
        self,
        sync_operation: SyncOperation,
        student_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """Sync student demographics from SIS to local system."""
        logger.info("Syncing demographics from SIS to local")
        
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            # Get integration
            integration = await self._get_integration(sync_operation.integration_id)
            
            # Get student mappings to sync
            mappings = await self._get_student_mappings(
                integration.id, student_ids, force_full_sync
            )
            
            # Process in batches
            for batch_start in range(0, len(mappings), self.batch_size):
                batch_end = min(batch_start + self.batch_size, len(mappings))
                batch_mappings = mappings[batch_start:batch_end]
                
                batch_results = await self._process_demographics_batch_from_sis(
                    sync_operation, integration, batch_mappings
                )
                
                results['successful'] += batch_results['successful']
                results['failed'] += batch_results['failed']
                results['conflicts'] += batch_results['conflicts']
                results['skipped'] += batch_results['skipped']
            
            return results
        
        except Exception as e:
            logger.error(f"Error syncing demographics from SIS: {e}")
            raise
    
    async def _sync_demographics_to_sis(
        self,
        sync_operation: SyncOperation,
        student_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """Sync student demographics from local system to SIS."""
        logger.info("Syncing demographics from local to SIS")
        
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            # Get integration
            integration = await self._get_integration(sync_operation.integration_id)
            
            # Get local students that need sync
            students = await self._get_local_students_for_sync(
                integration.id, student_ids, force_full_sync
            )
            
            # Process in batches
            for batch_start in range(0, len(students), self.batch_size):
                batch_end = min(batch_start + self.batch_size, len(students))
                batch_students = students[batch_start:batch_end]
                
                batch_results = await self._process_demographics_batch_to_sis(
                    sync_operation, integration, batch_students
                )
                
                results['successful'] += batch_results['successful']
                results['failed'] += batch_results['failed']
                results['conflicts'] += batch_results['conflicts']
                results['skipped'] += batch_results['skipped']
            
            return results
        
        except Exception as e:
            logger.error(f"Error syncing demographics to SIS: {e}")
            raise
    
    async def _process_demographics_batch_from_sis(
        self,
        sync_operation: SyncOperation,
        integration: SISIntegration,
        mappings: List[SISStudentMapping]
    ) -> Dict[str, Any]:
        """Process a batch of student demographics from SIS."""
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        # Get SIS student data for this batch
        sis_student_ids = [mapping.sis_student_id for mapping in mappings]
        
        try:
            # Use SIS service to get student data
            sis_data = await self.sis_service._get_provider_instance(integration)
            
            async with sis_data:
                students_data = await sis_data.get_students(sis_student_ids)
            
            for mapping in mappings:
                try:
                    sis_student_data = students_data.get(mapping.sis_student_id)
                    if not sis_student_data:
                        results['skipped'] += 1
                        continue
                    
                    # Get local student
                    result = await self.db.execute(
                        select(User).where(User.id == mapping.local_student_id)
                    )
                    local_student = result.scalar_one_or_none()
                    
                    if not local_student:
                        results['failed'] += 1
                        continue
                    
                    # Check for conflicts
                    conflict = await self._detect_student_data_conflict(
                        local_student, sis_student_data, mapping
                    )
                    
                    if conflict:
                        # Create conflict record
                        await self._create_sync_conflict(
                            sync_operation, mapping, local_student.__dict__, 
                            sis_student_data, conflict
                        )
                        results['conflicts'] += 1
                        continue
                    
                    # Preserve historical data
                    await self._preserve_historical_data(
                        sync_operation, 'student', str(mapping.local_student_id),
                        local_student.__dict__, 'before_update', SyncDirection.FROM_SIS
                    )
                    
                    # Update local student with SIS data
                    await self._update_local_student_from_sis(
                        local_student, sis_student_data
                    )
                    
                    # Create record change
                    await self._create_record_change(
                        sync_operation, 'student', str(mapping.local_student_id),
                        mapping.sis_student_id, 'update', True,
                        local_student.__dict__, sis_student_data
                    )
                    
                    # Update mapping sync status
                    mapping.last_synced_at = datetime.utcnow()
                    mapping.needs_sync = False
                    
                    results['successful'] += 1
                
                except Exception as e:
                    logger.error(f"Error processing student {mapping.local_student_id}: {e}")
                    await self._create_record_change(
                        sync_operation, 'student', str(mapping.local_student_id),
                        mapping.sis_student_id, 'update', False, error_message=str(e)
                    )
                    results['failed'] += 1
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Error processing demographics batch from SIS: {e}")
            await self.db.rollback()
            raise
        
        return results
    
    async def _process_demographics_batch_to_sis(
        self,
        sync_operation: SyncOperation,
        integration: SISIntegration,
        students: List[User]
    ) -> Dict[str, Any]:
        """Process a batch of student demographics to SIS."""
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            # Get SIS provider instance
            sis_provider = await self.sis_service._get_provider_instance(integration)
            
            async with sis_provider:
                for student in students:
                    try:
                        # Get student mapping
                        result = await self.db.execute(
                            select(SISStudentMapping).where(
                                and_(
                                    SISStudentMapping.integration_id == integration.id,
                                    SISStudentMapping.local_student_id == student.id
                                )
                            )
                        )
                        mapping = result.scalar_one_or_none()
                        
                        if not mapping:
                            results['skipped'] += 1
                            continue
                        
                        # Get current SIS data
                        sis_student_data = await sis_provider.get_student(mapping.sis_student_id)
                        
                        if not sis_student_data:
                            results['skipped'] += 1
                            continue
                        
                        # Check for conflicts
                        conflict = await self._detect_student_data_conflict(
                            student, sis_student_data, mapping, direction=SyncDirection.TO_SIS
                        )
                        
                        if conflict:
                            await self._create_sync_conflict(
                                sync_operation, mapping, student.__dict__,
                                sis_student_data, conflict
                            )
                            results['conflicts'] += 1
                            continue
                        
                        # Update SIS with local data
                        local_student_data = self._prepare_student_data_for_sis(student)
                        update_success = await sis_provider.update_student(
                            mapping.sis_student_id, local_student_data
                        )
                        
                        if update_success:
                            # Create record change
                            await self._create_record_change(
                                sync_operation, 'student', str(student.id),
                                mapping.sis_student_id, 'update', True,
                                sis_student_data, local_student_data
                            )
                            
                            # Update mapping
                            mapping.last_synced_at = datetime.utcnow()
                            mapping.needs_sync = False
                            
                            results['successful'] += 1
                        else:
                            results['failed'] += 1
                    
                    except Exception as e:
                        logger.error(f"Error syncing student {student.id} to SIS: {e}")
                        results['failed'] += 1
            
            await self.db.commit()
        
        except Exception as e:
            logger.error(f"Error processing demographics batch to SIS: {e}")
            await self.db.rollback()
            raise
        
        return results
    
    async def _sync_enrollment_from_sis(
        self,
        sync_operation: SyncOperation,
        class_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """Sync enrollment data from SIS to local system."""
        logger.info("Syncing enrollment from SIS to local")
        
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            # Get integration
            integration = await self._get_integration(sync_operation.integration_id)
            
            # Use SIS service to sync enrollments
            sis_result = await self.sis_service.sync_class_enrollments(
                integration.id, class_ids[0] if class_ids else None
            )
            
            results['successful'] = sis_result.get('successful', 0)
            results['failed'] = sis_result.get('failed', 0)
            
            return results
        
        except Exception as e:
            logger.error(f"Error syncing enrollment from SIS: {e}")
            raise
    
    async def _sync_enrollment_to_sis(
        self,
        sync_operation: SyncOperation,
        class_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        """Sync enrollment data from local system to SIS."""
        logger.info("Syncing enrollment from local to SIS")
        
        results = {'successful': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        # For now, enrollment sync to SIS is read-only from SIS
        # This could be implemented if SIS supports enrollment modifications
        logger.info("Enrollment sync to SIS not implemented (SIS is authoritative)")
        
        return results
    
    # Helper methods
    
    async def _create_sync_operation(
        self,
        integration_id: int,
        data_type: DataType,
        sync_direction: SyncDirection
    ) -> SyncOperation:
        """Create a new sync operation record."""
        operation = SyncOperation(
            integration_id=integration_id,
            operation_id=str(uuid.uuid4()),
            data_type=data_type,
            sync_direction=sync_direction,
            sync_type=SyncType.MANUAL,
            status=SyncStatus.RUNNING,
            started_at=datetime.utcnow()
        )
        
        self.db.add(operation)
        await self.db.commit()
        await self.db.refresh(operation)
        
        return operation
    
    async def _get_integration(self, integration_id: int) -> SISIntegration:
        """Get SIS integration by ID."""
        result = await self.db.execute(
            select(SISIntegration).where(SISIntegration.id == integration_id)
        )
        integration = result.scalar_one_or_none()
        
        if not integration:
            raise ValueError(f"Integration {integration_id} not found")
        
        return integration
    
    async def _get_student_mappings(
        self,
        integration_id: int,
        student_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> List[SISStudentMapping]:
        """Get student mappings for sync."""
        query = select(SISStudentMapping).where(
            SISStudentMapping.integration_id == integration_id
        )
        
        if student_ids:
            query = query.where(SISStudentMapping.local_student_id.in_(student_ids))
        
        if not force_full_sync:
            query = query.where(SISStudentMapping.needs_sync == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def _get_local_students_for_sync(
        self,
        integration_id: int,
        student_ids: Optional[List[int]] = None,
        force_full_sync: bool = False
    ) -> List[User]:
        """Get local students that need sync."""
        # Get students through their mappings
        mappings_query = select(SISStudentMapping.local_student_id).where(
            SISStudentMapping.integration_id == integration_id
        )
        
        if student_ids:
            mappings_query = mappings_query.where(
                SISStudentMapping.local_student_id.in_(student_ids)
            )
        
        if not force_full_sync:
            mappings_query = mappings_query.where(SISStudentMapping.needs_sync == True)
        
        result = await self.db.execute(mappings_query)
        local_student_ids = [row[0] for row in result.fetchall()]
        
        if not local_student_ids:
            return []
        
        # Get the actual student records
        students_query = select(User).where(User.id.in_(local_student_ids))
        result = await self.db.execute(students_query)
        return list(result.scalars().all())
    
    async def _detect_student_data_conflict(
        self,
        local_student: User,
        sis_data: Dict[str, Any],
        mapping: SISStudentMapping,
        direction: SyncDirection = SyncDirection.FROM_SIS
    ) -> Optional[List[str]]:
        """Detect conflicts between local and SIS student data."""
        conflicting_fields = []
        
        # Check key fields for conflicts
        field_mappings = {
            'email': 'email',
            'first_name': 'first_name',
            'last_name': 'last_name',
            'phone': 'phone_number'
        }
        
        for local_field, sis_field in field_mappings.items():
            local_value = getattr(local_student, local_field, None)
            sis_value = sis_data.get(sis_field)
            
            if local_value != sis_value and local_value and sis_value:
                # Check if this is a significant difference
                if local_field == 'email':
                    # Email conflicts are always significant
                    conflicting_fields.append(local_field)
                elif local_field in ['first_name', 'last_name']:
                    # Name conflicts require manual review
                    conflicting_fields.append(local_field)
                elif local_field == 'phone':
                    # Phone conflicts if both values exist and differ
                    conflicting_fields.append(local_field)
        
        return conflicting_fields if conflicting_fields else None
    
    async def _create_sync_conflict(
        self,
        sync_operation: SyncOperation,
        mapping: SISStudentMapping,
        local_data: Dict[str, Any],
        external_data: Dict[str, Any],
        conflicting_fields: List[str]
    ) -> SyncConflict:
        """Create a sync conflict record."""
        conflict = SyncConflict(
            sync_operation_id=sync_operation.id,
            record_type='student',
            local_record_id=str(mapping.local_student_id),
            external_record_id=mapping.sis_student_id,
            conflict_type='data_mismatch',
            local_data=local_data,
            external_data=external_data,
            conflicting_fields=conflicting_fields
        )
        
        self.db.add(conflict)
        await self.db.flush()  # Get the ID without committing
        
        return conflict
    
    async def _preserve_historical_data(
        self,
        sync_operation: SyncOperation,
        record_type: str,
        record_id: str,
        data_snapshot: Dict[str, Any],
        change_type: str,
        sync_direction: SyncDirection
    ) -> None:
        """Preserve historical data before changes."""
        historical = HistoricalData(
            sync_operation_id=sync_operation.id,
            record_type=record_type,
            record_id=record_id,
            data_snapshot=data_snapshot,
            change_type=change_type,
            sync_direction=sync_direction,
            source_system='local' if sync_direction == SyncDirection.TO_SIS else 'sis'
        )
        
        # Set expiry based on retention policy (default 1 year)
        historical.set_expiry(365)
        
        self.db.add(historical)
    
    async def _update_local_student_from_sis(
        self,
        local_student: User,
        sis_data: Dict[str, Any]
    ) -> None:
        """Update local student with SIS data."""
        # Update only non-conflicting fields
        if 'email' in sis_data:
            local_student.email = sis_data['email']
        if 'first_name' in sis_data:
            local_student.first_name = sis_data['first_name']
        if 'last_name' in sis_data:
            local_student.last_name = sis_data['last_name']
        if 'phone_number' in sis_data:
            local_student.phone = sis_data['phone_number']
        
        local_student.updated_at = datetime.utcnow()
    
    def _prepare_student_data_for_sis(self, local_student: User) -> Dict[str, Any]:
        """Prepare local student data for SIS update."""
        return {
            'email': local_student.email,
            'first_name': local_student.first_name,
            'last_name': local_student.last_name,
            'phone_number': local_student.phone,
            'updated_at': local_student.updated_at.isoformat() if local_student.updated_at else None
        }
    
    async def _create_record_change(
        self,
        sync_operation: SyncOperation,
        record_type: str,
        local_record_id: str,
        external_record_id: str,
        change_type: str,
        was_successful: bool,
        before_data: Optional[Dict[str, Any]] = None,
        after_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> SyncRecordChange:
        """Create a sync record change entry."""
        # Calculate field changes
        field_changes = {}
        if before_data and after_data:
            for field in set(before_data.keys()) | set(after_data.keys()):
                before_value = before_data.get(field)
                after_value = after_data.get(field)
                if before_value != after_value:
                    field_changes[field] = {
                        'before': before_value,
                        'after': after_value
                    }
        
        record_change = SyncRecordChange(
            sync_operation_id=sync_operation.id,
            record_type=record_type,
            local_record_id=local_record_id,
            external_record_id=external_record_id,
            change_type=change_type,
            field_changes=field_changes if field_changes else None,
            before_data=before_data,
            after_data=after_data,
            was_successful=was_successful,
            error_message=error_message
        )
        
        self.db.add(record_change)
        return record_change