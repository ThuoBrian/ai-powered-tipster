"""The GBM → Poisson hybrid model (ADR 0003) — the tipster's main engine.

Two-stage pricing:

1. Two LightGBM regressors (Poisson objective) predict each side's expected
   goals (``lambda_home``, ``lambda_away``) from the feature builder's 18
   engineered features. Training rows are **not** mirrored (home/away
   swapped) by default: a mirrored row puts an away-venue scoring rate in
   the home slot, so slot-level home advantage — the strongest single
   effect in football — averages toward zero across the mixture
   (empirically it inverts; see ``test_home_advantage_visible_in_lambdas``).
   ``mirror_rows=True`` remains available for ablation.
2. A Poisson layer with the Dixon-Coles low-score correction converts the
   lambdas into the scoreline matrix (shared with the DC reference), and
   every market is derived from that one matrix.

``rho`` (the DC correction strength) is a single scalar estimated per fit
by 1-D maximum likelihood given the GBM's predicted lambdas.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from tipster_core.contracts import (
    Fixture,
    MarketProbabilities,
    MatchPrediction,
    MatchResult,
)
from tipster_core.features import (
    FEATURE_COLUMNS,
    FeatureConfig,
    build_features,
    build_training_features,
)
from tipster_core.poisson import score_matrix

#: ``league_code``'s position in FEATURE_COLUMNS, passed to LightGBM as a
#: categorical by index (indices work regardless of input container).
_CATEGORICAL_INDICES: list[int] = [FEATURE_COLUMNS.index("league_code")]


@dataclass(frozen=True)
class GbmPoissonConfig:
    """LightGBM and hybrid knobs, sized for a ~5k match corpus."""

    n_estimators: int = 300
    learning_rate: float = 0.03
    num_leaves: int = 15
    min_data_in_leaf: int = 30
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    lambda_l2: float = 1.0
    seed: int = 42
    num_threads: int = 1
    mirror_rows: bool = False
    rho_lower: float = -0.2
    rho_upper: float = 0.2
    max_goals: int = 8


def _booster(config: GbmPoissonConfig) -> dict[str, Any]:
    """LightGBM constructor kwargs; values mix types (str / float / int / bool)."""
    return {
        "objective": "poisson",
        "n_estimators": config.n_estimators,
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "min_data_in_leaf": config.min_data_in_leaf,
        "feature_fraction": config.feature_fraction,
        "bagging_fraction": config.bagging_fraction,
        "bagging_freq": config.bagging_freq,
        "lambda_l2": config.lambda_l2,
        "seed": config.seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": config.num_threads,
        "verbosity": -1,
    }


def _swap_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Mirror a training frame: swap home/away slots (venue semantics kept).

    ``home_*`` columns receive the away team's stats *as they would appear
    in the away slots* and vice versa; ``elo_diff`` flips sign;
    ``league_code`` is invariant. Target columns are swapped separately by
    the caller.
    """
    swapped = frame.select(
        pl.col("league"),
        pl.col("date"),
        home_team=pl.col("away_team"),
        away_team=pl.col("home_team"),
        home_scored_form=pl.col("away_scored_form"),
        home_conceded_form=pl.col("away_conceded_form"),
        home_points_form=pl.col("away_points_form"),
        away_scored_form=pl.col("home_scored_form"),
        away_conceded_form=pl.col("home_conceded_form"),
        away_points_form=pl.col("home_points_form"),
        # Venue splits: the mirrored row's "home" side is the original away
        # team playing away — so its split stats are the away-venue ones.
        home_home_scored=pl.col("away_away_scored"),
        home_home_conceded=pl.col("away_away_conceded"),
        away_away_scored=pl.col("home_home_scored"),
        away_away_conceded=pl.col("home_home_conceded"),
        home_elo=pl.col("away_elo"),
        away_elo=pl.col("home_elo"),
        home_rest_days=pl.col("away_rest_days"),
        away_rest_days=pl.col("home_rest_days"),
        home_matches_played=pl.col("away_matches_played"),
        away_matches_played=pl.col("home_matches_played"),
        elo_diff=-pl.col("elo_diff"),
        league_code=pl.col("league_code"),
    )
    return swapped.select(FEATURE_COLUMNS)


