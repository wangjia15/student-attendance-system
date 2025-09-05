"""
Conflict resolution utilities for sync operations.

Handles data conflicts that arise during bidirectional synchronization
between the local system and external SIS systems.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.sync_metadata import SyncConflict, DataType
from app.models.user import User

logger = logging.getLogger(__name__)


class ConflictResolutionStrategy(str, Enum):
    """Available conflict resolution strategies."""
    LOCAL_WINS = "local_wins"
    EXTERNAL_WINS = "external_wins"
    NEWEST_WINS = "newest_wins"
    MERGE = "merge"
    MANUAL = "manual"
    ADMIN_OVERRIDE = "admin_override"


class ConflictType(str, Enum):
    """Types of conflicts that can occur."""
    DATA_MISMATCH = "data_mismatch"
    TIMESTAMP_CONFLICT = "timestamp_conflict"
    RECORD_DELETED = "record_deleted"
    DUPLICATE_RECORD = "duplicate_record"
    VALIDATION_FAILURE = "validation_failure"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class ConflictResolution:
    """Result of a conflict resolution."""
    strategy: ConflictResolutionStrategy
    resolved_data: Dict[str, Any]
    explanation: str
    confidence: float = 1.0  # 0.0 to 1.0
    requires_admin_review: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldConflict:
    """Information about a specific field conflict."""
    field_name: str
    local_value: Any
    external_value: Any
    local_timestamp: Optional[datetime] = None
    external_timestamp: Optional[datetime] = None
    data_type: str = "string"
    importance: int = 1  # 1-10, higher is more important


class ConflictResolver:
    """
    Main conflict resolution engine.
    
    Analyzes conflicts and applies appropriate resolution strategies
    based on configurable rules and data types.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._field_importance = self._initialize_field_importance()
        self._merge_strategies = self._initialize_merge_strategies()
    
    def _initialize_field_importance(self) -> Dict[str, int]:
        """Initialize field importance rankings."""
        return {
            # High importance - critical identity fields
            'email': 10,
            'student_id': 10,
            'state_id': 10,
            'first_name': 9,
            'last_name': 9,
            
            # Medium importance - important but changeable
            'phone': 7,
            'address': 6,
            'emergency_contact': 8,
            'grade_level': 8,
            'enrollment_status': 9,
            
            # Lower importance - preferences and metadata
            'preferred_name': 4,
            'notifications_enabled': 3,
            'last_login': 2,
            'ui_preferences': 1
        }
    
    def _initialize_merge_strategies(self) -> Dict[str, str]:
        """Initialize field-specific merge strategies."""
        return {
            'email': 'external_wins',  # SIS is authoritative for email
            'phone': 'newest_wins',    # Phone can change frequently
            'address': 'external_wins', # SIS is authoritative for address
            'emergency_contact': 'external_wins',
            'grade_level': 'external_wins',
            'enrollment_status': 'external_wins',
            'preferred_name': 'local_wins',  # Local preference
            'notifications_enabled': 'local_wins',
            'ui_preferences': 'local_wins'
        }
    
    async def resolve_conflict(
        self,
        conflict: SyncConflict,
        strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS,
        admin_user_id: Optional[int] = None
    ) -> ConflictResolution:
        """
        Resolve a sync conflict using the specified strategy.
        
        Args:
            conflict: The conflict to resolve
            strategy: Resolution strategy to use
            admin_user_id: User ID for admin override (required for admin_override strategy)
            
        Returns:
            ConflictResolution with resolved data and metadata
        """
        logger.info(f"Resolving conflict {conflict.id} using strategy {strategy}")
        
        try:
            if strategy == ConflictResolutionStrategy.LOCAL_WINS:
                return await self._resolve_local_wins(conflict)
            elif strategy == ConflictResolutionStrategy.EXTERNAL_WINS:
                return await self._resolve_external_wins(conflict)
            elif strategy == ConflictResolutionStrategy.NEWEST_WINS:
                return await self._resolve_newest_wins(conflict)
            elif strategy == ConflictResolutionStrategy.MERGE:
                return await self._resolve_merge(conflict)
            elif strategy == ConflictResolutionStrategy.ADMIN_OVERRIDE:
                return await self._resolve_admin_override(conflict, admin_user_id)
            else:  # MANUAL
                return await self._resolve_manual(conflict)
        
        except Exception as e:
            logger.error(f"Error resolving conflict {conflict.id}: {e}")
            raise
    
    async def _resolve_local_wins(self, conflict: SyncConflict) -> ConflictResolution:
        """Resolve by keeping local data."""
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.LOCAL_WINS,
            resolved_data=conflict.local_data,
            explanation="Local system data takes precedence",
            confidence=0.8
        )
    
    async def _resolve_external_wins(self, conflict: SyncConflict) -> ConflictResolution:
        """Resolve by using external (SIS) data."""
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.EXTERNAL_WINS,
            resolved_data=conflict.external_data,
            explanation="External SIS data takes precedence",
            confidence=0.9
        )
    
    async def _resolve_newest_wins(self, conflict: SyncConflict) -> ConflictResolution:
        """Resolve by using the most recently modified data."""
        local_timestamp = self._extract_timestamp(conflict.local_data)
        external_timestamp = self._extract_timestamp(conflict.external_data)
        
        if local_timestamp and external_timestamp:
            if local_timestamp > external_timestamp:
                return ConflictResolution(
                    strategy=ConflictResolutionStrategy.NEWEST_WINS,
                    resolved_data=conflict.local_data,
                    explanation=f"Local data is newer ({local_timestamp} > {external_timestamp})",
                    confidence=0.95
                )
            else:
                return ConflictResolution(
                    strategy=ConflictResolutionStrategy.NEWEST_WINS,
                    resolved_data=conflict.external_data,
                    explanation=f"External data is newer ({external_timestamp} > {local_timestamp})",
                    confidence=0.95
                )
        
        # Fallback to external wins if timestamps are unavailable
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.NEWEST_WINS,
            resolved_data=conflict.external_data,
            explanation="External data used (timestamps unavailable)",
            confidence=0.5
        )
    
    async def _resolve_merge(self, conflict: SyncConflict) -> ConflictResolution:
        """Resolve by intelligently merging local and external data."""
        field_conflicts = self._analyze_field_conflicts(conflict)
        merged_data = {}
        merge_details = []
        
        # Start with external data as base
        merged_data.update(conflict.external_data)
        
        # Apply field-specific merge strategies
        for field_conflict in field_conflicts:
            field_name = field_conflict.field_name
            merge_strategy = self._merge_strategies.get(field_name, 'newest_wins')
            
            if merge_strategy == 'local_wins':
                merged_data[field_name] = field_conflict.local_value
                merge_details.append(f"{field_name}: used local value")
            elif merge_strategy == 'external_wins':
                merged_data[field_name] = field_conflict.external_value
                merge_details.append(f"{field_name}: used external value")
            elif merge_strategy == 'newest_wins':
                if field_conflict.local_timestamp and field_conflict.external_timestamp:
                    if field_conflict.local_timestamp > field_conflict.external_timestamp:
                        merged_data[field_name] = field_conflict.local_value
                        merge_details.append(f"{field_name}: used local (newer)")
                    else:
                        merged_data[field_name] = field_conflict.external_value
                        merge_details.append(f"{field_name}: used external (newer)")
                else:
                    # Default to external if no timestamps
                    merged_data[field_name] = field_conflict.external_value
                    merge_details.append(f"{field_name}: used external (no timestamps)")
        
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.MERGE,
            resolved_data=merged_data,
            explanation=f"Intelligent merge: {'; '.join(merge_details)}",
            confidence=0.85,
            metadata={'merge_details': merge_details}
        )
    
    async def _resolve_admin_override(
        self,
        conflict: SyncConflict,
        admin_user_id: Optional[int]
    ) -> ConflictResolution:
        """Resolve with administrative override."""
        if not admin_user_id:
            raise ValueError("Admin user ID required for admin override")
        
        # Verify admin user exists
        result = await self.db.execute(
            select(User).where(User.id == admin_user_id)
        )
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            raise ValueError(f"Admin user {admin_user_id} not found")
        
        # Admin overrides always require manual review first
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.ADMIN_OVERRIDE,
            resolved_data=conflict.local_data,  # Default to local data
            explanation=f"Requires administrative review by {admin_user.email}",
            confidence=0.0,
            requires_admin_review=True
        )
    
    async def _resolve_manual(self, conflict: SyncConflict) -> ConflictResolution:
        """Mark conflict for manual resolution."""
        return ConflictResolution(
            strategy=ConflictResolutionStrategy.MANUAL,
            resolved_data=conflict.external_data,  # Temporary fallback
            explanation="Conflict requires manual resolution",
            confidence=0.0,
            requires_admin_review=True
        )
    
    def _extract_timestamp(self, data: Dict[str, Any]) -> Optional[datetime]:
        """Extract timestamp from data dictionary."""
        timestamp_fields = ['updated_at', 'modified_at', 'last_modified', 'timestamp']
        
        for field in timestamp_fields:
            if field in data:
                value = data[field]
                if isinstance(value, datetime):
                    return value
                elif isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except ValueError:
                        continue
        
        return None
    
    def _analyze_field_conflicts(self, conflict: SyncConflict) -> List[FieldConflict]:
        """Analyze field-level conflicts between local and external data."""
        field_conflicts = []
        
        # Get all fields that differ
        all_fields = set(conflict.local_data.keys()) | set(conflict.external_data.keys())
        
        for field_name in all_fields:
            local_value = conflict.local_data.get(field_name)
            external_value = conflict.external_data.get(field_name)
            
            # Skip if values are the same
            if local_value == external_value:
                continue
            
            # Extract timestamps if available
            local_timestamp = None
            external_timestamp = None
            
            if isinstance(local_value, dict) and 'updated_at' in local_value:
                local_timestamp = self._extract_timestamp(local_value)
            if isinstance(external_value, dict) and 'updated_at' in external_value:
                external_timestamp = self._extract_timestamp(external_value)
            
            field_conflict = FieldConflict(
                field_name=field_name,
                local_value=local_value,
                external_value=external_value,
                local_timestamp=local_timestamp,
                external_timestamp=external_timestamp,
                importance=self._field_importance.get(field_name, 5)
            )
            
            field_conflicts.append(field_conflict)
        
        # Sort by importance (highest first)
        field_conflicts.sort(key=lambda x: x.importance, reverse=True)
        
        return field_conflicts
    
    async def get_pending_conflicts(
        self,
        integration_id: Optional[int] = None,
        requires_admin: bool = False
    ) -> List[SyncConflict]:
        """Get pending conflicts that need resolution."""
        query = select(SyncConflict).where(SyncConflict.is_resolved == False)
        
        if integration_id:
            query = query.join(SyncConflict.sync_operation).where(
                SyncConflict.sync_operation.has(integration_id=integration_id)
            )
        
        if requires_admin:
            query = query.where(SyncConflict.requires_admin_review == True)
        
        query = query.order_by(SyncConflict.detected_at.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def apply_resolution(
        self,
        conflict: SyncConflict,
        resolution: ConflictResolution,
        user_id: int
    ) -> bool:
        """Apply a conflict resolution and update the conflict record."""
        try:
            # Update the conflict record
            conflict.resolve(
                strategy=resolution.strategy.value,
                resolved_data=resolution.resolved_data,
                user_id=user_id,
                admin_override=(resolution.strategy == ConflictResolutionStrategy.ADMIN_OVERRIDE)
            )
            
            # Add resolution metadata
            if resolution.metadata:
                if not conflict.sync_operation.sync_metadata:
                    conflict.sync_operation.sync_metadata = {}
                
                conflict.sync_operation.sync_metadata['conflict_resolution'] = {
                    'conflict_id': conflict.id,
                    'resolution_metadata': resolution.metadata,
                    'confidence': resolution.confidence,
                    'applied_at': datetime.utcnow().isoformat()
                }
            
            await self.db.commit()
            
            logger.info(f"Applied resolution for conflict {conflict.id} using {resolution.strategy}")
            return True
        
        except Exception as e:
            logger.error(f"Error applying resolution for conflict {conflict.id}: {e}")
            await self.db.rollback()
            return False


# Standalone utility functions

async def resolve_sync_conflicts(
    db: AsyncSession,
    integration_id: Optional[int] = None,
    auto_resolve: bool = True,
    strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.NEWEST_WINS
) -> Dict[str, Any]:
    """
    Resolve pending sync conflicts for an integration.
    
    Args:
        db: Database session
        integration_id: Specific integration to resolve conflicts for
        auto_resolve: Whether to automatically resolve conflicts
        strategy: Default resolution strategy
        
    Returns:
        Dictionary with resolution statistics
    """
    resolver = ConflictResolver(db)
    conflicts = await resolver.get_pending_conflicts(integration_id)
    
    stats = {
        'total_conflicts': len(conflicts),
        'resolved': 0,
        'failed': 0,
        'requires_manual': 0,
        'resolutions': []
    }
    
    for conflict in conflicts:
        try:
            if auto_resolve and not conflict.requires_admin_review:
                resolution = await resolver.resolve_conflict(conflict, strategy)
                
                if resolution.requires_admin_review:
                    stats['requires_manual'] += 1
                else:
                    # Apply the resolution (using system user ID 0 for auto-resolution)
                    success = await resolver.apply_resolution(conflict, resolution, 0)
                    
                    if success:
                        stats['resolved'] += 1
                        stats['resolutions'].append({
                            'conflict_id': conflict.id,
                            'strategy': resolution.strategy.value,
                            'confidence': resolution.confidence
                        })
                    else:
                        stats['failed'] += 1
            else:
                stats['requires_manual'] += 1
        
        except Exception as e:
            logger.error(f"Error resolving conflict {conflict.id}: {e}")
            stats['failed'] += 1
    
    return stats


async def merge_conflicting_data(
    local_data: Dict[str, Any],
    external_data: Dict[str, Any],
    merge_rules: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Merge two conflicting data dictionaries using specified rules.
    
    Args:
        local_data: Data from local system
        external_data: Data from external system
        merge_rules: Field-specific merge rules
        
    Returns:
        Merged data dictionary
    """
    if not merge_rules:
        merge_rules = {
            'email': 'external_wins',
            'phone': 'newest_wins',
            'address': 'external_wins',
            'preferred_name': 'local_wins'
        }
    
    merged = {}
    all_fields = set(local_data.keys()) | set(external_data.keys())
    
    for field in all_fields:
        local_value = local_data.get(field)
        external_value = external_data.get(field)
        
        # If values are the same, use either one
        if local_value == external_value:
            merged[field] = local_value or external_value
            continue
        
        # Apply merge rule for this field
        rule = merge_rules.get(field, 'external_wins')
        
        if rule == 'local_wins':
            merged[field] = local_value if local_value is not None else external_value
        elif rule == 'external_wins':
            merged[field] = external_value if external_value is not None else local_value
        elif rule == 'newest_wins':
            # Try to determine which is newer based on timestamps
            local_ts = None
            external_ts = None
            
            if isinstance(local_value, dict) and 'updated_at' in local_value:
                try:
                    local_ts = datetime.fromisoformat(str(local_value['updated_at']).replace('Z', '+00:00'))
                except:
                    pass
            
            if isinstance(external_value, dict) and 'updated_at' in external_value:
                try:
                    external_ts = datetime.fromisoformat(str(external_value['updated_at']).replace('Z', '+00:00'))
                except:
                    pass
            
            if local_ts and external_ts:
                merged[field] = local_value if local_ts > external_ts else external_value
            else:
                # Fallback to external wins
                merged[field] = external_value if external_value is not None else local_value
        else:
            # Default to external wins
            merged[field] = external_value if external_value is not None else local_value
    
    return merged