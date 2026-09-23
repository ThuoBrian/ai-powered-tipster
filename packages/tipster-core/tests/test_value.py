"""Value engine tests: Shin devig, EV, Kelly, and tip selection (ADR 0006)."""

from __future__ import annotations

from datetime import date

import pytest

from tipster_core.contracts import Fixture, MarketProbabilities, MatchOdds, OutcomeOdds
from tipster_core.leagues import LeagueCode
from tipster_core.value import (
    ValueTip,
    expected_value,
    find_value_tips,
    kelly_fraction,
    shin_probabilities,
)

_FIXTURE = Fixture(
    league=LeagueCode.PREMIER_LEAGUE,
    season="2526",
    date=date(2026, 1, 1),
    home_team="Arsenal",
    away_team="Chelsea",
)


def test_shin_probabilities_sum_to_one() -> None:
    odds = OutcomeOdds(home=2.0, draw=3.5, away=4.0)
    fair = shin_probabilities(odds)
    assert sum(fair) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= p <= 1.0 for p in fair)


def test_shin_probabilities_no_overround_is_a_no_op() -> None:
    # 1/2.0 + 0.3 + 0.2 == 1.0 exactly: a book with no margin should pass
    # straight through, not get an insider-rate correction applied to it.
    odds = OutcomeOdds(home=2.0, draw=1.0 / 0.3, away=1.0 / 0.2)
    fair = shin_probabilities(odds)
    assert fair == pytest.approx((0.5, 0.3, 0.2), abs=1e-6)


def test_shin_corrects_favourite_longshot_bias() -> None:
    # Shin's method should shift fair probability toward the favourite (the
    # lowest-odds outcome) relative to plain proportional devig, and away
    # from the longshot — that correction is the entire point of the method.
    odds = OutcomeOdds(home=2.0, draw=3.5, away=4.0)
    implied = (1.0 / odds.home, 1.0 / odds.draw, 1.0 / odds.away)
    market_sum = sum(implied)
    proportional = tuple(p / market_sum for p in implied)

    fair = shin_probabilities(odds)
    assert fair[0] > proportional[0]  # favourite (home) shifts up
    assert fair[2] < proportional[2]  # longshot (away) shifts down


def test_shin_probabilities_underround_book_still_normalises() -> None:
    # A book with no margin at all (stale/underround prices) has nothing for
    # Shin's method to correct; the result must still be a valid distribution.
    odds = OutcomeOdds(home=2.1, draw=3.6, away=4.2)
    fair = shin_probabilities(odds)
    assert sum(fair) == pytest.approx(1.0, abs=1e-9)


def test_expected_value_formula() -> None:
    assert expected_value(0.5, 2.1) == pytest.approx(0.05)
    assert expected_value(0.4, 2.0) == pytest.approx(-0.2)


def test_kelly_fraction_scales_with_edge() -> None:
    # Full Kelly at p=0.5, odds=2.1: (0.5*2.1 - 1) / 1.1 = 0.04545...
    # Quarter-Kelly (default) is a quarter of that.
    stake = kelly_fraction(0.5, 2.1)
    assert stake == pytest.approx(0.05 / 1.1 * 0.25, abs=1e-9)


def test_kelly_fraction_zero_on_negative_ev() -> None:
    assert kelly_fraction(0.3, 2.0) == 0.0


def test_kelly_fraction_respects_cap() -> None:
    assert kelly_fraction(0.9, 5.0, cap=0.05) == pytest.approx(0.05)


def test_find_value_tips_returns_only_positive_ev() -> None:
    # Model likes home more than the market's fair price implies; draw and
    # away roughly match the market, so only home should clear EV > 0.
    markets = MarketProbabilities(
        home=0.55, draw=0.25, away=0.20, over25=0.5, under25=0.5, btts_yes=0.5, btts_no=0.5
    )
    odds = MatchOdds(avg=OutcomeOdds(home=2.2, draw=3.5, away=4.0))
    tips = find_value_tips(_FIXTURE, "gbm-poisson", markets, odds)
    assert [tip.pick for tip in tips] == ["home"]
    assert tips[0].ev > 0.0
    assert tips[0].odds_source == "avg"
    assert tips[0].kelly_stake > 0.0


def test_find_value_tips_uses_fallback_ladder_when_pinnacle_missing() -> None:
    markets = MarketProbabilities(
        home=0.55, draw=0.25, away=0.20, over25=0.5, under25=0.5, btts_yes=0.5, btts_no=0.5
    )
    odds = MatchOdds(pinnacle=None, avg=OutcomeOdds(home=2.2, draw=3.5, away=4.0))
    tips = find_value_tips(_FIXTURE, "gbm-poisson", markets, odds)
    assert tips and tips[0].odds_source == "avg"


def test_find_value_tips_empty_when_no_odds_available() -> None:
    markets = MarketProbabilities(
        home=0.55, draw=0.25, away=0.20, over25=0.5, under25=0.5, btts_yes=0.5, btts_no=0.5
    )
    assert find_value_tips(_FIXTURE, "gbm-poisson", markets, MatchOdds()) == []


def test_find_value_tips_respects_requested_source() -> None:
    markets = MarketProbabilities(
        home=0.55, draw=0.25, away=0.20, over25=0.5, under25=0.5, btts_yes=0.5, btts_no=0.5
    )
    odds = MatchOdds(b365=OutcomeOdds(home=2.2, draw=3.5, away=4.0))
    # Requesting a source that isn't populated should not fall back silently.
    assert find_value_tips(_FIXTURE, "gbm-poisson", markets, odds, source="pinnacle") == []
    tips = find_value_tips(_FIXTURE, "gbm-poisson", markets, odds, source="b365")
    assert tips and tips[0].odds_source == "b365"


def test_find_value_tips_sorted_by_ev_descending() -> None:
    # Odds priced so both home and away clear zero EV against the model.
    markets = MarketProbabilities(
        home=0.5, draw=0.1, away=0.4, over25=0.5, under25=0.5, btts_yes=0.5, btts_no=0.5
    )
    odds = MatchOdds(avg=OutcomeOdds(home=2.05, draw=8.0, away=2.8))
    tips = find_value_tips(_FIXTURE, "gbm-poisson", markets, odds)
    assert len(tips) == 2
    assert tips[0].ev >= tips[1].ev


def test_value_tip_is_frozen_and_rejects_extra_fields() -> None:
    tip = ValueTip(
        fixture=_FIXTURE,
        model="gbm-poisson",
        pick="home",
        p_model=0.55,
        p_market_fair=0.48,
        odds=2.2,
        odds_source="avg",
        ev=0.21,
        kelly_stake=0.04,
    )
    with pytest.raises(ValueError):
        tip.pick = "draw"  # type: ignore[misc]
    with pytest.raises(ValueError):
        ValueTip(**{**tip.model_dump(), "extra_field": 1})
