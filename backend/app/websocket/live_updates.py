"""
WebSocket handler for real-time class session updates.
"""
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from ..core.security import jwt_manager
# Remove non-existent imports - we'll define these as Pydantic models below


class StudentJoin(BaseModel):
    """Model for student join events."""
    student_id: int
    student_name: str
    class_id: str
    joined_at: datetime
    join_method: str  # "qr" or "code"


class LiveSessionStats(BaseModel):
    """Model for live session statistics."""
    class_id: str
    class_name: str
    status: str
    time_remaining_minutes: int
    total_joins: int
    unique_students: int
    recent_joins: List[str]


class ConnectionManager:
    """Manages WebSocket connections for class sessions."""
    
    def __init__(self):
        # Dictionary of class_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Dictionary of WebSocket -> class_id for cleanup
        self.connection_class_map: Dict[WebSocket, str] = {}
    
    async def connect(self, websocket: WebSocket, class_id: str, token: str):
        """
        Connect a WebSocket to a class session with authentication.
        
        Args:
            websocket: WebSocket connection
            class_id: Class session ID
            token: JWT token for authentication
        """
        try:
            # Verify JWT token
            payload = jwt_manager.verify_class_session_token(token)
            
            # Verify class_id matches token
            if payload.get("class_id") != class_id:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return False
            
            # Accept connection
            await websocket.accept()
            
            # Add to active connections
            if class_id not in self.active_connections:
                self.active_connections[class_id] = set()
            
            self.active_connections[class_id].add(websocket)
            self.connection_class_map[websocket] = class_id
            
            # Send initial connection confirmation
            await self._send_to_websocket(websocket, {
                "type": "connection_confirmed",
                "class_id": class_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Connected to live updates"
            })
            
            return True
            
        except Exception as e:
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return False
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection and cleanup."""
        if websocket in self.connection_class_map:
            class_id = self.connection_class_map[websocket]
            
            # Remove from active connections
            if class_id in self.active_connections:
                self.active_connections[class_id].discard(websocket)
                
                # Clean up empty class sessions
                if not self.active_connections[class_id]:
                    del self.active_connections[class_id]
            
            # Remove from connection map
            del self.connection_class_map[websocket]
    
    async def broadcast_to_class(self, class_id: str, message: dict):
        """
        Broadcast message to all connections for a specific class.
        
        Args:
            class_id: Class session ID
            message: Message to broadcast
        """
        if class_id not in self.active_connections:
            return
        
        # Get copy of connections to avoid modification during iteration
        connections = self.active_connections[class_id].copy()
        
        # Send to all connections, removing failed ones
        failed_connections = []
        for websocket in connections:
            try:
                await self._send_to_websocket(websocket, message)
            except Exception:
                failed_connections.append(websocket)
        
        # Clean up failed connections
        for websocket in failed_connections:
            self.disconnect(websocket)
    
    async def _send_to_websocket(self, websocket: WebSocket, message: dict):
        """Send message to a specific WebSocket connection."""
        await websocket.send_text(json.dumps(message))
    
    def get_active_connections_count(self, class_id: str) -> int:
        """Get number of active WebSocket connections for a class."""
        return len(self.active_connections.get(class_id, set()))


class LiveUpdateService:
    """Service for managing real-time updates during class sessions."""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        # In-memory store for demo (use Redis in production)
        self.session_data: Dict[str, dict] = {}
    
    async def student_joined(self, student_join: StudentJoin):
        """
        Handle student join event and broadcast to connected teachers.
        
        Args:
            student_join: Student join information
        """
        message = {
            "type": "student_joined",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "student_id": student_join.student_id,
                "student_name": student_join.student_name,
                "joined_at": student_join.joined_at.isoformat(),
                "join_method": student_join.join_method
            }
        }
        
        await self.connection_manager.broadcast_to_class(
            student_join.class_id, 
            message
        )
        
        # Update session statistics
        await self._update_session_stats(student_join.class_id)
    
    async def session_updated(self, class_id: str, update_data: dict):
        """
        Handle session update events (e.g., regenerated codes).
        
        Args:
            class_id: Class session ID
            update_data: Updated session information
        """
        message = {
            "type": "session_updated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "class_id": class_id,
            "data": update_data
        }
        
        await self.connection_manager.broadcast_to_class(class_id, message)
    
    async def session_ended(self, class_id: str, final_stats: dict):
        """
        Handle session end event.
        
        Args:
            class_id: Class session ID
            final_stats: Final session statistics
        """
        message = {
            "type": "session_ended",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "class_id": class_id,
            "data": final_stats
        }
        
        await self.connection_manager.broadcast_to_class(class_id, message)
    
    async def broadcast_stats_update(self, class_id: str, stats: LiveSessionStats):
        """
        Broadcast updated session statistics.
        
        Args:
            class_id: Class session ID
            stats: Current session statistics
        """
        message = {
            "type": "stats_update",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "class_id": class_id,
            "data": stats.dict()
        }
        
        await self.connection_manager.broadcast_to_class(class_id, message)
    
    async def _update_session_stats(self, class_id: str):
        """Update and broadcast session statistics."""
        # This would typically fetch from database
        # For now, we'll create placeholder stats
        stats = LiveSessionStats(
            class_id=class_id,
            class_name="Sample Class",
            status="active",
            time_remaining_minutes=25,
            total_joins=1,
            unique_students=1,
            recent_joins=[]
        )
        
        await self.broadcast_stats_update(class_id, stats)
    
    async def handle_websocket_messages(self, websocket: WebSocket, class_id: str):
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
    
    async def _process_client_message(self, websocket: WebSocket, class_id: str, message: dict):
        """Process incoming client messages."""
        message_type = message.get("type")
        
        if message_type == "ping":
            await self.connection_manager._send_to_websocket(
                websocket,
                {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
            )
        elif message_type == "request_stats":
            # Send current session statistics
            await self._update_session_stats(class_id)
        else:
            await self.connection_manager._send_to_websocket(
                websocket,
                {"type": "error", "message": f"Unknown message type: {message_type}"}
            )


# Global instances
connection_manager = ConnectionManager()
live_update_service = LiveUpdateService(connection_manager)


class WebSocketManager:
    """Main WebSocket manager for FastAPI integration."""
    
    def __init__(self):
        self.connection_manager = connection_manager
        self.live_service = live_update_service
    
    async def websocket_endpoint(self, websocket: WebSocket, class_id: str, token: str = None):
        """
        FastAPI WebSocket endpoint handler.
        
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
            await self.live_service.handle_websocket_messages(websocket, class_id)


# Export manager instance for main.py
manager = WebSocketManager()