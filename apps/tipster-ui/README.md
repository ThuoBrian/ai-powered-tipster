# tipster-ui

The Streamlit dashboard for the AI-powered football tipster. Phase 0 ships
the data-status page (coverage by league/season, recent matches); the value
finder, backtest, and bankroll pages land in phases 1–2
([docs/design.md](../../docs/design.md#roadmap)).

## Run

From the repo root (the app resolves `data/tipster.duckdb` relative to the
working directory):

```bash
just tipster-ui-run        # or the alias: just run-ui
```

## Test

No UI-specific tests yet — the domain logic it renders is covered by
`tipster-core`'s suite (`just tipster-core-test`). The app also boots
headless for smoke checks:

```bash
uv run streamlit run apps/tipster-ui/src/tipster_ui/app.py --server.headless true
```

## Environment variables

None required. See the root `.env.example` for the keys phase 2 will use.
