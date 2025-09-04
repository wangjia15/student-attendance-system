from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import classes, auth, attendance
from app.websocket.live_updates import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    await init_db()
    yield
    # Cleanup if needed
    pass


app = FastAPI(
    title="Student Attendance System API",
    description="Real-time student attendance tracking system",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(classes.router, prefix="/api/v1/classes", tags=["classes"])
app.include_router(attendance.router, prefix="/api/v1/attendance", tags=["attendance"])

# WebSocket endpoint
app.websocket("/ws/{class_id}")(manager.websocket_endpoint)


@app.get("/")
async def root():
    return {"message": "Student Attendance System API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


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