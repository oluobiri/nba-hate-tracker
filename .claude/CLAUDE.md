# CLAUDE.md - NBA Hate Tracker

**Project:** Sentiment analysis pipeline to answer "Who is r/NBA's most hated player?"  
**Answer:** Draymond Green (51.0% negative rate, 22/30 fanbases agree)  

---

## Architecture Map

```
scripts/          → CLI entry points (download, filter, batch, aggregate)
pipeline/         → Data processing (ArcticShiftClient, batch, aggregation)
utils/            → Stateless helpers (constants, formatting, paths, player_config, team_config)
config/           → YAML configs (season.yaml, 2024-25/players.yaml, teams.yaml)
app/              → Streamlit dashboard
tests/            → pytest (unit/, conftest.py)
notebooks/        → EDA and exploration (01-06)
data/             → Not committed
  ├── 2024-25/    → V1 season data
  │   ├── raw/        → Arctic Shift downloads
  │   ├── filtered/   → Player-mention filtered JSONL
  │   ├── batches/    → Batch API requests/responses
  │   ├── processed/  → sentiment.parquet
  │   └── dashboard/  → aggregates.json + per-table Parquet files
  └── 2025-26/    → V2 season data (same structure)
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
- `data/2024-25/batches/requests/*.jsonl`
- `data/2024-25/batches/responses/*.jsonl`

**Dashboard input:**
- `data/2024-25/dashboard/aggregates.json` — precomputed views, ~2MB, safe to load

## DuckDB CLI

For ad-hoc queries on Parquet files. Read-only — never use to query `data/*/raw/` or `data/*/processed/sentiment.parquet`.

```bash
# Non-interactive (preferred in Claude Code)
duckdb -c "SELECT player, neg_rate FROM 'data/2024-25/dashboard/player_overall.parquet' ORDER BY neg_rate DESC LIMIT 10"

# Interactive shell
duckdb
SET access_mode = 'read_only';
SELECT * FROM 'data/2024-25/dashboard/player_overall.parquet' LIMIT 10;
```

A `.duckdbrc` at project root sets read-only mode globally. Always use aggregations or filters — never `SELECT *` without `LIMIT` (the `body` column on raw data will flood output).

## Rules

Domain-specific instructions in `.claude/rules/`:
- `git.md` — Commit convention (Angular style), branch naming
- `python.md` — Code style, patterns, logging, dataclasses
- `testing.md` — TDD workflow, pytest conventions

---

*Read rules before implementation. Run tests before commits.*