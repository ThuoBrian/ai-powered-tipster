# Repo Architecture

How `ai-powered-tipster` is laid out and the rules that keep it healthy.
The full product design lives in [design.md](design.md); decisions and their
reasoning live in [decisions/](decisions/README.md).

## Directory map

```text
ai-powered-tipster/
├── apps/
│   └── tipster-ui/          # Streamlit dashboard (deployable app)
├── packages/
│   └── tipster-core/        # Pure domain library: contracts, ingest,
│                            # storage, (later) features, model, value,
│                            # backtest. No framework imports.
├── services/
│   └── predictor/           # Scheduled fetch-and-predict job (port pending)
├── docs/
│   ├── design.md            # Product/system design
│   ├── architecture.md      # This file: repo map and rules
│   ├── onboarding.md        # Project registry + getting started
│   └── decisions/           # ADRs
├── data/                    # LOCAL ONLY (gitignored): DuckDB + raw CSVs
├── Makefile                 # make setup / make check + per-project targets
└── pyproject.toml           # uv workspace root, shared tool config
```

## Dependency rules

- `apps/` and `services/` may import `packages/`. Never the reverse.
- `packages/tipster-core` must never import `streamlit`, `httpx`-server
  frameworks, or anything UI-specific — it stays independently testable.
- Workspace members are declared explicitly in the root `pyproject.toml`
  (add a member when a project gains a `pyproject.toml`).

## Toolchain

- **uv** is the only package manager (workspace + lockfile, committed).
- **ruff** lints and formats everything (`make lint`, `make format`).
- **mypy** type-checks all package/app sources (`make typecheck`).
- **pytest** runs the test suite (`make test`).
- **pre-commit** runs the repo-wide, language-agnostic hygiene gate
  (`make check` includes it).
- **CI** (`.github/workflows/ci.yml`) runs the hygiene gate plus a Python
  job (uv sync, ruff, mypy, pytest) on every push and PR.

## Where things run

| Component | How it runs | Notes |
|-----------|--------------|-------|
| tipster-ui | `make run-ui` | Streamlit on localhost:8501 |
| tipster-ingest CLI | `make ingest` | Fills `data/tipster.duckdb` |
| predictor service | Not yet ported | See `services/predictor/README.md` |