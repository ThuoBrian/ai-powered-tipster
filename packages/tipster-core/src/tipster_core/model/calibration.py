"""Isotonic calibration per market family, sitting on top of any Predictor.

Protocol (ADR 0003): the wrapper fits calibrators on out-of-fold predictions
so calibration never sees data the underlying model was trained on. Inside
``fit``, the played corpus is split chronologically into ``n_folds + 1``
chunks; an expanding-window replay fits the inner model on the first
``i + 1`` chunks and predicts chunk ``i + 2``, so every chunk after the
first gets a genuinely out-of-fold prediction. Isotonic regressions map
those pooled (predicted, outcome) pairs per market family, and the inner
model is then *refit on the full corpus* for actual predictions.

The expanding window (not a single 80/20 split) is the load-bearing choice:
a model trained on less data is less confident than the final model, so a
single inner split yields calibration pairs whose predicted values never
reach the confident extremes the full model produces — the isotonic curve
is then fitted over too narrow a range and clips all the extremes to one
value. Pooling folds trained on 20%-80% of the corpus spans the confidence
range the final model actually emits, and every fold's training corpus is
strictly past-only, preserving the leak-free rule.

Correct score is not calibrated in v1: cell-level outcomes are far too
sparse for isotonic regression to learn anything stable. The matrix's raw
correct-score cells are emitted untouched.

The inner predictor must tolerate being fitted repeatedly (each ``fit``
fully replacing prior state); both shipped models do.
"""

from __future__ import annotations

from collections.abc import Sequence

from sklearn.isotonic import IsotonicRegression

from tipster_core.contracts import (
    Fixture,
    MarketProbabilities,
    MatchPrediction,
    MatchResult,
)
from tipster_core.predictor import Predictor

#: Market families calibrated as binary "positive class" problems.
_BINARY_FAMILIES: tuple[tuple[str, str], ...] = (
    ("home", "home"),
    ("draw", "draw"),
    ("away", "away"),
    ("over25", "over25"),
    ("btts", "btts_yes"),
)

#: Below this corpus size calibration is skipped (passthrough).
_MIN_CALIBRATION_ROWS = 20

_EPS = 1e-12


def _outcome(pair: tuple[int, int], family: str) -> float:
    home_goals, away_goals = pair
    if family == "home":
        return float(home_goals > away_goals)
    if family == "draw":
        return float(home_goals == away_goals)
    if family == "away":
        return float(home_goals < away_goals)
    if family == "over25":
        return float(home_goals + away_goals >= 3)
    if family == "btts":
        return float(home_goals >= 1 and away_goals >= 1)
    msg = f"unknown family {family!r}"
    raise ValueError(msg)


def _calibrated_markets(
    markets: MarketProbabilities,
    calibrators: dict[str, IsotonicRegression] | None,
) -> MarketProbabilities:
    """Apply per-family isotonic mapping and renormalise the 1X2 triple."""
    if calibrators is None:
        return markets
    values = {
        "home": markets.home,
        "draw": markets.draw,
        "away": markets.away,
        "over25": markets.over25,
        "btts": markets.btts_yes,
    }
    calibrated: dict[str, float] = {}
    for family, key in _BINARY_FAMILIES:
        if family in calibrators:
            calibrated[key] = float(calibrators[family].predict([values[family]])[0])
        else:
            calibrated[key] = values[family]

    # Renormalise the 1X2 triple; O/U and BTTS stay coherent by construction.
    triple = calibrated["home"] + calibrated["draw"] + calibrated["away"]
    if triple > 0:
        for key in ("home", "draw", "away"):
            calibrated[key] = calibrated[key] / triple

    return MarketProbabilities(
        home=calibrated["home"],
        draw=calibrated["draw"],
        away=calibrated["away"],
        over25=calibrated["over25"],
        under25=1.0 - calibrated["over25"],
        btts_yes=calibrated["btts_yes"],
        btts_no=1.0 - calibrated["btts_yes"],
        correct_scores=markets.correct_scores,
    )


class CalibratedPredictor:
    """Wraps any :class:`Predictor` with per-family isotonic calibration."""

    def __init__(self, inner: Predictor, n_folds: int = 4) -> None:
        self.inner = inner
        self.n_folds = n_folds
        self._calibrators: dict[str, IsotonicRegression] | None = None

    @property
    def name(self) -> str:
        return f"{self.inner.name}-calibrated"

    def fit(self, played: Sequence[MatchResult]) -> None:
        """Fit calibrators out-of-fold, then the inner model on the full corpus."""
        matches = list(played)
        if len(matches) < _MIN_CALIBRATION_ROWS:  # too little to calibrate
            self._calibrators = None
            self.inner.fit(matches)
            return

        ordered = sorted(matches, key=lambda match: match.date)
        n_chunks = self.n_folds + 1
        bounds = [i * len(ordered) // n_chunks for i in range(n_chunks + 1)]
        if any(bounds[i + 1] <= bounds[i] for i in range(1, n_chunks)):
            # A predict chunk would be empty — corpus too small for this fold count.
            self._calibrators = None
            self.inner.fit(matches)
            return

        # Expanding-window replay: fold i trains on chunks 0..i+1 (strictly
        # past-only) and predicts chunk i+2 — never data it was trained on.
        out_of_fold: list[tuple[MatchPrediction, MatchResult]] = []
        for fold in range(self.n_folds):
            train_end = bounds[fold + 1]
            holdout = ordered[bounds[fold + 1] : bounds[fold + 2]]
            self.inner.fit(ordered[:train_end])
            fold_predictions = self.inner.predict([match.to_fixture() for match in holdout])
            out_of_fold.extend(zip(fold_predictions, holdout, strict=True))

        calibrators: dict[str, IsotonicRegression] = {}
        for family, _ in _BINARY_FAMILIES:
            predicted: list[float] = []
            observed: list[float] = []
            for prediction, match in out_of_fold:
                values = {
                    "home": prediction.markets.home,
                    "draw": prediction.markets.draw,
                    "away": prediction.markets.away,
                    "over25": prediction.markets.over25,
                    "btts": prediction.markets.btts_yes,
                }
                predicted.append(max(values[family], _EPS))
                observed.append(_outcome((match.home_goals, match.away_goals), family))
            regressor = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            regressor.fit(predicted, observed)
            calibrators[family] = regressor
        self._calibrators = calibrators

        # Refit the inner model on the full corpus for actual predictions.
        self.inner.fit(matches)

    def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
        predictions = self.inner.predict(upcoming)
        return [
            MatchPrediction(
                fixture=prediction.fixture,
                matrix=prediction.matrix,
                markets=_calibrated_markets(prediction.markets, self._calibrators),
                model=self.name,
                lambda_home=prediction.lambda_home,
                lambda_away=prediction.lambda_away,
            )
            for prediction in predictions
        ]
