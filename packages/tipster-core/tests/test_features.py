"""Feature builder tests — the leakage suite is the anchor.

Every test here enforces one rule: a fixture on date *d* sees only matches
with ``date < d``. Zero tolerance for exceptions.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest
from synthetic import synthetic_matches

from tipster_core.features import (
    FEATURE_COLUMNS,
    FeatureConfig,
    build_features,
    build_training_features,
)


@pytest.fixture
def corpus() -> pl.DataFrame:
    """A small two-league synthetic corpus (deterministic)."""
    return synthetic_matches(seed=7, leagues=("E0", "SP1"), n_teams=8, n_weeks=20)


def _history_like(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select("league", "date", "home_team", "away_team", "home_goals", "away_goals")


def test_columns_and_order(corpus: pl.DataFrame) -> None:
    features = build_features(_history_like(corpus), _history_like(corpus))
    assert features.height == corpus.height
    assert list(features.columns) == [
        "fixture_id",
        "league",
        "date",
        "home_team",
        "away_team",
        *FEATURE_COLUMNS,
    ]
    # Output preserves input row order.
    assert features["fixture_id"].to_list() == list(range(corpus.height))
    assert features["home_team"].to_list() == corpus["home_team"].to_list()


def test_leakage_truncated_history_is_identical(corpus: pl.DataFrame) -> None:
    """Features for a fixture must not change when future matches exist."""
    history = _history_like(corpus)
    cut = date(2024, 9, 21)  # ~6 weeks in
    fixtures = history.filter(pl.col("date") == cut)
    assert fixtures.height > 0

    before = build_features(history.filter(pl.col("date") < cut), fixtures)
    after = build_features(history, fixtures)
    assert before.equals(after)


def test_leakage_fixture_goals_never_contribute(corpus: pl.DataFrame) -> None:
    """Perturbing a match's own goals must not change its features."""
    history = _history_like(corpus)
    last_day = history["date"].max()
    fixtures = history.filter(pl.col("date") == last_day)
    baseline = build_features(history, fixtures)

    # Corrupt every goal on the fixtures' own day — invisible by the
    # strict date < fixture_date rule.
    mutated = history.with_columns(
        home_goals=pl.when(pl.col("date") == last_day).then(9).otherwise(pl.col("home_goals")),
    )
    mutated_features = build_features(mutated, fixtures)
    assert baseline.select(FEATURE_COLUMNS).equals(mutated_features.select(FEATURE_COLUMNS))


def test_leakage_same_day_matches_invisible(corpus: pl.DataFrame) -> None:
    """A fixture must not see other matches played on its own date."""
    history = _history_like(corpus)
    day = history["date"].min() + timedelta(days=21)
    while day not in set(history["date"].to_list()):
        day += timedelta(days=7)
    fixtures = history.filter(pl.col("date") == day)

    truncated = history.filter(pl.col("date") < day)
    full = build_features(history, fixtures)
    partial = build_features(truncated, fixtures)
    assert full.select(FEATURE_COLUMNS).equals(partial.select(FEATURE_COLUMNS))


def test_rest_days_across_gap() -> None:
    history = pl.DataFrame(
        {
            "league": ["E0", "E0", "E0"],
            "date": [date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 18)],
            "home_team": ["Arsenal", "Spurs", "Arsenal"],
            "away_team": ["Spurs", "Chelsea", "Chelsea"],
            "home_goals": [1, 2, 3],
            "away_goals": [1, 0, 0],
        }
    )
    fixtures = pl.DataFrame(
        {
            "league": ["E0"],
            "date": [date(2025, 1, 25)],
            "home_team": ["Arsenal"],
            "away_team": ["Chelsea"],
        }
    )
    features = build_features(history, fixtures)
    # Arsenal last played Jan 18 -> 7 rest days; Chelsea also Jan 18 -> 7.
    assert features["home_rest_days"][0] == 7.0
    assert features["away_rest_days"][0] == 7.0
    assert features["home_matches_played"][0] == 2


