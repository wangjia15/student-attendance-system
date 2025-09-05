"""
Data Synchronization Engine

Comprehensive sync services for bidirectional data synchronization 
between local attendance system and external SIS systems.

Components:
- Bidirectional sync for student demographics and enrollment
- Grade book integration for participation grades
- Configurable sync schedules (real-time, hourly, daily)
- Data validation and integrity checks
- Conflict resolution with administrative override
- Historical data preservation
"""

from .sync_manager import SyncManager, SyncOperation, SyncOperationType, ConflictType, SyncResult
from .bidirectional_sync import BidirectionalSyncService
from .gradebook_integration import (
    GradebookIntegrationService,
    GradeCalculationMethod,
    ParticipationGradeConfig
)
from .schedule_manager import (
    SyncScheduleManager,
    ScheduleFrequency
)
from .data_validator import (
    DataValidator,
    ValidationError,
    ValidationResult,
    create_default_validation_rules
)

__all__ = [
    # Legacy sync manager
    'SyncManager',
    'SyncOperation', 
    'SyncOperationType',
    'ConflictType',
    'SyncResult',
    
    # New sync services
    'BidirectionalSyncService',
    'GradebookIntegrationService', 
    'GradeCalculationMethod',
    'ParticipationGradeConfig',
    'SyncScheduleManager',
    'ScheduleFrequency',
    'DataValidator',
    'ValidationError',
    'ValidationResult',
    'create_default_validation_rules'
]