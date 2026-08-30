# Ada Development Brain — Makefile
# ---------------------------------
# Prerequisite: `uv` must be on PATH (https://github.com/astral-sh/uv)
# ---------------------------------
# Usage: make <target>
# ---------------------------------

.PHONY: all test test-phase typecheck lint alembic docker-dev seed help

all: help ## Show this help message

# ---- Test targets ------------------------------------------------------

test: ## Run the full test suite (853 tests, ~80s)
	uv run pytest -p no:cacheprovider

test-phase: ## Run a specific phase test (set PHASE=35, 36, …)
	uv run pytest -q tests/test_phase$(PHASE)_*.py -p no:cacheprovider

# ---- Quality targets -------------------------------------------------

typecheck: ## Run mypy across 273 source files
	uv run mypy brain

lint: ## Run ruff format + check
	uv run ruff format tests brain
	uv run ruff check tests brain

# ---- Infrastructure targets ------------------------------------------

alembic: ## Run alembic upgrade head on brain_migration_test DB
	@echo "===> Ensure BRAIN_DATABASE_URL points to brain_migration_test"
	uv run alembic downgrade -1 2>&1 | tail -1
	uv run alembic upgrade head 2>&1 | tail -1
	@uv run psql "postgresql+asyncpg://postgres:postgres@localhost:5432/brain_migration_test" -c "SELECT version_num FROM alembic_version;"

up: ## Start the reference environment (6 overlay compose files)
	docker compose -f compose.yaml -f compose.openproject.yaml \
		-f compose.xwiki.yaml -f compose.docling.yaml \
		-f compose.backstage.yaml -f compose.gitlab.yaml up -d


down: ## Start the reference environment (6 overlay compose files)
	docker compose -f compose.yaml -f compose.openproject.yaml \
		-f compose.xwiki.yaml -f compose.docling.yaml \
		-f compose.backstage.yaml -f compose.gitlab.yaml down
# ---- Runtime targets -------------------------------------------------

run: ## Start the FastAPI dev server (http://localhost:8000)
	uv run uvicorn brain.api.app:app

# ---- Seed target -----------------------------------------------------

seed: ## Seed the reference scenario (login service + partial account-locking)
	@echo "===> See scenarios/reference/seed_repository/ and docs/runtime/ for scripts"
	@true

# ---- Help -------------------------------------------------------------

help: ## Show this help message
	@echo "Targets:"
	@echo "  test           - Run full test suite (853 tests)"
	@echo "  test-phase     - Run a specific phase test (set PHASE=35, 36, ...)"
	@echo "  typecheck      - Run mypy across 273 source files"
	@echo "  lint           - Run ruff format + check"
	@echo "  alembic        - Run alembic upgrade head on brain_migration_test DB"
	@echo "  docker-dev     - Start the reference environment (6 overlay compose files)"
	@echo "  run            - Start the FastAPI dev server (http://localhost:8000)"
	@echo "  seed           - Seed the reference scenario"
	@echo "  help           - Show this help message"