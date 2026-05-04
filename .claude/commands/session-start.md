# Session Start

Orient yourself at the beginning of a new work session.

## Steps

1. Read `.claude/notion.md` to get the workspace page IDs
2. Use `notion-fetch` to get the **Session Log** page, then fetch the most recent entry (the first child page)
3. Summarize for me:
   - What was done last session
   - What's next (the handoff items)
   - Any open questions
4. Use `notion-fetch` on the **Task Board** database and show me the current board state (group by Status)
5. Run `git status` and `git log --oneline -5` to show where the repo stands

If `.claude/notion.md` doesn't exist, skip Notion steps and just show git state.
