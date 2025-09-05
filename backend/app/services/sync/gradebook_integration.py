"""
Grade Book Integration Service

Handles integration between attendance system and SIS grade books,
calculating and syncing participation grades based on attendance patterns.
"""

import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc, text
from sqlalchemy.orm import selectinload, joinedload

from app.models.sync_metadata import (
    SyncOperation, SyncRecordChange, DataType, SyncDirection, 
    SyncStatus, SyncType
)
from app.models.sis_integration import SISIntegration, SISStudentMapping
from app.models.user import User
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.models.class_session import Class, ClassSession
from app.services.sis_service import SISService

logger = logging.getLogger(__name__)


class GradeCalculationMethod:
    """Methods for calculating participation grades from attendance."""
    
    PERCENTAGE_BASED = "percentage_based"  # Based on attendance percentage
    POINTS_BASED = "points_based"  # Points per attendance
    WEIGHTED = "weighted"  # Weighted by session importance
    CUSTOM = "custom"  # Custom calculation logic


class ParticipationGradeConfig:
    """Configuration for participation grade calculation."""
    
    def __init__(
        self,
        calculation_method: str = GradeCalculationMethod.PERCENTAGE_BASED,
        max_grade: float = 100.0,
        min_grade: float = 0.0,
        attendance_weight: float = 0.8,  # Weight for present attendance
        late_weight: float = 0.5,       # Weight for late attendance
        absent_weight: float = 0.0,     # Weight for absent (usually 0)
        excused_weight: float = 1.0,    # Weight for excused absence
        points_per_session: float = 1.0, # Points awarded per session
        minimum_sessions: int = 1,       # Minimum sessions for grade calculation
        rounding_decimals: int = 1       # Decimal places for rounding
    ):
        self.calculation_method = calculation_method
        self.max_grade = max_grade
        self.min_grade = min_grade
        self.attendance_weight = attendance_weight
        self.late_weight = late_weight
        self.absent_weight = absent_weight
        self.excused_weight = excused_weight
        self.points_per_session = points_per_session
        self.minimum_sessions = minimum_sessions
        self.rounding_decimals = rounding_decimals


