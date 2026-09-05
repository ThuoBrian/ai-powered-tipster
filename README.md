# AI-Powered Football Tipster

Value-betting engine for European football: a GBM → Poisson hybrid prices
every match as a full scoreline distribution, bookmaker odds are stripped of
their margin and compared against those probabilities, and only positive-EV
tips are surfaced — each explained by a locally-run LLM. Streamlit dashboard,
DuckDB storage, fully reproducible from free data.

**Status: phase 0** — historical ingest and the dashboard's data-status page
are live. The model, backtester, and value finder land in phases 1–2 (see
[docs/design.md](docs/design.md#roadmap)).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python ≥ 3.12 is managed for you).

```bash
make setup    # workspace deps + pre-commit hooks
make ingest   # big-5 European leagues, 2024/25 → 2026/27 → data/tipster.duckdb
make run-ui   # Streamlit dashboard on http://localhost:8501
make check    # the gate: hygiene + lint + types + tests
```

No API keys needed yet — phase 0 runs entirely on free data. Keys later
phases use are listed in [`.env.example`](.env.example).

## How it works

```text
football-data.co.uk CSVs  →  polars normalisation  →  DuckDB (data/tipster.duckdb)
                                                     │
                       phase 1: LightGBM expected goals → Poisson score matrix
                       phase 1: walk-forward backtests (Brier, log loss, ROI, CLV)
                       phase 2: devig market odds → EV → fractional Kelly staking
                       phase 3: Ollama LLM writes the reasoning behind each tip
                                                     │
                                       Streamlit: dashboard · value finder · bankroll
```

The core principle throughout: **price, don't predict** — the engine exists
to find disagreements between its own calibrated probabilities and the
market's, not to guess winners. Full design in
[docs/design.md](docs/design.md).

## Layout

```text
apps/tipster-ui/        Streamlit dashboard
packages/tipster-core/  Domain library: contracts, ingest, DuckDB storage
services/predictor/     Scheduled fetch-and-predict service (port pending)
docs/                   design · architecture · onboarding · ADRs
```

`data/` (DuckDB + raw CSVs) is local-only and gitignored — the repo ships
code, never data.

## Documentation

- [Design](docs/design.md) — the full system design
- [Architecture](docs/architecture.md) — repo map and dependency rules
- [Onboarding](docs/onboarding.md) — getting started and project registry
- [Decision records](docs/decisions/README.md) — ADRs 0001–0004

## Contributing

`make check` must pass. Significant decisions get an ADR in
`docs/decisions/`. Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).

## License

TBD — the template's LICENSE was removed from this repo pending a decision.
