from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import uvicorn
import logging
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db, get_db
from app.core.auth import get_current_user
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
# from app.core.websocket import websocket_server
from app.api.v1 import classes, auth, attendance, admin  # Admin module for system management
# from app.api.v1 import sis  # Temporarily disabled due to missing integration modules
from app.websocket.live_updates import manager
from app.websocket.event_handlers import attendance_event_handler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    await init_db()
    
    # Initialize WebSocket server
    # Event handlers are automatically registered in their __init__
    
    yield
    
    # Cleanup WebSocket server
    # await websocket_server.shutdown()


app = FastAPI(
    title="Student Attendance System API",
    description="Real-time student attendance tracking system",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for debugging
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(classes.router, prefix="/api/v1/classes", tags=["classes"])
app.include_router(attendance.router, prefix="/api/v1/attendance", tags=["attendance"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
# app.include_router(sis.router, prefix="/api/v1/sis", tags=["sis-integration"])  # Temporarily disabled

# WebSocket endpoints
app.websocket("/ws/{class_id}")(manager.websocket_endpoint)  # Legacy endpoint

# New production WebSocket endpoint with enhanced features
# @app.websocket("/ws/v2/{connection_id}")
# async def websocket_endpoint_v2(websocket: WebSocket, connection_id: str):
#     """Enhanced WebSocket endpoint with production features."""
#     success = await websocket_server.connect(websocket, connection_id)
#     
#     if success:
#         try:
#             while True:
#                 message = await websocket.receive_text()
#                 await websocket_server.handle_message(connection_id, message)
#         except WebSocketDisconnect:
#             await websocket_server.disconnect(connection_id)
#         except Exception as e:
#             logger.error(f"WebSocket error for {connection_id}: {e}")
#             await websocket_server.disconnect(connection_id)


@app.get("/")
async def root():
    return {"message": "Student Attendance System API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/health/websocket")
async def websocket_health():
    """Get WebSocket server health and metrics."""
    return {"status": "websocket_disabled"}


# Simple test endpoint 
@app.get("/test-simple")
async def test_simple():
    return {"message": "Simple endpoint works"}

# Temporary endpoint removed - using attendance router instead


@app.get("/metrics")
async def metrics():
    """Get system metrics for monitoring."""
    import psutil
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    # Return Prometheus metrics
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "status_code": 500}
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug"
    )