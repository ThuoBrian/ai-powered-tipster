# 0011 — More competitions and national-team tournaments

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

v1 covered the big-5 European leagues only. The user asked for more
matches, including international tournaments (World Cup, Euros, AFCON,
Copa América, qualifiers, Nations League). Research on 2026-09-23
confirmed three free sources:

- **football-data.co.uk main files** have 16 more divisions in the
  existing per-season format: England 2-5, Scotland 1-4, the German,
  Italian, Spanish and French second tiers, Belgium, Portugal, Turkey,
  Greece.
- **football-data.co.uk "extra" files** (`new/{CODE}.csv`) have 16 more
  countries, one file each with every season: Argentina, Austria, Brazil,
  China, Denmark, Finland, Ireland, Japan, Mexico, Norway, Poland,
  Romania, Russia, Sweden, Switzerland, USA. The format differs: `Home`,
  `Away`, `HG`, `AG`, a `Season` column that's either `2012` or
  `2012/2013`, a UTF-8 BOM, and closing odds only. The closing-odds
  column names match the main files, so the existing odds mapping reads
  them unchanged.
- **martj42/international_results** (CC0) has every national-team match
  since 1872, with a `neutral` flag. It has no odds.

Three things in the code blocked this. Seasons had to look like `2526`.
Nothing modelled a neutral venue. The UI and CLIs were hard-wired to
`BIG_5`.

## Decision

**Competitions.** `LeagueCode` gains 33 members: the 16 main divisions,
the 16 extra countries (value = file code, e.g. `BRA`) and `INT`. All
national teams form **one pool**, because they meet across tournaments
and splitting by tournament would thin already sparse data. New members
are appended, never inserted, because `features.league_code` is the enum
position.

**Seasons keep each source's native format**, which never collide because
the shapes differ: `2526` (main files), `2026` (calendar-year leagues and
`INT`), `2025/2026` (split-season extras). `validate_season` accepts all
three. `season_label(code, league)` uses the league to decide the one
ambiguous case: `2021` is the 2020/21 season in England but the year 2021
in Brazil. Bet settlement no longer matches on season, only on league,
date and teams, because a live fixture's derived season can be labelled
differently from the ingested result.

**Neutral venues.** `MatchResult` and `Fixture` gain `neutral: bool =
False`, and DuckDB gains a `neutral` column. `connect()` adds it to older
databases in write mode; read-only connections default it to `FALSE`.
Home advantage is multiplied by `(1 - neutral)` everywhere it appears:
the Elo bonus, `elo_diff`, and Dixon-Coles `gamma` in both fitting and
prediction. `neutral` is also a hybrid feature.

**Data windows.** Extra leagues keep matches from 2023 on, about the same
three seasons as the main-league default. Internationals keep matches from
2014 on: teams play 8-12 games a year, so they need a longer window.
Dixon-Coles time decay (half-life ~385 days) still weights recent form
most. Friendlies count at full weight.

**Live odds.** `SPORT_KEYS` covers 21 of the new leagues. The rest have no
Odds API feed, and the Value Finder points to Predict Fixtures (typed-in
odds) instead. Each international tournament is its own feed
(`INT_TOURNAMENTS`) with a neutral-venue default: finals yes, qualifiers
and Nations League no. The API doesn't identify host nations, so a host's
tournament games are priced as neutral. The UI lists only tournaments
that are in season, via the free `GET /v4/sports`.

**Ingest.** The default is every competition. The current season's file is
always re-downloaded. Previously a cached file was reused forever, so
`just ingest` never picked up new results and bets never settled.
All-seasons files (extras, internationals) are always re-downloaded.

**Calibration: goal markets only in the dashboard.** The first predictions
across the new leagues exposed two faults in full isotonic calibration.
Neutral games weren't symmetric, because home and away have separate
curves (Kenya v Uganda (n) ≠ Uganda v Kenya (n)). Smaller leagues also
collapsed to the base rate: every Brazil match came out 45/28/27. A
walk-forward check, raw vs calibrated Dixon-Coles, 14-day blocks from
2025/26:

| League | 1X2 log loss, raw → calibrated | Over 2.5 log loss, raw → calibrated |
|--------|------------------------------|-----------------------------------|
| E0 (410 fixtures) | **1.0429** → 1.0465 | 0.7415 → **0.6894** |
| BRA (657) | **1.0107** → 1.0202 | 0.7108 → **0.7011** |
| E1 (647) | 1.0927 → **1.0919** | 0.7298 → **0.7106** |

So the dashboard uses `CalibratedPredictor(DixonColesPredictor(),
calibrate_1x2=False)`: raw home/draw/away (symmetric, not flattened) plus
calibrated over/under and BTTS. The backtest's default arms keep full
calibration, so earlier runs stay comparable.

**First international result.** Dixon-Coles on `INT`, 450 matches from
Jan-Jul 2026 (60-day blocks, including the 2026 World Cup): 54.4% correct
result, 1X2 log loss 0.935. That's better than the leagues, because
international fixtures include more mismatches. There are no bets or CLV,
since there are no historical odds. A calibrated Dixon-Coles fit on `INT`
(301 teams) takes about 40 s once per session; it's cached.

## Consequences

- Predict Fixtures and the Value Finder work for about 40 competitions,
  including national teams.
- International predictions will be less accurate than league ones: few
  games per team, and squads that change between tournaments. With no
  historical odds, the backtest can measure `INT` hit rate and log loss
  but not ROI or CLV.
- Odds API team names for national teams haven't been seen live yet. The
  existing skip-and-warn and "did you mean" handle mismatches until
  aliases are added, as happened for La Liga (ADR 0008).
- Host nations at a neutral-flagged tournament lose their real home
  advantage. For AFCON 2027 (Kenya, Uganda, Tanzania), enter host games on
  Predict Fixtures without the `(n)` marker.
- `just ingest` downloads about 80 files. The first run takes a few
  minutes; later runs re-download only current-season and all-seasons
  files.
