---
description: "Use when a session is wrapping up or significant work has been completed to create a Notion handoff entry. Trigger when the user says they're done, asks to wrap up, or when a major milestone is reached."
user-invocable: true
allowed-tools: Read Bash mcp__claude_ai_Notion__notion-fetch mcp__claude_ai_Notion__notion-create-pages mcp__claude_ai_Notion__notion-update-page
---

# Session End

Wrap up the current session and create a handoff for next time.

## Steps

1. Read `docs/notion.md` to get the workspace page IDs
2. Review what happened this session (PRs, commits, decisions, pages created)
3. Draft a Session Log entry with this structure:
   - **Context** — what we were working on, which branch, the goal
   - **What got done** — bullet list of outcomes
   - **What's next** — 2-3 items for the next session to pick up
   - **Open questions** — anything unresolved
4. Show me the draft for approval
5. Once approved, use `notion-create-pages` to create the entry under the Session Log page
6. Update the Task Board if any milestones changed status (ask me first)

If `docs/notion.md` doesn't exist, just show the draft without creating it in Notion.
