# tipster-core

The tipster's domain library: league/season identifiers, pydantic contracts,
football-data.co.uk ingestion, and DuckDB storage. Pure Python — no UI
frameworks and no service code (dependency rules live in
[docs/architecture.md](../../docs/architecture.md)).

## Install, run, test

Everything runs through the repo workspace (`just setup` at the root). This
package's targets:

```bash
just tipster-core-test    # pytest for this package only
just tipster-core-ingest  # big-5 leagues, 2024/25 → 2026/27, into data/tipster.duckdb
```

The CLI is also directly usable for narrower pulls:

```bash
uv run tipster-ingest --leagues E0 --seasons 2526
uv run tipster-ingest --refresh          # re-download even if CSVs are cached
```

Options: `--leagues`, `--seasons` (comma-separated football-data.co.uk
codes), `--db`, `--raw-dir`, `--refresh`. Ingest is idempotent per
(league, season) — safe to re-run.

## Environment variables

None required. Phase 2 keys live in the root `.env.example`.

## Layout

```text
src/tipster_core/
├── leagues.py            LeagueCode enum, season code helpers, BIG_5
├── contracts.py          MatchResult / MatchOdds / OutcomeOdds (pydantic)
├── storage.py            DuckDB schema, connect, replace_season, queries
└── ingest/
    ├── football_data.py  URL builder, downloader, CSV parser (pure)
    ├── pipeline.py       fetch (with raw caching) → parse → store
    └── cli.py            the tipster-ingest entry point
```
