# Scaffold a new project

Scaffold a new project in this monorepo. Ask me for:

1. The project name (kebab-case) and a one-line description
2. The type: app, service, or package
3. The technology stack and how I intend to run it

Then:

1. Create the directory under `apps/`, `services/`, or `packages/` named in
   kebab-case.
2. Write a `README.md` in the project covering: what it is, how to install,
   how to run, how to test, required environment variables (via
   `.env.example`, never real secrets).
3. Add `.gitignore` entries for its build artifacts at the repo root if
   they're not covered yet.
4. Add Makefile targets `install`, `test`, `run` prefixed with the project
   name (e.g. `my-project-test`), wired to the project's own tooling.
5. Register the project in `docs/onboarding.md` (project table) and add it
   to the system map in `docs/architecture.md`.
6. If the stack introduces a significant new technology choice for this
   repo, write an ADR in `docs/decisions/` following the numbering and
   format in `docs/decisions/README.md`.

Finally, list everything created or changed so I can review.