@echo off
setlocal enabledelayedexpansion

REM Student Attendance System - Backend Development Setup Script (Windows)
REM This script sets up the development environment using uv

echo.
echo 🚀 Student Attendance System - Backend Setup
echo ============================================
echo.

REM Check if uv is installed
where uv >nul 2>nul
if errorlevel 1 (
    echo ❌ uv is not installed
    echo 💡 Install uv with PowerShell: irm https://astral.sh/uv/install.ps1 ^| iex
    echo    Or visit: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo ✅ uv is installed

REM Check Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set python_version=%%i
echo ✅ Python %python_version% is available

REM Create virtual environment and install dependencies
echo.
echo 📦 Installing dependencies with uv...
uv sync --group dev

echo ✅ Dependencies installed

REM Set up environment variables
if not exist ".env" (
    if exist ".env.example" (
        echo 📋 Copying .env.example to .env
        copy ".env.example" ".env"
        echo ⚠️  Please edit .env file with your configuration
    ) else (
        echo 📋 Creating .env file
        (
            echo # Development Environment Configuration
            echo ENVIRONMENT=development
            echo DEBUG=true
            echo.
            echo # Database
            echo DATABASE_URL=sqlite:///./attendance.db
            echo.
            echo # Redis ^(optional for development^)
            echo REDIS_URL=redis://localhost:6379/0
            echo.
            echo # JWT Configuration
            echo JWT_SECRET_KEY=dev-secret-key-change-in-production
            echo JWT_ALGORITHM=HS256
            echo JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
            echo JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
            echo.
            echo # CORS Settings
            echo BACKEND_CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
            echo.
            echo # Logging
            echo LOG_LEVEL=INFO
        ) > .env
    )
) else (
    echo ✅ .env file already exists
)

REM Run database migrations
echo.
echo 🗄️  Setting up database...

REM Check if migrations exist
if not exist "alembic\versions\*.py" (
    echo 📝 Creating initial database migration...
    uv run alembic revision --autogenerate -m "Initial database schema"
)

echo ⬆️  Running database migrations...
uv run alembic upgrade head

echo ✅ Database setup complete

REM Check if Redis is available (optional)
where redis-cli >nul 2>nul
if not errorlevel 1 (
    redis-cli ping >nul 2>nul
    if not errorlevel 1 (
        echo ✅ Redis is running
    ) else (
        echo ⚠️  Redis is not running ^(optional for development^)
        echo 💡 Start Redis with: redis-server
    )
) else (
    echo ⚠️  Redis not installed ^(optional for development^)
)

echo.
echo 🎉 Setup complete!
echo.
echo 🚀 To start development:
echo    1. Activate virtual environment: .venv\Scripts\activate
echo    2. Start the server: uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
echo    3. Open API docs: http://localhost:8000/docs
echo.
echo 🧪 Useful commands:
echo    uv run pytest                     # Run tests
echo    uv run pytest --cov=app           # Run tests with coverage  
echo    uv run black app/                 # Format code
echo    uv run flake8 app/                # Lint code
echo    uv run python run_comprehensive_tests.py  # Run all tests
echo.
echo Happy coding! 🎓
echo.
pause