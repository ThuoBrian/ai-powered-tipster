# 0009 — Paper-trading bet log

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

`docs/design.md` already commits to the shape of this: "everything is
paper-traded and logged (SQLite bet log) until CLV says otherwise," and
fractional Kelly runs "with flat staking alongside as the control arm."
Building it (`tipster_core.bet_log`) surfaced the decision content that was
still open:

- A bet is logged from the Value Finder UI at pricing time (model
  probability, market-fair probability, odds, EV, Kelly stake) but can only
  be *settled* later, once the real match has been played and re-ingested.
  The log needs a clean pending → settled lifecycle, not a single insert.
- The walk-forward backtest already judges arms against each other on ROI
  and CLV (ADR 0005); the bet log should let live paper-trading be judged
  the same way, Kelly vs. flat, rather than inventing a different metric
  vocabulary.
- Re-clicking "log this tip" in the UI (a double-click, or revisiting the
  same fixture across reruns) must not silently duplicate a bet.
- Settlement needs the closing price to compute CLV, which only exists in
  the historical corpus's closing-odds columns (ADR 0005's odds coverage
  gap: 1X2 only) — the same limitation that already bounds the backtest's
  ROI/CLV.

## Decision

**SQLite** (Python's stdlib `sqlite3`, no new dependency), per `docs/design.md`
— a small, mostly-append ledger, deliberately a different engine than the
analytical DuckDB matches store. One table, `bets`, with a `UNIQUE(model,
league, season, match_date, home_team, away_team, pick)` constraint;
`record_bet` uses `INSERT OR IGNORE` and reports whether the row was new,
so the caller (the UI) can tell "logged" from "already logged" without a
pre-check query.

**Two stakes per row, not two tables or two arms.** Every logged bet carries
both `kelly_stake` (the fractional-Kelly sizing already computed by
`find_value_tips`, ADR 0006) and a fixed `flat_stake` (default 1.0 unit).
Settlement computes profit for both from the same row, so Kelly and flat
are always compared on the identical set of bets — no risk of the two arms
silently diverging over which bets they include.

**Settlement matches on fixture identity, not a foreign key.** `settle_bets`
takes whatever `Sequence[MatchResult]` the caller loaded (typically "every
match in the store") and joins pending bets by `(league, season, date, home
team, away team)` — the same tuple a `Fixture` carries. A bet whose match
hasn't been (re-)ingested yet is left pending; nothing is guessed or
inferred from partial data.

**CLV reuses the backtest's own ladder and formula.** `settle_bets` calls
`tipster_core.backtest.baselines.closing_odds` (the ADR 0005 closing ladder:
`pinnacle_closing → avg_closing → b365_closing → max_closing`) and
`tipster_core.backtest.metrics.clv`, rather than a third reimplementation of
either. A match with no closing odds at all (same 1X2-only coverage gap as
the backtest) settles win/loss but leaves `clv_pct` null — visible as "no
CLV data" in the UI, not a silently wrong number.

**Summary reuses `RoiSummary`/`ClvSummary`** from `tipster_core.backtest.results`
instead of a new duplicate shape, so a live paper-trading summary and a
backtest arm's summary are structurally the same thing.

## Consequences

- The bet log has zero opinion about *which* tips get logged — that's the
  UI's job (currently: check a box, click "log"). This module only
  guarantees idempotent recording and honest settlement.
- Kelly and flat ROI can diverge meaningfully once enough bets settle; that
  divergence is the whole point of running both, per `docs/design.md`.
- CLV coverage on the live bet log inherits the same 1X2-only gap ADR 0005
  already flagged for the backtest — it lifts automatically once richer
  odds are ingested, no bet-log change needed.
- Nothing here closes the loop automatically: a scheduled job (or a human
  running `make settle-bets` / clicking "Settle pending bets now") still has
  to trigger settlement after `make ingest` picks up newly played fixtures.
