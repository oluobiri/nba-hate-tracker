# Notion Workflow

This project uses a 3-layer workflow:
- **GitHub Issues** — engineering tasks tied to PRs
- **CLAUDE.md + rules/** — agent conventions
- **Notion** — strategic tracking, session handoffs, technical reference

Workspace page IDs are in `docs/notion.md` (gitignored, not committed).

## Behaviors

- At session start: use the `/session-start` skill to fetch the latest Session Log and Task Board state.
- At session end: if meaningful work was done (PRs, decisions, structural changes), use the `/session-end` skill to create a handoff entry.
- The Task Board tracks PM-level milestones (Foundation, New Season, Dashboard, Launch). Engineering tasks belong in GitHub Issues, not Notion.
- Never commit `docs/notion.md` — it contains workspace-specific IDs.
