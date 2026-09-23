"""Elo engine tests: rating arithmetic and the per-league / no-leakage rules."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from tipster_core.elo import EloBook, expected_score, k_multiplier


def _frame(rows: list[tuple[str, str, str, str, int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "league": [r[0] for r in rows],
            "date": [date.fromisoformat(r[1]) for r in rows],
            "home_team": [r[2] for r in rows],
            "away_team": [r[3] for r in rows],
            "home_goals": [r[4] for r in rows],
            "away_goals": [r[5] for r in rows],
        },
        schema={
            "league": pl.String,
            "date": pl.Date,
            "home_team": pl.String,
            "away_team": pl.String,
            "home_goals": pl.Int64,
            "away_goals": pl.Int64,
        },
    )


def test_expected_score_bounds() -> None:
    # 200 Elo points = 10^(200/400) = ~2.5:1 odds, i.e. ~76% / ~24%.
    assert expected_score(1500.0, 1500.0) == pytest.approx(0.5)
    assert expected_score(1600.0, 1400.0) == pytest.approx(0.76, abs=1e-2)
    assert expected_score(1400.0, 1600.0) == pytest.approx(0.24, abs=1e-2)


def test_k_multiplier_steps() -> None:
    assert k_multiplier(0) == 1.0
    assert k_multiplier(1) == 1.0
    assert k_multiplier(-1) == 1.0
    assert k_multiplier(2) == 1.5
    assert k_multiplier(-2) == 1.5
    assert k_multiplier(3) == pytest.approx(1.75)
    assert k_multiplier(4) == pytest.approx(1.875)


def test_equal_rated_draw_changes_nothing() -> None:
    # Without home advantage a draw is exactly the expected result.
    book = EloBook(home_advantage=0.0)
    book.apply("E0", "Arsenal", "Chelsea", 1, 1)
    assert book.ratings[("E0", "Arsenal")] == pytest.approx(1500.0)
    assert book.ratings[("E0", "Chelsea")] == pytest.approx(1500.0)


def test_neutral_venue_drops_home_advantage() -> None:
    # With the default 75-point home bonus a draw costs the home side points;
    # at a neutral venue an equal-rated draw is exactly the expected result.
    home_game = EloBook()
    home_game.apply("INT", "Kenya", "Uganda", 1, 1)
    assert home_game.ratings[("INT", "Kenya")] < 1500.0

    neutral_game = EloBook()
    neutral_game.apply("INT", "Kenya", "Uganda", 1, 1, neutral=True)
    assert neutral_game.ratings[("INT", "Kenya")] == pytest.approx(1500.0)


def test_attach_reads_the_optional_neutral_column() -> None:
    frame = _frame([("INT", "2026-06-01", "Kenya", "Uganda", 1, 1)]).with_columns(
        neutral=pl.lit(True)
    )
    book = EloBook()
    book.attach(frame)
    assert book.ratings[("INT", "Kenya")] == pytest.approx(1500.0)


def test_win_moves_winner_up_and_loser_down() -> None:
    book = EloBook()
    book.apply("E0", "Arsenal", "Chelsea", 2, 1)
    assert book.ratings[("E0", "Arsenal")] > 1500.0
    assert book.ratings[("E0", "Chelsea")] < 1500.0
    # Rating change is conserved (zero-sum around the home-advantage pivot).
    delta_home = book.ratings[("E0", "Arsenal")] - 1500.0
    delta_away = book.ratings[("E0", "Chelsea")] - 1500.0
    assert delta_home + delta_away == pytest.approx(0.0, abs=1e-9)


def test_underdog_win_moves_ratings_more() -> None:
    favourite = EloBook()
    favourite.ratings[("E0", "Strong")] = 1700.0
    favourite.ratings[("E0", "Weak")] = 1300.0
    favourite.apply("E0", "Strong", "Weak", 2, 1)

    underdog = EloBook()
    underdog.ratings[("E0", "Strong")] = 1300.0
    underdog.ratings[("E0", "Weak")] = 1700.0
    underdog.apply("E0", "Strong", "Weak", 2, 1)

    # Same (absolute) margin, but the underdog win shifts far more mass.
    fav_shift = abs(favourite.ratings[("E0", "Strong")] - 1700.0)
    dog_shift = abs(underdog.ratings[("E0", "Strong")] - 1300.0)
    assert dog_shift > fav_shift


def test_goal_difference_multiplier_kicks_in() -> None:
    narrow = EloBook()
    narrow.apply("E0", "Arsenal", "Chelsea", 2, 1)
    heavy = EloBook()
    heavy.apply("E0", "Arsenal", "Chelsea", 3, 1)
    assert (heavy.ratings[("E0", "Arsenal")] - 1500.0) > (
        narrow.ratings[("E0", "Arsenal")] - 1500.0
    )


def test_leagues_keep_independent_pools() -> None:
    book = EloBook()
    book.apply("E0", "Arsenal", "Chelsea", 5, 0)
    # Same team name in another league is a different rating pool.
    assert ("SP1", "Arsenal") not in book.ratings
    assert book.ratings[("E0", "Arsenal")] > 1500.0


def test_attach_snapshots_exclude_same_day_and_later_matches() -> None:
    frame = _frame(
        [
            ("E0", "2025-08-09", "Arsenal", "Chelsea", 3, 0),
            ("E0", "2025-08-09", "Spurs", "West Ham", 1, 1),
            ("E0", "2025-08-16", "Arsenal", "Spurs", 2, 0),
            ("E0", "2025-08-23", "Chelsea", "West Ham", 1, 0),
        ]
    )

    # What a row on Aug 16 should see: exactly the Aug 9 state.
    after_aug9 = EloBook()
    after_aug9.apply("E0", "Arsenal", "Chelsea", 3, 0)
    after_aug9.apply("E0", "Spurs", "West Ham", 1, 1)

    attached = EloBook().attach(frame)
    # Row 0 must see the pristine 1500 start even though Spurs/West Ham
    # played the same day (strict date < rule).
    assert attached["home_elo_pre"][0] == pytest.approx(1500.0)
    assert attached["away_elo_pre"][0] == pytest.approx(1500.0)
    # Row 2 (Aug 16) sees the Aug 9 results but not the Aug 23 result.
    assert attached["home_elo_pre"][2] == pytest.approx(after_aug9.ratings[("E0", "Arsenal")])
    assert attached["away_elo_pre"][2] == pytest.approx(after_aug9.ratings[("E0", "Spurs")])
    # Row 3 (Aug 23) sees the Aug 9 results but not its own match.
    assert attached["home_elo_pre"][3] == pytest.approx(after_aug9.ratings[("E0", "Chelsea")])
    assert attached["away_elo_pre"][3] == pytest.approx(after_aug9.ratings[("E0", "West Ham")])


def test_attach_fixture_rows_never_applied() -> None:
    book = EloBook()
    frame = _frame(
        [
            ("E0", "2025-08-09", "Arsenal", "Chelsea", 3, 0),
            ("E0", "2025-08-16", "Arsenal", "Spurs", 2, 0),
        ]
    ).with_columns(
        home_goals=pl.when(pl.col("date") == date(2025, 8, 16))
        .then(None)
        .otherwise(pl.col("home_goals")),
        away_goals=pl.when(pl.col("date") == date(2025, 8, 16))
        .then(None)
        .otherwise(pl.col("away_goals")),
    )
    attached = book.attach(frame)
    # The fixture row gets a snapshot...
    assert attached["home_elo_pre"][1] > 1500.0
    # ...but the second match was never applied to the pool.
    assert ("E0", "Spurs") not in book.ratings


def test_attach_is_deterministic() -> None:
    frame = _frame(
        [
            ("E0", "2025-08-09", "Arsenal", "Chelsea", 3, 0),
            ("E0", "2025-08-16", "Chelsea", "Arsenal", 1, 2),
            ("E0", "2025-08-23", "Spurs", "Arsenal", 0, 1),
        ]
    )
    first = EloBook().attach(frame)
    second = EloBook().attach(frame)
    assert first.equals(second)
