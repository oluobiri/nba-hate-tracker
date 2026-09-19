# CLAUDE.md - NBA Hate Tracker

**Project:** Sentiment analysis pipeline to answer "Who is r/NBA's most hated player?"  
**Answer:** Draymond Green (51.0% negative rate, 22/30 fanbases agree)  

---

## Architecture Map

```
scripts/          → CLI entry points (download, filter, batch, aggregate, publish)
pipeline/         → Data processing (ArcticShiftClient, batch, aggregation)
utils/            → Stateless helpers (constants, formatting, paths, player_config, team_config)
config/           → YAML configs (season.yaml pointers; <season>/players.yaml + season.yaml facts; teams.yaml; publish.yaml target)
app/              → Streamlit dashboard
tests/            → pytest (unit/, conftest.py)
notebooks/        → EDA and exploration, season-scoped (2024-25/, 2025-26/)
data/             → Not committed
  ├── 2024-25/    → V1 season data
  │   ├── raw/        → Arctic Shift downloads
  │   ├── filtered/   → Player-mention filtered JSONL
  │   ├── batches/    → Batch API requests/responses, one subdir per classifier stage (sentiment/, target/)
  │   ├── processed/  → sentiment.parquet
  │   ├── reference/  → stats.nba.com snapshots (rosters, team/player game logs) + posts_bridge.parquet + corpus_daily.parquet
  │   └── dashboard/  → per-table Parquet files + manifest.json
  ├── 2025-26/    → V2 season data (same structure)
  └── media/      → headshots/ (PNG + WebP variants) and logos/ (SVG); season-independent, never committed
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

# Media (headshots + logos from cdn.nba.com into data/media/, WebP variants derived; resumable)
uv run python -m scripts.fetch_media --dry-run  # Plan only, no request
uv run python -m scripts.fetch_media            # Fetch what is missing, exit 1 on any miss

# Publishing (assumes the publish role; prompts for an MFA code, dry runs included)
uv run python -m scripts.publish_dashboard --season 2025-26 --dry-run  # Plan only
uv run python -m scripts.publish_dashboard --season 2025-26            # The drop
uv run python -m scripts.publish_media --dry-run                       # Media plan (all seasons' ids)
uv run python -m scripts.publish_media                                 # Media drop, before a season that points at it
```

## Code Patterns

- **Imports:** Absolute throughout
- **Scripts:** Thin wrappers that call pipeline/ modules. Use `if __name__ == "__main__":`
- **Error handling:** Specific exceptions with context, preserve chains with `from e`
- **Type hints:** Required on all function signatures
- **Docstrings:** Google style, required for all functions

## Data Files

**Never read directly (large files):**
- `data/2024-25/raw/*.jsonl` (12+ GB)
- `data/2024-25/filtered/*.jsonl` (2+ GB)
- `data/2024-25/processed/sentiment.parquet` (1.93M rows)
- `data/2024-25/batches/<stage>/requests/*.jsonl`
- `data/2024-25/batches/<stage>/responses/*.jsonl`

**Published outputs (safe to load):**
- `data/<season>/dashboard/*.parquet` + `manifest.json` — the contract. The committed `data/2024-25/dashboard/aggregates.json` is the V1 Streamlit lab's input only; it retires with the lab (#114).

**Schema contracts:**
- `pipeline/schemas.py` — single source of truth for produced-file schemas (`sentiment.parquet` + aggregate views) and the `Manifest` typed contract (identity, rules, season facts, table registry); `SCHEMA_VERSION` is stamped into every dashboard parquet's file metadata and into `manifest.json`. Don't duplicate column lists elsewhere.
- `pipeline/lineage.py` — the config-lineage registry: which config version stamps which produced file. Stamp keys are spelled there only.
- `pipeline/publish.py` — the publish step: the upload set is `manifest.json` plus exactly its table registry, pre-flighted against the contract before any write. `docs/publishing.md` has the as-built AWS shape and the runbook.

**Conceptual model:**
- `docs/data-model.md` — the star schema (one `ClassifiedComment` fact + Player/Team/Date dimensions), the role-playing `team` (roster vs. fan), and the view-lineage "cheap / needs-a-join / expensive" map. Read before designing a new aggregate view; it's the relationships behind `schemas.py`'s structure.

## DuckDB CLI

For ad-hoc queries on Parquet files. Read-only — never use to query `data/*/raw/` or `data/*/processed/sentiment.parquet`.

```bash
# Non-interactive (preferred in Claude Code)
duckdb -c "SELECT attributed_player, neg_rate FROM 'data/2024-25/dashboard/player_overall.parquet' ORDER BY neg_rate DESC LIMIT 10"

# Interactive shell
duckdb
SELECT * FROM 'data/2024-25/dashboard/player_overall.parquet' LIMIT 10;
```

Always use aggregations or filters — never `SELECT *` without `LIMIT` (the `body` column on raw data will flood output).

## Rules

Domain-specific instructions in `.claude/rules/`:
- `git.md` — Commit convention (Angular style), branch naming
- `python.md` — Code style, patterns, logging, dataclasses
- `testing.md` — TDD workflow, pytest conventions
- `notion.md` — Notion workflow, 3-layer separation, session handoff skills

---

*Read rules before implementation. Run tests before commits.*