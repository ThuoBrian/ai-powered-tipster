# Architecture Decision Records

ADRs capture the significant, hard-to-reverse decisions in this repo: why a
choice was made, what alternatives were considered, and what it costs us. They
are written for future maintainers (human and AI), so context matters more
than formality.

## Index

| Number | Decision | Status |
|--------|----------|--------|
| [0001](0001-monorepo-structure-uv-workspace.md) | Monorepo structure: uv workspace with apps/packages/services | Accepted |
| [0002](0002-data-sources.md) | Data sources: football-data.co.uk primary, The Odds API live | Accepted |
| [0003](0003-model-gbm-poisson-hybrid.md) | Model core: GBM → Poisson hybrid | Accepted |
| [0004](0004-reasoning-layer-local-ollama.md) | Reasoning layer: local LLM via Ollama | Accepted |
| [0005](0005-phase-1-evaluation-protocol.md) | Phase 1 evaluation protocol: walk-forward harness | Accepted |
| [0006](0006-phase-2-value-engine.md) | Phase 2 value engine: Shin devig, EV, Kelly | Accepted |
| [0007](0007-live-odds-ingestion.md) | Live odds ingestion: The Odds API | Accepted |
| [0008](0008-team-name-reconciliation.md) | Team-name reconciliation for live odds | Accepted |
| [0009](0009-paper-trading-bet-log.md) | Paper-trading bet log | Accepted |
| [0010](0010-task-runner-just.md) | Task runner: just replaces make | Accepted |
| [0011](0011-more-competitions-and-internationals.md) | More competitions and national-team tournaments | Accepted |

## Format

Each ADR lives at `docs/decisions/NNNN-kebab-case-title.md`, where `NNNN` is
the next unused number. Use this template:

```markdown
# NNNN — Short title of the decision

- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD

## Context

What forces are in play: constraints, requirements, prior decisions. Keep it
factual and specific to this repo.

## Decision

What we are doing, stated in the present tense. Prefer one clear sentence,
then details.

## Consequences

What becomes easier, what becomes harder, what we now have to watch out for.
Be honest about the downsides.
```

When a decision is superseded, do not delete the old ADR — mark its status
and update the index.
