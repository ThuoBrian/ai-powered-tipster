# predictor (service) — port pending

The scheduled fetch-and-predict service: pulls fixtures and lineups from
football-data.org v4, runs the model, and writes upcoming-match
probabilities. This is a placeholder — the working scaffold lives in the
architecture-template repo (`services/premier-league-predictor`, scaffolded
2026-08-30: Python service with httpx + pydantic, src layout, and a
`Predictor` ABC of `fit(played)` + `predict(upcoming)`).

## Port plan (phase 2–3)

1. Copy the scaffold here under `services/predictor`.
2. Register it as a uv workspace member in the root `pyproject.toml`.
3. Widen the `Predictor` ABC from H/D/A probabilities to the full score
   matrix ([ADR 0003](../../docs/decisions/0003-model-gbm-poisson-hybrid.md))
   and wire it to `tipster_core.storage`.
4. Add justfile recipes (`predictor-run`, `predictor-test`) and register in
   `docs/onboarding.md` / `docs/architecture.md`.

## Environment variables

`FOOTBALL_DATA_API_KEY` — football-data.org v4 (free tier); see the root
`.env.example`.
