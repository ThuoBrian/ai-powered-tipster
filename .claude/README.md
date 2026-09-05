# .claude/

Shared Claude Code configuration for this repository.

## What's here

- `settings.json` — permissions shared by everyone working in this repo.
  Personal/local overrides go in `settings.local.json` (git-ignored).
- `commands/` — repo-wide slash commands (see below)

## Adding a shared command

Create `commands/<name>.md` with a short, self-contained prompt. Keep
commands focused on tasks that recur across projects in this repo —
scaffolding a new project, updating the architecture map, writing an ADR.

Prefer pointing Claude at the canonical docs (`CLAUDE.md`,
`docs/conventions/`) over duplicating instructions inside commands.
