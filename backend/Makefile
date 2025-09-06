# Student Attendance System - Backend Makefile
# Provides convenient commands for development workflow

.PHONY: help install dev test lint format clean run migrations docker

# Default target
help:
	@echo "🎓 Student Attendance System - Backend Commands"
	@echo "=============================================="
	@echo ""
	@echo "📦 Setup & Installation:"
	@echo "  make install     Install dependencies with uv"
	@echo "  make install-dev Install with development dependencies"
	@echo "  make clean       Clean cache and build artifacts"
	@echo ""
	@echo "🚀 Development:"
	@echo "  make run         Start development server"
	@echo "  make run-prod    Start production server with Gunicorn"
	@echo "  make shell       Start interactive Python shell"
	@echo ""
	@echo "🗄️  Database:"
	@echo "  make migrate     Run database migrations"
	@echo "  make migration   Create new migration"
	@echo "  make db-reset    Reset database (WARNING: destroys data)"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test        Run all tests"
	@echo "  make test-unit   Run unit tests only"
	@echo "  make test-cov    Run tests with coverage report"
	@echo "  make test-perf   Run performance tests"
	@echo "  make test-sec    Run security tests"
	@echo "  make test-all    Run comprehensive test suite"
	@echo ""
	@echo "🔧 Code Quality:"
	@echo "  make lint        Run all linting tools"
	@echo "  make format      Format code with black and isort"
	@echo "  make type-check  Run type checking with mypy"
	@echo "  make pre-commit  Run pre-commit hooks"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  make docker-build    Build Docker image"
	@echo "  make docker-run      Run Docker container"
	@echo "  make docker-compose  Start with docker-compose"
	@echo ""

# Installation
install:
	@echo "📦 Installing dependencies..."
	uv sync

install-dev:
	@echo "📦 Installing development dependencies..."
	uv sync --group dev

# Development server
run:
	@echo "🚀 Starting development server..."
	uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

run-prod:
	@echo "🚀 Starting production server..."
	uv run gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

shell:
	@echo "🐍 Starting interactive Python shell..."
	uv run python -c "import IPython; IPython.start_ipython()"

# Database management
migrate:
	@echo "⬆️ Running database migrations..."
	uv run alembic upgrade head

migration:
	@echo "📝 Creating new migration..."
	@read -p "Migration message: " msg; \
	uv run alembic revision --autogenerate -m "$$msg"

db-reset:
	@echo "⚠️  This will destroy all data! Are you sure? [y/N]"
	@read confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		rm -f attendance.db; \
		uv run alembic upgrade head; \
		echo "✅ Database reset complete"; \
	else \
		echo "❌ Database reset cancelled"; \
	fi

# Testing
test:
	@echo "🧪 Running tests..."
	uv run pytest -v

test-unit:
	@echo "🧪 Running unit tests..."
	uv run pytest tests/unit/ -v

test-cov:
	@echo "🧪 Running tests with coverage..."
	uv run pytest --cov=app --cov-report=html --cov-report=term

test-perf:
	@echo "⚡ Running performance tests..."
	uv run pytest tests/performance/ -v -m performance

test-sec:
	@echo "🔒 Running security tests..."
	uv run pytest tests/security/ -v -m security

test-all:
	@echo "🧪 Running comprehensive test suite..."
	uv run python run_comprehensive_tests.py

# Code quality
lint:
	@echo "🔍 Running linting tools..."
	uv run flake8 app/
	uv run mypy app/
	@echo "✅ Linting complete"

format:
	@echo "🎨 Formatting code..."
	uv run black app/
	uv run isort app/
	@echo "✅ Code formatting complete"

type-check:
	@echo "🔍 Running type checker..."
	uv run mypy app/

pre-commit:
	@echo "🔧 Running pre-commit hooks..."
	uv run pre-commit run --all-files

# Docker
docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t student-attendance-backend .

docker-run:
	@echo "🐳 Running Docker container..."
	docker run -p 8000:8000 --env-file .env student-attendance-backend

docker-compose:
	@echo "🐳 Starting with docker-compose..."
	docker-compose up -d

# Cleanup
clean:
	@echo "🧹 Cleaning up..."
	find . -type d -name "__pycache__" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	@echo "✅ Cleanup complete"

# Development workflow shortcuts
dev: install-dev migrate
	@echo "🎉 Development environment ready!"
	@echo "Run 'make run' to start the server"

ci: lint test
	@echo "✅ CI checks passed"

# Quick setup for new developers
setup: install-dev migrate
	@echo "🎉 Setup complete!"
	@echo ""
	@echo "🚀 Next steps:"
	@echo "  1. Review .env file settings"
	@echo "  2. Run 'make run' to start development server"
	@echo "  3. Open http://localhost:8000/docs for API documentation"