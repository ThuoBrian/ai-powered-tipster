# 0006 — Phase 2 value engine: Shin devig, EV, Kelly

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

`docs/design.md` already commits to the shape of the value engine — devig
bookmaker odds with Shin's method, compute `EV = p_model * odds - 1`, size
stakes with fractional Kelly — but building it (`tipster_core.value`)
surfaced decision content the design doc left implicit:

- Shin's method has no closed form; it requires solving for the insider
  trading rate `z` that makes the devigged probabilities sum to 1, and the
  root-find needs bounds and a fallback for degenerate books.
- ADR 0005 already established that the store carries 1X2 odds only (no
  over/under or BTTS prices), and an opening-odds fallback ladder
  (`pinnacle → avg → b365 → max`) for picking a price when a preferred
  source is missing. The value engine needs the same kind of choice for
  live tips, not just backtest settlement.
- EV and devig serve different purposes: EV is paid at the actual bookmaker
  price, so it must use raw (vigged) odds, never the devigged fair price —
  devig only tells you whether the market disagrees with the model, EV
  tells you what you get paid for that disagreement.
- Kelly staking needs a default fraction and a hard cap so a single mispriced
  edge can't size an unreasonable bet.

## Decision

**`tipster_core.value`** is a pure-function module (no I/O, no framework
imports) with one public contract, `ValueTip`:

- **`shin_probabilities(odds)`** solves for `z` via bounded root-finding
  (`scipy.optimize.brentq` over `(0, 1)`) and returns fair `(home, draw,
  away)` probabilities. A book with no overround (`market_sum <= 1`, rare,
  e.g. stale prices) short-circuits to `z = 0` — there is no insider premium
  to correct for. The result is always renormalized to sum to 1.
- **`expected_value(p_model, odds)`** uses the raw bookmaker price, per
  `docs/design.md`'s formula — never the devigged one.
- **`kelly_fraction(p_model, odds, fraction=0.25, cap=0.05)`** computes full
  Kelly, floors negative-EV picks to zero stake (never shorts a market),
  scales by `fraction` (quarter-Kelly default, matching `docs/design.md`),
  and hard-caps the result.
- **Odds selection** reuses ADR 0005's ladder order (`pinnacle → avg → b365
  → max`) as the default when no source is requested; an explicit `source`
  that isn't populated returns no tips rather than silently falling back.
- **`find_value_tips(...)`** is 1X2-only for now, scoped to the odds the
  store actually carries (ADR 0005) — extending to over/under and BTTS is
  odds-ingestion work, not a value-engine change.

## Consequences

- The module is fully unit-testable without a database, an API key, or a
  fitted model — every function takes typed inputs and returns typed
  outputs, matching the rest of `tipster-core`.
- `ValueTip` is now the contract the Phase 2 UI (value finder) and bet log
  will consume; it carries both `p_market_fair` (for explaining the edge)
  and `odds`/`odds_source` (for settlement), so neither downstream consumer
  needs to recompute devig.
- 1X2-only staking means the value engine's coverage is bounded by the same
  odds gap ADR 0005 already flagged for ROI/CLV; it lifts automatically once
  richer odds are ingested, no interface change needed.
- An early implementation bug is worth recording: the Shin root-find's inner
  probability function cannot special-case `z = 0` to the naive proportional
  devig
  (`p_i / market_sum`) — the correct limit is `p_i / sqrt(market_sum)`.
  Conflating the two makes the root-find see `f(0) == 0` unconditionally and
  silently skip the correction, producing plain proportional devig with no
  error raised. Caught by a property test (`shin` must shift the favourite's
  share up and the longshot's down relative to proportional devig) — a pure
  "sums to 1" test would not have caught it, since proportional devig also
  sums to 1.
