from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import List
import secrets


class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "Student Attendance System"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Security settings
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS settings
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://attendance.school.edu"
    ]
    
    # Database settings
    DATABASE_URL: str = "sqlite+aiosqlite:///./attendance.db"
    DATABASE_ECHO: bool = False
    
    # Redis settings (optional for caching)
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_ENABLED: bool = False
    
    # Application URLs
    BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    
    # QR Code settings
    QR_CODE_SIZE: int = 10
    QR_CODE_BORDER: int = 4
    
    # Push Notification settings
    # Firebase Cloud Messaging (FCM)
    FCM_SERVICE_ACCOUNT_PATH: str = ""
    
    # Web Push (VAPID)
    WEB_PUSH_VAPID_PUBLIC_KEY: str = ""
    WEB_PUSH_VAPID_PRIVATE_KEY: str = ""
    WEB_PUSH_VAPID_SUBJECT: str = "mailto:admin@attendance.school.edu"
    
    # Notification settings
    NOTIFICATION_BATCH_INTERVAL_MINUTES: int = 30
    NOTIFICATION_MAX_BATCH_SIZE: int = 5
    NOTIFICATION_CLEANUP_DAYS: int = 30
    
    @validator("ALLOWED_ORIGINS", pre=True)
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    @validator("DATABASE_URL")
    def validate_database_url(cls, v):
        if not v:
            raise ValueError("DATABASE_URL is required")
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()