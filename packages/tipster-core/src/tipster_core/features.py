"""The feature builder (ADR 0003): engineered features from match history.

Every feature for a fixture on date *d* is computed from matches with
``date < d`` — strict inequality, no exceptions. That single rule makes the
builder safe for both training (a match never sees itself or its day) and
prediction (a fixture never sees anything from its day onwards), and it
means training features and prediction features are produced by the *same*
code path: training is just ``build_features(matches, matches)``.

Feature list (18, home perspective — away side mirrors):

- ``{side}_scored_form`` / ``{side}_conceded_form``: mean goals over the
  side's last ``form_window`` matches (any venue)
- ``{side}_points_form``: points per game over the same window
- ``home_home_scored`` / ``home_home_conceded``: the home team's means over
  its last ``split_window`` **home** matches; ``away_away_*`` mirrors for
  away-venue matches
- ``{side}_elo``: per-league Elo (:mod:`tipster_core.elo`) as of the day
  before the fixture; ``elo_diff = home_elo + home_advantage - away_elo``
- ``{side}_rest_days``: days since the side's previous match
- ``{side}_matches_played``: prior-match count (lets the GBM discount
  cold-start rows toward the priors)
- ``league_code``: league identity, a LightGBM categorical

Cold start (no history): rolling stats fall back to the league's average
goals (computed only from pre-date matches), then to ``prior_goals``; Elo
falls back to ``elo_start``; rest days to ``default_rest_days``.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from tipster_core.elo import EloBook
from tipster_core.leagues import LeagueCode

_HISTORY_COLUMNS = ("league", "date", "home_team", "away_team", "home_goals", "away_goals")
_FIXTURE_COLUMNS = ("league", "date", "home_team", "away_team")

#: Canonical feature order — also the LightGBM ``feature_name`` list.
FEATURE_COLUMNS: tuple[str, ...] = (
    "home_scored_form",
    "home_conceded_form",
    "home_home_scored",
    "home_home_conceded",
    "home_points_form",
    "home_elo",
    "home_rest_days",
    "home_matches_played",
    "away_scored_form",
    "away_conceded_form",
    "away_away_scored",
    "away_away_conceded",
    "away_points_form",
    "away_elo",
    "away_rest_days",
    "away_matches_played",
    "elo_diff",
    "league_code",
)

_LEAGUE_CODE_INDEX: dict[str, int] = {member.value: i for i, member in enumerate(LeagueCode)}


@dataclass(frozen=True)
class FeatureConfig:
    """Knobs for the feature builder. Defaults tuned for ~5k match corpus."""

    form_window: int = 10
    split_window: int = 6
    elo_start: float = 1500.0
    elo_home_advantage: float = 75.0
    elo_k: float = 20.0
    default_rest_days: float = 7.0
    prior_goals: float = 1.4


def _validate_history(history: pl.DataFrame) -> None:
    missing = [name for name in _HISTORY_COLUMNS if name not in history.columns]
    if missing:
        msg = f"history frame is missing columns: {missing}"
        raise ValueError(msg)


def _validate_fixtures(fixtures: pl.DataFrame) -> None:
    missing = [name for name in _FIXTURE_COLUMNS if name not in fixtures.columns]
    if missing:
        msg = f"fixtures frame is missing columns: {missing}"
        raise ValueError(msg)


def _appearances(history: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """The long view: one row per team per match, with post-match rolling stats.

    Rolling means are computed *up to and including* the row's match; the
    caller as-of joins these states onto fixtures at ``date < fixture_date``
    so a fixture's own day is never visible. ``next_day`` (match date + 1)
    is the as-of join key: ``next_day <= fixture_date`` is exactly the
    strict ``date < fixture_date`` rule.
    """
    points = (
        pl.when(pl.col("goals_for") > pl.col("goals_against"))
        .then(pl.lit(3.0))
        .when(pl.col("goals_for") < pl.col("goals_against"))
        .then(pl.lit(0.0))
        .otherwise(pl.lit(1.0))
    )
    home = history.select(
        league=pl.col("league"),
        team=pl.col("home_team"),
        app_date=pl.col("date"),
        venue=pl.lit("home"),
        goals_for=pl.col("home_goals"),
        goals_against=pl.col("away_goals"),
    ).with_columns(points=points)
    away = history.select(
        league=pl.col("league"),
        team=pl.col("away_team"),
        app_date=pl.col("date"),
        venue=pl.lit("away"),
        goals_for=pl.col("away_goals"),
        goals_against=pl.col("home_goals"),
    ).with_columns(points=points)
    appearances = pl.concat([home, away]).sort("app_date", "league", "team", "venue")

    over = ["league", "team"]
    form = appearances.with_columns(
        pl.col("goals_for")
        .rolling_mean(config.form_window, min_samples=1)
        .over(over)
        .alias("scored_form"),
        pl.col("goals_against")
        .rolling_mean(config.form_window, min_samples=1)
        .over(over)
        .alias("conceded_form"),
        pl.col("points")
        .rolling_mean(config.form_window, min_samples=1)
        .over(over)
        .alias("points_form"),
        pl.int_range(pl.len()).over(over).add(1).alias("matches_played"),
        next_day=pl.col("app_date") + pl.duration(days=1),
    )

    # Venue splits: rolling means over only the team's home (resp. away)
    # matches, feeding the home-side (resp. away-side) split features.
    splits = [
        (
            form.filter(pl.col("venue") == venue)
            .with_columns(
                pl.col("goals_for")
                .rolling_mean(config.split_window, min_samples=1)
                .over(over)
                .alias("venue_scored"),
                pl.col("goals_against")
                .rolling_mean(config.split_window, min_samples=1)
                .over(over)
                .alias("venue_conceded"),
            )
            .select("league", "team", "app_date", "next_day", "venue_scored", "venue_conceded")
        )
        for venue in ("home", "away")
    ]
    return form.join(pl.concat(splits), on=["league", "team", "app_date", "next_day"], how="left")


def _league_priors(history: pl.DataFrame) -> pl.DataFrame:
    """Average goals per team per match per league, as of the start of each day.

    Used as the cold-start fallback: a team with no history inherits its
    league's scoring rate — never a number computed from same-day or later
    matches.
    """
    per_day = (
        history.with_columns(total_goals=pl.col("home_goals") + pl.col("away_goals"))
        .group_by("league", "date")
        .agg(goals=pl.col("total_goals").sum(), matches=pl.len())
        .sort("date", "league")
    )
    state = per_day.with_columns(
        cum_goals=pl.col("goals").cum_sum().over("league"),
        cum_matches=pl.col("matches").cum_sum().over("league"),
    ).with_columns(next_day=pl.col("date") + pl.duration(days=1))
    # Each day exposes its end-of-day state under next_day = date + 1: a
    # fixture on the same day cannot see it (next_day > fixture_date), and
    # a later fixture gets exactly the pre-date average.
    return state.select(
        "league",
        "next_day",
        league_avg_goals=pl.col("cum_goals") / (2.0 * pl.col("cum_matches")),
    )


def _side_features(fixtures: pl.DataFrame, form: pl.DataFrame, side: str) -> pl.DataFrame:
    """As-of join a team's rolling state onto its fixtures for one side.

    Two separate as-of joins: the overall stream (any-venue form, matches
    played, rest days) and the venue stream for this side's split features —
    ``home_home_scored`` must be the home-venue mean even when the team's
    most recent match was away, which a single join on the latest
    appearance cannot guarantee.
    """
    team_col = "home_team" if side == "home" else "away_team"
    venue = "home" if side == "home" else "away"
    prefixed = fixtures.select(
        "fixture_id",
        league=pl.col("league"),
        team=pl.col(team_col),
        date=pl.col("date"),
    ).sort("date")

    overall = form.select(
        "league",
        "team",
        "app_date",
        "next_day",
        "scored_form",
        "conceded_form",
        "points_form",
        "matches_played",
    ).sort("next_day")
    joined = prefixed.join_asof(
        overall,
        left_on="date",
        right_on="next_day",
        by=["league", "team"],
        strategy="backward",
    )

    stream = (
        form.filter(pl.col("venue") == venue)
        .select(
            "league",
            "team",
            venue_next_day=pl.col("next_day"),
            venue_scored=pl.col("venue_scored"),
            venue_conceded=pl.col("venue_conceded"),
        )
        .sort("venue_next_day")
    )
    joined = joined.join_asof(
        stream,
        left_on="date",
        right_on="venue_next_day",
        by=["league", "team"],
        strategy="backward",
    )

    return joined.select(
        "fixture_id",
        pl.col("scored_form").alias(f"{side}_scored_form"),
        pl.col("conceded_form").alias(f"{side}_conceded_form"),
        pl.col("points_form").alias(f"{side}_points_form"),
        pl.col("venue_scored").alias(f"{side}_{venue}_scored"),
        pl.col("venue_conceded").alias(f"{side}_{venue}_conceded"),
        pl.col("matches_played").alias(f"{side}_matches_played"),
        (pl.col("date") - pl.col("app_date"))
        .dt.total_days()
        .cast(pl.Float64)
        .alias(f"{side}_rest_days"),
    )


def _elo_features(
    history: pl.DataFrame, fixtures: pl.DataFrame, config: FeatureConfig
) -> pl.DataFrame:
    """Pre-fixture Elo ratings via a single chronological replay.

    Fixture rows are appended to the replay with null goals so each one's
    snapshot is the end-of-previous-day state (see :meth:`EloBook.attach`).
    """
    # pl.concat matches columns by position — both sides use the exact
    # same order: fixture_id, identity, goals, kind.
    replay = pl.concat(
        [
            history.select(
                fixture_id=pl.lit(0, dtype=pl.UInt32),
                league=pl.col("league"),
                date=pl.col("date"),
                home_team=pl.col("home_team"),
                away_team=pl.col("away_team"),
                home_goals=pl.col("home_goals"),
                away_goals=pl.col("away_goals"),
                kind=pl.lit("history"),
            ),
            fixtures.select(
                "fixture_id",
                league=pl.col("league"),
                date=pl.col("date"),
                home_team=pl.col("home_team"),
                away_team=pl.col("away_team"),
                home_goals=pl.lit(None, dtype=pl.Int64),
                away_goals=pl.lit(None, dtype=pl.Int64),
                kind=pl.lit("fixture"),
            ),
        ],
        how="vertical_relaxed",
    )
    attached = EloBook(
        start=config.elo_start,
        home_advantage=config.elo_home_advantage,
        base_k=config.elo_k,
    ).attach(replay)
    return (
        attached.filter(pl.col("kind") == "fixture")
        .select(
            "fixture_id",
            home_elo=pl.col("home_elo_pre"),
            away_elo=pl.col("away_elo_pre"),
        )
        .sort("fixture_id")
    )


def build_features(
    history: pl.DataFrame, fixtures: pl.DataFrame, config: FeatureConfig | None = None
) -> pl.DataFrame:
    """Build the feature frame for *fixtures* from *history*.

    The output keeps the input row order and adds a ``fixture_id`` (the
    input position), the fixture identity columns, and
    :data:`FEATURE_COLUMNS`. *history* and *fixtures* may overlap — each
    fixture still only sees matches strictly before its date.
    """
    config = config or FeatureConfig()
    _validate_history(history)
    _validate_fixtures(fixtures)

    identity = fixtures.with_row_index("fixture_id")
    if identity.height == 0:
        return identity.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(name)
            for name in FEATURE_COLUMNS
            if name != "league_code"
        ).with_columns(pl.lit(None, dtype=pl.Int32).alias("league_code"))

    fixture_core = identity.select("fixture_id", "league", "date", "home_team", "away_team")
    form = _appearances(history, config)

    features = (
        fixture_core.join(_side_features(fixture_core, form, "home"), on="fixture_id", how="left")
        .join(_side_features(fixture_core, form, "away"), on="fixture_id", how="left")
        .join(_elo_features(history, fixture_core, config), on="fixture_id", how="left")
    )

    # Cold start: league priors (pre-date only), then global defaults.
    features = features.sort("date").join_asof(
        _league_priors(history).sort("next_day"),
        left_on="date",
        right_on="next_day",
        by="league",
        strategy="backward",
    )

    features = features.with_columns(
        league_prior=pl.col("league_avg_goals").fill_null(config.prior_goals),
        league_code=pl.col("league").replace_strict(_LEAGUE_CODE_INDEX).cast(pl.Int32),
        home_elo=pl.col("home_elo").fill_null(config.elo_start),
        away_elo=pl.col("away_elo").fill_null(config.elo_start),
        home_rest_days=pl.col("home_rest_days").fill_null(config.default_rest_days),
        away_rest_days=pl.col("away_rest_days").fill_null(config.default_rest_days),
        home_matches_played=pl.col("home_matches_played").fill_null(0),
        away_matches_played=pl.col("away_matches_played").fill_null(0),
    )
    features = features.with_columns(
        elo_diff=pl.col("home_elo") + config.elo_home_advantage - pl.col("away_elo"),
    )
    for side in ("home", "away"):
        venue = "home" if side == "home" else "away"
        features = features.with_columns(
            pl.col(f"{side}_scored_form").fill_null(pl.col("league_prior")),
            pl.col(f"{side}_conceded_form").fill_null(pl.col("league_prior")),
            pl.col(f"{side}_points_form").fill_null(1.0),
            pl.col(f"{side}_{venue}_scored").fill_null(pl.col("league_prior")),
            pl.col(f"{side}_{venue}_conceded").fill_null(pl.col("league_prior")),
        )

    return features.select(
        "fixture_id",
        "league",
        "date",
        "home_team",
        "away_team",
        *FEATURE_COLUMNS,
    ).sort("fixture_id")


def build_training_features(
    matches: pl.DataFrame, config: FeatureConfig | None = None
) -> pl.DataFrame:
    """Featurise a played-matches frame for training, aligned row-for-row.

    Equivalent to ``build_features(matches, matches, config)`` with the
    target columns (``home_goals``, ``away_goals``) attached in input order.
    """
    config = config or FeatureConfig()
    _validate_history(matches)
    features = build_features(matches, matches, config)
    targets = matches.select("home_goals", "away_goals").with_row_index("fixture_id")
    return features.join(targets, on="fixture_id", how="left").drop("fixture_id")
