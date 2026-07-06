.PHONY: help install dev test lint format check pre-commit clean llm-record

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
	@echo "  make llm-record   Re-record LLM cassettes (record mode; any provider key)"
	@echo ""
	@echo "Utilities:"
	@echo "  make env-check    Validate env var consistency"
	@echo "  make clean        Clean generated files"

install:
	bash tools/bootstrap.sh

pre-commit:
	uvx pre-commit install
	@echo "Pre-commit hooks installed"

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
	@cd apps/frontend && npm run lint -- --fix || { \
		echo ""; \
		echo "⚠️  Some ESLint issues could not be auto-fixed"; \
		echo "   Run 'npm run lint' in apps/frontend to see details"; \
	}

check: lint env-check
	@echo "✅ All checks passed"

test:
	moon run :test

# Re-record the LLM cassettes against a live provider. Provider-agnostic: it uses
# whatever provider key the env config resolves (any provider, not only the GLM
# plan). Records in `record` mode (real call + write/update cassette under
# common/testing/fixtures/llm_cassettes); commit the resulting diff. CI runs
# the same tests in `replay` mode with no key. Pass extra args via ARGS=...
#
# Covers the AC23.5 non-streaming layer and the AC23.6 streaming bridge. To record
# the (currently skipped) extraction scaffold cassettes — the real text/vision/
# #1254-class statements — add the marker and flip the skip:
#   make llm-record ARGS='tests/extraction/test_extraction_cassette_replay.py -m needs_real_cassette'
# then remove the `needs_real_cassette` module skip so the dedicated replay CI
# step runs them with no key.
#
# After re-recording a statement cassette, raise the GRADED field-accuracy floor
# (EPIC-023 AC23.8) so the ratchet adopts the new (>=) scores; commit cassettes +
# baseline together:
#   python tools/check_cassette_graded_eval.py --update
llm-record:
	cd apps/backend && LLM_CASSETTE_REFRESH=1 uv run pytest tests/llm/test_cassette.py tests/llm/test_streaming_cassette.py --llm-record $(ARGS)

env-check:
	python tools/check_env_keys.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf apps/backend/.coverage apps/backend/coverage.* 2>/dev/null || true
	rm -rf apps/frontend/.next 2>/dev/null || true
	@echo "✅ Cleaned"
