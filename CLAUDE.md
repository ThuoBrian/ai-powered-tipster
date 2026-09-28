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
| First run → dashboard (sync, ingest if no DB, UI) | `just start` |
| One-time setup (deps + hooks) | `just setup` |
| The gate (hygiene + lint + types + tests) | `just check` |
| Tests only | `just test` (or `just tipster-core-test`) |
| Lint / auto-fix | `just lint` / `just format` |
| Typecheck | `just typecheck` |
| Ingest data | `just ingest` (football-data.co.uk → `data/tipster.duckdb`) |
| Dashboard | `just run-ui` (Streamlit, localhost:8501) |

Always run commands through `uv run` (the justfile does). Never use raw pip.

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

## Current state (2026-09-28)

Phases 0–2 complete: ingest for ~40 competitions (ADR 0011), feature
builder, GBM → Poisson hybrid and Dixon-Coles models, walk-forward backtest,
value engine (Shin devig, EV, Kelly), live odds, and the Streamlit pages
(predict fixtures, value finder, bet log). The hybrid failed its gate
against Dixon-Coles, so the dashboard prices with calibrated Dixon-Coles
(`tipster_ui.shared.fit_for_league`, [ADR 0003 amendment](docs/decisions/0003-model-gbm-poisson-hybrid.md)).
Phase 3 next: port `services/predictor` and add the Ollama reasoning layer
([ADR 0004](docs/decisions/0004-reasoning-layer-local-ollama.md)).
Key extension points: `tipster_core.contracts` (domain models),
`tipster_core.storage` (DuckDB schema), and `tipster_core.predictor`
(the model protocol).
