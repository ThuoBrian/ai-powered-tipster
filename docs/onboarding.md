# Onboarding

Everything a newcomer (or a fresh agent session) needs to get productive.

## Getting started

```bash
# 1. Install uv (one-time): https://docs.astral.sh/uv/
# 2. Set up the workspace (deps + pre-commit hooks)
make setup

# 3. Pull historical data into data/tipster.duckdb
make ingest

# 4. Run the checks (the gate: lint + types + tests)
make check

# 5. Launch the dashboard
make run-ui
```

No environment variables are required yet. `.env.example` lists the keys
later phases need (`THE_ODDS_API_KEY`, `FOOTBALL_DATA_API_KEY`) — copy to
`.env` when you get there; `.env` is gitignored.

## Project registry

| Project | Type | Path | Stack | Status |
|---------|------|------|-------|--------|
| tipster-core | package | `packages/tipster-core` | Python, pydantic, polars, DuckDB, httpx | Phase 0 done (ingest + storage); model in phase 1 |
| tipster-ui | app | `apps/tipster-ui` | Python, Streamlit | Phase 0 done (status page); value finder in phase 2 |
| predictor | service | `services/predictor` | Python, httpx (port pending) | Placeholder — scaffold lives in the template repo |

## Conventions

- Python via `uv run <command>` — never raw pip installs.
- Changes to data flow or schemas get a test; significant decisions get an
  ADR in `docs/decisions/`.
- `data/` is local-only: DuckDB files and raw CSVs are never committed.
- Makefile targets for a project are prefixed with its name
  (`tipster-core-test`, `tipster-ui-run`).

## Current state (2026-09)

Phase 0 complete: monorepo scaffold, football-data.co.uk ingestion into
DuckDB, pydantic contracts, Streamlit status page. Next: phase 1 — feature
builder, GBM → Poisson hybrid model, walk-forward backtest harness
(see [design.md](design.md#roadmap)).