"""Synthetic match corpora for model and harness tests.

Everything model-shaped runs on this generator: seeded, analytically
checkable, and never requiring network or the real ``data/tipster.duckdb``.
Goals are drawn from a ground-truth Poisson process with per-team attack /
defense strengths and a home advantage, so fitted models can be judged
against known parameters.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import polars as pl

from tipster_core.contracts import MatchOdds, MatchResult, OutcomeOdds

_TEAM_PREFIX = {"E0": "Eng", "SP1": "Esp"}


def _fair_odds(p: float) -> float:
    return 1.0 / max(p, 0.01)


def synthetic_matches(
    *,
    seed: int = 42,
    leagues: tuple[str, ...] = ("E0", "SP1"),
    n_teams: int = 10,
    n_weeks: int = 40,
    start: date = date(2024, 8, 10),
    season: str = "2425",
    home_advantage: float = 0.25,
    with_odds: bool = True,
    pinnacle_dropout: float = 0.25,
) -> pl.DataFrame:
    """A seeded round-robin corpus with ground-truth strengths.

    Teams play every ``start + 7*k`` day, round-robin pairings, Poisson goals
    from ``exp(attack_i + defense_j + home_advantage)``-style rates. With
    ``with_odds=True`` the canonical odds columns are filled from the true
    probabilities plus noise, with some sources dropped out per row.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, float | int | str | None]] = []

    for league in leagues:
        prefix = _TEAM_PREFIX.get(league, league)
        teams = [f"{prefix} Team {i:02d}" for i in range(n_teams)]
        attack = rng.uniform(-0.35, 0.35, n_teams)
        defense = rng.uniform(-0.35, 0.35, n_teams)

        for week in range(n_weeks):
            # Round-robin: rotate the tail, pair head-to-tail.
            rotation = [0] + [1 + ((week + i - 1) % (n_teams - 1)) for i in range(n_teams - 1)]
            pairings = [(rotation[k], rotation[n_teams - 1 - k]) for k in range(n_teams // 2)]
            day = start + timedelta(days=7 * week)
            for k, (i, j) in enumerate(pairings):
                home_i, away_j = (i, j) if (week + k) % 2 == 0 else (j, i)
                lambda_home = math.exp(attack[home_i] + defense[away_j] + home_advantage)
                lambda_away = math.exp(attack[away_j] + defense[home_i])
                home_goals = int(rng.poisson(lambda_home))
                away_goals = int(rng.poisson(lambda_away))

                row: dict[str, float | int | str | None] = {
                    "league": league,
                    "season": season,
                    "date": day,
                    "home_team": teams[home_i],
                    "away_team": teams[away_j],
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "source_file": f"synthetic/{league}-{season}.csv",
                }
                if with_odds:
                    # True 1X2 probabilities from a rho=0 Poisson grid.
                    p_home = sum(
                        math.exp(-lambda_home)
                        * lambda_home**a
                        / math.factorial(a)
                        * math.exp(-lambda_away)
                        * lambda_away**b
                        / math.factorial(b)
                        for a in range(6)
                        for b in range(6)
                        if a > b
                    )
                    p_draw = sum(
                        math.exp(-lambda_home)
                        * lambda_home**a
                        / math.factorial(a)
                        * math.exp(-lambda_away)
                        * lambda_away**a
                        / math.factorial(a)
                        for a in range(6)
                    )
                    p_away = 1.0 - p_home - p_draw
                    noise = rng.uniform(-0.05, 0.05, 3)
                    probs = (
                        max(p_home + noise[0], 0.02),
                        max(p_draw + noise[1], 0.02),
                        max(p_away + noise[2], 0.02),
                    )
                    total = sum(probs)
                    probs = tuple(p / total for p in probs)

                    for source, margin in (
                        ("b365", 0.06),
                        ("pinnacle", 0.02),
                        ("avg", 0.04),
                        ("max", 0.05),
                    ):
                        for suffix, p in (("h", probs[0]), ("d", probs[1]), ("a", probs[2])):
                            row[f"odds_{source}_{suffix}"] = _fair_odds(p) * (1.0 + margin)
                            row[f"odds_{source}_c_{suffix}"] = _fair_odds(p) * (1.0 + margin * 0.5)
                    if rng.random() < pinnacle_dropout:
                        for suffix in ("h", "d", "a"):
                            row[f"odds_pinnacle_{suffix}"] = None
                            row[f"odds_pinnacle_c_{suffix}"] = None
                rows.append(row)

    schema = {
        "league": pl.String,
        "season": pl.String,
        "date": pl.Date,
        "home_team": pl.String,
        "away_team": pl.String,
        "home_goals": pl.Int64,
        "away_goals": pl.Int64,
        "source_file": pl.String,
        **{
            f"odds_{source}{closing}_{outcome}": pl.Float64
            for source in ("b365", "pinnacle", "avg", "max")
            for closing in ("", "_c")
            for outcome in ("h", "d", "a")
        },
    }
    frame = pl.DataFrame(rows)
    # Reorder to canonical storage order.
    canonical = (
        "league",
        "season",
        "date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "source_file",
        *(
            f"odds_{source}{closing}_{outcome}"
            for source in ("b365", "pinnacle", "avg", "max")
            for closing in ("", "_c")
            for outcome in ("h", "d", "a")
        ),
    )
    ordered = frame.select(*[name for name in canonical if name in frame.columns])
    return ordered.cast({name: schema[name] for name in ordered.columns})


def _outcome_odds(row: dict[str, object], prefix: str) -> OutcomeOdds | None:
    """The three 1X2 odds for one source prefix, or None if any is missing."""
    home, draw, away = row[f"odds_{prefix}_h"], row[f"odds_{prefix}_d"], row[f"odds_{prefix}_a"]
    if home is None or draw is None or away is None:
        return None
    return OutcomeOdds(home=float(home), draw=float(draw), away=float(away))


def to_match_results(frame: pl.DataFrame, *, with_odds: bool = True) -> list[MatchResult]:
    """Convert a synthetic frame into validated ``MatchResult`` objects."""
    results: list[MatchResult] = []
    for row in frame.iter_rows(named=True):
        odds: MatchOdds | None = None
        if with_odds and "odds_b365_h" in frame.columns:
            odds = MatchOdds(
                b365=_outcome_odds(row, "b365"),
                pinnacle=_outcome_odds(row, "pinnacle"),
                avg=_outcome_odds(row, "avg"),
                max=_outcome_odds(row, "max"),
                b365_closing=_outcome_odds(row, "b365_c"),
                pinnacle_closing=_outcome_odds(row, "pinnacle_c"),
                avg_closing=_outcome_odds(row, "avg_c"),
                max_closing=_outcome_odds(row, "max_c"),
            )
        results.append(
            MatchResult(
                league=row["league"],
                season=row["season"],
                date=row["date"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_goals=row["home_goals"],
                away_goals=row["away_goals"],
                odds=odds,
            )
        )
    return results
