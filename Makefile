.PHONY: help install dev test lint format check pre-commit clean

help:
	@echo "Finance Report - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install      Install all dependencies + pre-commit hooks"
	@echo "  make pre-commit   Install pre-commit hooks only"
	@echo ""
	@echo "Development:"
	@echo "  make dev          Start backend + frontend dev servers"
	@echo "  make backend      Start backend only"
	@echo "  make frontend     Start frontend only"
	@echo ""
	@echo "Quality:"
	@echo "  make lint         Run linters (ruff + eslint)"
	@echo "  make format       Auto-format code"
	@echo "  make check        Run all checks (lint + env-check)"
	@echo "  make test         Run backend tests"
	@echo ""
	@echo "Utilities:"
	@echo "  make env-check    Validate env var consistency"
	@echo "  make clean        Clean generated files"

install: pre-commit
	cd apps/backend && uv sync
	cd apps/frontend && npm install

pre-commit:
	pip install pre-commit
	pre-commit install
	@echo "✅ Pre-commit hooks installed"

dev:
	@echo "Starting dev servers (use Ctrl+C to stop)..."
	@trap 'kill 0' INT; \
	(cd apps/backend && uv run uvicorn src.main:app --reload --port 8000) & \
	(cd apps/frontend && npm run dev) & \
	wait

backend:
	cd apps/backend && uv run uvicorn src.main:app --reload --port 8000

frontend:
	cd apps/frontend && npm run dev

lint:
	cd apps/backend && uv run ruff check src/
	cd apps/frontend && npm run lint

format:
	cd apps/backend && uv run ruff check src/ --fix
	cd apps/backend && uv run ruff format src/
	cd apps/frontend && npm run lint -- --fix || true

check: lint env-check
	@echo "✅ All checks passed"

test:
	moon run backend:test

env-check:
	python scripts/check_env_keys.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf apps/backend/.coverage apps/backend/coverage.* 2>/dev/null || true
	rm -rf apps/frontend/.next 2>/dev/null || true
	@echo "✅ Cleaned"
