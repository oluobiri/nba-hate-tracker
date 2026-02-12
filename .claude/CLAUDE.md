# CLAUDE.md - NBA Hate Tracker

**Project:** Sentiment analysis pipeline to answer "Who is r/NBA's most hated player?"  
**Answer:** Draymond Green (51.0% negative rate, 23/30 fanbases agree)  
**Budget:** $254.20 spent of $300 ceiling  
**Phase:** 6 (Visualization & Deployment)

---

## Architecture Map

```
scripts/          → CLI entry points (download, filter, batch, aggregate)
pipeline/         → Data processing (ArcticShiftClient, CommentPipeline, batch, aggregation)
utils/            → Stateless helpers (constants, formatting, paths, player_config, team_config)
config/           → YAML configs (players.yaml v1.2, teams.yaml)
app/              → Streamlit dashboard
tests/            → pytest (unit/, conftest.py)
notebooks/        → EDA and exploration (01-06)
data/             → Not committed
  ├── raw/        → Arctic Shift downloads
  ├── filtered/   → Cleaned + player-mention filtered
  ├── batches/    → Batch API requests/responses
  ├── processed/  → sentiment.parquet (1.93M rows)
  └── dashboard/  → aggregates.json (precomputed views)
```

## Commands

```bash
# Package management (uv only, never pip)
uv sync                              # Install dependencies
uv add <package>                     # Add dependency
uv run python -m scripts.<name>      # Run scripts as modules

# Testing
uv run pytest                        # Run all tests
uv run pytest tests/unit/            # Unit tests only
uv run pytest -x                     # Stop on first failure

# Linting
uv run ruff check .                  # Check
uv run ruff check . --fix            # Auto-fix
uv run ruff format .                 # Format

# Streamlit
uv run streamlit run app/streamlit_app.py  # Local dev
```

## Code Patterns

- **Imports:** Relative within packages, absolute cross-package
- **Scripts:** Thin wrappers that call pipeline/ modules. Use `if __name__ == "__main__":`
- **Error handling:** Specific exceptions with context, preserve chains with `from e`
- **Type hints:** Required on all function signatures
- **Docstrings:** Google style, required for all functions

## Data Files

**Never read directly (large files):**
- `data/raw/*.jsonl` (12+ GB)
- `data/filtered/*.jsonl` (2+ GB)
- `data/processed/sentiment.parquet` (1.93M rows)
- `data/batches/requests/*.jsonl`
- `data/batches/responses/*.jsonl`

**Dashboard input:**
- `data/dashboard/aggregates.json` — precomputed views, ~2MB, safe to load

## Current State (Phase 6)

**Completed:**
- 1.57M comments attributed to 112 players
- `aggregates.json` ready with 4 views: player_overall, player_temporal, player_team, team_overall

**Phase 6 Tracks:**
1. **Bar Race (Flourish):** Animated neg_rate rankings over 40 weeks — Draymond overtaking Embiid is the hook
2. **Dashboard (Streamlit):** Leaderboard, Flair View, Player Detail → deploy to Streamlit Cloud
3. **r/NBA Post:** Bar race + key findings + dashboard link

## Rules

Domain-specific instructions in `.claude/rules/`:
- `git.md` — Commit convention (Angular style), branch naming
- `python.md` — Code style, patterns, logging, dataclasses
- `testing.md` — TDD workflow, pytest conventions

---

*Read rules before implementation. Run tests before commits.*