class GbmPoissonPredictor:
    """LightGBM lambdas → DC-corrected Poisson matrix. Fits per corpus."""

    def __init__(
        self,
        gbm_config: GbmPoissonConfig | None = None,
        feature_config: FeatureConfig | None = None,
    ) -> None:
        self.gbm_config = gbm_config or GbmPoissonConfig()
        self.feature_config = feature_config or FeatureConfig()
        self._history: pl.DataFrame | None = None
        self._booster_home: lgb.LGBMRegressor | None = None
        self._booster_away: lgb.LGBMRegressor | None = None
        self._rho: float = 0.0

    @property
    def name(self) -> str:
        return "gbm-poisson"

    @property
    def rho(self) -> float:
        """The fitted DC low-score correction (0 before fit)."""
        return self._rho

    def fit(self, played: Sequence[MatchResult]) -> None:
        """Train both regressors on the played corpus, then fit rho."""
        if not played:
            return
        history = pl.DataFrame(
            {
                "league": [match.league.value for match in played],
                "date": [match.date for match in played],
                "home_team": [match.home_team for match in played],
                "away_team": [match.away_team for match in played],
                "home_goals": [match.home_goals for match in played],
                "away_goals": [match.away_goals for match in played],
            }
        )
        self._history = history
        training = build_training_features(history, self.feature_config)

        features = training.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
        home_target = training["home_goals"].to_numpy().astype(np.float64)
        away_target = training["away_goals"].to_numpy().astype(np.float64)

        if self.gbm_config.mirror_rows:
            mirrored = _swap_columns(training)
            features = np.vstack([features, mirrored.to_numpy().astype(np.float64)])
            # The mirrored row's home target is the original away_goals and
            # vice versa — copy both before rebinding either array.
            original_home_target = home_target.copy()
            original_away_target = away_target.copy()
            home_target = np.concatenate([original_home_target, original_away_target])
            away_target = np.concatenate([original_away_target, original_home_target])

        params = _booster(self.gbm_config)
        self._booster_home = lgb.LGBMRegressor(**params)
        self._booster_home.fit(
            features,
            home_target,
            feature_name=list(FEATURE_COLUMNS),
            categorical_feature=_CATEGORICAL_INDICES,
        )
        self._booster_away = lgb.LGBMRegressor(**params)
        self._booster_away.fit(
            features,
            away_target,
            feature_name=list(FEATURE_COLUMNS),
            categorical_feature=_CATEGORICAL_INDICES,
        )

        self._rho = self._fit_rho(
            self._lambdas_from_features(
                training.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
            ),
            training["home_goals"].to_numpy().astype(np.int64),
            training["away_goals"].to_numpy().astype(np.int64),
        )

    def _lambdas_from_features(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        assert self._booster_home is not None and self._booster_away is not None
        lambda_home = np.asarray(self._booster_home.predict(features), dtype=np.float64)
        lambda_away = np.asarray(self._booster_away.predict(features), dtype=np.float64)
        return np.clip(lambda_home, 1e-3, None), np.clip(lambda_away, 1e-3, None)

    def _fit_rho(
        self,
        lambdas: tuple[np.ndarray, np.ndarray],
        home_goals: np.ndarray,
        away_goals: np.ndarray,
    ) -> float:
        """1-D maximum likelihood for rho given the GBM's predicted lambdas."""

        def nll(rho: float) -> float:
            lambda_home, lambda_away = lambdas
            log_p = (
                -lambda_home
                + home_goals * np.log(lambda_home)
                - np.array([math.lgamma(k + 1.0) for k in home_goals])
                - lambda_away
                + away_goals * np.log(lambda_away)
                - np.array([math.lgamma(k + 1.0) for k in away_goals])
            )
            tau = np.ones_like(log_p)
            tau = np.where(
                (home_goals == 0) & (away_goals == 0), 1.0 - lambda_home * lambda_away * rho, tau
            )
            tau = np.where((home_goals == 0) & (away_goals == 1), 1.0 + lambda_home * rho, tau)
            tau = np.where((home_goals == 1) & (away_goals == 0), 1.0 + lambda_away * rho, tau)
            tau = np.where((home_goals == 1) & (away_goals == 1), 1.0 - rho, tau)
            return float(-np.log(np.clip(tau, 1e-12, None)).sum() - log_p.sum())

        result = minimize_scalar(
            nll,
            bounds=(self.gbm_config.rho_lower, self.gbm_config.rho_upper),
            method="bounded",
        )
        return float(np.clip(result.x, self.gbm_config.rho_lower, self.gbm_config.rho_upper))

    def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
        """Price fixtures with features built from the fitted history."""
        if self._history is None or self._booster_home is None or self._booster_away is None:
            msg = "predict() called before fit()"
            raise ValueError(msg)
        if not upcoming:
            return []

        fixtures = pl.DataFrame(
            {
                "league": [fixture.league.value for fixture in upcoming],
                "date": [fixture.date for fixture in upcoming],
                "home_team": [fixture.home_team for fixture in upcoming],
                "away_team": [fixture.away_team for fixture in upcoming],
            }
        )
        features = build_features(self._history, fixtures, self.feature_config)
        matrix_features = features.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
        lambda_home, lambda_away = self._lambdas_from_features(matrix_features)

        predictions: list[MatchPrediction] = []
        for i, fixture in enumerate(upcoming):
            matrix = score_matrix(
                float(lambda_home[i]),
                float(lambda_away[i]),
                rho=self._rho,
                max_goals=self.gbm_config.max_goals,
            )
            predictions.append(
                MatchPrediction(
                    fixture=fixture,
                    matrix=matrix,
                    markets=MarketProbabilities.from_matrix(matrix),
                    model=self.name,
                    lambda_home=float(lambda_home[i]),
                    lambda_away=float(lambda_away[i]),
                )
            )
        return predictions
