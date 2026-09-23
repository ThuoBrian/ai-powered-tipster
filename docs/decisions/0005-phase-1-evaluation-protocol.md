# 0005 — Phase 1 evaluation protocol: walk-forward harness

- **Status:** Accepted
- **Date:** 2026-09-06

## Context

ADR 0003 committed to walk-forward validation as the gate for the GBM →
Poisson hybrid, but left the protocol underspecified. Several details had
real decision content, discovered while building the harness
(`packages/tipster-core/src/tipster_core/backtest/`):

- football-data.co.uk has no gameweek column, and the store's odds
  coverage is 1X2-only — no over/under or BTTS prices exist, so
  stake-based metrics cannot cover every market.
- The closing-line favourite baseline emits degenerate probabilities
  (1.0 on one outcome), which makes unclipped log loss infinite.
- Isotonic calibration needs its own data, but every training row is
  also a scoring row in walk-forward folds.
- Odds columns drift by source and season (Pinnacle gaps are common),
  so settlement needs a deterministic fallback.

## Decision

**Blocks and warm-up.** Evaluation blocks are rolling date windows of
`block_days` (default 7), anchored on the first evaluable match, all big-5
leagues pooled. A match is evaluable when at least `min_training_matches`
(default 400) matches strictly precede its date. Every model arm is re-fit
from scratch per block on all matches with `date < block_start`; the same
matches are featurized only from their own past (the feature builder's
as-of joins are all strict `date < fixture_date`, implemented via a
`next_day = date + 1` join key so same-day matches are invisible too).

**Odds fallback ladders.** Settlement uses closing odds with the ladder
`pinnacle_closing → avg_closing → b365_closing → max_closing`; opening
odds are never used for settlement. CLV's "taken" price uses the opening
ladder `pinnacle → avg → b365 → max`, compared against the Pinnacle
closing price of the same pick (fixtures missing either side are skipped
from CLV, not imputed).

**1X2-only ROI and CLV.** Because the store carries only 1X2 odds,
flat-stake ROI and CLV are computed on 1X2 picks only — one unit on the
argmax outcome per fixture. Over/under, BTTS, and correct score are
scored probabilistically (Brier, log loss, reliability) but not staked.
If richer odds land later, the ladders extend; the ladder order is the
decision, not the 1X2 restriction.

**Clipping.** Log loss clips probabilities to `[1e-6, 1 - 1e-6]` for all
arms uniformly, so the degenerate baseline gets a large-but-finite
penalty instead of infinity. Brier is never clipped — hard wrong
predictions keep their full quadratic penalty.

**Calibration inner split.** `CalibratedPredictor` fits isotonic
regressors per market family (home/draw/away/over2.5/BTTS-yes) using a
leak-free expanding-window protocol: the training slice is split
chronologically into five chunks; the inner model is fitted on chunks
0..i and predicts chunk i+1 for each fold, and isotonic is fit on the
pooled out-of-fold (probability, outcome) pairs; the inner model is then
refit on 100% before predicting the block. The expanding window matters:
the first real-data run showed that a single 80/20 inner split leaves the
isotonic fitted over a confidence range narrower than the full model
emits (a less-trained model is less confident), so the most confident —
and most wrong — predictions passed through nearly uncalibrated, and both
model arms scored worse than constant base rates on 1X2 log loss.
Pooling folds trained on 20%–80% of the corpus spans the range the final
model actually produces. Correct score is not calibrated in v1 (too
sparse to bin). 1X2 probabilities are renormalized after isotonic so the
triple still sums to 1.

**Gate, reported not asserted.** The gate compares the hybrid against
the pure Dixon-Coles reference and the closing-line favourite baseline
on 1X2 log loss AND Brier. It is printed by `tipster-backtest` and
stored in `report.json`, never asserted in CI — synthetic-data
comparisons in tests are meaningless, and the real-data verdict is a
finding to record, not a regression to block.

**CLV honesty wall.** `Predictor`s see only `Fixture` objects (no goals,
no odds); the harness strips results and odds via `MatchResult.to_fixture()`
before calling `predict`. The odds-fed baseline deliberately lives
outside the `Predictor` protocol — it cannot leak into production paths.

## Consequences

- Every number the harness prints is reproducible: LightGBM runs with
  `seed=42, deterministic=True, force_row_wise=True, num_threads=1`.
- ROI/CLV understate the tipster's staking surface until over/under and
  BTTS odds are ingested; the probabilistic families carry the evaluation
  meanwhile.
- The calibration wrapper quintuples model fit cost per block (four
  expanding-window fold fits, then the 100% refit) — seconds, not
  minutes, but real.
- The gate can fail honestly; when it does, the finding goes into this
  ADR's record (or a tuning note), not a lowered bar.

## Amendment (2026-09-23)

Two defects found while adding a 1X2 hit rate to the report:

- **Outcome labels were swapped.** The harness encoded an away win as `1`
  and a draw as `2`, while the metrics and picks index `(home, draw, away)`.
  Every backtest before this date scored away wins as draws (and vice
  versa) in 1X2 Brier, log loss, ROI settlement, and the gate. Those
  results are void; re-run `just backtest`. The model's training and
  calibration used their own, correct labels and were unaffected.
- **Calibration could emit hard 0s.** On small corpora, isotonic regression
  mapped sparse bins to exactly 0 (e.g. a 0% away win), and the 1X2
  renormalisation inflated the favourite to match. Calibrated
  probabilities are now bounded to `[0.02, 0.98]`.

The report also gains `hit_rate_1x2`: the share of fixtures where the
arm's most likely 1X2 outcome happened.
