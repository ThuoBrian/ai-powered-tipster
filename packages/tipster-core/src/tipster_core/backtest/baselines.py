"""The closing-line favourite baseline and the odds fallback ladders.

The baseline is *not* a :class:`Predictor`: models only ever see
goal-free fixtures (the CLV honesty wall, ``predictor.py``), but this
baseline consumes the played row's odds directly — so it lives here, in
backtest land, and emits ``MatchPrediction``-shaped records the harness can
treat uniformly.

Odds fallback ladders (ADR 0005): settlement prices use closing odds
``pinnacle → avg → b365 → max``; the "taken" price for CLV uses the best
*opening* odds ``pinnacle → avg → b365 → max``. Opening odds are never used
for settlement.
"""

from __future__ import annotations

from collections.abc import Sequence

from tipster_core.backtest.metrics import OddsSource
from tipster_core.contracts import (
    MarketProbabilities,
    MatchOdds,
    MatchPrediction,
    MatchResult,
    OutcomeOdds,
    ScoreMatrix,
)

_CLOSING_LADDER: tuple[tuple[str, OddsSource], ...] = (
    ("pinnacle_closing", "pinnacle"),
    ("avg_closing", "avg"),
    ("b365_closing", "b365"),
    ("max_closing", "max"),
)
_OPENING_LADDER: tuple[tuple[str, OddsSource], ...] = (
    ("pinnacle", "pinnacle"),
    ("avg", "avg"),
    ("b365", "b365"),
    ("max", "max"),
)


def _from_ladder(
    odds: MatchOdds | None,
    ladder: tuple[tuple[str, OddsSource], ...],
) -> tuple[OutcomeOdds, OddsSource] | None:
    if odds is None:
        return None
    for attr, source in ladder:
        value = getattr(odds, attr)
        if value is not None:
            return value, source
    return None


def closing_odds(match: MatchResult) -> tuple[OutcomeOdds, OddsSource] | None:
    """The settlement price: first closing source present on the row."""
    return _from_ladder(match.odds, _CLOSING_LADDER)


def opening_odds(match: MatchResult) -> tuple[OutcomeOdds, OddsSource] | None:
    """The "taken" price for CLV: first opening source present on the row."""
    return _from_ladder(match.odds, _OPENING_LADDER)


def _degenerate_matrix(home_goals: int, away_goals: int) -> ScoreMatrix:
    rows = [[0.0, 0.0], [0.0, 0.0]]
    rows[home_goals][away_goals] = 1.0
    return ScoreMatrix(max_goals=1, rows=(tuple(rows[0]), tuple(rows[1])))


def closing_favourite_predictions(
    played: Sequence[MatchResult],
) -> list[MatchPrediction]:
    """Hard predictions on the favourite implied by the best closing odds.

    A fixture with no closing odds at all gets no baseline prediction —
    the harness simply has fewer baseline records than model records for
    it. Probabilities are exactly 1.0 on the favourite; log loss handles
    this via the uniform 1e-6 clip (``backtest.metrics``).
    """
    predictions: list[MatchPrediction] = []
    for match in played:
        chosen = closing_odds(match)
        if chosen is None:
            continue
        odds, _source = chosen
        # Favourite = lowest decimal odds.
        candidates: tuple[tuple[float, int, int], ...] = (
            (odds.home, 1, 0),
            (odds.draw, 0, 0),
            (odds.away, 0, 1),
        )
        _price, home_goals, away_goals = min(candidates, key=lambda c: c[0])
        matrix = _degenerate_matrix(home_goals, away_goals)
        predictions.append(
            MatchPrediction(
                fixture=match.to_fixture(),
                matrix=matrix,
                markets=MarketProbabilities.from_matrix(matrix),
                model="closing-favourite",
            )
        )
    return predictions
