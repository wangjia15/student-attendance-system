"""
Real-time roster synchronization with conflict resolution for SIS integrations.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update, insert
from sqlalchemy.orm import selectinload

from app.models.sis_integration import (
    SISIntegration, SISStudentMapping, SISSyncOperation
)
from app.models.user import User, UserRole
from app.core.sis_config import BaseSISProvider, sis_config_manager
from app.integrations.sis.providers.powerschool import PowerSchoolProvider
from app.integrations.sis.providers.infinite_campus import InfiniteCampusProvider
from app.integrations.sis.providers.skyward import SkywardProvider
from app.integrations.sis.oauth_service import SISOAuthService


logger = logging.getLogger(__name__)


class ConflictResolutionStrategy(str, Enum):
    """Strategies for resolving data conflicts during sync."""
    SIS_WINS = "sis_wins"           # SIS data takes precedence
    LOCAL_WINS = "local_wins"       # Local data takes precedence
    MANUAL = "manual"               # Require manual resolution
    NEWEST_WINS = "newest_wins"     # Most recently updated data wins


class SyncConflict:
    """Represents a data conflict during synchronization."""
    
    def __init__(
        self,
        field: str,
        local_value: Any,
        sis_value: Any,
        local_updated: Optional[datetime] = None,
        sis_updated: Optional[datetime] = None
    ):
        self.field = field
        self.local_value = local_value
        self.sis_value = sis_value
        self.local_updated = local_updated
        self.sis_updated = sis_updated
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict to dictionary for storage."""
        return {
            'field': self.field,
            'local_value': str(self.local_value) if self.local_value is not None else None,
            'sis_value': str(self.sis_value) if self.sis_value is not None else None,
            'local_updated': self.local_updated.isoformat() if self.local_updated else None,
            'sis_updated': self.sis_updated.isoformat() if self.sis_updated else None,
            'detected_at': datetime.utcnow().isoformat()
        }


