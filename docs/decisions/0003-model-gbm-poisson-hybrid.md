# 0003 — Model core: GBM → Poisson hybrid

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

The product prices matches, it does not just pick winners: the value engine
needs coherent probabilities across many markets (1X2, over/under 2.5, BTTS,
correct score) from a single source of truth, calibrated well enough to
compare against bookmaker odds. Training data is small — roughly 1,700
matches per season across the big five leagues. The prior predictor scaffold
left the model choice deliberately open (its ADR 0003 slot).

Options considered:

| Option | Strengths | Weaknesses |
|--------|-----------|------------|
| Dixon-Coles / bivariate Poisson | One model → full score matrix; all markets derived exactly; interpretable; tiny | Cannot absorb modern features (rest days, form, injuries) |
| Per-market GBM (LightGBM) | Strong tabular performance, fast | Markets priced independently → incoherent probabilities |
| Neural sequence model | Trendy, handles ordered history | Data-hungry; loses to GBMs on ~10k rows |
| TabPFN v2 | Pretrained tabular transformer, strong on small data | Also per-target; adds a heavier dependency |

## Decision

A two-stage hybrid:

1. **LightGBM regressors** predict each team's expected goals (`lambda_home`,
   `lambda_away`) from engineered features: rolling goal form, per-league Elo,
   rest days, home/away splits, league identity. Elo pools stay per-league —
   strengths are never merged across leagues.
2. A **Poisson layer with the Dixon-Coles low-score correction** converts the
   two lambdas into a scoreline probability matrix; every market's
   probability is then derived exactly from that one matrix.

Isotonic calibration sits on top, scored per market family. The evaluation
gate is **walk-forward validation** (train on the past, predict the next
gameweek, roll forward) measured by Brier score and log loss; the hybrid must
beat a kept Dixon-Coles reference implementation and the closing-line
favourite baseline to justify its complexity. The existing `Predictor` ABC
contract is widened from H/D/A probabilities to the full score matrix.

## Consequences

- Market coherence and ML flexibility at once, with a small artifact that
  retrains in seconds — the "small model" requirement holds.
- Two stages mean two failure modes (bad lambdas, bad matrix assumptions);
  the walk-forward harness and calibration plots are the guardrails.
- Feature engineering becomes the main leverage point; xG data (Understat/
  FBref) is the highest-value future addition.
- A Dixon-Coles reference implementation must be maintained alongside the
  hybrid — that is the cost of having a honest benchmark.
