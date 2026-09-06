"""The Poisson layer with the Dixon-Coles low-score correction.

Every model in the tipster — the GBM → Poisson hybrid and the pure
Dixon-Coles reference — converts a pair of expected goals (lambdas) into a
scoreline probability matrix through this one module, and every market is
derived from that matrix (ADR 0003). Sharing the math is what makes the
Dixon-Coles reference an honest benchmark: differences in backtest results
come from the lambdas, not the matrix code.
"""

from __future__ import annotations

import math

from tipster_core.contracts import ScoreMatrix

_MAX_GOALS = 8


def _tau(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> float:
    """The Dixon-Coles (1997) low-score correction factor.

    ``tau`` adjusts the four lowest-score cells (0-0, 1-0, 0-1, 1-1) to
    capture the observed dependence between low scores — draws and narrow
    wins are more common than independent Poissons imply. It is 1 everywhere
    else.
    """
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lambda_home * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lambda_away * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float = 0.0,
    max_goals: int = _MAX_GOALS,
) -> ScoreMatrix:
    """Build the DC-corrected scoreline matrix for a pair of expected goals.

    ``P(i, j) = Pois(i; lambda_home) * Pois(j; lambda_away) * tau(i, j)``.
    The grid is truncated at ``max_goals`` and renormalised so the matrix
    sums to exactly 1 — tail mass at realistic lambdas (< 4) is < 1e-4.
    """
    if lambda_home <= 0 or lambda_away <= 0:
        msg = f"lambdas must be positive, got {lambda_home!r}, {lambda_away!r}"
        raise ValueError(msg)

    rows: list[tuple[float, ...]] = []
    for i in range(max_goals + 1):
        row: list[float] = []
        for j in range(max_goals + 1):
            mass = (
                math.exp(-lambda_home)
                * lambda_home**i
                / math.factorial(i)
                * math.exp(-lambda_away)
                * lambda_away**j
                / math.factorial(j)
                * _tau(i, j, lambda_home, lambda_away, rho)
            )
            row.append(max(mass, 0.0))
        rows.append(tuple(row))

    total = sum(cell for row in rows for cell in row)
    if total <= 0:
        msg = f"matrix mass is zero for lambdas {lambda_home!r}, {lambda_away!r}"
        raise ValueError(msg)
    return ScoreMatrix(
        max_goals=max_goals,
        rows=tuple(tuple(cell / total for cell in row) for row in rows),
    )


def log_likelihood(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
    max_goals: int = _MAX_GOALS,
) -> float:
    """The DC log-likelihood of an observed scoreline (negative is better)."""
    if not (0 <= home_goals <= max_goals and 0 <= away_goals <= max_goals):
        msg = f"scoreline ({home_goals}, {away_goals}) outside the 0..{max_goals} grid"
        raise ValueError(msg)
    lambda_home = float(lambda_home)
    lambda_away = float(lambda_away)
    mass = (
        math.exp(-lambda_home)
        * lambda_home**home_goals
        / math.factorial(home_goals)
        * math.exp(-lambda_away)
        * lambda_away**away_goals
        / math.factorial(away_goals)
        * _tau(home_goals, away_goals, lambda_home, lambda_away, rho)
    )
    return math.log(max(mass, 1e-300))
