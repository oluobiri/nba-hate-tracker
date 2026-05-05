---
description: "Use at the beginning of a session to orient, fetch last session context from Notion, and show project state. Trigger when the user starts a new conversation, says they're picking up work, or asks what to do next."
user-invocable: true
allowed-tools: Read Bash mcp__claude_ai_Notion__notion-fetch
---

# Session Start

Orient yourself at the beginning of a new work session.

## Steps

1. Read `docs/notion.md` to get the workspace page IDs
2. Use `notion-fetch` to get the **Session Log** page, then fetch the most recent entry (the first child page)
3. Summarize for me:
   - What was done last session
   - What's next (the handoff items)
   - Any open questions
4. Run `git status` and `git log --oneline -5` to show where the repo stands
5. Run `gh issue list --assignee @me --state open` to show active engineering work

Do NOT fetch the Task Board — that's PM-level context, not relevant during code sessions. The Session Log is the bridge between strategic planning and engineering execution.

If `docs/notion.md` doesn't exist, skip Notion steps and just show git state + issues.
