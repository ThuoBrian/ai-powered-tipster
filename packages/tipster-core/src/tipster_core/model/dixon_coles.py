"""The pure Dixon-Coles reference model (ADR 0003).

No GBM, no Elo, no engineered features: per-league maximum likelihood over
``attack``, ``defense`` (sum-to-zero), home advantage ``gamma``, and the
low-score correlation ``rho``, with the original exponential time decay.
This is the kept benchmark the hybrid must beat — it shares the exact same
Poisson layer (:mod:`tipster_core.poisson`) so any backtest difference comes
from the lambdas, not the matrix math.

Teams unseen in training (cold start mid-backtest, e.g. promoted sides) get
league-average parameters: ``attack = defense = 0`` in the sum-to-zero
parametrisation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import polars as pl
from scipy.optimize import minimize

from tipster_core.contracts import (
    Fixture,
    MarketProbabilities,
    MatchPrediction,
    MatchResult,
)
from tipster_core.leagues import LeagueCode
from tipster_core.poisson import score_matrix

#: Last-resort ceiling on emitted lambdas; no real match rate comes near.
_LAMBDA_CEILING = 12.0


@dataclass(frozen=True)
class DixonColesConfig:
    """Fitting knobs for the reference model."""

    #: Exponential time decay per day (DC's xi): older matches count less.
    xi: float = 0.0018
    rho_lower: float = -0.2
    rho_upper: float = 0.2
    #: L2 ridge on attack/defense/gamma. Without it the MLE diverges on
    #: tiny or separated training slices (e.g. the calibration wrapper's
    #: first expanding-window folds) — lambdas in the millions.
    ridge: float = 0.1
    #: Hard bound on each attack/defense/gamma log-rate.
    rate_bound: float = 3.0


@dataclass(frozen=True)
class _LeagueParams:
    attack: dict[str, float] = field(default_factory=dict)
    defense: dict[str, float] = field(default_factory=dict)
    gamma: float = 0.0
    rho: float = 0.0
    teams: tuple[str, ...] = ()

    def lambda_home(self, home_team: str, away_team: str) -> float:
        rate = self.attack.get(home_team, 0.0) + self.defense.get(away_team, 0.0)
        return float(np.clip(math.exp(rate + self.gamma), 1e-3, _LAMBDA_CEILING))

    def lambda_away(self, home_team: str, away_team: str) -> float:
        rate = self.attack.get(away_team, 0.0) + self.defense.get(home_team, 0.0)
        return float(np.clip(math.exp(rate), 1e-3, _LAMBDA_CEILING))


def _negative_log_likelihood(
    params: np.ndarray,
    n_teams: int,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    weights: np.ndarray,
    log_factorial: np.ndarray,
    ridge: float,
) -> float:
    """Weighted DC negative log-likelihood, vectorised over matches.

    ``params`` is ``[attack_1..attack_{n-1}, defense_1..defense_{n-1},
    gamma, rho]``; the last team's attack/defense are pinned by the
    sum-to-zero constraint. ``n_teams`` is the count of distinct teams
    (a team that never appears at home would make ``home_idx.max()``
    undercount). The ridge term keeps the MLE finite on degenerate slices.
    """
    attack_params = params[: n_teams - 1]
    defense_params = params[n_teams - 1 : 2 * n_teams - 2]
    attack = np.append(attack_params, -attack_params.sum())
    defense = np.append(defense_params, -defense_params.sum())
    gamma = params[-2]
    rho = params[-1]

    lambda_home = np.exp(attack[home_idx] + defense[away_idx] + gamma)
    lambda_away = np.exp(attack[away_idx] + defense[home_idx])

    log_p = (
        -lambda_home
        + home_goals * np.log(lambda_home)
        - log_factorial[home_goals]
        - lambda_away
        + away_goals * np.log(lambda_away)
        - log_factorial[away_goals]
    )

    # The DC tau correction at the four low-score cells.
    tau = np.ones_like(lambda_home)
    tau = np.where(
        (home_goals == 0) & (away_goals == 0), 1.0 - lambda_home * lambda_away * rho, tau
    )
    tau = np.where((home_goals == 0) & (away_goals == 1), 1.0 + lambda_home * rho, tau)
    tau = np.where((home_goals == 1) & (away_goals == 0), 1.0 + lambda_away * rho, tau)
    tau = np.where((home_goals == 1) & (away_goals == 1), 1.0 - rho, tau)
    log_p = log_p + np.log(np.clip(tau, 1e-12, None))

    penalty = ridge * float(attack @ attack + defense @ defense + gamma * gamma)
    return float(-(weights * log_p).sum()) + penalty


class DixonColesPredictor:
    """Pure Dixon-Coles, fitted per league. A first-class :class:`Predictor`."""

    def __init__(self, config: DixonColesConfig | None = None) -> None:
        self.config = config or DixonColesConfig()
        self._params: dict[LeagueCode, _LeagueParams] = {}

    @property
    def name(self) -> str:
        return "dixon-coles"

    def fit(self, played: Sequence[MatchResult]) -> None:
        """Maximum-likelihood fit per league over the played corpus."""
        if not played:
            return
        frame = pl.DataFrame(
            {
                "league": [match.league.value for match in played],
                "date": [match.date for match in played],
                "home_team": [match.home_team for match in played],
                "away_team": [match.away_team for match in played],
                "home_goals": [match.home_goals for match in played],
                "away_goals": [match.away_goals for match in played],
            }
        )
        self._params = {}
        for league in frame["league"].unique().sort().to_list():
            code = LeagueCode.from_code(league)
            self._params[code] = self._fit_league(frame.filter(pl.col("league") == league))

    def _fit_league(self, league_frame: pl.DataFrame) -> _LeagueParams:
        teams = (
            pl.concat([league_frame["home_team"], league_frame["away_team"]])
            .unique()
            .sort()
            .to_list()
        )
        index = {team: i for i, team in enumerate(teams)}
        home_idx = np.array([index[t] for t in league_frame["home_team"]], dtype=np.int64)
        away_idx = np.array([index[t] for t in league_frame["away_team"]], dtype=np.int64)
        home_goals = league_frame["home_goals"].to_numpy().astype(np.int64)
        away_goals = league_frame["away_goals"].to_numpy().astype(np.int64)

        reference = league_frame["date"].max()
        days_ago = np.array([(reference - d).days for d in league_frame["date"]], dtype=np.float64)
        weights = np.exp(-self.config.xi * days_ago)

        max_goals = int(max(home_goals.max(), away_goals.max()))
        log_factorial = np.array(
            [math.lgamma(k + 1.0) for k in range(max_goals + 1)], dtype=np.float64
        )

        n_teams = len(teams)
        # [attack_1..n-1, defense_1..n-1, gamma, rho], zero init (deterministic).
        x0 = np.zeros(2 * (n_teams - 1) + 2)
        bounds = [(-self.config.rate_bound, self.config.rate_bound)] * (2 * (n_teams - 1) + 1) + [
            (self.config.rho_lower, self.config.rho_upper)
        ]
        result = minimize(
            _negative_log_likelihood,
            x0,
            args=(
                n_teams,
                home_idx,
                away_idx,
                home_goals,
                away_goals,
                weights,
                log_factorial,
                self.config.ridge,
            ),
            method="L-BFGS-B",
            bounds=bounds,
        )
        if not np.all(np.isfinite(result.x)):
            # Pathological slice: fall back to league-average parameters
            # rather than emitting inf/nan rates.
            return _LeagueParams(teams=tuple(teams))
        params = np.asarray(result.x, dtype=np.float64)
        attack = np.append(params[: n_teams - 1], -params[: n_teams - 1].sum())
        defense = np.append(
            params[n_teams - 1 : 2 * n_teams - 2], -params[n_teams - 1 : 2 * n_teams - 2].sum()
        )
        return _LeagueParams(
            attack={team: float(attack[i]) for i, team in enumerate(teams)},
            defense={team: float(defense[i]) for i, team in enumerate(teams)},
            gamma=float(params[-2]),
            rho=float(np.clip(params[-1], self.config.rho_lower, self.config.rho_upper)),
            teams=tuple(teams),
        )

    def predict(self, upcoming: Sequence[Fixture]) -> list[MatchPrediction]:
        """Price fixtures through the shared Poisson layer with fitted rho."""
        predictions: list[MatchPrediction] = []
        for fixture in upcoming:
            params = self._params.get(fixture.league, _LeagueParams())
            matrix = score_matrix(
                params.lambda_home(fixture.home_team, fixture.away_team),
                params.lambda_away(fixture.home_team, fixture.away_team),
                rho=params.rho,
            )
            predictions.append(
                MatchPrediction(
                    fixture=fixture,
                    matrix=matrix,
                    markets=MarketProbabilities.from_matrix(matrix),
                    model=self.name,
                )
            )
        return predictions