def test_cold_start_defaults() -> None:
    history = pl.DataFrame(
        {
            "league": ["E0", "E0"],
            "date": [date(2025, 1, 4), date(2025, 1, 11)],
            "home_team": ["Arsenal", "Arsenal"],
            "away_team": ["Spurs", "Chelsea"],
            "home_goals": [2, 1],
            "away_goals": [0, 1],
        }
    )
    # A brand-new team: everything falls back to priors and defaults.
    fixtures = pl.DataFrame(
        {
            "league": ["E0"],
            "date": [date(2025, 1, 18)],
            "home_team": ["Newcomers"],
            "away_team": ["Chelsea"],
        }
    )
    config = FeatureConfig()
    features = build_features(history, fixtures, config)
    row = features.row(0, named=True)
    assert row["home_matches_played"] == 0
    assert row["home_rest_days"] == config.default_rest_days
    assert row["home_elo"] == config.elo_start
    # Chelsea played once: scored 1, conceded 1 -> both means 1.0.
    assert features["away_scored_form"][0] == pytest.approx(1.0)
    assert features["away_conceded_form"][0] == pytest.approx(1.0)


def test_cold_start_prior_uses_only_pre_date_matches() -> None:
    history = pl.DataFrame(
        {
            "league": ["E0", "E0"],
            "date": [date(2025, 1, 4), date(2025, 1, 18)],
            "home_team": ["Arsenal", "Arsenal"],
            "away_team": ["Spurs", "Spurs"],
            "home_goals": [2, 10],
            "away_goals": [0, 10],
        }
    )
    fixtures = pl.DataFrame(
        {
            "league": ["E0"],
            "date": [date(2025, 1, 11)],
            "home_team": ["Newcomers"],
            "away_team": ["AlsoNew"],
        }
    )
    config = FeatureConfig()
    features = build_features(history, fixtures, config)
    # League prior from Jan 4 only: total goals 2 -> per-team average 1.0.
    assert features["home_scored_form"][0] == pytest.approx(1.0)
    # The 20-goal shootout on Jan 18 must be invisible.
    assert features["home_conceded_form"][0] == pytest.approx(1.0)


def test_elo_diff_includes_home_advantage(corpus: pl.DataFrame) -> None:
    history = _history_like(corpus)
    features = build_features(history, history.head(50))
    config = FeatureConfig()
    expected = features["home_elo"] + config.elo_home_advantage - features["away_elo"]
    assert features["elo_diff"].equals(expected)


def test_training_features_carry_targets(corpus: pl.DataFrame) -> None:
    frame = _history_like(corpus)
    training = build_training_features(frame)
    assert training.height == frame.height
    assert training["home_goals"].to_list() == frame["home_goals"].to_list()
    assert training["away_goals"].to_list() == frame["away_goals"].to_list()
    # Train/predict parity: predicting a match from history-only reproduces
    # its training feature row exactly.
    predictions = build_features(frame, frame)
    assert training.drop("home_goals", "away_goals").equals(predictions.drop("fixture_id"))


def test_stronger_team_rolls_higher_form() -> None:
    # A dominant team should show high scored form and low conceded form.
    rows = {
        "league": ["E0"] * 12,
        "date": [date(2025, 1, 4) + timedelta(days=7 * i) for i in range(12)],
        "home_team": ["Strong"] * 12,
        "away_team": [f"Weak{i % 3}" for i in range(12)],
        "home_goals": [3] * 12,
        "away_goals": [0] * 12,
    }
    history = pl.DataFrame(rows)
    fixtures = history.filter(pl.col("date") == history["date"].max())
    features = build_features(history, fixtures)
    assert features["home_scored_form"][0] == pytest.approx(3.0)
    assert features["home_conceded_form"][0] == pytest.approx(0.0)
    assert features["home_points_form"][0] == pytest.approx(3.0)
    assert features["home_elo"][0] > features["away_elo"][0]
