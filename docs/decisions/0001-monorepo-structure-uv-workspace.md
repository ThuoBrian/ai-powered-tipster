# 0001 — Monorepo structure: uv workspace with apps/packages/services

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

The tipster started as a predictor service scaffold inside
`my-claude-project-architecture-template` and has outgrown that home: the
product now has three deployable units (a Streamlit UI, a core domain library,
and a scheduled predictor service) that share one domain model. This repo
already carries the template's repo-wide hygiene tooling (language-agnostic
pre-commit gate, CI skeleton, editorconfig), and the tooling of choice for
Python in 2026 is `uv`, which has first-class workspace support.

## Decision

This is a dedicated product repo organised as a `uv` workspace:

- `apps/tipster-ui` — Streamlit dashboard. Deployable app.
- `packages/tipster-core` — pure Python library: data contracts, ingestion,
  DuckDB storage, and (in later phases) features, the model, the value
  engine, and backtesting. No framework imports (never Streamlit).
- `services/predictor` — scheduled fetch-and-predict job, ported from the
  template scaffold in a later phase.

The root `pyproject.toml` is a virtual (non-package) project holding shared
tool configuration (ruff, mypy, pytest) and the dev dependency group;
workspace members are listed explicitly there. Dependency direction is
strictly downward: `apps/` and `services/` may import `packages/`; `packages/`
never imports from `apps/` or `services/`. Python floor is 3.10 for sandbox
reproducibility; `uv` manages newer interpreters where available.

## Consequences

- One lockfile, one virtualenv, one command (`uv sync --all-packages`) to get
  every component runnable; CI stays cheap.
- Shared domain logic has a single home in `tipster-core`, which is also what
  keeps the package testable without a UI.
- Root-level tool config means a future non-Python project in this repo would
  carry Python lint config it does not use; acceptable until that happens.
- The predictor scaffold still needs porting from the template repo
  (tracked in `services/predictor/README.md`).