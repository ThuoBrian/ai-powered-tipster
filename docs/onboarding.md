# Onboarding

Everything a newcomer (or a fresh agent session) needs to get productive.

## Getting started

Just want the dashboard? `just start` syncs deps, downloads data on the
first run, and opens it. The full contributor path:

```bash
# 1. Install uv and just (one-time): https://docs.astral.sh/uv/ ,
#    winget install Casey.Just  (or: brew install just)
# 2. Set up the workspace (deps + pre-commit hooks)
just setup

# 3. Pull historical data into data/tipster.duckdb
just ingest

# 4. Run the checks (the gate: lint + types + tests)
just check

# 5. Run the walk-forward backtest (prints the model gate verdict)
just backtest

# 6. Launch the dashboard
just run-ui
```

Historical data needs no keys. For live odds, copy `.env.example` to `.env`
and set `THE_ODDS_API_KEY`. Every `just` recipe loads `.env` automatically,
and `.env` is gitignored.

## Project registry

| Project | Type | Path | Stack | Status |
|---------|------|------|-------|--------|
| tipster-core | package | `packages/tipster-core` | Python, pydantic, polars, DuckDB, httpx, LightGBM, scipy | Phase 1 in progress: ingest + storage + features + GBM → Poisson hybrid + backtest harness |
| tipster-ui | app | `apps/tipster-ui` | Python, Streamlit | Phase 0 done (status page); value finder in phase 2 |
| predictor | service | `services/predictor` | Python, httpx (port pending) | Placeholder — scaffold lives in the template repo |

## Conventions

- Python via `uv run <command>` — never raw pip installs.
- Changes to data flow or schemas get a test; significant decisions get an
  ADR in `docs/decisions/`.
- `data/` is local-only: DuckDB files and raw CSVs are never committed.
- justfile recipes for a project are prefixed with its name
  (`tipster-core-test`, `tipster-ui-run`).

## Current state (2026-09)

Phase 1 complete: feature builder, per-league Elo, GBM → Poisson hybrid
(ADR 0003) with isotonic calibration, pure Dixon-Coles reference, and the
walk-forward backtest harness (ADR 0005) — `just backtest` prints per-arm
Brier/log loss, ROI, CLV, and the gate verdict. Next: phase 2 — the value
engine and LLM reasoning layer (see [design.md](design.md#roadmap)).
