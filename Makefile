# AI-Powered Football Tipster — developer entrypoint.
# Conventions: a root gate (setup/check) plus per-project prefixed targets.

.DEFAULT_GOAL := help
PYTHON := uv run --all-packages

.PHONY: help setup check precommit lint format typecheck test ingest clean clean-data run-ui tipster-core-test tipster-core-ingest tipster-ui-run

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: ## Install all workspace packages + pre-commit hooks
	uv sync --all-packages
	$(PYTHON) pre-commit install

check: precommit lint typecheck test ## Full gate: hygiene + lint + types + tests

precommit: ## Repo-wide hygiene hooks (language-agnostic)
	$(PYTHON) pre-commit run --all-files

lint: ## ruff lint + format check
	$(PYTHON) ruff check .
	$(PYTHON) ruff format --check .

format: ## Auto-format and fix
	$(PYTHON) ruff format .
	$(PYTHON) ruff check --fix .

typecheck: ## mypy across all workspace sources
	$(PYTHON) mypy

test: ## Full pytest suite
	$(PYTHON) pytest

ingest: tipster-core-ingest ## Pull big-5 league data into data/tipster.duckdb

tipster-core-test: ## Run tipster-core tests only
	$(PYTHON) pytest packages/tipster-core

tipster-core-ingest: ## Ingest football-data.co.uk CSVs (big-5, 2024/25 onward)
	$(PYTHON) tipster-ingest

tipster-ui-run: ## Launch the Streamlit dashboard
	$(PYTHON) streamlit run apps/tipster-ui/src/tipster_ui/app.py

run-ui: tipster-ui-run ## Alias for tipster-ui-run (name used in docs)

clean: ## Remove tool caches
	rm -rf .ruff_cache .mypy_cache .pytest_cache

clean-data: ## Remove local data (DuckDB + raw CSV cache) — requires re-ingest
	rm -rf data
