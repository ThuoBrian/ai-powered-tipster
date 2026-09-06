"""The model contract: what every tipster model must implement.

ADR 0003 widens the original ``Predictor`` idea (H/D/A probabilities) to the
full scoreline matrix: every market is derived from one ``ScoreMatrix``, so
models stay coherent across 1X2, over/under, BTTS, and correct score.

Hard rule (CLV honesty, docs/design.md): implementations receive *fixtures*
— no goals, no odds. Models that could read the closing line would make the
closing-line-value metric self-referential, so the interface makes that
impossible by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from tipster_core.contracts import Fixture, MatchPrediction, MatchResult


@runtime_checkable
class Predictor(Protocol):
    """A model that fits on played matches and prices upcoming fixtures."""

    @property
    def name(self) -> str:
        """Short identifier used in backtest reports and the UI."""

    def fit(self, played: Sequence[MatchResult]) -> None:
        """Learn from *played* matches (chronological order not required)."""
        ...

    def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
        """Price *upcoming* fixtures, aligned with input order."""
        ...
