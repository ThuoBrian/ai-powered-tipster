# 0007 — Live odds ingestion: The Odds API

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

ADR 0002 committed to The Odds API for live odds but left the integration
unspecified. Building it (`tipster_core.ingest.odds_api`) surfaced decision
content:

- The Odds API's `h2h` (moneyline) market returns per-bookmaker outcomes
  keyed by team name plus `"Draw"`, not the four named sources
  (`b365`/`pinnacle`/`avg`/`max`) `MatchOdds` already models for
  football-data.co.uk history — coverage varies by fixture and region, and
  a specific bookmaker (e.g. Bet365) is sometimes entirely absent from a
  given event's response.
- The free tier is 500 requests/month (ADR 0002); a naive per-fixture or
  polling design burns quota fast for no benefit — European top-flight
  fixtures don't reprice minute to minute the way the design doc's polling
  language implies.
- The API's team names are its own (`"Man City"`, `"Spurs"`, etc.) and are
  not guaranteed to match football-data.co.uk's naming, which the historical
  corpus and the model are trained on.
- `ValueTip`'s odds-source ladder (ADR 0006) and `MatchOdds`'s shape are
  already fixed; live ingestion needs to produce that same shape, not a new
  one, or the value engine would need two code paths.

## Decision

**Reuse `MatchOdds`/`Fixture` as the output shape**, populated as follows
per fixture:

- `pinnacle` / `b365` — read directly from those bookmaker keys when The
  Odds API includes them for that fixture; `None` otherwise.
- `avg` — the mean price per outcome across every bookmaker that returned a
  complete 3-way price for that fixture (mirrors football-data.co.uk's own
  "market average" semantics).
- `max` — the best price per outcome across the same set (mirrors
  football-data.co.uk's "market max").
- Closing-odds fields are always `None` — live ingestion has no concept of
  a closing line until kickoff has passed.

A bookmaker missing the draw price, or quoting a price ≤ 1.0 (never valid
for decimal odds — a data glitch), is dropped entirely rather than partially
trusted. A fixture with zero usable bookmaker prices is dropped from the
output — there is nothing to devig or price against.

**One request per league, not per fixture.** `fetch_odds(league, api_key)`
hits `GET /v4/sports/{sport_key}/odds` once and gets every upcoming fixture
for that league in the response. `fetch_live_odds` (the orchestration layer,
`tipster_core.ingest.pipeline`) caches the raw JSON under
`data/raw/live_odds/{league}.json` and defaults to `refresh=True` (unlike
`ingest_season`'s CSV cache, which defaults to reuse) — a live snapshot
goes stale immediately, so overwriting is the safe default; `refresh=False`
replays the cache for development without spending quota.

**Team names pass through unnormalised.** No effort is made in this ADR to
reconcile The Odds API's naming with football-data.co.uk's. This is a real
gap for anything that needs to join live odds against historical form (the
model's feature builder keys off exact team names) — flagged as a known
consequence, not solved here.

**`tipster-odds` is a separate CLI**, not a flag on `tipster-ingest`: live
odds are never written to the `matches` DuckDB table (that table is played
history), so the two commands have no shared state to justify merging.

## Consequences

- The value engine (`tipster_core.value.find_value_tips`) works unmodified
  against live odds — it only ever sees `MatchOdds`, regardless of source.
- Quota discipline is structural: one call fetches a whole league, and nothing
  in this layer loops or polls on its own. A future scheduler (the predictor
  service, phase 3) still has to be deliberate about how often it calls
  `fetch_live_odds`.
- The team-name gap means live tips can be generated and priced today, but
  automatically joining a live fixture to its model prediction (which is
  keyed by the feature builder's team names) needs a name-reconciliation
  step before that wiring happens — likely the first task when building the
  Streamlit value-finder page.
- `avg`/`max` quality depends on how many bookmakers The Odds API's `regions`
  parameter returns for a given fixture; thin coverage (one or two books)
  makes `avg` and `max` nearly identical and less meaningful as a "devig
  against the market" reference. Not a defect, just a limit of the free
  tier worth remembering when reading tip output.
