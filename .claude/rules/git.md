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
| `pipeline` | data processing, batch jobs |
| `data` | Data processing, schemas, Polars transforms |
| `sentiment` | Classification logic, prompts |
| `api` | Anthropic Batch API integration |
| `app` | Streamlit dashboard |
| `config` | Environment, pyproject.toml, settings |
| `tests` | Test files, fixtures |
| `docs` | README, strategy docs |
| `deps` | Dependency changes |

## Commit Cadence

- **One logical change per commit** — a reviewer should be able to read the
  branch commit-by-commit, each with its own what/why body.
- **Commit at behavior boundaries, not file boundaries:** a red-green TDD
  cycle is one commit — the test and the implementation it pins land
  together. Never separate tests from the code they cover.
- **Every commit passes the gate alone.** The pre-commit hook runs ruff +
  pytest against the staged state, so this is enforced — don't fight it
  with `--no-verify`.
- **Order commits dependency-first:** contract/loader changes, then
  consumers, then docs.

## PR Scope

- One ticket, one branch, one PR. A PR spanning multiple pipeline stages
  with unrelated changes means the ticket was too big — split the ticket.
- A sub-deliverable that is independently mergeable and useful (e.g. a new
  loader + its wiring) may go as its own preceding PR.
- Merge strategy: squash is the default (main stays one-commit-per-ticket;
  intra-PR commits serve review). Use rebase-merge only when the commit
  structure itself is worth preserving on main.

## Branch Naming

```
<type>/<descriptive-name>
```

Prefixes: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`, `test/`

Examples: `feature/arctic-shift-client`, `fix/rate-limit-handling`, `refactor/season-config`

## PR Titles

Use commit format: `type(scope): subject`

## Pre-Commit

Run `uv run pytest` and `uv run ruff check .` before committing.