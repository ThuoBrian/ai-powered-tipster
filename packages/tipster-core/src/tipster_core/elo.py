"""Per-league Elo ratings (ADR 0003).

Rating pools are keyed ``(league, team)`` and are never merged across
leagues — a team's rating in one league says nothing about its rating in
another. The update rule is the World-Football-Elo style: the K factor is
scaled by the margin of victory, so a 3-0 win moves ratings more than a
2-1 win.
"""

from __future__ import annotations

import polars as pl

from tipster_core.leagues import LeagueCode

#: An (league, team) key into the rating pools.
type TeamKey = tuple[LeagueCode, str]

_START = 1500.0
_HOME_ADVANTAGE = 75.0
_BASE_K = 20.0


def expected_score(elo_a: float, elo_b: float) -> float:
    """The expected score (win probability, draw = 0.5) of *a* against *b*."""
    return float(1.0 / (1.0 + 10.0 ** (-(elo_a - elo_b) / 400.0)))


def k_multiplier(goal_difference: int) -> float:
    """The margin-of-victory multiplier applied to the base K factor."""
    abs_gd = abs(goal_difference)
    if abs_gd <= 1:
        return 1.0
    if abs_gd == 2:
        return 1.5
    return (11.0 + abs_gd) / 8.0


def _points(home_goals: int, away_goals: int) -> tuple[float, float]:
    """Home/away scores: win = 1, draw = 0.5, loss = 0."""
    if home_goals > away_goals:
        return 1.0, 0.0
    if home_goals < away_goals:
        return 0.0, 1.0
    return 0.5, 0.5


class EloBook:
    """Ratings replayed chronologically over a frame of matches.

    :meth:`attach` is the bulk entry point: it returns pre-match ratings for
    every row. A row's snapshot is the rating state at the *end of the
    previous day* — the strict ``date <`` cutoff every feature obeys — so a
    row never sees same-day or later matches, and fixture rows (null goals)
    never contribute to the replay at all.
    """

    def __init__(
        self,
        start: float = _START,
        home_advantage: float = _HOME_ADVANTAGE,
        base_k: float = _BASE_K,
    ) -> None:
        self.start = start
        self.home_advantage = home_advantage
        self.base_k = base_k
        self.ratings: dict[TeamKey, float] = {}

    def _rating(self, key: TeamKey) -> float:
        return self.ratings.get(key, self.start)

    def apply(
        self, league: LeagueCode, home_team: str, away_team: str, home_goals: int, away_goals: int
    ) -> None:
        """Update both teams' ratings after one played match."""
        home_key = (league, home_team)
        away_key = (league, away_team)
        home_elo = self._rating(home_key)
        away_elo = self._rating(away_key)

        expected_home = expected_score(home_elo + self.home_advantage, away_elo)
        score_home, score_away = _points(home_goals, away_goals)
        k = self.base_k * k_multiplier(home_goals - away_goals)

        self.ratings[home_key] = home_elo + k * (score_home - expected_home)
        self.ratings[away_key] = away_elo + k * (score_away - (1.0 - expected_home))

    def attach(self, matches: pl.DataFrame) -> pl.DataFrame:
        """Return the input frame with pre-match ratings for every row.

        Requires ``league, date, home_team, away_team, home_goals,
        away_goals`` — the goal columns may be null (fixture rows), in
        which case the row is snapshotted but never applied to the replay.
        Rows are processed by date; all rows on a date are snapshotted
        *before* that date's matches are applied, enforcing the strict
        ``date <`` rule. Returns the input columns plus ``home_elo_pre`` /
        ``away_elo_pre`` and ``row_id`` (the input position) for joins.
        """
        required = {"league", "date", "home_team", "away_team", "home_goals", "away_goals"}
        missing = required - set(matches.columns)
        if missing:
            msg = f"missing columns for Elo replay: {sorted(missing)}"
            raise ValueError(msg)

        indexed = matches.with_row_index("row_id")
        if indexed.height == 0:
            return indexed.with_columns(
                home_elo_pre=pl.lit(self.start, dtype=pl.Float64),
                away_elo_pre=pl.lit(self.start, dtype=pl.Float64),
            )

        snapshots: list[dict[str, float | int]] = []
        by_day = indexed.sort("date").group_by("date", maintain_order=True)
        for (_day,), day_rows in by_day:
            for row in day_rows.iter_rows(named=True):
                league = LeagueCode.from_code(row["league"])
                snapshots.append(
                    {
                        "row_id": row["row_id"],
                        "home_elo_pre": self._rating((league, row["home_team"])),
                        "away_elo_pre": self._rating((league, row["away_team"])),
                    }
                )
            for row in day_rows.iter_rows(named=True):
                if row["home_goals"] is None or row["away_goals"] is None:
                    continue  # fixture row: snapshot only, never applied
                self.apply(
                    LeagueCode.from_code(row["league"]),
                    row["home_team"],
                    row["away_team"],
                    row["home_goals"],
                    row["away_goals"],
                )

        elo_frame = pl.DataFrame(
            snapshots,
            schema={
                "row_id": pl.UInt32,
                "home_elo_pre": pl.Float64,
                "away_elo_pre": pl.Float64,
            },
        )
        return indexed.join(elo_frame, on="row_id", how="left")
