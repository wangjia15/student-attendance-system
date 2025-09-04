"""
WebSocket handler for real-time attendance updates and teacher dashboard functionality.
"""
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..core.security import jwt_manager
from ..core.database import get_db
from ..models.user import User, UserRole
from ..models.class_session import ClassSession
from ..models.attendance import AttendanceRecord, AttendanceStatus
from ..services.attendance_engine import AttendanceEngine


class AttendanceUpdate(BaseModel):
    """Model for attendance update events."""
    type: str
    class_session_id: int
    student_id: int
    student_name: str
    old_status: Optional[AttendanceStatus]
    new_status: AttendanceStatus
    updated_by: int
    updated_by_name: str
    reason: Optional[str]
    timestamp: datetime
    is_override: bool = False
    late_minutes: Optional[int] = None


class ClassStatsUpdate(BaseModel):
    """Model for real-time class statistics."""
    class_session_id: int
    total_enrolled: int
    checked_in_count: int
    present_count: int
    late_count: int
    absent_count: int
    excused_count: int
    attendance_rate: float
    last_updated: datetime


class BulkOperationUpdate(BaseModel):
    """Model for bulk operation updates."""
    type: str = "bulk_operation"
    class_session_id: int
    operation: str
    affected_students: List[int]
    updated_by: int
    updated_by_name: str
    processed_count: int
    failed_count: int
    timestamp: datetime


class AlertUpdate(BaseModel):
    """Model for attendance alert updates."""
    type: str = "attendance_alert"
    class_session_id: int
    alert_type: str
    severity: str
    student_id: int
    student_name: str
    message: str
    data: Dict[str, Any]
    timestamp: datetime


