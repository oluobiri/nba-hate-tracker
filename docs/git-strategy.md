# Git Strategy 

This document defines the Git workflow, commit conventions, and branch naming strategies for the NBA Hate Tracker project. **AI assistants should follow these guidelines when creating commits, branches, and pull requests.**

---

## Commit Message Convention

We follow the [Angular Commit Message Convention](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md) with project-specific scopes.

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Example:**
```
feat(pipeline): implement ArcticShiftClient with pagination

- Add fetch_comments() and fetch_posts() methods
- Implement rate limiting with configurable delay
- Handle API pagination with cursor-based iteration

Enables reusable data fetching for Phase 2
```

### Type

Must be one of the following:

| Type | Use For |
|------|---------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only changes |
| `style` | Formatting, no code change (white-space, missing semi-colons, etc.) |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `build` | Build system, dependencies, tooling |
| `chore` | Maintenance tasks |

### Scope

Project-specific scopes for NBA Hate Tracker:

#### Data & Pipeline
| Scope | Use For |
|-------|---------|
| `pipeline` | ArcticShiftClient, CommentPipeline, processors, batch jobs |
| `data` | Data processing, schemas, Polars transforms, filtering |
| `sentiment` | Classification logic, prompts, result parsing |

#### Infrastructure
| Scope | Use For |
|-------|---------|
| `api` | Anthropic Batch API integration |
| `infra` | AWS resources (S3, Athena, DynamoDB, Step Functions) |
| `app` | Streamlit dashboard, UI components |

#### Technical
| Scope | Use For |
|-------|---------|
| `config` | Environment variables, pyproject.toml, yaml configs |
| `tests` | Test files, fixtures, conftest.py |
| `deps` | Dependency updates |
| `build` | uv setup, project structure |

#### Meta
| Scope | Use For |
|-------|---------|
| `docs` | README, strategy docs, CLAUDE.md |

**Scope is optional but recommended.** Use the most specific applicable scope.

### Subject

- Use the imperative, present tense: "add" not "added" nor "adds"
- Don't capitalize the first letter
- No period (.) at the end
- Maximum 72 characters

### Body

- Explain *what* and *why*, not *how*
- Wrap at 72 characters
- Separate from subject with blank line
- Optional for simple changes

### Footer

- Reference issues or PRs if applicable
- Breaking changes noted with `BREAKING CHANGE:` prefix

---

## Branching Strategy

We use a **feature branch workflow**:

- `main` - Stable code, passing tests
- Feature/fix branches - Created from `main`, merged via PR

**No direct commits to `main`.** All changes go through pull requests.

### Branch Naming Convention

```
<type>/<descriptive-name>
```

| Prefix | Use For |
|--------|---------|
| `feature/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring |
| `perf/` | Performance improvements |
| `test/` | Adding or updating tests |
| `docs/` | Documentation changes |
| `chore/` | Maintenance tasks |

**Naming guidelines:**
- Use lowercase
- Use hyphens to separate words
- Be descriptive but concise

**Examples:**
```
feature/arctic-shift-client
feature/comment-pipeline
feature/batch-api-integration
fix/rate-limit-handling
fix/flair-normalization
refactor/extract-formatting-utils
perf/streaming-decompression
test/processor-unit-tests
docs/update-readme
chore/upgrade-polars
```

### Branch Workflow

1. **Create branch from `main`:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/your-feature-name
   ```

2. **Make commits following convention:**
   ```bash
   uv run pytest                    # Run tests
   uv run ruff check . --fix        # Lint and fix
   git add .
   git commit -m "type(scope): subject"
   ```

3. **Push and create PR:**
   ```bash
   git push origin feature/your-feature-name
   ```

4. **After merge:**
   - Delete the feature branch
   - Pull latest main: `git pull origin main`

---

## Pull Request Guidelines

### PR Title

Use commit message format: `<type>(<scope>): <subject>`

**Examples:**
```
feat(pipeline): implement ArcticShiftClient
fix(data): handle malformed JSON in comments
refactor(utils): extract formatting utilities
test(pipeline): add processor unit tests
docs(docs): update engineering spec to v2.0
```

### PR Description

Use the template in `.github/PULL_REQUEST_TEMPLATE.md`.

### PR Best Practices

- Keep PRs focused (< 500 lines preferred)
- Ensure all tests pass before requesting review
- Delete branch after merge

---

## Example Commits

### Good Examples

```
feat(pipeline): implement ArcticShiftClient with pagination

- Add fetch_comments() and fetch_posts() methods
- Implement rate limiting with configurable delay
- Handle cursor-based pagination

Enables reusable API client for comments and posts download
```

```
feat(data): add comment cleaning pipeline

- Validate body field (non-empty, non-deleted)
- Extract required fields for sentiment analysis
- Track processing statistics

Achieves 97.87% acceptance rate on r/NBA comments
```

```
refactor(utils): extract formatting utilities

- Move format_duration() to utils/formatting.py
- Move format_size() to utils/formatting.py
- Update imports in download and clean scripts

Eliminates code duplication across scripts
```

```
fix(pipeline): handle rate limiting gracefully

Add exponential backoff when Arctic Shift returns 429.
Max 3 retries with 2/4/8 second delays.

Prevents data loss during high-volume downloads
```

```
test(pipeline): add ArcticShiftClient unit tests

- Test pagination logic with mock responses
- Test rate limiting behavior
- Test error handling for API failures

Achieves 90% coverage for arctic_shift.py
```

```
docs(docs): update spec with Phase 1 actuals

- Add actual volume numbers (6.89M comments)
- Document 22.4% player mention finding
- Update cost projections based on EDA

Version 2.0 reflects Phase 1 completion
```

```
chore(deps): upgrade polars to 1.2.0

Performance improvements for lazy evaluation.
No breaking changes.
```

### Bad Examples (Avoid)

```
❌ Update stuff
❌ Fixed bug
❌ WIP
❌ Changes
❌ asdfasdf
❌ Final version
```

---

## Testing Requirements

**Before committing:**
```bash
uv run pytest                    # All tests
uv run pytest tests/unit/        # Unit tests only
uv run pytest -x                 # Stop on first failure
uv run ruff check .              # Lint check
```

**Test expectations:**
| Change Type | Test Requirement |
|-------------|------------------|
| New pipeline components | Required: unit tests |
| New utility functions | Required if complex logic |
| Bug fixes | Required: regression test |
| Refactors | Existing tests must pass |
| Documentation | No tests needed |

---

## Pre-Commit Checklist

- [ ] Code runs without errors
- [ ] All tests pass (`uv run pytest`)
- [ ] Linting passes (`uv run ruff check .`)
- [ ] Commit message follows convention
- [ ] No hardcoded values (use `constants.py`)
- [ ] No large data files staged

## Pre-PR Checklist

- [ ] All commits follow convention
- [ ] Branch name follows convention
- [ ] Tests pass locally
- [ ] PR title follows format
- [ ] PR description is complete
- [ ] No merge conflicts with `main`

---

**Last Updated:** January 2, 2025  
**Version:** 1.0  
**Project:** NBA Hate Tracker