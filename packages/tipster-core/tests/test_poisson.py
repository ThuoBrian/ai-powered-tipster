"""Poisson layer tests: the DC math must match the analytic cases exactly."""

from __future__ import annotations

import math

import pytest

from tipster_core.poisson import _tau, log_likelihood, score_matrix


def test_rho_zero_is_independent_poisson() -> None:
    matrix = score_matrix(1.3, 1.1, rho=0.0, max_goals=8)
    # With rho=0 both marginals are exactly Poisson: P(0 goals) = e^-lambda.
    # The matrix renormalises after truncating the tail (~2e-6 of mass at
    # these lambdas), hence the 1e-4 tolerance.
    assert sum(matrix.rows[0]) == pytest.approx(math.exp(-1.3), abs=1e-4)
    assert sum(row[0] for row in matrix.rows) == pytest.approx(math.exp(-1.1), abs=1e-4)


def test_tau_formula_at_low_scores() -> None:
    lh, la, rho = 1.3, 1.1, 0.05
    assert _tau(0, 0, lh, la, rho) == pytest.approx(1.0 - lh * la * rho)
    assert _tau(0, 1, lh, la, rho) == pytest.approx(1.0 + lh * rho)
    assert _tau(1, 0, lh, la, rho) == pytest.approx(1.0 + la * rho)
    assert _tau(1, 1, lh, la, rho) == pytest.approx(1.0 - rho)
    # Everywhere else tau is 1.
    assert _tau(0, 2, lh, la, rho) == 1.0
    assert _tau(2, 1, lh, la, rho) == 1.0
    assert _tau(2, 2, lh, la, rho) == 1.0


def test_matrix_sums_to_one() -> None:
    for lh, la, rho in [(1.3, 1.1, 0.0), (2.4, 0.7, 0.05), (0.5, 0.5, -0.1), (3.9, 1.8, 0.12)]:
        matrix = score_matrix(lh, la, rho=rho)
        total = sum(cell for row in matrix.rows for cell in row)
        assert total == pytest.approx(1.0, abs=1e-9)
        assert matrix.max_goals == 8


def test_negative_rho_shifts_mass_toward_draws() -> None:
    # In the DC parameterisation fitted rho is negative: tau(0,0) and
    # tau(1,1) grow above 1 -> more draws and 0-0s, while 1-0 / 0-1 shrink.
    neutral = score_matrix(1.2, 1.0, rho=0.0)
    negative = score_matrix(1.2, 1.0, rho=-0.1)
    assert negative.p(0, 0) > neutral.p(0, 0)
    assert negative.p_draw > neutral.p_draw
    assert negative.p(0, 1) < neutral.p(0, 1)
    assert negative.p(1, 0) < neutral.p(1, 0)


def test_markets_partition_mass() -> None:
    matrix = score_matrix(1.5, 1.2, rho=0.03)
    assert matrix.p_home + matrix.p_draw + matrix.p_away == pytest.approx(1.0, abs=1e-9)
    assert matrix.p_over25 + matrix.p_under25 == pytest.approx(1.0, abs=1e-9)
    assert matrix.p_btts + matrix.p_btts_no == pytest.approx(1.0, abs=1e-9)


def test_stronger_home_lambda_means_home_favourite() -> None:
    matrix = score_matrix(2.0, 0.8)
    assert matrix.p_home > matrix.p_away


def test_non_positive_lambdas_rejected() -> None:
    with pytest.raises(ValueError):
        score_matrix(0.0, 1.1)
    with pytest.raises(ValueError):
        score_matrix(-1.3, 1.1)


def test_log_likelihood_matches_matrix_cells() -> None:
    # The matrix renormalises after truncating the tail, so cells differ from
    # the raw density by the (tiny) missing tail mass — hence 1e-4 tolerance.
    matrix = score_matrix(1.4, 1.0, rho=0.05)
    for hg, ag in [(0, 0), (1, 1), (2, 0), (0, 3)]:
        assert log_likelihood(hg, ag, 1.4, 1.0, 0.05) == pytest.approx(
            math.log(matrix.p(hg, ag)), abs=1e-4
        )
