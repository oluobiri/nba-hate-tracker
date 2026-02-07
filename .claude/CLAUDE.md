# CLAUDE.md - NBA Hate Tracker

**Project:** Sentiment analysis pipeline to answer "Who is r/NBA's most hated player?"  
**Budget:** $254.20 spent of $300 ceiling  
**Phase:** 5 (Analytics & Aggregation)

---

## Architecture Map

```
scripts/          → CLI entry points (download, filter, batch, aggregate)
pipeline/         → Data processing (ArcticShiftClient, CommentPipeline, batch)
utils/            → Stateless helpers (constants, formatting, paths, player_config)
config/           → YAML configs (players.yaml, teams.yaml)
app/              → Streamlit dashboard
tests/            → pytest (unit/, conftest.py)
notebooks/        → EDA and exploration
data/             → Not committed
  ├── raw/        → Arctic Shift downloads
  ├── filtered/   → Cleaned + player-mention filtered
  ├── batches/    → Batch API requests/responses
  ├── processed/  → sentiment.parquet (final output)
  └── dashboard/  → Precomputed aggregates for Streamlit
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
- `data/processed/sentiment.parquet` (1.9M rows)
- `data/batches/requests/*.jsonl`
- `data/batches/responses/*.jsonl`

**For schema inspection:** Use `head -3 <file> | python -m json.tool` or Polars sampling.

## Current State (Phase 5)

**Completed:**
- 1.94M comments classified via Batch API
- `data/processed/sentiment.parquet` ready for aggregation
- 97.25% usable data (1.89M rows)

**Next:**
- `scripts/aggregate_sentiment.py` → player rankings, flair segmentation
- `data/dashboard/aggregates.json` → precomputed metrics for Streamlit

## Rules

Domain-specific instructions in `.claude/rules/`:
- `git.md` — Commit convention (Angular style), branch naming
- `python.md` — Code style, patterns, logging, dataclasses
- `testing.md` — TDD workflow, pytest conventions

---

*Read rules before implementation. Run tests before commits.*