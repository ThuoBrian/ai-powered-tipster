"""Models implementing the :class:`tipster_core.predictor.Predictor` protocol.

Phase 1 ships two arms: the pure Dixon-Coles reference (the honest
benchmark the hybrid must beat, ADR 0003) and the GBM → Poisson hybrid —
plus an isotonic calibration wrapper that can sit on top of either.
"""

from tipster_core.model.dixon_coles import DixonColesPredictor
from tipster_core.model.hybrid import GbmPoissonPredictor

__all__ = [
    "DixonColesPredictor",
    "GbmPoissonPredictor",
]
