# 0010 — Task runner: just replaces make

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

Every developer command was documented as a `make` target, but the primary
development machine is Windows, where `make` isn't installed, so none of the
documented commands ran as written. CI never used `make`; it calls `uv`
directly. Separately, nothing loaded `.env`: `THE_ODDS_API_KEY` set there
never reached the Value Finder or `tipster-odds` unless it was exported by
hand.

Starting the project also took three commands in the right order (`setup`,
`ingest`, `run-ui`), and `ingest` was only needed the first time.

## Decision

A root `justfile` replaces the `Makefile`, with the same recipe names so
docs change only `make x` → `just x`.

- `set dotenv-load` loads `.env` (when present) into every recipe's
  environment. The code keeps reading `os.environ`; nothing else changes.
- `set windows-shell` runs recipes under PowerShell, so Windows doesn't need
  Git Bash's `sh`. Every recipe line is portable (`uv`, `python -c`, `echo`),
  so the same file works on macOS and Linux. `clean`/`clean-data` use
  `shutil.rmtree` instead of `rm -rf`.
- `just start` is the one-command entry point: `uv sync`, ingest only if
  `data/tipster.duckdb` doesn't exist yet, then launch the dashboard.
- Short names (`ingest`, `run-ui`, …) are `alias`es of the per-project
  `tipster-core-*` / `tipster-ui-*` recipes, keeping the prefix convention.

## Consequences

- Contributors need `just` installed (`winget install Casey.Just`, `brew
  install just`). That's one more tool than `uv` alone, but it's a single
  static binary and was already present on the dev machine.
- CI is unaffected.
- `just start` won't re-ingest once a database exists. Pulling newly played
  fixtures is still an explicit `just ingest`.
- Earlier ADRs mention `make` targets. They're left as historical records;
  read those as the equivalent `just` recipe.
