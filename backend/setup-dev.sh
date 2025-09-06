#!/bin/bash

# Student Attendance System - Backend Development Setup Script
# This script sets up the development environment using uv

set -e

echo "🚀 Student Attendance System - Backend Setup"
echo "============================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv is not installed${NC}"
    echo -e "${BLUE}💡 Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    echo -e "${BLUE}   Or visit: https://docs.astral.sh/uv/getting-started/installation/${NC}"
    exit 1
fi

echo -e "${GREEN}✅ uv is installed${NC}"

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
required_version="3.11"

if [[ $(echo "$python_version >= $required_version" | bc -l) -eq 0 ]]; then
    echo -e "${RED}❌ Python $required_version or higher is required. Found: $python_version${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python $python_version is compatible${NC}"

# Create virtual environment and install dependencies
echo -e "${BLUE}📦 Installing dependencies with uv...${NC}"
uv sync --group dev

echo -e "${GREEN}✅ Dependencies installed${NC}"

# Set up environment variables
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${BLUE}📋 Copying .env.example to .env${NC}"
        cp .env.example .env
        echo -e "${YELLOW}⚠️  Please edit .env file with your configuration${NC}"
    else
        echo -e "${BLUE}📋 Creating .env file${NC}"
        cat > .env << EOF
# Development Environment Configuration
ENVIRONMENT=development
DEBUG=true

# Database
DATABASE_URL=sqlite:///./attendance.db

# Redis (optional for development)
REDIS_URL=redis://localhost:6379/0

# JWT Configuration
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# External Services (optional for development)
# TWILIO_ACCOUNT_SID=your-twilio-sid
# TWILIO_AUTH_TOKEN=your-twilio-token
# SENDGRID_API_KEY=your-sendgrid-key

# SIS Integration (optional)
# POWERSCHOOL_CLIENT_ID=your-client-id
# POWERSCHOOL_CLIENT_SECRET=your-client-secret

# CORS Settings
BACKEND_CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# Logging
LOG_LEVEL=INFO
EOF
    fi
else
    echo -e "${GREEN}✅ .env file already exists${NC}"
fi

# Run database migrations
echo -e "${BLUE}🗄️  Setting up database...${NC}"
if [ ! -d "alembic/versions" ] || [ -z "$(ls -A alembic/versions)" ]; then
    echo -e "${BLUE}📝 Creating initial database migration...${NC}"
    uv run alembic revision --autogenerate -m "Initial database schema"
fi

echo -e "${BLUE}⬆️  Running database migrations...${NC}"
uv run alembic upgrade head

echo -e "${GREEN}✅ Database setup complete${NC}"

# Check if Redis is running (optional)
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        echo -e "${GREEN}✅ Redis is running${NC}"
    else
        echo -e "${YELLOW}⚠️  Redis is not running (optional for development)${NC}"
        echo -e "${BLUE}💡 Start Redis with: redis-server${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Redis not installed (optional for development)${NC}"
fi

# Create pre-commit hook
if command -v pre-commit &> /dev/null; then
    echo -e "${BLUE}🔧 Setting up pre-commit hooks...${NC}"
    uv run pre-commit install
    echo -e "${GREEN}✅ Pre-commit hooks installed${NC}"
fi

echo ""
echo -e "${GREEN}🎉 Setup complete!${NC}"
echo ""
echo -e "${BLUE}🚀 To start development:${NC}"
echo -e "   ${BLUE}1.${NC} Activate virtual environment: ${YELLOW}source .venv/bin/activate${NC}"
echo -e "   ${BLUE}2.${NC} Start the server: ${YELLOW}uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000${NC}"
echo -e "   ${BLUE}3.${NC} Open API docs: ${YELLOW}http://localhost:8000/docs${NC}"
echo ""
echo -e "${BLUE}🧪 Useful commands:${NC}"
echo -e "   ${YELLOW}uv run pytest${NC}                    # Run tests"
echo -e "   ${YELLOW}uv run pytest --cov=app${NC}          # Run tests with coverage"
echo -e "   ${YELLOW}uv run black app/${NC}                # Format code"
echo -e "   ${YELLOW}uv run flake8 app/${NC}               # Lint code"
echo -e "   ${YELLOW}uv run python run_comprehensive_tests.py${NC}  # Run all tests"
echo ""
echo -e "${GREEN}Happy coding! 🎓${NC}"