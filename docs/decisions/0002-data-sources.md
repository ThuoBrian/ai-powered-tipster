# 0002 — Data sources: football-data.co.uk primary, The Odds API live

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

The value engine's ground truth is *historical odds*, not just results: to
backtest we need, for every past match, what the market actually priced.
Live operation additionally needs current odds and upcoming fixtures. Kenya's
local bookmakers (Sportybet, Odibets, Betway KE) are a deliberate target for
price comparison but expose no public APIs.

## Decision

- **football-data.co.uk** is the primary historical corpus. Free CSVs per
  league/season with results, match stats, and opening *and closing* odds
  (Bet365, Pinnacle, plus market average and max) for the big European
  leagues. Ingested into DuckDB at `data/tipster.duckdb`, with raw CSVs
  cached under `data/raw/`. The `data/` directory is never committed.
- **The Odds API** supplies live odds (free tier, 500 requests/month;
  Betway is covered, local books are not). Key goes in `.env` via
  `THE_ODDS_API_KEY`.
- **football-data.org v4** stays the fixture/lineup source for the scheduled
  predictor service, continuing the earlier scaffold's decision (ADR 0002 in
  the template repo).
- **Understat / FBref** xG data is deferred to the feature-engineering phase.
- **Local bookmaker odds** enter as manual snapshots through the UI
  (phase 4); scraping local sites is explicitly out of scope until separately
  decided.

## Consequences

- A backtest corpus covering 2024/25 onward is available in minutes, and
  Pinnacle closing odds make CLV measurable — our primary honesty metric.
- Free-tier limits mean live odds are polled sparingly (fixtures close to
  kickoff), not continuously.
- Licensing: football-data.co.uk data is for personal use; we ingest at
  runtime and redistribute nothing, which also keeps the repo data-free.
- Column formats drift between seasons, so the parser treats odds columns as
  optional and normalises aggressively (ADR 0003's backtests depend on this).
