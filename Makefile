.PHONY: help setup install lint format check test clean run worker docker-up docker-down migrate migrate-new pre-commit

# --- Config ---
PYTHON := uv run
APP := app
TESTS := tests

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup ---

setup: install pre-commit ## Full project setup (first time)
	@echo "✅ Setup complete"

install: ## Install all dependencies
	uv sync --group dev

pre-commit: ## Install pre-commit hooks
	$(PYTHON) pre-commit install

# --- Code Quality ---

lint: ## Run linter with auto-fix
	$(PYTHON) ruff check $(APP) $(TESTS) --fix

format: ## Format code
	$(PYTHON) ruff format $(APP) $(TESTS)

check: ## Run all checks without fixing (CI mode)
	$(PYTHON) ruff check $(APP) $(TESTS)
	$(PYTHON) ruff format $(APP) $(TESTS) --check
	$(PYTHON) mypy $(APP)

typecheck: ## Run type checking
	$(PYTHON) mypy $(APP)

# --- Testing ---

test: ## Run all tests
	$(PYTHON) pytest $(TESTS) -v

test-unit: ## Run unit tests only
	$(PYTHON) pytest $(TESTS)/unit -v

test-cov: ## Run tests with coverage
	$(PYTHON) pytest $(TESTS) -v --cov=$(APP) --cov-report=term-missing

# --- Run ---

run: ## Start FastAPI server
	$(PYTHON) uvicorn $(APP).main:app --reload --port 8000

worker: ## Start Temporal worker
	$(PYTHON) python -m $(APP).worker

# --- Docker ---

docker-up: ## Start all services (Postgres, Redis, Temporal)
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

docker-logs: ## Tail docker logs
	docker compose logs -f

docker-reset: ## Stop services and wipe volumes
	docker compose down -v

# --- Database ---

migrate: ## Run all pending migrations
	$(PYTHON) alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new msg="add orders table")
	$(PYTHON) alembic revision --autogenerate -m "$(msg)"

migrate-down: ## Rollback last migration
	$(PYTHON) alembic downgrade -1

migrate-history: ## Show migration history
	$(PYTHON) alembic history

# --- Cleanup ---

clean: ## Remove cache and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "🧹 Cleaned"