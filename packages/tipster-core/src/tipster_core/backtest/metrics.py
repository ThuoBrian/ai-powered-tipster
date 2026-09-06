"""Backtest metrics: Brier, log loss, reliability, ROI, and CLV.

Pure functions over plain sequences — the harness owns the typed wrappers
(``backtest.results``). Every market family is scored from one arm's
``MarketProbabilities`` plus the true scoreline.

Conventions (ADR 0005):

- 1X2 Brier is the standard multiclass form: the mean of the three
  ``(p - y)²`` terms per fixture, then averaged.
- Log loss clips probabilities to ``[1e-6, 1 - 1e-6]`` — uniformly for all
  arms — because the closing-favourite baseline emits hard 0/1
  probabilities; without clipping its log loss would be infinite and the
  comparison meaningless. Brier is never clipped.
- Correct score is scored as log loss over the observed cell only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

#: Market families scored with Brier and log loss.
Family = Literal["1x2", "over25", "btts", "correct-score"]

#: Binary variants with individual reliability curves.
OutcomeVariant = Literal["home", "draw", "away", "over25", "btts"]

#: Which odds source settled a bet.
OddsSource = Literal["pinnacle", "avg", "b365", "max"]

FAMILIES: tuple[Family, ...] = ("1x2", "over25", "btts", "correct-score")

_CLIP = 1e-6


def clip(p: float) -> float:
    return min(max(p, _CLIP), 1.0 - _CLIP)


def brier_1x2(
    probabilities: Sequence[tuple[float, float, float]],
    outcomes: Sequence[Literal[0, 1, 2]],
) -> float:
    """Multiclass Brier for 1X2: mean over fixtures of Σ (p_k - y_k)²."""
    if not outcomes:
        return 0.0
    total = 0.0
    for (home, draw, away), outcome in zip(probabilities, outcomes, strict=True):
        total += (home - (1.0 if outcome == 0 else 0.0)) ** 2
        total += (draw - (1.0 if outcome == 1 else 0.0)) ** 2
        total += (away - (1.0 if outcome == 2 else 0.0)) ** 2
    return total / len(outcomes)


def log_loss_1x2(
    probabilities: Sequence[tuple[float, float, float]],
    outcomes: Sequence[Literal[0, 1, 2]],
) -> float:
    """Categorical cross-entropy for 1X2, with uniform probability clipping."""
    if not outcomes:
        return 0.0
    total = 0.0
    for (home, draw, away), outcome in zip(probabilities, outcomes, strict=True):
        picked = (home, draw, away)[outcome]
        total -= math.log(clip(picked))
    return total / len(outcomes)


def brier_binary(probabilities: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Binary Brier on the positive class."""
    if not outcomes:
        return 0.0
    total = sum(
        (p - (1.0 if outcome else 0.0)) ** 2
        for p, outcome in zip(probabilities, outcomes, strict=True)
    )
    return total / len(outcomes)


def log_loss_binary(probabilities: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Binary log loss on the positive class, with clipping."""
    if not outcomes:
        return 0.0
    total = 0.0
    for p, outcome in zip(probabilities, outcomes, strict=True):
        y = 1.0 if outcome else 0.0
        total -= y * math.log(clip(p)) + (1.0 - y) * math.log(clip(1.0 - p))
    return total / len(outcomes)


def log_loss_correct_score(observed_cells: Sequence[float]) -> float:
    """Mean -log P(observed scoreline), with clipping."""
    if not observed_cells:
        return 0.0
    return -sum(math.log(clip(p)) for p in observed_cells) / len(observed_cells)


def reliability(
    probabilities: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10
) -> list[tuple[float, float, float, int]]:
    """Equal-width probability bins: (midpoint, predicted_mean, observed_rate, count).

    A prediction ``p`` lands in bin ``floor(p * n_bins)``; the midpoint is
    the bin's centre ``(k + 0.5) / n_bins``. Empty bins are dropped.
    """
    sums: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(n_bins)]
    for p, outcome in zip(probabilities, outcomes, strict=True):
        idx = min(int(p * n_bins), n_bins - 1)
        sums[idx][0] += p
        sums[idx][1] += 1.0 if outcome else 0.0
        sums[idx][2] += 1
    bins: list[tuple[float, float, float, int]] = []
    for k, (p_total, o_total, count) in enumerate(sums):
        if count == 0:
            continue
        midpoint = (k + 0.5) / n_bins
        bins.append((midpoint, p_total / count, o_total / count, int(count)))
    return bins


def flat_stake(pick_odds: float, won: bool) -> float:
    """Profit of a 1-unit flat stake at decimal odds."""
    return pick_odds - 1.0 if won else -1.0


def clv(taken_odds: float, closing_odds: float) -> float:
    """Closing line value as a fraction: (closing - taken) / taken."""
    return (closing_odds - taken_odds) / taken_odds
