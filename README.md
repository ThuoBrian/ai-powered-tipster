# AI-Powered Football Tipster

Value-betting engine for club and international football — about 40
competitions, from the Premier League to Brazil's Série A to the World Cup
and AFCON. A Poisson score model prices every match as a full scoreline
distribution, bookmaker odds are stripped of their margin and compared
against those probabilities, and only positive-EV tips are surfaced.
Streamlit dashboard, DuckDB storage, fully reproducible from free data.

**Status: phase 2** — the model, walk-forward backtester, value finder, and
paper-trading bet log are live. The LLM reasoning layer is phase 3 (see
[docs/design.md](docs/design.md#roadmap)).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python ≥ 3.12 is managed for you)
and [just](https://just.systems/) (`winget install Casey.Just`, `brew install just`).

```bash
just start    # sync deps, download data on first run, open http://localhost:8501
```

That's it. The first run downloads about 40 competitions (league and
international results, a few minutes) into `data/tipster.duckdb`; later
runs go straight to the dashboard. Run `just ingest` whenever you want the
latest results.

For live odds, copy `.env.example` to `.env` and set `THE_ODDS_API_KEY`
(free tier from [The Odds API](https://the-odds-api.com/)). Every `just`
recipe loads `.env` automatically. Run `just` with no arguments to list
every recipe. Contributors should also run `just setup` (pre-commit hooks)
and `just check` (the gate).

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
- [Decision records](docs/decisions/README.md) — ADRs 0001–0010

## Contributing

`just check` must pass. Significant decisions get an ADR in
`docs/decisions/`. Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).

## License

[MIT](LICENSE) — Copyright (c) 2026 Brian Thuo