class AttendanceConnectionManager:
    """Manages WebSocket connections for attendance updates with role-based access."""
    
    def __init__(self):
        # Dictionary of class_id -> set of WebSocket connections
        self.teacher_connections: Dict[int, Set[WebSocket]] = {}
        self.student_connections: Dict[int, Set[WebSocket]] = {}
        
        # Dictionary of WebSocket -> connection info for cleanup
        self.connection_info: Dict[WebSocket, Dict[str, Any]] = {}
        
        # Track active operations to prevent conflicts
        self.active_operations: Dict[str, Dict[str, Any]] = {}
    
    async def connect(self, websocket: WebSocket, class_id: int, token: str):
        """
        Connect a WebSocket to attendance updates with authentication and role checking.
        
        Args:
            websocket: WebSocket connection
            class_id: Class session ID
            token: JWT token for authentication
        """
        try:
            # Verify JWT token
            payload = jwt_manager.verify_token(token)
            user_id = payload.get("user_id")
            user_role = payload.get("role")
            
            if not user_id or not user_role:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return False
            
            # Get database session (simplified - in real app you'd inject this)
            # For now, we'll just validate the connection
            
            # Accept connection
            await websocket.accept()
            
            # Store connection info
            self.connection_info[websocket] = {
                "user_id": user_id,
                "user_role": user_role,
                "class_id": class_id,
                "connected_at": datetime.now(timezone.utc)
            }
            
            # Add to appropriate connection pool
            if user_role == UserRole.TEACHER.value:
                if class_id not in self.teacher_connections:
                    self.teacher_connections[class_id] = set()
                self.teacher_connections[class_id].add(websocket)
                
                # Send teacher-specific connection confirmation
                await self._send_to_websocket(websocket, {
                    "type": "teacher_connected",
                    "class_id": class_id,
                    "permissions": ["view_all", "edit_attendance", "bulk_operations"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Connected to teacher dashboard"
                })
            else:
                if class_id not in self.student_connections:
                    self.student_connections[class_id] = set()
                self.student_connections[class_id].add(websocket)
                
                # Send student-specific connection confirmation
                await self._send_to_websocket(websocket, {
                    "type": "student_connected",
                    "class_id": class_id,
                    "permissions": ["view_own", "check_in"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Connected to attendance updates"
                })
            
            return True
            
        except Exception as e:
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return False
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection and cleanup."""
        if websocket not in self.connection_info:
            return
            
        connection_info = self.connection_info[websocket]
        class_id = connection_info["class_id"]
        user_role = connection_info["user_role"]
        
        # Remove from appropriate connection pool
        if user_role == UserRole.TEACHER.value:
            if class_id in self.teacher_connections:
                self.teacher_connections[class_id].discard(websocket)
                if not self.teacher_connections[class_id]:
                    del self.teacher_connections[class_id]
        else:
            if class_id in self.student_connections:
                self.student_connections[class_id].discard(websocket)
                if not self.student_connections[class_id]:
                    del self.student_connections[class_id]
        
        # Remove connection info
        del self.connection_info[websocket]
    
    async def broadcast_attendance_update(self, update: AttendanceUpdate):
        """
        Broadcast attendance update to appropriate connections.
        
        Args:
            update: Attendance update information
        """
        class_id = update.class_session_id
        message = {
            "type": "attendance_updated",
            "data": update.dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Send to all teachers for this class (they can see everything)
        await self._broadcast_to_teachers(class_id, message)
        
        # Send limited info to students (only their own updates)
        student_message = {
            "type": "attendance_updated",
            "data": {
                "student_id": update.student_id,
                "new_status": update.new_status,
                "is_override": update.is_override,
                "timestamp": update.timestamp.isoformat()
            } if update.student_id else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self._broadcast_to_students(class_id, student_message, update.student_id)
    
    async def broadcast_stats_update(self, stats: ClassStatsUpdate):
        """Broadcast updated class statistics to teachers."""
        message = {
            "type": "stats_updated",
            "data": stats.dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Only teachers need full statistics
        await self._broadcast_to_teachers(stats.class_session_id, message)
    
    async def broadcast_bulk_operation(self, bulk_update: BulkOperationUpdate):
        """Broadcast bulk operation results to teachers."""
        message = {
            "type": "bulk_operation_completed",
            "data": bulk_update.dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Only teachers need bulk operation results
        await self._broadcast_to_teachers(bulk_update.class_session_id, message)
    
    async def broadcast_alert(self, alert: AlertUpdate):
        """Broadcast attendance alert to teachers."""
        message = {
            "type": "attendance_alert",
            "data": alert.dict(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Only teachers need alerts
        await self._broadcast_to_teachers(alert.class_session_id, message)
    
    async def notify_conflict(self, class_id: int, operation: str, user_id: int):
        """Notify about potential conflicts in concurrent operations."""
        message = {
            "type": "operation_conflict",
            "data": {
                "class_id": class_id,
                "operation": operation,
                "conflicting_user": user_id,
                "message": f"Another teacher is currently performing {operation}"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self._broadcast_to_teachers(class_id, message)
    
    def start_operation(self, operation_id: str, class_id: int, user_id: int, operation_type: str):
        """Track start of an operation to detect conflicts."""
        self.active_operations[operation_id] = {
            "class_id": class_id,
            "user_id": user_id,
            "operation_type": operation_type,
            "started_at": datetime.now(timezone.utc)
        }
    
    def end_operation(self, operation_id: str):
        """Mark operation as completed."""
        if operation_id in self.active_operations:
            del self.active_operations[operation_id]
    
    def check_operation_conflict(self, class_id: int, operation_type: str, user_id: int) -> bool:
        """Check if there's a conflicting operation in progress."""
        for op_id, op_info in self.active_operations.items():
            if (op_info["class_id"] == class_id and 
                op_info["operation_type"] == operation_type and 
                op_info["user_id"] != user_id):
                return True
        return False
    
    async def _broadcast_to_teachers(self, class_id: int, message: dict):
        """Broadcast message to all teacher connections for a class."""
        if class_id not in self.teacher_connections:
            return
        
        connections = self.teacher_connections[class_id].copy()
        failed_connections = []
        
        for websocket in connections:
            try:
                await self._send_to_websocket(websocket, message)
            except Exception:
                failed_connections.append(websocket)
        
        # Clean up failed connections
        for websocket in failed_connections:
            self.disconnect(websocket)
    
    async def _broadcast_to_students(self, class_id: int, message: dict, target_student_id: Optional[int] = None):
        """Broadcast message to student connections, optionally filtered by student ID."""
        if class_id not in self.student_connections:
            return
        
        connections = self.student_connections[class_id].copy()
        failed_connections = []
        
        for websocket in connections:
            try:
                connection_info = self.connection_info.get(websocket)
                if not connection_info:
                    continue
                
                # If target_student_id is specified, only send to that student
                if target_student_id and connection_info["user_id"] != target_student_id:
                    continue
                
                await self._send_to_websocket(websocket, message)
            except Exception:
                failed_connections.append(websocket)
        
        # Clean up failed connections
        for websocket in failed_connections:
            self.disconnect(websocket)
    
    async def _send_to_websocket(self, websocket: WebSocket, message: dict):
        """Send message to a specific WebSocket connection."""
        await websocket.send_text(json.dumps(message))
    
    def get_active_connections_count(self, class_id: int) -> Dict[str, int]:
        """Get number of active connections by role for a class."""
        return {
            "teachers": len(self.teacher_connections.get(class_id, set())),
            "students": len(self.student_connections.get(class_id, set()))
        }


class AttendanceUpdateService:
    """Service for managing real-time attendance updates and teacher dashboard features."""
    
    def __init__(self, connection_manager: AttendanceConnectionManager):
        self.connection_manager = connection_manager
    
    async def handle_attendance_change(
        self,
        class_session_id: int,
        student_id: int,
        student_name: str,
        old_status: Optional[AttendanceStatus],
        new_status: AttendanceStatus,
        updated_by: int,
        updated_by_name: str,
        reason: Optional[str] = None,
        is_override: bool = False,
        late_minutes: Optional[int] = None
    ):
        """Handle an attendance status change and broadcast updates."""
        
        # Create attendance update
        update = AttendanceUpdate(
            type="status_change",
            class_session_id=class_session_id,
            student_id=student_id,
            student_name=student_name,
            old_status=old_status,
            new_status=new_status,
            updated_by=updated_by,
            updated_by_name=updated_by_name,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
            is_override=is_override,
            late_minutes=late_minutes
        )
        
        # Broadcast the update
        await self.connection_manager.broadcast_attendance_update(update)
        
        # Update class statistics
        await self._update_and_broadcast_stats(class_session_id)
    
    async def handle_bulk_operation(
        self,
        class_session_id: int,
        operation: str,
        affected_students: List[int],
        updated_by: int,
        updated_by_name: str,
        processed_count: int,
        failed_count: int
    ):
        """Handle completion of bulk attendance operations."""
        
        bulk_update = BulkOperationUpdate(
            class_session_id=class_session_id,
            operation=operation,
            affected_students=affected_students,
            updated_by=updated_by,
            updated_by_name=updated_by_name,
            processed_count=processed_count,
            failed_count=failed_count,
            timestamp=datetime.now(timezone.utc)
        )
        
        await self.connection_manager.broadcast_bulk_operation(bulk_update)
        
        # Update class statistics after bulk operation
        await self._update_and_broadcast_stats(class_session_id)
    
    async def handle_attendance_alert(
        self,
        class_session_id: int,
        alert_type: str,
        severity: str,
        student_id: int,
        student_name: str,
        message: str,
        data: Dict[str, Any]
    ):
        """Handle attendance alerts and broadcast to teachers."""
        
        alert = AlertUpdate(
            class_session_id=class_session_id,
            alert_type=alert_type,
            severity=severity,
            student_id=student_id,
            student_name=student_name,
            message=message,
            data=data,
            timestamp=datetime.now(timezone.utc)
        )
        
        await self.connection_manager.broadcast_alert(alert)
    
    async def _update_and_broadcast_stats(self, class_session_id: int):
        """Calculate and broadcast updated class statistics."""
        try:
            # This would typically use the database to calculate stats
            # For now, we'll create a placeholder
            stats = ClassStatsUpdate(
                class_session_id=class_session_id,
                total_enrolled=25,  # Would be calculated from database
                checked_in_count=20,
                present_count=18,
                late_count=2,
                absent_count=5,
                excused_count=0,
                attendance_rate=0.8,
                last_updated=datetime.now(timezone.utc)
            )
            
            await self.connection_manager.broadcast_stats_update(stats)
        except Exception as e:
            print(f"Error updating stats: {e}")
    
    async def handle_websocket_messages(self, websocket: WebSocket, class_id: int):
        """
        Handle incoming WebSocket messages from clients.
        
        Args:
            websocket: WebSocket connection
            class_id: Associated class session ID
        """
        try:
            while True:
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                    await self._process_client_message(websocket, class_id, message)
                except json.JSONDecodeError:
                    await self.connection_manager._send_to_websocket(
                        websocket,
                        {
                            "type": "error",
                            "message": "Invalid JSON format"
                        }
                    )
                
        except WebSocketDisconnect:
            self.connection_manager.disconnect(websocket)
        except Exception as e:
            await self.connection_manager._send_to_websocket(
                websocket,
                {
                    "type": "error", 
                    "message": f"Connection error: {str(e)}"
                }
            )
            self.connection_manager.disconnect(websocket)
    
    async def _process_client_message(self, websocket: WebSocket, class_id: int, message: dict):
        """Process incoming client messages."""
        message_type = message.get("type")
        connection_info = self.connection_manager.connection_info.get(websocket)
        
        if not connection_info:
            return
        
        if message_type == "ping":
            await self.connection_manager._send_to_websocket(
                websocket,
                {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
            )
        elif message_type == "request_stats":
            await self._update_and_broadcast_stats(class_id)
        elif message_type == "start_operation":
            # Handle operation conflict detection
            operation_type = message.get("operation_type")
            operation_id = message.get("operation_id")
            user_id = connection_info["user_id"]
            
            if self.connection_manager.check_operation_conflict(class_id, operation_type, user_id):
                await self.connection_manager.notify_conflict(class_id, operation_type, user_id)
                await self.connection_manager._send_to_websocket(
                    websocket,
                    {
                        "type": "operation_blocked",
                        "message": f"Another teacher is currently performing {operation_type}"
                    }
                )
            else:
                self.connection_manager.start_operation(operation_id, class_id, user_id, operation_type)
                await self.connection_manager._send_to_websocket(
                    websocket,
                    {
                        "type": "operation_started",
                        "operation_id": operation_id
                    }
                )
        elif message_type == "end_operation":
            operation_id = message.get("operation_id")
            self.connection_manager.end_operation(operation_id)
        else:
            await self.connection_manager._send_to_websocket(
                websocket,
                {"type": "error", "message": f"Unknown message type: {message_type}"}
            )


# Global instances
attendance_connection_manager = AttendanceConnectionManager()
attendance_update_service = AttendanceUpdateService(attendance_connection_manager)


class AttendanceWebSocketManager:
    """Main WebSocket manager for attendance updates."""
    
    def __init__(self):
        self.connection_manager = attendance_connection_manager
        self.update_service = attendance_update_service
    
    async def websocket_endpoint(self, websocket: WebSocket, class_id: int, token: str = None):
        """
        FastAPI WebSocket endpoint handler for attendance updates.
        
        Args:
            websocket: WebSocket connection
            class_id: Class session ID
            token: JWT token for authentication (from query params)
        """
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        # Attempt connection with authentication
        connected = await self.connection_manager.connect(websocket, class_id, token)
        
        if connected:
            # Handle incoming messages
            await self.update_service.handle_websocket_messages(websocket, class_id)
    
    async def notify_attendance_change(
        self,
        class_session_id: int,
        student_id: int,
        student_name: str,
        old_status: Optional[AttendanceStatus],
        new_status: AttendanceStatus,
        updated_by: int,
        updated_by_name: str,
        reason: Optional[str] = None,
        is_override: bool = False,
        late_minutes: Optional[int] = None
    ):
        """Public method to notify of attendance changes."""
        await self.update_service.handle_attendance_change(
            class_session_id, student_id, student_name, old_status, new_status,
            updated_by, updated_by_name, reason, is_override, late_minutes
        )
    
    async def notify_bulk_operation(
        self,
        class_session_id: int,
        operation: str,
        affected_students: List[int],
        updated_by: int,
        updated_by_name: str,
        processed_count: int,
        failed_count: int
    ):
        """Public method to notify of bulk operations."""
        await self.update_service.handle_bulk_operation(
            class_session_id, operation, affected_students, updated_by,
            updated_by_name, processed_count, failed_count
        )
    
    async def notify_alert(
        self,
        class_session_id: int,
        alert_type: str,
        severity: str,
        student_id: int,
        student_name: str,
        message: str,
        data: Dict[str, Any]
    ):
        """Public method to notify of attendance alerts."""
        await self.update_service.handle_attendance_alert(
            class_session_id, alert_type, severity, student_id,
            student_name, message, data
        )


# Export manager instance
attendance_ws_manager = AttendanceWebSocketManager()