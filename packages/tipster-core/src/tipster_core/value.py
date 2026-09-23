"""The value engine: Shin's devig, expected value, fractional Kelly (ADR 0006).

Core principle (docs/design.md): price, don't predict. This module never
guesses anything — it takes two probabilities that already exist (the
model's, and the bookmaker's devigged fair price) and turns their
disagreement into a sized tip. Every number here is auditable by hand.

Odds coverage note (ADR 0005): the store carries 1X2 odds only, so tips are
1X2-only for now; over/under and BTTS become tippable once their odds are
ingested.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import brentq

from tipster_core.contracts import Fixture, MarketProbabilities, MatchOdds, OutcomeOdds

#: Where a tip's price came from: one of ``MatchOdds``'s (non-closing) fields,
#: or ``"manual"`` for odds a user typed in (never a ``MatchOdds`` field).
OddsSource = Literal["pinnacle", "avg", "b365", "max", "manual"]

#: Fallback order when no source is requested (ADR 0005's CLV "taken" ladder).
_ODDS_LADDER: tuple[OddsSource, ...] = ("pinnacle", "avg", "b365", "max")

Outcome = Literal["home", "draw", "away"]


class ValueTip(BaseModel):
    """One positive-EV pick: the model's edge over the devigged market, sized."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture: Fixture
    model: str
    pick: Outcome
    p_model: float = Field(ge=0.0, le=1.0)
    p_market_fair: float = Field(ge=0.0, le=1.0)
    odds: float = Field(gt=1.0)
    odds_source: OddsSource
    ev: float
    kelly_stake: float = Field(ge=0.0)


def _shin_prob(implied: float, z: float, market_sum: float) -> float:
    """One outcome's Shin-devigged probability, given the solved insider rate.

    Well-defined at ``z = 0``: the value there is ``implied / sqrt(market_sum)``,
    not the proportional devig ``implied / market_sum``.
    """
    inner = z**2 + 4.0 * (1.0 - z) * implied**2 / market_sum
    return (math.sqrt(max(inner, 0.0)) - z) / (2.0 * (1.0 - z))


def _solve_z(implied: tuple[float, float, float], market_sum: float) -> float:
    """The insider-trading rate that makes Shin's probabilities sum to 1.

    ``f(0) = sqrt(market_sum) - 1 > 0`` whenever there is an overround, and
    ``f`` decreases toward ``sum(p_i^2) / market_sum - 1 < 1`` as ``z -> 1``,
    so a root exists in ``(0, 1)``; ``brentq`` finds it. A book with no
    overround (``market_sum <= 1``, rare but possible with stale prices) has
    no insider premium to solve for.
    """
    if market_sum <= 1.0:
        return 0.0

    def f(z: float) -> float:
        return sum(_shin_prob(p, z, market_sum) for p in implied) - 1.0

    try:
        return float(brentq(f, 0.0, 1.0 - 1e-9))
    except ValueError:
        return 0.0


def shin_probabilities(odds: OutcomeOdds) -> tuple[float, float, float]:
    """Devig 1X2 odds via Shin's method: fair (home, draw, away) probabilities.

    Shin's method models the overround as insider-trading risk rather than a
    flat margin, which corrects the favourite-longshot bias that a plain
    proportional devig (``p_i / sum(p)``) leaves in: the favourite's fair
    share comes out slightly higher, the longshot's slightly lower.
    """
    implied = (1.0 / odds.home, 1.0 / odds.draw, 1.0 / odds.away)
    market_sum = sum(implied)
    z = _solve_z(implied, market_sum)
    fair = tuple(_shin_prob(p, z, market_sum) for p in implied)
    total = sum(fair)
    return (fair[0] / total, fair[1] / total, fair[2] / total)


def expected_value(p_model: float, odds: float) -> float:
    """EV of a unit stake: ``p_model * odds - 1`` (docs/design.md)."""
    return p_model * odds - 1.0


def kelly_fraction(p_model: float, odds: float, fraction: float = 0.25, cap: float = 0.05) -> float:
    """Fractional-Kelly stake as a share of bankroll, capped per bet.

    Full Kelly on decimal odds ``odds`` (net odds ``b = odds - 1``) is
    ``(p*b - (1-p)) / b``. Negative-EV picks size to zero rather than short
    the market. ``fraction`` defaults to quarter-Kelly, ``cap`` bounds any
    single bet regardless of edge (docs/design.md).
    """
    net_odds = odds - 1.0
    full_kelly = (p_model * odds - 1.0) / net_odds
    sized = max(0.0, full_kelly) * fraction
    return min(sized, cap)


def _select_odds(
    odds: MatchOdds, source: OddsSource | None
) -> tuple[OutcomeOdds, OddsSource] | None:
    """The requested price source, or the first populated rung of the ladder."""
    if source is not None:
        chosen = getattr(odds, source)
        return (chosen, source) if chosen is not None else None
    for candidate in _ODDS_LADDER:
        chosen = getattr(odds, candidate)
        if chosen is not None:
            return chosen, candidate
    return None


def find_value_tips(
    fixture: Fixture,
    model: str,
    markets: MarketProbabilities,
    odds: MatchOdds,
    *,
    source: OddsSource | None = None,
    ev_threshold: float = 0.0,
    kelly_fraction_size: float = 0.25,
    kelly_cap: float = 0.05,
) -> list[ValueTip]:
    """Every 1X2 outcome where the model beats the devigged market by ``ev_threshold``.

    Returns tips sorted by EV, most positive first. An empty list means no
    odds were available at ``source`` (or anywhere on the fallback ladder),
    or none cleared the threshold — never a partial/best-effort guess.
    """
    selected = _select_odds(odds, source)
    if selected is None:
        return []
    outcome_odds, odds_source = selected
    p_fair_home, p_fair_draw, p_fair_away = shin_probabilities(outcome_odds)

    candidates: tuple[tuple[Outcome, float, float, float], ...] = (
        ("home", markets.home, outcome_odds.home, p_fair_home),
        ("draw", markets.draw, outcome_odds.draw, p_fair_draw),
        ("away", markets.away, outcome_odds.away, p_fair_away),
    )

    tips: list[ValueTip] = []
    for pick, p_model, price, p_fair in candidates:
        ev = expected_value(p_model, price)
        if ev <= ev_threshold:
            continue
        tips.append(
            ValueTip(
                fixture=fixture,
                model=model,
                pick=pick,
                p_model=p_model,
                p_market_fair=p_fair,
                odds=price,
                odds_source=odds_source,
                ev=ev,
                kelly_stake=kelly_fraction(
                    p_model, price, fraction=kelly_fraction_size, cap=kelly_cap
                ),
            )
        )
    return sorted(tips, key=lambda tip: tip.ev, reverse=True)
