"""
Core WebSocket infrastructure for production-scale real-time communication.

This module provides:
- Connection pooling and resource management
- Authentication middleware
- Message routing and event handling
- Health monitoring and metrics
- Performance optimization for 1000+ concurrent connections
"""
import asyncio
import logging
import time
import weakref
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
try:
    import orjson
    # Use orjson for better performance
    json_dumps = lambda x: orjson.dumps(x).decode()
    json_loads = orjson.loads
except ImportError:
    import json
    # Fallback to standard json
    json_dumps = json.dumps
    json_loads = json.loads
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from fastapi import WebSocket, WebSocketDisconnect, status
from ..core.security import jwt_manager


# Metrics for monitoring
if PROMETHEUS_AVAILABLE:
    WEBSOCKET_CONNECTIONS = Gauge('websocket_connections_total', 'Total WebSocket connections', ['status'])
    WEBSOCKET_MESSAGES = Counter('websocket_messages_total', 'Total WebSocket messages', ['type', 'direction'])
    WEBSOCKET_LATENCY = Histogram('websocket_latency_seconds', 'WebSocket message latency')
    WEBSOCKET_ERRORS = Counter('websocket_errors_total', 'WebSocket errors', ['error_type'])
else:
    # Mock metrics when prometheus is not available
    class MockMetric:
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
    
    WEBSOCKET_CONNECTIONS = MockMetric()
    WEBSOCKET_MESSAGES = MockMetric()
    WEBSOCKET_LATENCY = MockMetric()
    WEBSOCKET_ERRORS = MockMetric()

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    CONNECTING = "connecting"
    CONNECTED = "connected" 
    AUTHENTICATED = "authenticated"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class MessageType(Enum):
    """WebSocket message types."""
    # Connection management
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    PING = "ping"
    PONG = "pong"
    
    # Authentication
    AUTH = "auth"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILED = "auth_failed"
    
    # Real-time events
    STUDENT_JOINED = "student_joined"
    STUDENT_LEFT = "student_left"
    ATTENDANCE_UPDATE = "attendance_update"
    SESSION_UPDATE = "session_update"
    SESSION_ENDED = "session_ended"
    STATS_UPDATE = "stats_update"
    
    # System events
    ERROR = "error"
    SYSTEM_NOTIFICATION = "system_notification"


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection."""
    websocket: WebSocket
    connection_id: str
    class_id: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[str] = None  # teacher, student, admin
    state: ConnectionState = ConnectionState.CONNECTING
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_ping: Optional[datetime] = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    error_count: int = 0


class ConnectionPool:
    """Manages WebSocket connections with resource pooling and cleanup."""
    
    def __init__(self, max_connections_per_class: int = 100):
        self.max_connections_per_class = max_connections_per_class
        
        # Connection storage
        self._connections: Dict[str, ConnectionInfo] = {}
        self._class_connections: Dict[str, Set[str]] = defaultdict(set)
        self._user_connections: Dict[str, Set[str]] = defaultdict(set)
        
        # Weak references for automatic cleanup
        self._websocket_refs: Dict[str, weakref.ref] = {}
        
        # Performance tracking
        self._connection_stats = {
            'total_connections': 0,
            'peak_connections': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'errors': 0
        }
        
        # Start background tasks
        self._cleanup_task = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def _periodic_cleanup(self):
        """Periodically clean up stale connections."""
        while True:
            try:
                await asyncio.sleep(30)  # Cleanup every 30 seconds
                await self._cleanup_stale_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
    
    async def _cleanup_stale_connections(self):
        """Remove stale and disconnected connections."""
        current_time = datetime.now(timezone.utc)
        stale_connections = []
        
        for conn_id, conn_info in self._connections.items():
            # Check for stale connections (no activity for 5 minutes)
            if (current_time - conn_info.last_activity).total_seconds() > 300:
                stale_connections.append(conn_id)
            
            # Check if websocket is still alive
            websocket_ref = self._websocket_refs.get(conn_id)
            if websocket_ref and websocket_ref() is None:
                stale_connections.append(conn_id)
        
        for conn_id in stale_connections:
            await self._remove_connection(conn_id)
    
    async def add_connection(self, websocket: WebSocket, connection_id: str) -> ConnectionInfo:
        """Add a new WebSocket connection to the pool."""
        if len(self._connections) >= 10000:  # Global connection limit
            raise RuntimeError("Maximum global connections exceeded")
        
        conn_info = ConnectionInfo(
            websocket=websocket,
            connection_id=connection_id
        )
        
        self._connections[connection_id] = conn_info
        self._websocket_refs[connection_id] = weakref.ref(websocket)
        
        # Update stats
        self._connection_stats['total_connections'] += 1
        current_count = len(self._connections)
        if current_count > self._connection_stats['peak_connections']:
            self._connection_stats['peak_connections'] = current_count
        
        # Update metrics
        WEBSOCKET_CONNECTIONS.labels(status='connected').inc()
        
        logger.info(f"Added connection {connection_id}, total: {len(self._connections)}")
        return conn_info
    
    async def authenticate_connection(
        self, 
        connection_id: str, 
        class_id: str, 
        user_id: str, 
        user_type: str
    ) -> bool:
        """Authenticate a connection and assign it to a class."""
        if connection_id not in self._connections:
            return False
        
        conn_info = self._connections[connection_id]
        
        # Check class connection limits
        if len(self._class_connections[class_id]) >= self.max_connections_per_class:
            logger.warning(f"Class {class_id} exceeded connection limit")
            return False
        
        # Update connection info
        conn_info.class_id = class_id
        conn_info.user_id = user_id
        conn_info.user_type = user_type
        conn_info.state = ConnectionState.AUTHENTICATED
        
        # Add to indexes
        self._class_connections[class_id].add(connection_id)
        self._user_connections[user_id].add(connection_id)
        
        logger.info(f"Authenticated connection {connection_id} for user {user_id} in class {class_id}")
        return True
    
    async def remove_connection(self, connection_id: str):
        """Remove a connection from the pool."""
        await self._remove_connection(connection_id)
    
    async def _remove_connection(self, connection_id: str):
        """Internal method to remove a connection."""
        if connection_id not in self._connections:
            return
        
        conn_info = self._connections[connection_id]
        
        # Remove from indexes
        if conn_info.class_id:
            self._class_connections[conn_info.class_id].discard(connection_id)
            if not self._class_connections[conn_info.class_id]:
                del self._class_connections[conn_info.class_id]
        
        if conn_info.user_id:
            self._user_connections[conn_info.user_id].discard(connection_id)
            if not self._user_connections[conn_info.user_id]:
                del self._user_connections[conn_info.user_id]
        
        # Remove from main storage
        del self._connections[connection_id]
        self._websocket_refs.pop(connection_id, None)
        
        # Update metrics
        WEBSOCKET_CONNECTIONS.labels(status='connected').dec()
        
        logger.info(f"Removed connection {connection_id}, total: {len(self._connections)}")
    
    def get_connection(self, connection_id: str) -> Optional[ConnectionInfo]:
        """Get connection info by ID."""
        return self._connections.get(connection_id)
    
    def get_class_connections(self, class_id: str) -> List[ConnectionInfo]:
        """Get all connections for a class."""
        connection_ids = self._class_connections.get(class_id, set())
        return [self._connections[conn_id] for conn_id in connection_ids if conn_id in self._connections]
    
    def get_user_connections(self, user_id: str) -> List[ConnectionInfo]:
        """Get all connections for a user."""
        connection_ids = self._user_connections.get(user_id, set())
        return [self._connections[conn_id] for conn_id in connection_ids if conn_id in self._connections]
    
    def update_activity(self, connection_id: str):
        """Update last activity timestamp for a connection."""
        if connection_id in self._connections:
            self._connections[connection_id].last_activity = datetime.now(timezone.utc)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics."""
        return {
            **self._connection_stats,
            'active_connections': len(self._connections),
            'active_classes': len(self._class_connections),
            'active_users': len(self._user_connections),
            'memory_usage': psutil.Process().memory_info().rss / 1024 / 1024 if PSUTIL_AVAILABLE else 0,  # MB
        }
    
    async def shutdown(self):
        """Shutdown the connection pool and cleanup resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections
        for conn_info in self._connections.values():
            try:
                if conn_info.websocket.client_state.name != 'DISCONNECTED':
                    await conn_info.websocket.close()
            except Exception as e:
                logger.error(f"Error closing websocket: {e}")
        
        self._connections.clear()
        self._class_connections.clear()
        self._user_connections.clear()
        self._websocket_refs.clear()


class MessageRouter:
    """Routes WebSocket messages to appropriate handlers."""
    
    def __init__(self):
        self._handlers: Dict[MessageType, List[Callable]] = defaultdict(list)
        self._middleware: List[Callable] = []
    
    def register_handler(self, message_type: MessageType, handler: Callable):
        """Register a message handler for a specific message type."""
        self._handlers[message_type].append(handler)
    
    def register_middleware(self, middleware: Callable):
        """Register middleware that runs before message handlers."""
        self._middleware.append(middleware)
    
    async def route_message(
        self, 
        message_type: MessageType, 
        message_data: Dict[str, Any],
        connection_info: ConnectionInfo
    ):
        """Route a message to its handlers."""
        try:
            # Run middleware
            for middleware in self._middleware:
                result = await middleware(message_type, message_data, connection_info)
                if result is False:  # Middleware can block message processing
                    return
            
            # Run handlers
            handlers = self._handlers.get(message_type, [])
            if not handlers:
                logger.warning(f"No handlers registered for message type: {message_type}")
                return
            
            for handler in handlers:
                try:
                    await handler(message_data, connection_info)
                except Exception as e:
                    logger.error(f"Error in message handler {handler.__name__}: {e}")
                    WEBSOCKET_ERRORS.labels(error_type='handler_error').inc()
        
        except Exception as e:
            logger.error(f"Error routing message {message_type}: {e}")
            WEBSOCKET_ERRORS.labels(error_type='routing_error').inc()


class WebSocketServer:
    """Production-grade WebSocket server with comprehensive features."""
    
    def __init__(self):
        self.connection_pool = ConnectionPool()
        self.message_router = MessageRouter()
        
        # Performance tracking
        self.start_time = datetime.now(timezone.utc)
        
        # Register default handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default message handlers."""
        self.message_router.register_handler(MessageType.PING, self._handle_ping)
        self.message_router.register_handler(MessageType.AUTH, self._handle_auth)
        self.message_router.register_middleware(self._auth_middleware)
    
    async def _auth_middleware(
        self, 
        message_type: MessageType, 
        message_data: Dict[str, Any],
        connection_info: ConnectionInfo
    ) -> bool:
        """Authentication middleware."""
        # Allow auth and ping messages without authentication
        if message_type in [MessageType.AUTH, MessageType.PING, MessageType.CONNECT]:
            return True
        
        # Check if connection is authenticated
        if connection_info.state != ConnectionState.AUTHENTICATED:
            await self._send_error(connection_info, "Authentication required")
            return False
        
        return True
    
    async def _handle_ping(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle ping messages."""
        connection_info.last_ping = datetime.now(timezone.utc)
        await self._send_message(connection_info, MessageType.PONG, {
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    async def _handle_auth(self, message_data: Dict[str, Any], connection_info: ConnectionInfo):
        """Handle authentication messages."""
        try:
            token = message_data.get('token')
            class_id = message_data.get('class_id')
            
            if not token or not class_id:
                await self._send_message(connection_info, MessageType.AUTH_FAILED, {
                    "error": "Missing token or class_id"
                })
                return
            
            # Verify JWT token
            payload = jwt_manager.verify_class_session_token(token)
            
            # Verify class_id matches token
            if payload.get("class_id") != class_id:
                await self._send_message(connection_info, MessageType.AUTH_FAILED, {
                    "error": "Invalid class_id for token"
                })
                return
            
            # Authenticate connection
            user_id = payload.get("teacher_id", payload.get("user_id", "unknown"))
            user_type = payload.get("user_type", "teacher")
            
            success = await self.connection_pool.authenticate_connection(
                connection_info.connection_id,
                class_id,
                user_id,
                user_type
            )
            
            if success:
                await self._send_message(connection_info, MessageType.AUTH_SUCCESS, {
                    "class_id": class_id,
                    "user_id": user_id,
                    "user_type": user_type
                })
            else:
                await self._send_message(connection_info, MessageType.AUTH_FAILED, {
                    "error": "Authentication failed"
                })
        
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await self._send_message(connection_info, MessageType.AUTH_FAILED, {
                "error": "Authentication error"
            })
    
    async def connect(self, websocket: WebSocket, connection_id: str) -> bool:
        """Handle new WebSocket connection."""
        try:
            await websocket.accept()
            
            conn_info = await self.connection_pool.add_connection(websocket, connection_id)
            conn_info.state = ConnectionState.CONNECTED
            
            # Send connection confirmation
            await self._send_message(conn_info, MessageType.CONNECT, {
                "connection_id": connection_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            logger.info(f"WebSocket connected: {connection_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting WebSocket {connection_id}: {e}")
            WEBSOCKET_ERRORS.labels(error_type='connection_error').inc()
            return False
    
    async def disconnect(self, connection_id: str):
        """Handle WebSocket disconnection."""
        await self.connection_pool.remove_connection(connection_id)
        logger.info(f"WebSocket disconnected: {connection_id}")
    
    async def handle_message(self, connection_id: str, raw_message: str):
        """Handle incoming WebSocket message."""
        start_time = time.time()
        
        try:
            # Parse message
            message = json_loads(raw_message)
            message_type = MessageType(message.get('type', 'unknown'))
            message_data = message.get('data', {})
            
            # Get connection info
            conn_info = self.connection_pool.get_connection(connection_id)
            if not conn_info:
                logger.warning(f"Message received for unknown connection: {connection_id}")
                return
            
            # Update activity
            self.connection_pool.update_activity(connection_id)
            conn_info.message_count += 1
            
            # Route message
            await self.message_router.route_message(message_type, message_data, conn_info)
            
            # Update metrics
            WEBSOCKET_MESSAGES.labels(type=message_type.value, direction='received').inc()
            WEBSOCKET_LATENCY.observe(time.time() - start_time)
        
        except Exception as e:
            logger.error(f"Error handling message from {connection_id}: {e}")
            WEBSOCKET_ERRORS.labels(error_type='message_error').inc()
            
            # Try to send error response
            conn_info = self.connection_pool.get_connection(connection_id)
            if conn_info:
                conn_info.error_count += 1
                await self._send_error(conn_info, f"Message processing error: {str(e)}")
    
    async def broadcast_to_class(self, class_id: str, message_type: MessageType, data: Dict[str, Any]):
        """Broadcast a message to all connections in a class."""
        connections = self.connection_pool.get_class_connections(class_id)
        if not connections:
            return
        
        # Prepare message
        message = {
            "type": message_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data
        }
        
        # Send to all connections concurrently
        tasks = [
            self._send_raw_message(conn_info, message)
            for conn_info in connections
            if conn_info.state == ConnectionState.AUTHENTICATED
        ]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            WEBSOCKET_MESSAGES.labels(type=message_type.value, direction='sent').inc(len(tasks))
    
    async def send_to_user(self, user_id: str, message_type: MessageType, data: Dict[str, Any]):
        """Send a message to all connections for a specific user."""
        connections = self.connection_pool.get_user_connections(user_id)
        if not connections:
            return
        
        tasks = [
            self._send_message(conn_info, message_type, data)
            for conn_info in connections
            if conn_info.state == ConnectionState.AUTHENTICATED
        ]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_message(
        self, 
        conn_info: ConnectionInfo, 
        message_type: MessageType, 
        data: Dict[str, Any]
    ):
        """Send a typed message to a connection."""
        message = {
            "type": message_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data
        }
        await self._send_raw_message(conn_info, message)
    
    async def _send_raw_message(self, conn_info: ConnectionInfo, message: Dict[str, Any]):
        """Send a raw message to a connection."""
        try:
            if conn_info.websocket.client_state.name == 'DISCONNECTED':
                await self.connection_pool.remove_connection(conn_info.connection_id)
                return
            
            json_data = json_dumps(message)
            await conn_info.websocket.send_text(json_data)
            
        except Exception as e:
            logger.error(f"Error sending message to {conn_info.connection_id}: {e}")
            await self.connection_pool.remove_connection(conn_info.connection_id)
    
    async def _send_error(self, conn_info: ConnectionInfo, error_message: str):
        """Send an error message to a connection."""
        await self._send_message(conn_info, MessageType.ERROR, {
            "error": error_message
        })
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get server health status and metrics."""
        stats = self.connection_pool.get_stats()
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        return {
            "status": "healthy",
            "uptime_seconds": uptime,
            "connections": {
                "active": stats['active_connections'],
                "peak": stats['peak_connections'],
                "total_served": stats['total_connections']
            },
            "classes": {
                "active": stats['active_classes']
            },
            "users": {
                "active": stats['active_users']
            },
            "messages": {
                "sent": stats['messages_sent'],
                "received": stats['messages_received']
            },
            "resources": {
                "memory_mb": stats['memory_usage'],
                "cpu_percent": psutil.Process().cpu_percent() if PSUTIL_AVAILABLE else 0
            },
            "errors": stats['errors']
        }
    
    async def shutdown(self):
        """Shutdown the WebSocket server."""
        logger.info("Shutting down WebSocket server")
        await self.connection_pool.shutdown()


# Global WebSocket server instance
websocket_server = WebSocketServer()