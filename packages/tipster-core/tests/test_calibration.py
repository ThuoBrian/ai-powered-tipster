"""Calibration wrapper tests: isotonic mapping, renormalisation, fit protocol."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import pytest

from tipster_core.contracts import Fixture, MarketProbabilities, MatchPrediction, MatchResult
from tipster_core.model.calibration import CalibratedPredictor
from tipster_core.poisson import score_matrix
from tipster_core.predictor import Predictor


class _ScriptedPredictor:
    """A fake inner model: probabilities looked up per home team."""

    def __init__(self, table: dict[str, tuple[float, float, float]]) -> None:
        self.table = table
        self.fit_calls: list[int] = []

    @property
    def name(self) -> str:
        return "scripted"

    def fit(self, played: Sequence[MatchResult]) -> None:
        self.fit_calls.append(len(played))

    def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
        predictions = []
        for fixture in upcoming:
            home, draw, away = self.table[fixture.home_team]
            markets = MarketProbabilities(
                home=home,
                draw=draw,
                away=away,
                over25=0.5,
                under25=0.5,
                btts_yes=0.5,
                btts_no=0.5,
            )
            predictions.append(
                MatchPrediction(
                    fixture=fixture,
                    matrix=score_matrix(1.3, 1.1),
                    markets=markets,
                    model=self.name,
                )
            )
        return predictions


def _match(day: int, home: str, away: str, home_goals: int, away_goals: int) -> MatchResult:
    return MatchResult(
        league="E0",
        season="2425",
        date=date(2025, 1, 1) + timedelta(days=day),
        home_team=home,
        away_team=away,
        home_goals=home_goals,
        away_goals=away_goals,
    )


def test_overconfident_predictions_are_pulled_down() -> None:
    # Arsenal always predicted at 0.8 home but wins only half its games.
    table = {"Arsenal": (0.8, 0.0, 0.2)}
    matches = [
        _match(i, "Arsenal", "Spurs", 1 if i % 2 == 0 else 0, 0 if i % 2 == 0 else 1)
        for i in range(40)
    ]
    # Wins half (no draws) -> isotonic maps 0.8 -> 0.5, away 0.2 -> 0.5.
    inner = _ScriptedPredictor(table)
    wrapper = CalibratedPredictor(inner)
    wrapper.fit(matches)
    prediction = wrapper.predict([matches[0].to_fixture()])[0]
    assert prediction.markets.home == pytest.approx(0.5, abs=0.05)


def test_1x2_stays_renormalised() -> None:
    table = {"Arsenal": (0.7, 0.2, 0.1), "Spurs": (0.1, 0.2, 0.7)}
    matches = [
        _match(
            i,
            "Arsenal" if i % 2 == 0 else "Spurs",
            "Spurs" if i % 2 == 0 else "Arsenal",
            1 if i % 3 == 0 else 0,
            0,
        )
        for i in range(40)
    ]
    inner = _ScriptedPredictor(table)
    wrapper = CalibratedPredictor(inner)
    wrapper.fit(matches)
    prediction = wrapper.predict([matches[0].to_fixture()])[0]
    total = prediction.markets.home + prediction.markets.draw + prediction.markets.away
    assert total == pytest.approx(1.0, abs=1e-9)


def test_fit_protocol_expanding_window_then_full() -> None:
    table = {"Arsenal": (0.6, 0.2, 0.2), "Spurs": (0.2, 0.2, 0.6)}
    matches = [
        _match(i, "Arsenal" if i % 2 == 0 else "Spurs", "Spurs" if i % 2 == 0 else "Arsenal", 1, 0)
        for i in range(50)
    ]
    inner = _ScriptedPredictor(table)
    wrapper = CalibratedPredictor(inner)
    wrapper.fit(matches)
    # Expanding-window out-of-fold protocol: folds train on 1..4 chunks of
    # the 5-chunk corpus, each predicting the strictly-later chunk, then the
    # inner model is refit on the full corpus (the leak-free protocol).
    assert inner.fit_calls == [10, 20, 30, 40, 50]


def test_calibration_never_trains_on_a_predicted_match() -> None:
    """Every fold's fit corpus must end before its holdout chunk starts."""
    base = date(2025, 1, 1)
    table = {"Arsenal": (0.6, 0.2, 0.2), "Spurs": (0.2, 0.2, 0.6)}

    class _RecordingPredictor(_ScriptedPredictor):
        def __init__(self) -> None:
            super().__init__(table)
            self.holdouts: list[tuple[int, int]] = []  # (train size, predicted day)

        def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
            train_size = self.fit_calls[-1]
            self.holdouts.extend((train_size, (fixture.date - base).days) for fixture in upcoming)
            return super().predict(upcoming)

    matches = [
        _match(i, "Arsenal" if i % 2 == 0 else "Spurs", "Spurs" if i % 2 == 0 else "Arsenal", 1, 0)
        for i in range(50)
    ]
    inner = _RecordingPredictor()
    wrapper = CalibratedPredictor(inner)
    wrapper.fit(matches)

    # Every out-of-fold prediction (bar the final passthrough fit) was made
    # by a model whose training corpus ended strictly before the match's day:
    # matches are one-per-day, so chronological index == day offset.
    assert len(inner.holdouts) == 40
    for train_size, day in inner.holdouts:
        assert train_size <= day, f"fold trained on {train_size} matches, predicted day {day}"


def test_small_corpus_skips_calibration_gracefully() -> None:
    table = {"Arsenal": (0.6, 0.2, 0.2)}
    matches = [_match(i, "Arsenal", "Spurs", 1, 0) for i in range(5)]
    inner = _ScriptedPredictor(table)
    wrapper = CalibratedPredictor(inner)
    wrapper.fit(matches)
    assert inner.fit_calls == [5]
    prediction = wrapper.predict([matches[0].to_fixture()])[0]
    # Uncalibrated passthrough.
    assert prediction.markets.home == pytest.approx(0.6)


def test_name_and_protocol_conformance() -> None:
    inner = _ScriptedPredictor({"Arsenal": (0.5, 0.25, 0.25)})
    wrapper = CalibratedPredictor(inner)
    assert wrapper.name == "scripted-calibrated"
    assert isinstance(wrapper, Predictor)  # runtime_checkable protocol
