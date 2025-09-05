"""
Student enrollment and withdrawal handling for SIS integrations.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update, insert
from sqlalchemy.orm import selectinload

from app.models.sis_integration import SISIntegration, SISStudentMapping, SISSyncOperation
from app.models.user import User, UserRole
from app.models.class_session import ClassSession, StudentEnrollment
from app.core.sis_config import BaseSISProvider, sis_config_manager
from app.integrations.sis.providers.powerschool import PowerSchoolProvider
from app.integrations.sis.providers.infinite_campus import InfiniteCampusProvider
from app.integrations.sis.providers.skyward import SkywardProvider
from app.integrations.sis.oauth_service import SISOAuthService


logger = logging.getLogger(__name__)


class EnrollmentAction(str, Enum):
    """Types of enrollment actions."""
    ENROLL = "enroll"
    WITHDRAW = "withdraw"
    TRANSFER = "transfer"
    UPDATE = "update"


class EnrollmentStatus(str, Enum):
    """Enrollment status values."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    WITHDRAWN = "withdrawn"
    TRANSFERRED = "transferred"
    PENDING = "pending"


class EnrollmentEvent:
    """Represents an enrollment event from SIS."""
    
    def __init__(
        self,
        action: EnrollmentAction,
        student_id: str,
        enrollment_data: Dict[str, Any],
        effective_date: Optional[datetime] = None
    ):
        self.action = action
        self.student_id = student_id
        self.enrollment_data = enrollment_data
        self.effective_date = effective_date or datetime.utcnow()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for logging/storage."""
        return {
            'action': self.action,
            'student_id': self.student_id,
            'enrollment_data': self.enrollment_data,
            'effective_date': self.effective_date.isoformat()
        }


class StudentEnrollmentHandler:
    """Service for handling student enrollment and withdrawal events."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._provider_classes = {
            'powerschool': PowerSchoolProvider,
            'infinite_campus': InfiniteCampusProvider,
            'skyward': SkywardProvider
        }
        
    async def process_enrollment_updates(
        self,
        integration_id: int,
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """
        Process enrollment updates for a specific integration.
        
        Args:
            integration_id: ID of the SIS integration
            batch_size: Number of enrollments to process at once
            
        Returns:
            Processing results summary
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
            
        logger.info(f"Processing enrollment updates for integration {integration.provider_id}")
        
        # Create sync operation record
        sync_op = SISSyncOperation(
            integration_id=integration.id,
            operation_type='enrollment_sync',
            status='running',
            started_at=datetime.utcnow()
        )
        self.db.add(sync_op)
        await self.db.commit()
        await self.db.refresh(sync_op)
        
        try:
            # Get provider and process enrollments
            provider = await self._get_provider(integration)
            
            result = await self._process_enrollments_with_provider(
                integration,
                provider,
                sync_op,
                batch_size
            )
            
            # Update sync operation as successful
            sync_op.status = 'completed'
            sync_op.completed_at = datetime.utcnow()
            sync_op.successful_records = result.get('enrollments_processed', 0)
            sync_op.processed_records = result.get('total_enrollments', 0)
            
            # Update integration sync success
            integration.update_sync_success(
                enrollments_count=result.get('enrollments_processed', 0)
            )
            
            await self.db.commit()
            
            logger.info(
                f"Successfully processed enrollments for integration {integration.provider_id}: "
                f"{result.get('enrollments_processed', 0)} processed"
            )
            
            return {
                'integration_id': integration.id,
                'provider_id': integration.provider_id,
                'success': True,
                'sync_operation_id': sync_op.id,
                **result
            }
            
        except Exception as e:
            # Update sync operation as failed
            sync_op.status = 'failed'
            sync_op.completed_at = datetime.utcnow()
            sync_op.error_message = str(e)
            
            # Update integration sync failure
            integration.update_sync_failure()
            
            await self.db.commit()
            
            logger.error(f"Failed to process enrollments for integration {integration.provider_id}: {e}")
            raise e
            
    async def handle_student_enrollment(
        self,
        integration_id: int,
        enrollment_event: EnrollmentEvent
    ) -> bool:
        """
        Handle a single student enrollment event.
        
        Args:
            integration_id: ID of the SIS integration
            enrollment_event: Enrollment event to process
            
        Returns:
            True if successful
        """
        try:
            # Find student mapping
            result = await self.db.execute(
                select(SISStudentMapping)
                .where(
                    and_(
                        SISStudentMapping.integration_id == integration_id,
                        SISStudentMapping.sis_student_id == enrollment_event.student_id
                    )
                )
                .options(selectinload(SISStudentMapping.local_student))
            )
            mapping = result.scalar_one_or_none()
            
            if not mapping:
                logger.warning(
                    f"Student mapping not found for SIS ID {enrollment_event.student_id} "
                    f"in integration {integration_id}"
                )
                return False
                
            student = mapping.local_student
            
            # Process based on action type
            if enrollment_event.action == EnrollmentAction.ENROLL:
                success = await self._handle_enrollment(
                    student,
                    enrollment_event.enrollment_data,
                    enrollment_event.effective_date
                )
            elif enrollment_event.action == EnrollmentAction.WITHDRAW:
                success = await self._handle_withdrawal(
                    student,
                    enrollment_event.enrollment_data,
                    enrollment_event.effective_date
                )
            elif enrollment_event.action == EnrollmentAction.TRANSFER:
                success = await self._handle_transfer(
                    student,
                    enrollment_event.enrollment_data,
                    enrollment_event.effective_date
                )
            elif enrollment_event.action == EnrollmentAction.UPDATE:
                success = await self._handle_enrollment_update(
                    student,
                    enrollment_event.enrollment_data,
                    enrollment_event.effective_date
                )
            else:
                logger.error(f"Unknown enrollment action: {enrollment_event.action}")
                return False
                
            if success:
                logger.info(
                    f"Successfully handled {enrollment_event.action} for student "
                    f"{student.full_name} (SIS ID: {enrollment_event.student_id})"
                )
                
            return success
            
        except Exception as e:
            logger.error(
                f"Error handling enrollment event for student {enrollment_event.student_id}: {e}"
            )
            return False
            
    async def sync_class_enrollments(
        self,
        integration_id: int,
        class_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Sync class enrollments with SIS.
        
        Args:
            integration_id: ID of the SIS integration
            class_id: Optional specific class to sync
            
        Returns:
            Sync results
        """
        # Get integration
        result = await self.db.execute(
            select(SISIntegration)
            .where(SISIntegration.id == integration_id)
        )
        integration = result.scalar_one_or_none()
        
        if not integration:
            raise ValueError(f"Integration {integration_id} not found")
            
        logger.info(f"Syncing class enrollments for integration {integration.provider_id}")
        
        try:
            provider = await self._get_provider(integration)
            
            # Get enrollments from SIS
            async with provider:
                if class_id:
                    # Sync specific class
                    sis_enrollments = await provider.get_enrollments(class_id=class_id)
                else:
                    # Sync all enrollments
                    sis_enrollments = await provider.get_enrollments()
                    
            # Process enrollments
            results = await self._sync_sis_enrollments(
                integration_id,
                sis_enrollments
            )
            
            logger.info(
                f"Synced class enrollments for integration {integration.provider_id}: "
                f"{results.get('enrollments_synced', 0)} enrollments synced"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Error syncing class enrollments: {e}")
            raise e
            
    async def handle_bulk_withdrawals(
        self,
        integration_id: int,
        withdrawal_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle bulk student withdrawals.
        
        Args:
            integration_id: ID of the SIS integration
            withdrawal_list: List of withdrawal data
            
        Returns:
            Processing results
        """
        logger.info(f"Processing bulk withdrawals: {len(withdrawal_list)} students")
        
        results = {
            'total_withdrawals': len(withdrawal_list),
            'successful_withdrawals': 0,
            'failed_withdrawals': 0,
            'errors': []
        }
        
        for withdrawal in withdrawal_list:
            try:
                event = EnrollmentEvent(
                    action=EnrollmentAction.WITHDRAW,
                    student_id=withdrawal.get('student_id'),
                    enrollment_data=withdrawal,
                    effective_date=datetime.fromisoformat(withdrawal.get('effective_date', datetime.utcnow().isoformat()))
                )
                
                success = await self.handle_student_enrollment(integration_id, event)
                
                if success:
                    results['successful_withdrawals'] += 1
                else:
                    results['failed_withdrawals'] += 1
                    
            except Exception as e:
                results['failed_withdrawals'] += 1
                results['errors'].append({
                    'student_id': withdrawal.get('student_id'),
                    'error': str(e)
                })
                
        logger.info(
            f"Bulk withdrawals completed: {results['successful_withdrawals']} successful, "
            f"{results['failed_withdrawals']} failed"
        )
        
        return results
        
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
        
    async def _process_enrollments_with_provider(
        self,
        integration: SISIntegration,
        provider: BaseSISProvider,
        sync_op: SISSyncOperation,
        batch_size: int
    ) -> Dict[str, Any]:
        """Process enrollments with SIS provider."""
        async with provider:
            # Get enrollments from SIS
            sis_enrollments = await provider.get_enrollments()
            
            sync_op.total_records = len(sis_enrollments)
            await self.db.commit()
            
            # Process enrollments in batches
            results = await self._sync_sis_enrollments(
                integration.id,
                sis_enrollments,
                batch_size
            )
            
            sync_op.processed_records = results.get('total_enrollments', 0)
            await self.db.commit()
            
            return results
            
    async def _sync_sis_enrollments(
        self,
        integration_id: int,
        sis_enrollments: List[Dict[str, Any]],
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """Sync SIS enrollments with local class enrollments."""
        enrollments_processed = 0
        enrollments_created = 0
        enrollments_updated = 0
        enrollments_failed = 0
        
        # Process in batches
        for i in range(0, len(sis_enrollments), batch_size):
            batch = sis_enrollments[i:i + batch_size]
            
            for sis_enrollment in batch:
                try:
                    success = await self._sync_single_enrollment(
                        integration_id,
                        sis_enrollment
                    )
                    
                    if success == 'created':
                        enrollments_created += 1
                    elif success == 'updated':
                        enrollments_updated += 1
                        
                    enrollments_processed += 1
                    
                except Exception as e:
                    logger.error(
                        f"Error syncing enrollment for student "
                        f"{sis_enrollment.get('student_id', 'unknown')}: {e}"
                    )
                    enrollments_failed += 1
                    
            # Commit batch
            await self.db.commit()
            
        return {
            'total_enrollments': len(sis_enrollments),
            'enrollments_processed': enrollments_processed,
            'enrollments_created': enrollments_created,
            'enrollments_updated': enrollments_updated,
            'enrollments_failed': enrollments_failed
        }
        
    async def _sync_single_enrollment(
        self,
        integration_id: int,
        sis_enrollment: Dict[str, Any]
    ) -> str:
        """Sync a single enrollment record."""
        student_id = sis_enrollment.get('student_id')
        section_id = sis_enrollment.get('section_id')
        
        if not student_id or not section_id:
            raise ValueError("Student ID and section ID are required")
            
        # Find student mapping
        result = await self.db.execute(
            select(SISStudentMapping)
            .where(
                and_(
                    SISStudentMapping.integration_id == integration_id,
                    SISStudentMapping.sis_student_id == student_id
                )
            )
            .options(selectinload(SISStudentMapping.local_student))
        )
        mapping = result.scalar_one_or_none()
        
        if not mapping:
            logger.warning(f"Student mapping not found for SIS ID {student_id}")
            return 'failed'
            
        # Find or create class session based on SIS section
        class_session = await self._find_or_create_class_session(
            sis_enrollment,
            integration_id
        )
        
        if not class_session:
            logger.warning(f"Could not find or create class session for section {section_id}")
            return 'failed'
            
        # Check if enrollment already exists
        result = await self.db.execute(
            select(StudentEnrollment)
            .where(
                and_(
                    StudentEnrollment.student_id == mapping.local_student_id,
                    StudentEnrollment.class_session_id == class_session.id
                )
            )
        )
        enrollment = result.scalar_one_or_none()
        
        if enrollment:
            # Update existing enrollment
            enrollment.is_active = sis_enrollment.get('active', True)
            if sis_enrollment.get('start_date'):
                enrollment.enrolled_at = datetime.fromisoformat(sis_enrollment['start_date'])
            return 'updated'
        else:
            # Create new enrollment
            enrollment = StudentEnrollment(
                student_id=mapping.local_student_id,
                class_session_id=class_session.id,
                is_active=sis_enrollment.get('active', True),
                enrolled_at=datetime.fromisoformat(sis_enrollment.get('start_date', datetime.utcnow().isoformat()))
            )
            self.db.add(enrollment)
            return 'created'
            
    async def _find_or_create_class_session(
        self,
        sis_enrollment: Dict[str, Any],
        integration_id: int
    ) -> Optional[ClassSession]:
        """Find or create a class session based on SIS enrollment data."""
        section_id = sis_enrollment.get('section_id')
        course_name = sis_enrollment.get('course_name', 'Unknown Course')
        teacher_name = sis_enrollment.get('teacher_name', 'Unknown Teacher')
        
        # Try to find existing class session by external ID
        result = await self.db.execute(
            select(ClassSession)
            .where(ClassSession.external_id == section_id)
        )
        class_session = result.scalar_one_or_none()
        
        if class_session:
            return class_session
            
        # Try to find teacher
        teacher = await self._find_or_create_teacher(
            sis_enrollment.get('teacher_id'),
            teacher_name,
            integration_id
        )
        
        if not teacher:
            logger.warning(f"Could not find or create teacher for section {section_id}")
            return None
            
        # Create new class session
        class_session = ClassSession(
            name=course_name,
            teacher_id=teacher.id,
            external_id=section_id,
            room=sis_enrollment.get('room', ''),
            schedule=sis_enrollment.get('period', ''),
            is_active=sis_enrollment.get('active', True)
        )
        self.db.add(class_session)
        await self.db.commit()
        await self.db.refresh(class_session)
        
        return class_session
        
    async def _find_or_create_teacher(
        self,
        sis_teacher_id: Optional[str],
        teacher_name: str,
        integration_id: int
    ) -> Optional[User]:
        """Find or create a teacher based on SIS data."""
        teacher = None
        
        # Try to find existing teacher by SIS ID mapping
        if sis_teacher_id:
            # This would require a teacher mapping table similar to student mappings
            # For now, try to find by username or email pattern
            username = f"teacher_{sis_teacher_id}"
            result = await self.db.execute(
                select(User)
                .where(
                    and_(
                        User.username == username,
                        User.role == UserRole.TEACHER
                    )
                )
            )
            teacher = result.scalar_one_or_none()
            
        if not teacher and teacher_name and teacher_name != 'Unknown Teacher':
            # Try to find by name (fuzzy match)
            result = await self.db.execute(
                select(User)
                .where(
                    and_(
                        User.full_name.ilike(f"%{teacher_name}%"),
                        User.role == UserRole.TEACHER
                    )
                )
            )
            teacher = result.scalar_one_or_none()
            
        if not teacher:
            # Create placeholder teacher
            username = f"teacher_{sis_teacher_id}" if sis_teacher_id else f"teacher_{teacher_name.lower().replace(' ', '_')}"
            email = f"{username}@school.edu"
            
            teacher = User(
                email=email,
                username=username,
                full_name=teacher_name,
                hashed_password="",  # Will need to be set later
                role=UserRole.TEACHER,
                is_active=True,
                is_verified=False
            )
            self.db.add(teacher)
            await self.db.commit()
            await self.db.refresh(teacher)
            
        return teacher
        
    async def _handle_enrollment(
        self,
        student: User,
        enrollment_data: Dict[str, Any],
        effective_date: datetime
    ) -> bool:
        """Handle student enrollment."""
        try:
            # Activate student if not already active
            if not student.is_active:
                student.is_active = True
                logger.info(f"Activated student {student.full_name}")
                
            # Process any class enrollments in the enrollment data
            if 'classes' in enrollment_data:
                for class_info in enrollment_data['classes']:
                    # This would handle enrolling student in specific classes
                    pass
                    
            return True
            
        except Exception as e:
            logger.error(f"Error handling enrollment for student {student.full_name}: {e}")
            return False
            
    async def _handle_withdrawal(
        self,
        student: User,
        withdrawal_data: Dict[str, Any],
        effective_date: datetime
    ) -> bool:
        """Handle student withdrawal."""
        try:
            # Deactivate student
            student.is_active = False
            
            # Deactivate all current enrollments
            await self.db.execute(
                update(StudentEnrollment)
                .where(StudentEnrollment.student_id == student.id)
                .values(is_active=False, withdrawn_at=effective_date)
            )
            
            logger.info(f"Withdrew student {student.full_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling withdrawal for student {student.full_name}: {e}")
            return False
            
    async def _handle_transfer(
        self,
        student: User,
        transfer_data: Dict[str, Any],
        effective_date: datetime
    ) -> bool:
        """Handle student transfer."""
        try:
            # Handle transfer logic (could involve school changes, etc.)
            # For now, keep student active but update relevant fields
            
            logger.info(f"Processed transfer for student {student.full_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling transfer for student {student.full_name}: {e}")
            return False
            
    async def _handle_enrollment_update(
        self,
        student: User,
        update_data: Dict[str, Any],
        effective_date: datetime
    ) -> bool:
        """Handle enrollment updates."""
        try:
            # Update student information based on enrollment changes
            if 'grade_level' in update_data:
                # Update grade level if we had that field
                pass
                
            logger.info(f"Updated enrollment for student {student.full_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling enrollment update for student {student.full_name}: {e}")
            return False