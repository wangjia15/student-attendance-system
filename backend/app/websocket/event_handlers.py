"""
WebSocket event handlers for real-time attendance system.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from ..core.websocket import websocket_server, MessageType, ConnectionInfo

logger = logging.getLogger(__name__)


class StudentJoinEvent(BaseModel):
    """Student join event data."""
    student_id: int
    student_name: str
    class_id: str
    session_id: str
    joined_at: datetime
    join_method: str  # "qr", "code", "link"
    location: Optional[str] = None
    device_info: Optional[str] = None


class AttendanceUpdateEvent(BaseModel):
    """Attendance update event data."""
    class_id: str
    session_id: str
    student_id: int
    status: str  # "present", "late", "absent"
    timestamp: datetime
    updated_by: str


class SessionStatsEvent(BaseModel):
    """Session statistics event data."""
    class_id: str
    session_id: str
    total_students: int
    present_count: int
    late_count: int
    absent_count: int
    recent_joins: List[Dict[str, Any]]
    attendance_rate: float
    time_remaining_minutes: Optional[int] = None


class AttendanceEventHandler:
    """Handles real-time attendance events."""
    
    def __init__(self):
        # Register event handlers with the WebSocket server
        self._register_handlers()
    
    def _register_handlers(self):
        """Register event handlers with the message router."""
        router = websocket_server.message_router
        
        # Real-time event handlers
        router.register_handler(MessageType.STUDENT_JOINED, self._handle_student_joined_message)
        router.register_handler(MessageType.ATTENDANCE_UPDATE, self._handle_attendance_update_message)
        router.register_handler(MessageType.SESSION_UPDATE, self._handle_session_update_message)
        router.register_handler(MessageType.STATS_UPDATE, self._handle_stats_request)
    
    async def student_joined(self, event: StudentJoinEvent):
        """Handle student join event and broadcast to teachers."""
        try:
            # Prepare event data for broadcast
            event_data = {
                "student_id": event.student_id,
                "student_name": event.student_name,
                "session_id": event.session_id,
                "joined_at": event.joined_at.isoformat(),
                "join_method": event.join_method,
                "location": event.location,
                "device_info": event.device_info
            }
            
            # Broadcast to all teachers in the class
            await websocket_server.broadcast_to_class(
                event.class_id,
                MessageType.STUDENT_JOINED,
                event_data
            )
            
            # Update session statistics and broadcast
            await self._update_and_broadcast_stats(event.class_id, event.session_id)
            
            logger.info(f"Student {event.student_name} joined class {event.class_id}")
            
        except Exception as e:
            logger.error(f"Error handling student join event: {e}")
    
    async def attendance_updated(self, event: AttendanceUpdateEvent):
        """Handle attendance status update and broadcast to teachers."""
        try:
            event_data = {
                "session_id": event.session_id,
                "student_id": event.student_id,
                "status": event.status,
                "timestamp": event.timestamp.isoformat(),
                "updated_by": event.updated_by
            }
            
            # Broadcast to all teachers in the class
            await websocket_server.broadcast_to_class(
                event.class_id,
                MessageType.ATTENDANCE_UPDATE,
                event_data
            )
            
            # Update session statistics and broadcast
            await self._update_and_broadcast_stats(event.class_id, event.session_id)
            
            logger.info(f"Attendance updated for student {event.student_id} in class {event.class_id}")
            
        except Exception as e:
            logger.error(f"Error handling attendance update event: {e}")
    
    async def session_updated(self, class_id: str, session_id: str, update_data: Dict[str, Any]):
        """Handle session update events (e.g., new QR codes, time extensions)."""
        try:
            event_data = {
                "session_id": session_id,
                "updates": update_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Broadcast to all connected users in the class
            await websocket_server.broadcast_to_class(
                class_id,
                MessageType.SESSION_UPDATE,
                event_data
            )
            
            logger.info(f"Session updated for class {class_id}: {update_data}")
            
        except Exception as e:
            logger.error(f"Error handling session update event: {e}")
    
    async def session_ended(self, class_id: str, session_id: str, final_stats: Dict[str, Any]):
        """Handle session end event."""
        try:
            event_data = {
                "session_id": session_id,
                "final_stats": final_stats,
                "ended_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Broadcast to all connected users in the class
            await websocket_server.broadcast_to_class(
                class_id,
                MessageType.SESSION_ENDED,
                event_data
            )
            
            logger.info(f"Session ended for class {class_id}")
            
        except Exception as e:
            logger.error(f"Error handling session end event: {e}")
    
    async def _handle_student_joined_message(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle incoming student joined message from WebSocket."""
        try:
            # This would typically come from the attendance service
            # For now, we'll just acknowledge the message
            pass
        except Exception as e:
            logger.error(f"Error handling student joined message: {e}")
    
    async def _handle_attendance_update_message(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle incoming attendance update message from WebSocket."""
        try:
            # This would typically trigger database updates
            # For now, we'll just acknowledge the message
            pass
        except Exception as e:
            logger.error(f"Error handling attendance update message: {e}")
    
    async def _handle_session_update_message(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle incoming session update message from WebSocket."""
        try:
            # This would typically update session settings
            # For now, we'll just acknowledge the message
            pass
        except Exception as e:
            logger.error(f"Error handling session update message: {e}")
    
    async def _handle_stats_request(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle request for current session statistics."""
        try:
            class_id = connection_info.class_id
            if not class_id:
                return
            
            session_id = message_data.get('session_id')
            if not session_id:
                return
            
            # Get current session statistics
            stats = await self._get_session_stats(class_id, session_id)
            
            # Send stats to requesting connection
            await websocket_server._send_message(
                connection_info,
                MessageType.STATS_UPDATE,
                stats
            )
            
        except Exception as e:
            logger.error(f"Error handling stats request: {e}")
    
    async def _update_and_broadcast_stats(self, class_id: str, session_id: str):
        """Update and broadcast session statistics to all connected users."""
        try:
            stats = await self._get_session_stats(class_id, session_id)
            
            await websocket_server.broadcast_to_class(
                class_id,
                MessageType.STATS_UPDATE,
                stats
            )
        except Exception as e:
            logger.error(f"Error updating and broadcasting stats: {e}")
    
    async def _get_session_stats(self, class_id: str, session_id: str) -> Dict[str, Any]:
        """Get current session statistics."""
        try:
            # This would typically query the database for real statistics
            # For now, we'll return placeholder data
            return {
                "class_id": class_id,
                "session_id": session_id,
                "total_students": 25,
                "present_count": 18,
                "late_count": 3,
                "absent_count": 4,
                "attendance_rate": 72.0,
                "time_remaining_minutes": 15,
                "recent_joins": [
                    {
                        "student_name": "John Doe",
                        "joined_at": datetime.now(timezone.utc).isoformat(),
                        "join_method": "qr"
                    }
                ],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting session stats: {e}")
            return {}


class SystemEventHandler:
    """Handles system-level events and notifications."""
    
    def __init__(self):
        self._register_handlers()
    
    def _register_handlers(self):
        """Register system event handlers."""
        router = websocket_server.message_router
        router.register_handler(MessageType.SYSTEM_NOTIFICATION, self._handle_system_notification)
    
    async def send_system_notification(self, class_id: str, notification: Dict[str, Any]):
        """Send a system notification to all users in a class."""
        try:
            await websocket_server.broadcast_to_class(
                class_id,
                MessageType.SYSTEM_NOTIFICATION,
                notification
            )
            logger.info(f"Sent system notification to class {class_id}: {notification.get('message', '')}")
        except Exception as e:
            logger.error(f"Error sending system notification: {e}")
    
    async def _handle_system_notification(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle system notification messages."""
        # System notifications are typically one-way (server to client)
        pass


class HealthMonitorHandler:
    """Handles health monitoring and diagnostic events."""
    
    def __init__(self):
        self._register_handlers()
    
    def _register_handlers(self):
        """Register health monitoring handlers."""
        # Health monitoring is typically handled via HTTP endpoints
        # but we can also provide WebSocket-based monitoring
        pass
    
    async def broadcast_health_alert(self, alert_data: Dict[str, Any]):
        """Broadcast a health alert to system administrators."""
        try:
            # This would typically send to admin users only
            # For now, we'll log the alert
            logger.warning(f"Health alert: {alert_data}")
        except Exception as e:
            logger.error(f"Error broadcasting health alert: {e}")


# Global event handler instances
attendance_event_handler = AttendanceEventHandler()
system_event_handler = SystemEventHandler()
health_monitor_handler = HealthMonitorHandler()