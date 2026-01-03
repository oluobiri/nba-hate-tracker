# CLAUDE.md

**Project:** Sentiment analysis pipeline to answer "Who is r/NBA's most hated player?"  
**Budget:** $300 ceiling, $200 target  
**Phase:** 2 (Posts download + filtering pipeline)

---

## Architecture Map

```
scripts/          → CLI entry points (thin wrappers)
pipeline/         → Data processing (ArcticShiftClient, CommentPipeline, batch jobs)
utils/            → Stateless helpers (constants, formatting)
analytics/        → SQL for Athena
app/              → Streamlit dashboard
tests/            → pytest (unit/, conftest.py)
notebooks/        → EDA and exploration
data/             → Not committed (raw/, filtered/)
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

- **Imports:** Use relative imports within packages, absolute for cross-package
- **Scripts:** Thin wrappers that call pipeline/ modules. Use `if __name__ == "__main__":`
- **Error handling:** Specific exceptions with context, preserve chains with `from e`
- **Type hints:** Required on all function signatures
- **Docstrings:** Google style, required for public functions

## Data Files

**Never read directly:**
- `data/raw/*.jsonl` (12+ GB)
- `data/filtered/*.jsonl` (2+ GB)

**For schema inspection:** Use `head -3 <file> | python -m json.tool` or sampling scripts.

## Rules

Domain-specific instructions in `.claude/rules/`:
- `git.md` — Commit convention (Angular style), branch naming
- `python.md` — Code style, patterns, anti-patterns
- `testing.md` — Testing conventions, rules, TDD workflow
- `polars.md` — Lazy evaluation, expression API (Phase 2+)

---

*Read rules before implementation. Run tests before commits.*