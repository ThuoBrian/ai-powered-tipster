# CLAUDE.md

Guidance for Claude (and any coding agent) working in this repo.

## What this is

An AI-powered football tipster: a value-betting engine that prices matches
with a GBM → Poisson hybrid, compares against devigged bookmaker odds, and
surfaces positive-EV tips with LLM-written reasoning. Core principle:
**price, don't predict**. Full design in [docs/design.md](docs/design.md).

## Commands

| Task | Command |
|------|---------|
| One-time setup (deps + hooks) | `make setup` |
| The gate (hygiene + lint + types + tests) | `make check` |
| Tests only | `make test` (or `make tipster-core-test`) |
| Lint / auto-fix | `make lint` / `make format` |
| Typecheck | `make typecheck` |
| Ingest data | `make ingest` (football-data.co.uk → `data/tipster.duckdb`) |
| Dashboard | `make run-ui` (Streamlit, localhost:8501) |

Always run commands through `uv run` (the Makefile does). Never use raw pip.

## Rules

- uv workspace; members are listed explicitly in the root `pyproject.toml`.
  Add a member when a project gains its own `pyproject.toml`.
- Dependency direction: `apps/` and `services/` may import `packages/`;
  never the reverse. `tipster-core` must never import `streamlit`.
- `data/` is local-only (gitignored): DuckDB files and raw CSVs are never
  committed, and neither is `.env` (see `.env.example` for required keys).
- Significant decisions get an ADR in `docs/decisions/` (format and next
  number in its README). Register new projects in `docs/onboarding.md` and
  `docs/architecture.md`.
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`.
- Ingest is idempotent per (league, season). The parser must tolerate
  missing odds columns — column sets drift between seasons.

## Current state (2026-09-05)

Phase 0 complete: scaffold, ingest, storage, contracts, Streamlit status
page. Phase 1 next: feature builder, GBM → Poisson hybrid, walk-forward
backtest harness ([ADR 0003](docs/decisions/0003-model-gbm-poisson-hybrid.md)).
Key extension points: `tipster_core.contracts` (domain models) and
`tipster_core.storage` (DuckDB schema).