class RosterSyncService:
    """Service for real-time roster synchronization with conflict resolution."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._provider_classes = {
            'powerschool': PowerSchoolProvider,
            'infinite_campus': InfiniteCampusProvider,
            'skyward': SkywardProvider
        }
        
    async def sync_all_integrations(
        self,
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS
    ) -> Dict[str, Any]:
        """
        Sync rosters for all active integrations.
        
        Args:
            conflict_strategy: Strategy for resolving data conflicts
            
        Returns:
            Summary of sync results
        """
        logger.info("Starting roster sync for all active integrations")
        
        # Get all active integrations
        result = await self.db.execute(
            select(SISIntegration)
            .where(
                and_(
                    SISIntegration.enabled == True,
                    SISIntegration.status == "active"
                )
            )
        )
        integrations = result.scalars().all()
        
        sync_results = {
            'total_integrations': len(integrations),
            'successful_syncs': 0,
            'failed_syncs': 0,
            'conflicts_detected': 0,
            'students_processed': 0,
            'results': []
        }
        
        # Process each integration
        for integration in integrations:
            try:
                result = await self.sync_integration_roster(
                    integration.id,
                    conflict_strategy
                )
                sync_results['results'].append(result)
                
                if result['success']:
                    sync_results['successful_syncs'] += 1
                    sync_results['students_processed'] += result.get('students_processed', 0)
                    sync_results['conflicts_detected'] += result.get('conflicts_detected', 0)
                else:
                    sync_results['failed_syncs'] += 1
                    
            except Exception as e:
                logger.error(f"Error syncing integration {integration.provider_id}: {e}")
                sync_results['failed_syncs'] += 1
                sync_results['results'].append({
                    'integration_id': integration.id,
                    'provider_id': integration.provider_id,
                    'success': False,
                    'error': str(e)
                })
                
        logger.info(
            f"Completed roster sync: {sync_results['successful_syncs']} successful, "
            f"{sync_results['failed_syncs']} failed, "
            f"{sync_results['students_processed']} students processed"
        )
        
        return sync_results
        
    async def sync_integration_roster(
        self,
        integration_id: int,
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS
    ) -> Dict[str, Any]:
        """
        Sync roster for a specific integration.
        
        Args:
            integration_id: ID of the SIS integration
            conflict_strategy: Strategy for resolving data conflicts
            
        Returns:
            Sync result summary
        """
        # Get integration
        result = await self.db.execute(
            select(SISIntegration)
            .where(SISIntegration.id == integration_id)
        )
        integration = result.scalar_one_or_none()
        
        if not integration:
            raise ValueError(f"Integration {integration_id} not found")
            
        if not integration.enabled:
            raise ValueError(f"Integration {integration.provider_id} is disabled")
            
        logger.info(f"Starting roster sync for integration {integration.provider_id}")
        
        # Create sync operation record
        sync_op = SISSyncOperation(
            integration_id=integration.id,
            operation_type='roster_sync',
            status='running',
            started_at=datetime.utcnow()
        )
        self.db.add(sync_op)
        await self.db.commit()
        await self.db.refresh(sync_op)
        
        try:
            # Get provider and sync students
            provider = await self._get_provider(integration)
            
            sync_result = await self._sync_students_with_provider(
                integration,
                provider,
                sync_op,
                conflict_strategy
            )
            
            # Update sync operation as successful
            sync_op.status = 'completed'
            sync_op.completed_at = datetime.utcnow()
            sync_op.successful_records = sync_result.get('students_synced', 0)
            sync_op.processed_records = sync_result.get('students_processed', 0)
            sync_op.failed_records = sync_result.get('students_failed', 0)
            
            # Update integration sync success
            integration.update_sync_success(
                students_count=sync_result.get('students_synced', 0)
            )
            
            await self.db.commit()
            
            logger.info(
                f"Successfully synced roster for integration {integration.provider_id}: "
                f"{sync_result.get('students_synced', 0)} students synced"
            )
            
            return {
                'integration_id': integration.id,
                'provider_id': integration.provider_id,
                'success': True,
                'sync_operation_id': sync_op.id,
                **sync_result
            }
            
        except Exception as e:
            # Update sync operation as failed
            sync_op.status = 'failed'
            sync_op.completed_at = datetime.utcnow()
            sync_op.error_message = str(e)
            
            # Update integration sync failure
            integration.update_sync_failure()
            
            await self.db.commit()
            
            logger.error(f"Failed to sync roster for integration {integration.provider_id}: {e}")
            raise e
            
    async def resolve_student_conflicts(
        self,
        mapping_id: int,
        resolutions: Dict[str, Any]
    ) -> bool:
        """
        Manually resolve conflicts for a student mapping.
        
        Args:
            mapping_id: ID of the student mapping with conflicts
            resolutions: Field resolutions (field_name -> chosen_value)
            
        Returns:
            True if successful
        """
        # Get student mapping with conflicts
        result = await self.db.execute(
            select(SISStudentMapping)
            .where(SISStudentMapping.id == mapping_id)
            .options(selectinload(SISStudentMapping.local_student))
        )
        mapping = result.scalar_one_or_none()
        
        if not mapping or not mapping.sync_conflicts:
            return False
            
        try:
            student = mapping.local_student
            
            # Apply resolutions
            for field, value in resolutions.items():
                if hasattr(student, field):
                    setattr(student, field, value)
                    
            # Clear conflicts
            mapping.clear_conflicts()
            mapping.needs_sync = False
            mapping.last_synced_at = datetime.utcnow()
            
            await self.db.commit()
            
            logger.info(f"Resolved conflicts for student mapping {mapping_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error resolving conflicts for mapping {mapping_id}: {e}")
            await self.db.rollback()
            return False
            
    async def get_pending_conflicts(
        self,
        integration_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all pending conflicts that require manual resolution.
        
        Args:
            integration_id: Optional filter by integration ID
            
        Returns:
            List of pending conflicts
        """
        query = select(SISStudentMapping).where(
            SISStudentMapping.sync_conflicts.isnot(None)
        )
        
        if integration_id:
            query = query.where(SISStudentMapping.integration_id == integration_id)
            
        query = query.options(
            selectinload(SISStudentMapping.local_student),
            selectinload(SISStudentMapping.integration)
        )
        
        result = await self.db.execute(query)
        mappings = result.scalars().all()
        
        conflicts = []
        for mapping in mappings:
            conflict_data = {
                'mapping_id': mapping.id,
                'integration_id': mapping.integration_id,
                'provider_id': mapping.integration.provider_id,
                'student_id': mapping.local_student_id,
                'student_name': mapping.local_student.full_name,
                'student_email': mapping.local_student.email,
                'sis_student_id': mapping.sis_student_id,
                'conflicts': mapping.sync_conflicts,
                'last_synced_at': mapping.last_synced_at
            }
            conflicts.append(conflict_data)
            
        return conflicts
        
    async def _get_provider(self, integration: SISIntegration) -> BaseSISProvider:
        """Get provider instance for integration."""
        provider_config = sis_config_manager.get_provider_config(integration.provider_id)
        if not provider_config:
            raise ValueError(f"Provider configuration not found for {integration.provider_id}")
            
        provider_class = self._provider_classes.get(integration.provider_type)
        if not provider_class:
            raise ValueError(f"Provider class not found for type {integration.provider_type}")
            
        async_oauth_service = SISOAuthService(self.db)
        return provider_class(provider_config, integration, async_oauth_service)
        
    async def _sync_students_with_provider(
        self,
        integration: SISIntegration,
        provider: BaseSISProvider,
        sync_op: SISSyncOperation,
        conflict_strategy: ConflictResolutionStrategy
    ) -> Dict[str, Any]:
        """Sync students with SIS provider."""
        async with provider:
            # Get students from SIS
            sis_students = await provider.get_students()
            
            sync_op.total_records = len(sis_students)
            await self.db.commit()
            
            students_synced = 0
            students_failed = 0
            conflicts_detected = 0
            
            # Process each student
            for sis_student in sis_students:
                try:
                    conflicts = await self._sync_single_student(
                        integration,
                        sis_student,
                        conflict_strategy
                    )
                    
                    if conflicts:
                        conflicts_detected += len(conflicts)
                        
                    students_synced += 1
                    
                except Exception as e:
                    logger.error(f"Error syncing student {sis_student.get('sis_student_id', 'unknown')}: {e}")
                    students_failed += 1
                    
                # Update progress
                sync_op.processed_records = students_synced + students_failed
                
                # Commit periodically
                if (students_synced + students_failed) % 10 == 0:
                    await self.db.commit()
                    
            return {
                'students_processed': len(sis_students),
                'students_synced': students_synced,
                'students_failed': students_failed,
                'conflicts_detected': conflicts_detected
            }
            
    async def _sync_single_student(
        self,
        integration: SISIntegration,
        sis_student: Dict[str, Any],
        conflict_strategy: ConflictResolutionStrategy
    ) -> List[SyncConflict]:
        """Sync a single student and detect conflicts."""
        sis_student_id = sis_student.get('sis_student_id')
        if not sis_student_id:
            raise ValueError("SIS student ID is required")
            
        # Find or create student mapping
        result = await self.db.execute(
            select(SISStudentMapping)
            .where(
                and_(
                    SISStudentMapping.integration_id == integration.id,
                    SISStudentMapping.sis_student_id == sis_student_id
                )
            )
            .options(selectinload(SISStudentMapping.local_student))
        )
        mapping = result.scalar_one_or_none()
        
        if not mapping:
            # Try to find existing user by email
            email = sis_student.get('email', '').strip().lower()
            local_student = None
            
            if email:
                result = await self.db.execute(
                    select(User)
                    .where(
                        and_(
                            User.email == email,
                            User.role == UserRole.STUDENT
                        )
                    )
                )
                local_student = result.scalar_one_or_none()
                
            if not local_student:
                # Create new student
                local_student = await self._create_student_from_sis(sis_student)
                
            # Create mapping
            mapping = SISStudentMapping(
                integration_id=integration.id,
                local_student_id=local_student.id,
                sis_student_id=sis_student_id,
                sis_student_number=sis_student.get('sis_student_number'),
                sis_email=sis_student.get('email'),
                sis_state_id=sis_student.get('state_id')
            )
            self.db.add(mapping)
            await self.db.commit()
            await self.db.refresh(mapping)
            mapping.local_student = local_student
            
        # Detect and handle conflicts
        conflicts = self._detect_conflicts(mapping.local_student, sis_student)
        
        if conflicts:
            # Apply conflict resolution strategy
            resolved_conflicts = await self._resolve_conflicts(
                mapping,
                conflicts,
                conflict_strategy
            )
            
            if conflict_strategy == ConflictResolutionStrategy.MANUAL:
                # Store conflicts for manual resolution
                mapping.needs_sync = True
                for conflict in conflicts:
                    mapping.add_conflict(
                        conflict.field,
                        conflict.local_value,
                        conflict.sis_value
                    )
            else:
                # Auto-resolve conflicts
                await self._apply_conflict_resolutions(
                    mapping.local_student,
                    resolved_conflicts
                )
                mapping.clear_conflicts()
                mapping.needs_sync = False
                
        else:
            # No conflicts, update normally
            await self._update_student_from_sis(mapping.local_student, sis_student)
            mapping.clear_conflicts()
            mapping.needs_sync = False
            
        # Update mapping metadata
        mapping.last_synced_at = datetime.utcnow()
        
        # Update SIS metadata fields
        mapping.sis_student_number = sis_student.get('sis_student_number')
        mapping.sis_email = sis_student.get('email')
        mapping.sis_state_id = sis_student.get('state_id')
        
        return conflicts
        
    def _detect_conflicts(
        self,
        local_student: User,
        sis_student: Dict[str, Any]
    ) -> List[SyncConflict]:
        """Detect conflicts between local and SIS student data."""
        conflicts = []
        
        # Check conflicting fields
        field_mappings = {
            'full_name': ('first_name', 'last_name'),
            'email': 'email',
        }
        
        for local_field, sis_fields in field_mappings.items():
            local_value = getattr(local_student, local_field, None)
            
            if isinstance(sis_fields, tuple):
                # Composite field (e.g., full_name from first + last)
                sis_parts = []
                for field in sis_fields:
                    value = sis_student.get(field, '').strip()
                    if value:
                        sis_parts.append(value)
                sis_value = ' '.join(sis_parts) if sis_parts else None
            else:
                sis_value = sis_student.get(sis_fields)
                
            # Check for conflicts (ignore case and whitespace for strings)
            if local_value and sis_value:
                if isinstance(local_value, str) and isinstance(sis_value, str):
                    local_normalized = local_value.strip().lower()
                    sis_normalized = sis_value.strip().lower()
                    if local_normalized != sis_normalized:
                        conflicts.append(SyncConflict(
                            field=local_field,
                            local_value=local_value,
                            sis_value=sis_value,
                            local_updated=local_student.updated_at,
                            # SIS updated time would need to come from API if available
                        ))
                elif local_value != sis_value:
                    conflicts.append(SyncConflict(
                        field=local_field,
                        local_value=local_value,
                        sis_value=sis_value,
                        local_updated=local_student.updated_at,
                    ))
                    
        return conflicts
        
    async def _resolve_conflicts(
        self,
        mapping: SISStudentMapping,
        conflicts: List[SyncConflict],
        strategy: ConflictResolutionStrategy
    ) -> Dict[str, Any]:
        """Resolve conflicts based on strategy."""
        resolutions = {}
        
        for conflict in conflicts:
            if strategy == ConflictResolutionStrategy.SIS_WINS:
                resolutions[conflict.field] = conflict.sis_value
            elif strategy == ConflictResolutionStrategy.LOCAL_WINS:
                resolutions[conflict.field] = conflict.local_value
            elif strategy == ConflictResolutionStrategy.NEWEST_WINS:
                # Use timestamps to determine winner (if available)
                if conflict.local_updated and conflict.sis_updated:
                    if conflict.sis_updated > conflict.local_updated:
                        resolutions[conflict.field] = conflict.sis_value
                    else:
                        resolutions[conflict.field] = conflict.local_value
                else:
                    # Default to SIS if no timestamps
                    resolutions[conflict.field] = conflict.sis_value
            # MANUAL strategy doesn't auto-resolve
            
        return resolutions
        
    async def _apply_conflict_resolutions(
        self,
        student: User,
        resolutions: Dict[str, Any]
    ) -> None:
        """Apply conflict resolutions to student."""
        for field, value in resolutions.items():
            if hasattr(student, field):
                setattr(student, field, value)
                
    async def _create_student_from_sis(self, sis_student: Dict[str, Any]) -> User:
        """Create a new student from SIS data."""
        # Generate username from email or name
        email = sis_student.get('email', '').strip()
        first_name = sis_student.get('first_name', '').strip()
        last_name = sis_student.get('last_name', '').strip()
        
        if email:
            username = email.split('@')[0]
        else:
            username = f"{first_name.lower()}.{last_name.lower()}" if first_name and last_name else f"student_{sis_student.get('sis_student_id', 'unknown')}"
            
        # Create student user
        student = User(
            email=email or f"{username}@school.edu",
            username=username,
            full_name=f"{first_name} {last_name}".strip() or "Unknown Student",
            hashed_password="",  # Will need to be set later
            role=UserRole.STUDENT,
            is_active=sis_student.get('active', True),
            is_verified=False
        )
        
        self.db.add(student)
        await self.db.commit()
        await self.db.refresh(student)
        
        return student
        
    async def _update_student_from_sis(
        self,
        student: User,
        sis_student: Dict[str, Any]
    ) -> None:
        """Update student with SIS data (no conflicts)."""
        first_name = sis_student.get('first_name', '').strip()
        last_name = sis_student.get('last_name', '').strip()
        
        if first_name and last_name:
            student.full_name = f"{first_name} {last_name}"
            
        if sis_student.get('email'):
            student.email = sis_student['email'].strip()
            
        if 'active' in sis_student:
            student.is_active = sis_student['active']