# AI-Powered Football Tipster — developer entrypoint (ADR 0010).
# Conventions: a root gate (setup/check) plus per-project prefixed recipes.

set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

run := "uv run --all-packages"
db := "data/tipster.duckdb"

alias ingest := tipster-core-ingest
alias fetch-odds := tipster-core-fetch-odds
alias backtest := tipster-core-backtest
alias settle-bets := tipster-core-settle-bets
alias run-ui := tipster-ui-run

# Show available recipes
default:
    @just --list

# First run to dashboard: sync deps, ingest only if there's no DB yet, launch the UI
start:
    uv sync --all-packages
    {{ if path_exists(db) == "true" { "echo 'Data found, skipping ingest'" } else { run + " tipster-ingest" } }}
    {{ run }} streamlit run apps/tipster-ui/src/tipster_ui/app.py

# Install all workspace packages + pre-commit hooks
setup:
    uv sync --all-packages
    {{ run }} pre-commit install

# Full gate: hygiene + lint + types + tests
check: precommit lint typecheck test

# Repo-wide hygiene hooks (language-agnostic)
precommit:
    {{ run }} pre-commit run --all-files

# ruff lint + format check
lint:
    {{ run }} ruff check .
    {{ run }} ruff format --check .

# Auto-format and fix
format:
    {{ run }} ruff format .
    {{ run }} ruff check --fix .

# mypy across all workspace sources
typecheck:
    {{ run }} mypy

# Full pytest suite
test:
    {{ run }} pytest

# Run tipster-core tests only
tipster-core-test:
    {{ run }} pytest packages/tipster-core

# Ingest football-data.co.uk CSVs (big-5, 2024/25 onward) into data/tipster.duckdb
tipster-core-ingest:
    {{ run }} tipster-ingest

# Fetch live 1X2 odds (big-5) -> data/raw/live_odds/ (needs THE_ODDS_API_KEY in .env)
tipster-core-fetch-odds:
    {{ run }} tipster-odds

# Walk-forward backtest (all arms) -> data/backtests/
tipster-core-backtest:
    {{ run }} tipster-backtest

# Settle paper bets in data/bets.sqlite against played matches
tipster-core-settle-bets:
    {{ run }} tipster-bets

# Launch the Streamlit dashboard
tipster-ui-run:
    {{ run }} streamlit run apps/tipster-ui/src/tipster_ui/app.py

# Remove tool caches
clean:
    {{ run }} python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('.ruff_cache', '.mypy_cache', '.pytest_cache')]"

# Remove local data (DuckDB + raw CSV cache) — requires re-ingest
clean-data:
    {{ run }} python -c "import shutil; shutil.rmtree('data', ignore_errors=True)"
