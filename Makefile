# AI-Powered Football Tipster — developer entrypoint.
# Conventions: a root gate (setup/check) plus per-project prefixed targets.

.DEFAULT_GOAL := help
PYTHON := uv run --all-packages

.PHONY: help setup check precommit lint format typecheck test ingest fetch-odds backtest settle-bets clean clean-data run-ui tipster-core-test tipster-core-ingest tipster-core-fetch-odds tipster-core-backtest tipster-core-settle-bets tipster-ui-run

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

fetch-odds: tipster-core-fetch-odds ## Fetch live 1X2 odds from The Odds API (needs THE_ODDS_API_KEY)

backtest: tipster-core-backtest ## Run the walk-forward backtest over the local DuckDB

settle-bets: tipster-core-settle-bets ## Settle pending paper bets, print the ledger summary

tipster-core-test: ## Run tipster-core tests only
	$(PYTHON) pytest packages/tipster-core

tipster-core-ingest: ## Ingest football-data.co.uk CSVs (big-5, 2024/25 onward)
	$(PYTHON) tipster-ingest

tipster-core-settle-bets: ## Settle paper bets in data/bets.sqlite against played matches
	$(PYTHON) tipster-bets

tipster-core-fetch-odds: ## Fetch live 1X2 odds (big-5) -> data/raw/live_odds/
	$(PYTHON) tipster-odds

tipster-core-backtest: ## Walk-forward backtest (all arms) -> data/backtests/
	$(PYTHON) tipster-backtest

tipster-ui-run: ## Launch the Streamlit dashboard
	$(PYTHON) streamlit run apps/tipster-ui/src/tipster_ui/app.py

run-ui: tipster-ui-run ## Alias for tipster-ui-run (name used in docs)

clean: ## Remove tool caches
	rm -rf .ruff_cache .mypy_cache .pytest_cache

clean-data: ## Remove local data (DuckDB + raw CSV cache) — requires re-ingest
	rm -rf data
