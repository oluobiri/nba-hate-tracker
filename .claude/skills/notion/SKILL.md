---
description: "Use when needing to interact with or reference the project's Notion workspace — finding pages, checking task board state, or understanding the workspace structure."
user-invocable: true
allowed-tools: Read mcp__claude_ai_Notion__notion-fetch mcp__claude_ai_Notion__notion-search
---

# Notion Workspace Reference

Show the Notion workspace navigation map for this project.

## Steps

1. Read `docs/notion.md` and display:
   - All section pages with their IDs
   - Task Board schema (properties, views)
   - Session Log template format
2. If a specific section is mentioned in $ARGUMENTS, fetch that page from Notion and display its current content

This is a quick-reference command — don't modify anything, just show the current state.
