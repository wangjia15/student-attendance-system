"""
Utility modules for the Student Attendance System.
"""

from .conflict_resolution import (
    ConflictResolver,
    ConflictResolutionStrategy,
    resolve_sync_conflicts,
    merge_conflicting_data
)

__all__ = [
    "ConflictResolver",
    "ConflictResolutionStrategy", 
    "resolve_sync_conflicts",
    "merge_conflicting_data"
]