# AI-Powered Football Tipster

A value-betting engine for club and international football. It prices each
match as a full scoreline distribution, strips the bookmaker's margin off
the odds, and shows you only the bets where its own probability beats the
market's by enough to have positive expected value. It covers about 40
competitions, from the Premier League and Brazil's Série A to the World Cup
and AFCON, and runs entirely on free data.

The guiding rule is **price, don't predict**. Bookmakers already predict
football well. The engine's job is to find the matches where it disagrees
with them, and to judge itself by calibration and closing-line value rather
than a lucky week of profit. Outputs are probabilities and EV, not betting
advice, and nothing places bets for you.

**Status:** phase 2. The model, walk-forward backtester, value finder,
fixture predictor and paper-trading bet log all work. The LLM reasoning
layer (phase 3) isn't built yet.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12+ for
you) and [just](https://just.systems/) (`winget install Casey.Just` or
`brew install just`).

```bash
just start
```

This syncs dependencies, downloads match history on the first run, and
opens the dashboard at <http://localhost:8501>. The first download takes a few
minutes and writes `data/tipster.duckdb`. After that, `just start` goes
straight to the dashboard. Run `just ingest` when you want the latest
results.

Live odds are optional. To turn them on, copy `.env.example` to `.env` and
set `THE_ODDS_API_KEY` (the free tier from
[The Odds API](https://the-odds-api.com/) is enough). Every `just` recipe
loads `.env` for you.

## Using the dashboard

- **Predict fixtures.** Pick a league, paste games one per line and get
  1X2, over/under 2.5, BTTS and the likeliest scorelines. Add the bookie's
  odds to a line and you also get EV and a Kelly stake, which you can log
  as a paper bet. Mark neutral venues with `(n)`:

  ```text
  Arsenal v Chelsea
  Man City v Liverpool, 1.85, 3.90, 4.20
  Kenya v Uganda (n)
  ```

  Team names with no history in the database are flagged with a spelling
  suggestion instead of being priced as an average team.

- **Value finder.** Pulls live 1X2 odds, devigs them with Shin's method,
  and lists positive-EV tips sized by fractional Kelly (quarter-Kelly by
  default, capped per bet). The EV threshold, Kelly fraction, stake cap and
  odds source are all adjustable in the sidebar. Without an API key it uses
  the last cached snapshot. Leagues with no live feed point you to Predict
  fixtures.

- **Bet log.** Every tip you log is tracked in `data/bets.sqlite`. Settling
  checks pending bets against ingested results and reports ROI for the
  Kelly stake and a flat one-unit control side by side, plus CLV.

## Commands

Run `just` on its own to list every recipe. The ones you'll use most:

| Command | What it does |
| ------- | ------------ |
| `just start` | Sync, ingest if there's no database yet, launch the dashboard |
| `just run-ui` | Launch the dashboard only |
| `just ingest` | Download results for every competition into DuckDB |
| `just fetch-odds` | Snapshot live odds to `data/raw/live_odds/` (needs the API key) |
| `just backtest` | Walk-forward backtest of every model; artifacts in `data/backtests/` |
| `just settle-bets` | Settle pending paper bets against played matches |
| `just check` | The full gate: pre-commit hooks, ruff, mypy, pytest |
| `just clean-data` | Delete `data/` (you'll need to re-ingest) |

The CLIs behind these take flags. For example, to backtest two leagues over
one season:

```bash
uv run --all-packages tipster-backtest --leagues E0,SP1 --seasons 2526
```

`tipster-ingest --help` and `tipster-backtest --help` list the rest.

## How it works

```text
football-data.co.uk CSVs ─┐
international results CSV ┴→ polars normalisation → DuckDB (data/tipster.duckdb)
                                                         │
                              Dixon-Coles score matrix (+ GBM hybrid, backtest only)
                              walk-forward backtest: Brier, log loss, ROI, CLV
The Odds API (live 1X2) ──→   Shin devig → EV → fractional Kelly
                                                         │
                              Streamlit: predict fixtures · value finder · bet log
```

Results and historical odds come from
[football-data.co.uk](https://www.football-data.co.uk/). National-team
results come from the
[martj42/international_results](https://github.com/martj42/international_results)
dataset. Live odds come from The Odds API and are cached as JSON, never
written into the match history.

Every model produces a scoreline probability matrix, and every market
(1X2, over/under, BTTS, correct score) is read off that one matrix, so the
prices stay consistent with each other. Models only ever see fixtures, never
odds, so the closing-line-value metric can't leak into training.

Two models are in the repo. `GbmPoissonPredictor` uses LightGBM to predict
each side's expected goals and feeds them into a Dixon-Coles-corrected
Poisson matrix. `DixonColesPredictor` is the classic reference model. The
hybrid had to beat Dixon-Coles in the walk-forward backtest to earn its
place, and so far it hasn't: on 410 Premier League fixtures from August 2025
to September 2026 it scored 1.089 log loss against Dixon-Coles' 1.047. The
dashboard prices with calibrated Dixon-Coles until the hybrid passes on a
bigger corpus ([ADR 0003](docs/decisions/0003-model-gbm-poisson-hybrid.md)).

## Layout

```text
apps/tipster-ui/        Streamlit dashboard (home, predict fixtures, value finder, bet log)
packages/tipster-core/  Domain library: contracts, ingest, storage, models, value engine,
                        backtest, bet log, CLIs
services/predictor/     Placeholder for the scheduled fetch-and-predict service (not built)
docs/                   Design, architecture, onboarding, ADRs
```

`apps/` may import `packages/`, never the other way round, and
`tipster-core` never imports Streamlit. `data/` holds the DuckDB file, raw
CSVs, odds snapshots, backtest runs and the bet log. It's gitignored, so
the repo ships code and never data.

## Documentation

- [Design](docs/design.md): the full system design and roadmap
- [Architecture](docs/architecture.md): repo map and dependency rules
- [Onboarding](docs/onboarding.md): getting started and the project registry
- [Decision records](docs/decisions/README.md): ADRs 0001 to 0011

## Contributing

Run `just setup` once to install the pre-commit hooks. `just check` must
pass before you push. Significant decisions get an ADR in
`docs/decisions/`, and commits follow conventional prefixes (`feat:`,
`fix:`, `docs:`, `chore:`).

## License

[MIT](LICENSE). Copyright (c) 2026 Brian Thuo.