class GradebookIntegrationService:
    """
    Service for integrating attendance data with SIS grade books.
    
    Calculates participation grades based on attendance patterns and
    syncs them with external SIS grade book systems.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.sis_service = SISService(db)
        
        # Default grade calculation configuration
        self.default_config = ParticipationGradeConfig()
    
    async def calculate_participation_grades(
        self,
        integration_id: int,
        class_id: Optional[int] = None,
        student_ids: Optional[List[int]] = None,
        date_range: Optional[Tuple[date, date]] = None,
        config: Optional[ParticipationGradeConfig] = None
    ) -> Dict[str, Any]:
        """
        Calculate participation grades based on attendance data.
        
        Args:
            integration_id: SIS integration ID
            class_id: Specific class to calculate for (None for all)
            student_ids: Specific students to calculate for (None for all)
            date_range: Date range for calculation (None for all time)
            config: Grade calculation configuration
            
        Returns:
            Dictionary with calculation results and statistics
        """
        logger.info(f"Calculating participation grades for integration {integration_id}")
        
        if not config:
            config = self.default_config
        
        try:
            # Get classes to process
            classes = await self._get_classes_for_calculation(
                integration_id, class_id
            )
            
            results = {
                'classes_processed': 0,
                'students_processed': 0,
                'grades_calculated': 0,
                'errors': 0,
                'grade_details': []
            }
            
            for class_obj in classes:
                try:
                    class_results = await self._calculate_class_participation_grades(
                        integration_id, class_obj, student_ids, date_range, config
                    )
                    
                    results['classes_processed'] += 1
                    results['students_processed'] += class_results['students_processed']
                    results['grades_calculated'] += class_results['grades_calculated']
                    results['errors'] += class_results['errors']
                    results['grade_details'].extend(class_results['grade_details'])
                
                except Exception as e:
                    logger.error(f"Error calculating grades for class {class_obj.id}: {e}")
                    results['errors'] += 1
            
            logger.info(f"Grade calculation completed: {results}")
            return results
        
        except Exception as e:
            logger.error(f"Error calculating participation grades: {e}")
            raise
    
    async def sync_participation_grades(
        self,
        integration_id: int,
        class_id: Optional[int] = None,
        student_ids: Optional[List[int]] = None,
        recalculate: bool = True,
        config: Optional[ParticipationGradeConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync participation grades to SIS grade book.
        
        Args:
            integration_id: SIS integration ID
            class_id: Specific class to sync (None for all)
            student_ids: Specific students to sync (None for all)
            recalculate: Whether to recalculate grades before syncing
            config: Grade calculation configuration
            
        Returns:
            Sync operation results
        """
        logger.info(f"Syncing participation grades for integration {integration_id}")
        
        # Create sync operation
        sync_operation = await self._create_sync_operation(
            integration_id, DataType.PARTICIPATION
        )
        
        try:
            results = {'successful': 0, 'failed': 0, 'skipped': 0}
            
            # Calculate grades if requested
            if recalculate:
                calc_results = await self.calculate_participation_grades(
                    integration_id, class_id, student_ids, None, config
                )
                logger.info(f"Calculated {calc_results['grades_calculated']} grades")
            
            # Get integration
            integration = await self._get_integration(integration_id)
            
            # Get classes to sync
            classes = await self._get_classes_for_calculation(
                integration_id, class_id
            )
            
            # Sync each class
            for class_obj in classes:
                try:
                    class_results = await self._sync_class_participation_grades(
                        sync_operation, integration, class_obj, student_ids, config
                    )
                    
                    results['successful'] += class_results['successful']
                    results['failed'] += class_results['failed']
                    results['skipped'] += class_results['skipped']
                
                except Exception as e:
                    logger.error(f"Error syncing grades for class {class_obj.id}: {e}")
                    results['failed'] += 1
            
            # Update sync operation
            total_processed = sum(results.values())
            sync_operation.update_progress(
                processed=total_processed,
                successful=results['successful'],
                failed=results['failed'],
                skipped=results['skipped']
            )
            
            sync_operation.mark_completed(success=results['failed'] == 0)
            await self.db.commit()
            
            logger.info(f"Completed participation grade sync: {results}")
            return results
        
        except Exception as e:
            logger.error(f"Participation grade sync failed: {e}")
            sync_operation.status = SyncStatus.FAILED
            sync_operation.error_message = str(e)
            sync_operation.completed_at = datetime.utcnow()
            await self.db.commit()
            raise
    
    async def _calculate_class_participation_grades(
        self,
        integration_id: int,
        class_obj: Class,
        student_ids: Optional[List[int]] = None,
        date_range: Optional[Tuple[date, date]] = None,
        config: ParticipationGradeConfig = None
    ) -> Dict[str, Any]:
        """Calculate participation grades for a specific class."""
        if not config:
            config = self.default_config
        
        results = {
            'students_processed': 0,
            'grades_calculated': 0,
            'errors': 0,
            'grade_details': []
        }
        
        # Get students in this class
        students = await self._get_students_for_class(
            integration_id, class_obj.id, student_ids
        )
        
        # Get class sessions in date range
        sessions = await self._get_class_sessions(
            class_obj.id, date_range
        )
        
        if len(sessions) < config.minimum_sessions:
            logger.warning(f"Class {class_obj.id} has insufficient sessions ({len(sessions)}) for grade calculation")
            return results
        
        # Calculate grade for each student
        for student in students:
            try:
                grade_info = await self._calculate_student_participation_grade(
                    student, class_obj, sessions, config
                )
                
                if grade_info:
                    results['grades_calculated'] += 1
                    results['grade_details'].append(grade_info)
                
                results['students_processed'] += 1
            
            except Exception as e:
                logger.error(f"Error calculating grade for student {student.id}: {e}")
                results['errors'] += 1
        
        return results
    
    async def _calculate_student_participation_grade(
        self,
        student: User,
        class_obj: Class,
        sessions: List[ClassSession],
        config: ParticipationGradeConfig
    ) -> Optional[Dict[str, Any]]:
        """Calculate participation grade for a specific student."""
        
        # Get attendance records for this student and class
        session_ids = [session.id for session in sessions]
        
        result = await self.db.execute(
            select(AttendanceRecord).where(
                and_(
                    AttendanceRecord.student_id == student.id,
                    AttendanceRecord.class_session_id.in_(session_ids)
                )
            )
        )
        attendance_records = list(result.scalars().all())
        
        # Create attendance map
        attendance_map = {record.class_session_id: record for record in attendance_records}
        
        # Calculate grade based on method
        if config.calculation_method == GradeCalculationMethod.PERCENTAGE_BASED:
            grade = await self._calculate_percentage_based_grade(
                sessions, attendance_map, config
            )
        elif config.calculation_method == GradeCalculationMethod.POINTS_BASED:
            grade = await self._calculate_points_based_grade(
                sessions, attendance_map, config
            )
        elif config.calculation_method == GradeCalculationMethod.WEIGHTED:
            grade = await self._calculate_weighted_grade(
                sessions, attendance_map, config
            )
        else:
            logger.warning(f"Unsupported calculation method: {config.calculation_method}")
            return None
        
        # Apply min/max constraints and rounding
        grade = max(config.min_grade, min(config.max_grade, grade))
        grade = round(grade, config.rounding_decimals)
        
        # Prepare grade details
        attendance_summary = self._summarize_attendance(sessions, attendance_map)
        
        return {
            'student_id': student.id,
            'class_id': class_obj.id,
            'grade': grade,
            'total_sessions': len(sessions),
            'attendance_summary': attendance_summary,
            'calculation_method': config.calculation_method,
            'calculated_at': datetime.utcnow()
        }
    
    async def _calculate_percentage_based_grade(
        self,
        sessions: List[ClassSession],
        attendance_map: Dict[int, AttendanceRecord],
        config: ParticipationGradeConfig
    ) -> float:
        """Calculate grade based on attendance percentage."""
        total_weighted_score = 0.0
        total_possible_score = 0.0
        
        for session in sessions:
            attendance = attendance_map.get(session.id)
            
            if attendance:
                if attendance.status == AttendanceStatus.PRESENT:
                    score = config.attendance_weight
                elif attendance.status == AttendanceStatus.LATE:
                    score = config.late_weight
                elif attendance.status == AttendanceStatus.EXCUSED:
                    score = config.excused_weight
                else:  # ABSENT
                    score = config.absent_weight
            else:
                # No record means absent
                score = config.absent_weight
            
            total_weighted_score += score
            total_possible_score += config.attendance_weight  # Max possible score per session
        
        if total_possible_score == 0:
            return config.min_grade
        
        percentage = (total_weighted_score / total_possible_score) * 100
        return percentage * (config.max_grade / 100)
    
    async def _calculate_points_based_grade(
        self,
        sessions: List[ClassSession],
        attendance_map: Dict[int, AttendanceRecord],
        config: ParticipationGradeConfig
    ) -> float:
        """Calculate grade based on points per session."""
        total_points = 0.0
        
        for session in sessions:
            attendance = attendance_map.get(session.id)
            
            if attendance:
                if attendance.status == AttendanceStatus.PRESENT:
                    points = config.points_per_session * config.attendance_weight
                elif attendance.status == AttendanceStatus.LATE:
                    points = config.points_per_session * config.late_weight
                elif attendance.status == AttendanceStatus.EXCUSED:
                    points = config.points_per_session * config.excused_weight
                else:  # ABSENT
                    points = config.points_per_session * config.absent_weight
            else:
                points = config.points_per_session * config.absent_weight
            
            total_points += points
        
        # Convert to grade scale
        max_possible_points = len(sessions) * config.points_per_session * config.attendance_weight
        
        if max_possible_points == 0:
            return config.min_grade
        
        percentage = (total_points / max_possible_points) * 100
        return percentage * (config.max_grade / 100)
    
    async def _calculate_weighted_grade(
        self,
        sessions: List[ClassSession],
        attendance_map: Dict[int, AttendanceRecord],
        config: ParticipationGradeConfig
    ) -> float:
        """Calculate grade with weighted sessions (could be based on session importance)."""
        # For now, this is the same as percentage-based
        # In a more advanced implementation, sessions could have different weights
        return await self._calculate_percentage_based_grade(sessions, attendance_map, config)
    
    def _summarize_attendance(
        self,
        sessions: List[ClassSession],
        attendance_map: Dict[int, AttendanceRecord]
    ) -> Dict[str, int]:
        """Summarize attendance statistics."""
        summary = {
            'total_sessions': len(sessions),
            'present': 0,
            'late': 0,
            'absent': 0,
            'excused': 0
        }
        
        for session in sessions:
            attendance = attendance_map.get(session.id)
            
            if attendance:
                if attendance.status == AttendanceStatus.PRESENT:
                    summary['present'] += 1
                elif attendance.status == AttendanceStatus.LATE:
                    summary['late'] += 1
                elif attendance.status == AttendanceStatus.EXCUSED:
                    summary['excused'] += 1
                else:
                    summary['absent'] += 1
            else:
                summary['absent'] += 1
        
        return summary
    
    async def _sync_class_participation_grades(
        self,
        sync_operation: SyncOperation,
        integration: SISIntegration,
        class_obj: Class,
        student_ids: Optional[List[int]] = None,
        config: Optional[ParticipationGradeConfig] = None
    ) -> Dict[str, Any]:
        """Sync participation grades for a specific class to SIS."""
        results = {'successful': 0, 'failed': 0, 'skipped': 0}
        
        try:
            # Get SIS provider instance
            sis_provider = await self.sis_service._get_provider_instance(integration)
            
            # Calculate current grades
            grade_results = await self._calculate_class_participation_grades(
                integration.id, class_obj, student_ids, None, config
            )
            
            async with sis_provider:
                for grade_detail in grade_results['grade_details']:
                    try:
                        # Get student SIS mapping
                        result = await self.db.execute(
                            select(SISStudentMapping).where(
                                and_(
                                    SISStudentMapping.integration_id == integration.id,
                                    SISStudentMapping.local_student_id == grade_detail['student_id']
                                )
                            )
                        )
                        mapping = result.scalar_one_or_none()
                        
                        if not mapping:
                            logger.warning(f"No SIS mapping for student {grade_detail['student_id']}")
                            results['skipped'] += 1
                            continue
                        
                        # Prepare grade data for SIS
                        grade_data = {
                            'student_id': mapping.sis_student_id,
                            'class_id': class_obj.sis_class_id if hasattr(class_obj, 'sis_class_id') else str(class_obj.id),
                            'assignment_name': 'Participation',
                            'grade': grade_detail['grade'],
                            'max_points': config.max_grade if config else 100,
                            'assignment_type': 'participation',
                            'calculated_at': grade_detail['calculated_at'].isoformat()
                        }
                        
                        # Check if SIS provider supports grade submission
                        if hasattr(sis_provider, 'submit_grade'):
                            success = await sis_provider.submit_grade(grade_data)
                            
                            if success:
                                # Create record change
                                await self._create_record_change(
                                    sync_operation, 'grade', 
                                    str(grade_detail['student_id']),
                                    mapping.sis_student_id,
                                    'create', True, None, grade_data
                                )
                                results['successful'] += 1
                            else:
                                results['failed'] += 1
                        else:
                            logger.warning(f"SIS provider {integration.provider_type} does not support grade submission")
                            results['skipped'] += 1
                    
                    except Exception as e:
                        logger.error(f"Error syncing grade for student {grade_detail['student_id']}: {e}")
                        results['failed'] += 1
            
        except Exception as e:
            logger.error(f"Error syncing participation grades for class {class_obj.id}: {e}")
            raise
        
        return results
    
    # Helper methods
    
    async def _get_classes_for_calculation(
        self,
        integration_id: int,
        class_id: Optional[int] = None
    ) -> List[Class]:
        """Get classes for grade calculation."""
        query = select(Class)
        
        if class_id:
            query = query.where(Class.id == class_id)
        
        # Add any integration-specific filtering if needed
        # For now, get all classes
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def _get_students_for_class(
        self,
        integration_id: int,
        class_id: int,
        student_ids: Optional[List[int]] = None
    ) -> List[User]:
        """Get students enrolled in a specific class."""
        # This would need to be implemented based on your enrollment model
        # For now, get students through SIS mappings
        
        mappings_query = select(SISStudentMapping.local_student_id).where(
            SISStudentMapping.integration_id == integration_id
        )
        
        if student_ids:
            mappings_query = mappings_query.where(
                SISStudentMapping.local_student_id.in_(student_ids)
            )
        
        result = await self.db.execute(mappings_query)
        local_student_ids = [row[0] for row in result.fetchall()]
        
        if not local_student_ids:
            return []
        
        students_query = select(User).where(User.id.in_(local_student_ids))
        result = await self.db.execute(students_query)
        return list(result.scalars().all())
    
    async def _get_class_sessions(
        self,
        class_id: int,
        date_range: Optional[Tuple[date, date]] = None
    ) -> List[ClassSession]:
        """Get class sessions for grade calculation."""
        query = select(ClassSession).where(ClassSession.class_id == class_id)
        
        if date_range:
            start_date, end_date = date_range
            query = query.where(
                and_(
                    func.date(ClassSession.start_time) >= start_date,
                    func.date(ClassSession.start_time) <= end_date
                )
            )
        
        query = query.order_by(ClassSession.start_time)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def _create_sync_operation(
        self,
        integration_id: int,
        data_type: DataType
    ) -> SyncOperation:
        """Create a new sync operation record."""
        operation = SyncOperation(
            integration_id=integration_id,
            operation_id=str(uuid.uuid4()),
            data_type=data_type,
            sync_direction=SyncDirection.TO_SIS,
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
        record_change = SyncRecordChange(
            sync_operation_id=sync_operation.id,
            record_type=record_type,
            local_record_id=local_record_id,
            external_record_id=external_record_id,
            change_type=change_type,
            before_data=before_data,
            after_data=after_data,
            was_successful=was_successful,
            error_message=error_message
        )
        
        self.db.add(record_change)
        return record_change