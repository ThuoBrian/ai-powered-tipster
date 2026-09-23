# 0008 — Team-name reconciliation for live odds

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

ADR 0007 shipped live-odds ingestion but explicitly left team-name
reconciliation unsolved: The Odds API uses each club's full/official name
(`"Manchester United"`, `"Borussia Mönchengladbach"`), while
football-data.co.uk — and therefore every model feature keyed on team
identity (rolling form, per-league Elo) — uses its own short-form
convention (`"Man United"`, `"M'gladbach"`). Wiring live odds to real model
predictions needs this solved, or every live fixture looks like a brand-new
team with no history to the feature builder.

This repo has not made a live call to The Odds API (no key configured in
this environment), so there is no way to build or verify the mapping against
real responses right now.

## Decision

**`tipster_core.team_aliases`** is a static `(league, Odds-API-name) ->
football-data.co.uk-name` lookup table, seeded from general football-naming
knowledge (short forms, legal-entity prefixes like "1. FC", diacritics) for
the big five leagues. `resolve_team_name(league, name)` returns the mapped
name, or the input unchanged when nothing is registered.

**Unverified by construction.** No entry in this table has been checked
against an actual Odds API response — there is no key to check it with. The
module docstring and this ADR say so explicitly, and it is treated as a
starting point, not a finished mapping.

**Silent passthrough on a miss.** An unmapped name and an already-matching
name are indistinguishable to the caller — both just pass through
unchanged. This is deliberate (most teams' names already match, e.g.
`"Arsenal"`, `"Liverpool"`, so raising on every non-hit would be far too
noisy) but it means a genuinely wrong or missing alias fails silently: the
fixture still gets a `Fixture`/`MatchOdds` pair and a model prediction, just
one built from zero history for that team, treated as a cold start rather
than an error.

**Applied at ingestion, not at the value engine.** `odds_api.parse_odds_response`
resolves both team names before constructing the `Fixture`; bookmaker price
lookups still use the API's original names internally (that's what the
API's own outcome objects are keyed by), so resolution never touches price
correctness — only fixture identity.

## Consequences

- Live odds can now join to real model predictions for any team whose alias
  is both needed and correctly seeded — unblocking end-to-end tips.
- The unverified/silent-passthrough combination is a real risk: a wrong or
  missing alias produces a *confidently wrong* prediction (cold-start
  features treated as normal), not a visible failure. The Streamlit
  value-finder page (next slice) should surface a per-fixture "matched to
  history" signal — e.g. checking whether the resolved team name appears in
  the historical corpus at all — rather than trusting this table blindly.
- The table needs a first real-data pass the moment a `THE_ODDS_API_KEY` is
  available: run `tipster-odds`, diff the raw team names against
  `tipster_core.storage.load_matches`'s distinct team names per league, and
  correct any misses found.
- Scope is the big five leagues only, matching `docs/design.md`'s v1 scope;
  Eredivisie (ingestable per ADR 0007 but outside v1 scope) has no aliases
  yet.
