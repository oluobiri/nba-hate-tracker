# Git Conventions

## Commit Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Subject rules:**
- Imperative mood: "add" not "added" or "adds"
- Lowercase first letter
- No period at end
- Max 72 characters

**Body:** Explain *what* and *why*, not *how*. Wrap at 72 characters.

## Valid Types

`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `chore`

## Valid Scopes

| Scope | Use For |
|-------|---------|
| `pipeline` | ArcticShiftClient, processors, batch jobs |
| `data` | Data processing, schemas, Polars transforms |
| `sentiment` | Classification logic, prompts |
| `api` | Anthropic Batch API integration |
| `app` | Streamlit dashboard |
| `config` | Environment, pyproject.toml, settings |
| `tests` | Test files, fixtures |
| `docs` | README, strategy docs |
| `deps` | Dependency changes |

## Branch Naming

```
<type>/<descriptive-name>
```

Prefixes: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`, `test/`

Examples: `feature/arctic-shift-client`, `fix/rate-limit-handling`, `refactor/comment-pipeline`

## PR Titles

Use commit format: `type(scope): subject`

## Pre-Commit

Run `uv run pytest` and `uv run ruff check .` before committing.