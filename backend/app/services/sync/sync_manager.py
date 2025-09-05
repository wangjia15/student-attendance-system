"""
Sync Manager Service

Handles offline sync operations on the backend:
- Processes sync operations from offline clients
- Manages conflict resolution on the server side
- Provides bandwidth-optimized responses
- Integrates with real-time WebSocket updates
- Maintains sync operation audit logs
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import and_, or_, desc, func

from ...core.database import get_db
from ...models.attendance import Attendance, AttendanceRecord
from ...models.class_session import ClassSession
from ...models.user import User
from ...websocket.live_updates import broadcast_attendance_update
from ..attendance_engine import AttendanceEngine

logger = logging.getLogger(__name__)

class SyncOperationType(Enum):
    CHECK_IN = "check_in"
    STATUS_UPDATE = "status_update"
    BULK_OPERATION = "bulk_operation"
    SESSION_UPDATE = "session_update"

class ConflictType(Enum):
    ATTENDANCE_STATUS = "attendance_status"
    TIMESTAMP_CONFLICT = "timestamp_conflict"
    CONCURRENT_MODIFICATION = "concurrent_modification"
    DATA_INTEGRITY = "data_integrity"

class SyncResult(Enum):
    SUCCESS = "success"
    CONFLICT = "conflict"
    ERROR = "error"
    PARTIAL_SUCCESS = "partial_success"

class SyncOperation:
    """Represents a sync operation to be processed"""
    
    def __init__(self, 
                 operation_type: SyncOperationType,
                 data: Dict[str, Any],
                 timestamp: datetime,
                 client_id: str,
                 user_id: int,
                 priority: int = 1):
        self.operation_type = operation_type
        self.data = data
        self.timestamp = timestamp
        self.client_id = client_id
        self.user_id = user_id
        self.priority = priority
        self.result: Optional[SyncResult] = None
        self.conflict_data: Optional[Dict[str, Any]] = None
        self.error_message: Optional[str] = None

class ConflictResolution:
    """Represents a conflict and its resolution"""
    
    def __init__(self,
                 conflict_type: ConflictType,
                 local_data: Dict[str, Any],
                 server_data: Dict[str, Any],
                 resolution_strategy: str,
                 resolved_data: Dict[str, Any]):
        self.conflict_type = conflict_type
        self.local_data = local_data
        self.server_data = server_data
        self.resolution_strategy = resolution_strategy
        self.resolved_data = resolved_data
        self.timestamp = datetime.utcnow()

class SyncManager:
    """Main sync manager for handling offline sync operations"""
    
    def __init__(self, db: Session):
        self.db = db
        self.attendance_engine = AttendanceEngine(db)
        self.conflict_resolvers = {
            ConflictType.ATTENDANCE_STATUS: self._resolve_attendance_conflict,
            ConflictType.TIMESTAMP_CONFLICT: self._resolve_timestamp_conflict,
            ConflictType.CONCURRENT_MODIFICATION: self._resolve_concurrent_modification,
            ConflictType.DATA_INTEGRITY: self._resolve_data_integrity_conflict
        }
    
    async def process_sync_batch(self, 
                                operations: List[Dict[str, Any]], 
                                user_id: int,
                                client_id: str) -> Dict[str, Any]:
        """Process a batch of sync operations"""
        
        results = {
            "processed": 0,
            "successful": 0,
            "conflicts": 0,
            "errors": 0,
            "operations": [],
            "conflicts_data": [],
            "total_time_ms": 0
        }
        
        start_time = datetime.utcnow()
        
        try:
            # Convert to SyncOperation objects and sort by priority and timestamp
            sync_ops = []
            for op_data in operations:
                sync_op = SyncOperation(
                    operation_type=SyncOperationType(op_data["type"]),
                    data=op_data["data"],
                    timestamp=datetime.fromisoformat(op_data["timestamp"].replace('Z', '+00:00')),
                    client_id=client_id,
                    user_id=user_id,
                    priority=op_data.get("priority", 1)
                )
                sync_ops.append(sync_op)
            
            # Sort by priority (higher first) then timestamp (older first)
            sync_ops.sort(key=lambda x: (-x.priority, x.timestamp))
            
            # Process operations with dependency resolution
            resolved_ops = await self._resolve_dependencies(sync_ops)
            
            # Process each operation
            for sync_op in resolved_ops:
                try:
                    result = await self._process_single_operation(sync_op)
                    
                    results["operations"].append({
                        "type": sync_op.operation_type.value,
                        "result": result.value,
                        "data": sync_op.data,
                        "conflict_data": sync_op.conflict_data,
                        "error": sync_op.error_message
                    })
                    
                    results["processed"] += 1
                    
                    if result == SyncResult.SUCCESS:
                        results["successful"] += 1
                    elif result == SyncResult.CONFLICT:
                        results["conflicts"] += 1
                        if sync_op.conflict_data:
                            results["conflicts_data"].append(sync_op.conflict_data)
                    else:
                        results["errors"] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to process sync operation: {e}")
                    results["errors"] += 1
                    results["operations"].append({
                        "type": sync_op.operation_type.value,
                        "result": SyncResult.ERROR.value,
                        "error": str(e)
                    })
            
            # Commit successful operations
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Sync batch processing failed: {e}")
            self.db.rollback()
            results["errors"] = len(operations)
            
        finally:
            end_time = datetime.utcnow()
            results["total_time_ms"] = int((end_time - start_time).total_seconds() * 1000)
            
        return results
    
    async def _process_single_operation(self, sync_op: SyncOperation) -> SyncResult:
        """Process a single sync operation"""
        
        try:
            if sync_op.operation_type == SyncOperationType.CHECK_IN:
                return await self._process_check_in(sync_op)
            elif sync_op.operation_type == SyncOperationType.STATUS_UPDATE:
                return await self._process_status_update(sync_op)
            elif sync_op.operation_type == SyncOperationType.BULK_OPERATION:
                return await self._process_bulk_operation(sync_op)
            elif sync_op.operation_type == SyncOperationType.SESSION_UPDATE:
                return await self._process_session_update(sync_op)
            else:
                sync_op.error_message = f"Unknown operation type: {sync_op.operation_type}"
                return SyncResult.ERROR
                
        except Exception as e:
            sync_op.error_message = str(e)
            return SyncResult.ERROR
    
    async def _process_check_in(self, sync_op: SyncOperation) -> SyncResult:
        """Process a student check-in operation"""
        
        try:
            data = sync_op.data
            student_id = data.get("student_id")
            session_id = data.get("session_id")
            check_in_method = data.get("method", "offline")
            location = data.get("location")
            
            if not student_id or not session_id:
                sync_op.error_message = "Missing required fields: student_id, session_id"
                return SyncResult.ERROR
            
            # Check if session exists and is active
            session = self.db.query(ClassSession).filter(ClassSession.id == session_id).first()
            if not session:
                sync_op.error_message = f"Session {session_id} not found"
                return SyncResult.ERROR
            
            # Check for existing attendance record
            existing_record = self.db.query(Attendance).filter(
                and_(
                    Attendance.student_id == student_id,
                    Attendance.class_session_id == session_id
                )
            ).first()
            
            if existing_record:
                # Check for conflict with existing record
                conflict = await self._detect_attendance_conflict(
                    existing_record, sync_op.data, sync_op.timestamp
                )
                
                if conflict:
                    sync_op.conflict_data = conflict
                    return SyncResult.CONFLICT
            
            # Process the check-in using attendance engine
            result = await self.attendance_engine.process_check_in(
                student_id=student_id,
                session_id=session_id,
                method=check_in_method,
                location=location,
                timestamp=sync_op.timestamp
            )
            
            # Broadcast real-time update
            await self._broadcast_sync_update(sync_op, result)
            
            return SyncResult.SUCCESS
            
        except IntegrityError as e:
            logger.warning(f"Check-in integrity error: {e}")
            # This might be a duplicate - check for conflicts
            conflict = await self._handle_integrity_conflict(sync_op)
            if conflict:
                sync_op.conflict_data = conflict
                return SyncResult.CONFLICT
            else:
                sync_op.error_message = "Data integrity violation"
                return SyncResult.ERROR
        
        except Exception as e:
            logger.error(f"Check-in processing failed: {e}")
            sync_op.error_message = str(e)
            return SyncResult.ERROR
    
    async def _process_status_update(self, sync_op: SyncOperation) -> SyncResult:
        """Process an attendance status update"""
        
        try:
            data = sync_op.data
            student_id = data.get("student_id")
            session_id = data.get("session_id")
            new_status = data.get("status")
            
            if not all([student_id, session_id, new_status]):
                sync_op.error_message = "Missing required fields"
                return SyncResult.ERROR
            
            # Get existing attendance record
            attendance = self.db.query(Attendance).filter(
                and_(
                    Attendance.student_id == student_id,
                    Attendance.class_session_id == session_id
                )
            ).first()
            
            if not attendance:
                sync_op.error_message = f"Attendance record not found"
                return SyncResult.ERROR
            
            # Check for conflicts with server state
            conflict = await self._detect_status_update_conflict(
                attendance, sync_op.data, sync_op.timestamp
            )
            
            if conflict:
                sync_op.conflict_data = conflict
                return SyncResult.CONFLICT
            
            # Update the status
            old_status = attendance.status
            attendance.status = new_status
            attendance.updated_at = sync_op.timestamp
            attendance.updated_by = sync_op.user_id
            
            # Add to attendance records
            record = AttendanceRecord(
                attendance_id=attendance.id,
                status=new_status,
                timestamp=sync_op.timestamp,
                method="offline_sync",
                updated_by=sync_op.user_id
            )
            self.db.add(record)
            
            # Broadcast real-time update
            await self._broadcast_status_update(attendance, old_status, new_status)
            
            return SyncResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Status update failed: {e}")
            sync_op.error_message = str(e)
            return SyncResult.ERROR
    
    async def _process_bulk_operation(self, sync_op: SyncOperation) -> SyncResult:
        """Process bulk operations"""
        
        try:
            operations = sync_op.data.get("operations", [])
            
            if not operations:
                sync_op.error_message = "No operations in bulk request"
                return SyncResult.ERROR
            
            successful = 0
            conflicts = []
            errors = []
            
            # Process each operation in the bulk
            for op_data in operations:
                try:
                    # Create sub-operation
                    sub_op = SyncOperation(
                        operation_type=SyncOperationType(op_data["type"]),
                        data=op_data["data"],
                        timestamp=datetime.fromisoformat(op_data["timestamp"].replace('Z', '+00:00')),
                        client_id=sync_op.client_id,
                        user_id=sync_op.user_id
                    )
                    
                    result = await self._process_single_operation(sub_op)
                    
                    if result == SyncResult.SUCCESS:
                        successful += 1
                    elif result == SyncResult.CONFLICT:
                        conflicts.append({
                            "operation": op_data,
                            "conflict": sub_op.conflict_data
                        })
                    else:
                        errors.append({
                            "operation": op_data,
                            "error": sub_op.error_message
                        })
                        
                except Exception as e:
                    errors.append({
                        "operation": op_data,
                        "error": str(e)
                    })
            
            # Determine overall result
            if errors:
                sync_op.error_message = f"{len(errors)} operations failed"
                if successful > 0:
                    return SyncResult.PARTIAL_SUCCESS
                else:
                    return SyncResult.ERROR
            elif conflicts:
                sync_op.conflict_data = {
                    "type": "bulk_conflicts",
                    "conflicts": conflicts,
                    "successful": successful
                }
                return SyncResult.CONFLICT
            else:
                return SyncResult.SUCCESS
                
        except Exception as e:
            logger.error(f"Bulk operation failed: {e}")
            sync_op.error_message = str(e)
            return SyncResult.ERROR
    
    async def _process_session_update(self, sync_op: SyncOperation) -> SyncResult:
        """Process session configuration updates"""
        
        try:
            data = sync_op.data
            session_id = data.get("session_id")
            updates = data.get("updates", {})
            
            if not session_id or not updates:
                sync_op.error_message = "Missing session_id or updates"
                return SyncResult.ERROR
            
            # Get session
            session = self.db.query(ClassSession).filter(ClassSession.id == session_id).first()
            if not session:
                sync_op.error_message = f"Session {session_id} not found"
                return SyncResult.ERROR
            
            # Check for conflicts
            conflict = await self._detect_session_update_conflict(
                session, updates, sync_op.timestamp
            )
            
            if conflict:
                sync_op.conflict_data = conflict
                return SyncResult.CONFLICT
            
            # Apply updates
            for field, value in updates.items():
                if hasattr(session, field):
                    setattr(session, field, value)
            
            session.updated_at = sync_op.timestamp
            
            return SyncResult.SUCCESS
            
        except Exception as e:
            logger.error(f"Session update failed: {e}")
            sync_op.error_message = str(e)
            return SyncResult.ERROR
    
    async def _resolve_dependencies(self, operations: List[SyncOperation]) -> List[SyncOperation]:
        """Resolve operation dependencies"""
        
        # For now, just return in priority order
        # In a more complex implementation, we would analyze dependencies
        # between operations and reorder them accordingly
        return operations
    
    async def _detect_attendance_conflict(self, 
                                        existing: Attendance, 
                                        new_data: Dict[str, Any],
                                        new_timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Detect conflicts in attendance records"""
        
        # Check if the existing record was updated more recently
        if existing.updated_at and existing.updated_at > new_timestamp:
            return {
                "type": ConflictType.TIMESTAMP_CONFLICT.value,
                "local_data": new_data,
                "server_data": {
                    "student_id": existing.student_id,
                    "session_id": existing.class_session_id,
                    "status": existing.status,
                    "updated_at": existing.updated_at.isoformat()
                },
                "message": "Server record is more recent"
            }
        
        # Check for status conflicts
        local_status = new_data.get("status")
        if local_status and existing.status != local_status:
            
            # Special case: if one is "present" and other is "absent", it's a conflict
            if (existing.status == "absent" and local_status == "present") or \
               (existing.status == "present" and local_status == "absent"):
                return {
                    "type": ConflictType.ATTENDANCE_STATUS.value,
                    "local_data": new_data,
                    "server_data": {
                        "status": existing.status,
                        "updated_at": existing.updated_at.isoformat() if existing.updated_at else None
                    },
                    "message": f"Status conflict: local={local_status}, server={existing.status}"
                }
        
        return None
    
    async def _detect_status_update_conflict(self,
                                           attendance: Attendance,
                                           new_data: Dict[str, Any],
                                           new_timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Detect conflicts in status updates"""
        
        # Check timestamp conflicts
        if attendance.updated_at and attendance.updated_at > new_timestamp:
            return {
                "type": ConflictType.TIMESTAMP_CONFLICT.value,
                "local_data": new_data,
                "server_data": {
                    "status": attendance.status,
                    "updated_at": attendance.updated_at.isoformat()
                },
                "message": "Server has more recent update"
            }
        
        return None
    
    async def _detect_session_update_conflict(self,
                                            session: ClassSession,
                                            updates: Dict[str, Any],
                                            new_timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Detect conflicts in session updates"""
        
        # Check if session was updated more recently
        if session.updated_at and session.updated_at > new_timestamp:
            return {
                "type": ConflictType.CONCURRENT_MODIFICATION.value,
                "local_data": updates,
                "server_data": {
                    "updated_at": session.updated_at.isoformat()
                },
                "message": "Session was modified more recently on server"
            }
        
        return None
    
    async def _handle_integrity_conflict(self, sync_op: SyncOperation) -> Optional[Dict[str, Any]]:
        """Handle database integrity conflicts"""
        
        # Check if this is a duplicate check-in attempt
        student_id = sync_op.data.get("student_id")
        session_id = sync_op.data.get("session_id")
        
        if student_id and session_id:
            existing = self.db.query(Attendance).filter(
                and_(
                    Attendance.student_id == student_id,
                    Attendance.class_session_id == session_id
                )
            ).first()
            
            if existing:
                return {
                    "type": ConflictType.DATA_INTEGRITY.value,
                    "local_data": sync_op.data,
                    "server_data": {
                        "status": existing.status,
                        "checked_in_at": existing.checked_in_at.isoformat() if existing.checked_in_at else None
                    },
                    "message": "Student already checked in"
                }
        
        return None
    
    async def _broadcast_sync_update(self, sync_op: SyncOperation, result: Any):
        """Broadcast sync updates via WebSocket"""
        
        try:
            # Broadcast the attendance update
            await broadcast_attendance_update({
                "type": "sync_update",
                "operation": sync_op.operation_type.value,
                "student_id": sync_op.data.get("student_id"),
                "session_id": sync_op.data.get("session_id"),
                "timestamp": sync_op.timestamp.isoformat(),
                "source": "offline_sync"
            })
        except Exception as e:
            logger.warning(f"Failed to broadcast sync update: {e}")
    
    async def _broadcast_status_update(self, attendance: Attendance, old_status: str, new_status: str):
        """Broadcast status update via WebSocket"""
        
        try:
            await broadcast_attendance_update({
                "type": "status_update",
                "student_id": attendance.student_id,
                "session_id": attendance.class_session_id,
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": attendance.updated_at.isoformat() if attendance.updated_at else None,
                "source": "offline_sync"
            })
        except Exception as e:
            logger.warning(f"Failed to broadcast status update: {e}")
    
    # Conflict resolution methods
    async def _resolve_attendance_conflict(self, conflict_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve attendance status conflicts"""
        
        local_data = conflict_data["local_data"]
        server_data = conflict_data["server_data"]
        
        local_status = local_data.get("status")
        server_status = server_data.get("status")
        
        # Resolution strategy: presence takes precedence over absence
        if local_status == "present" and server_status in ["absent", "late"]:
            return {
                "strategy": "local_wins",
                "resolved_data": local_data,
                "explanation": "Presence takes precedence"
            }
        elif server_status == "present" and local_status in ["absent", "late"]:
            return {
                "strategy": "server_wins", 
                "resolved_data": server_data,
                "explanation": "Presence takes precedence"
            }
        else:
            # Use timestamp-based resolution
            local_time = datetime.fromisoformat(local_data.get("timestamp", "1970-01-01").replace('Z', '+00:00'))
            server_time = datetime.fromisoformat(server_data.get("updated_at", "1970-01-01").replace('Z', '+00:00'))
            
            if local_time > server_time:
                return {
                    "strategy": "local_wins",
                    "resolved_data": local_data,
                    "explanation": "Local change is more recent"
                }
            else:
                return {
                    "strategy": "server_wins",
                    "resolved_data": server_data,
                    "explanation": "Server change is more recent"
                }
    
    async def _resolve_timestamp_conflict(self, conflict_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve timestamp-based conflicts"""
        
        # Always use the most recent timestamp
        local_data = conflict_data["local_data"]
        server_data = conflict_data["server_data"]
        
        local_time = datetime.fromisoformat(local_data.get("timestamp", "1970-01-01").replace('Z', '+00:00'))
        server_time = datetime.fromisoformat(server_data.get("updated_at", "1970-01-01").replace('Z', '+00:00'))
        
        if local_time > server_time:
            return {
                "strategy": "local_wins",
                "resolved_data": local_data,
                "explanation": "Local timestamp is more recent"
            }
        else:
            return {
                "strategy": "server_wins",
                "resolved_data": server_data,
                "explanation": "Server timestamp is more recent"
            }
    
    async def _resolve_concurrent_modification(self, conflict_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve concurrent modification conflicts"""
        
        # For concurrent modifications, prefer server state but log the conflict
        return {
            "strategy": "server_wins",
            "resolved_data": conflict_data["server_data"],
            "explanation": "Server state preserved due to concurrent modification",
            "requires_manual_review": True
        }
    
    async def _resolve_data_integrity_conflict(self, conflict_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve data integrity conflicts"""
        
        # For integrity conflicts, preserve existing data
        return {
            "strategy": "server_wins",
            "resolved_data": conflict_data["server_data"],
            "explanation": "Existing record preserved to maintain data integrity"
        }
    
    async def get_sync_statistics(self, user_id: int, days: int = 7) -> Dict[str, Any]:
        """Get sync statistics for a user"""
        
        # This would query sync logs if we had a sync_logs table
        # For now, return basic statistics
        return {
            "sync_operations_processed": 0,
            "conflicts_resolved": 0,
            "average_processing_time_ms": 0,
            "success_rate": 100.0,
            "period_days": days
        }