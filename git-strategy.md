# Git Strategy - NBA Hate Tracker

This document defines the Git workflow and commit conventions for the NBA Hate Tracker project. **AI assistants should follow these guidelines when creating commits, branches, and pull requests.**

---

## Commit Message Convention

We follow the [Angular Commit Message Convention](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md) with project-specific scopes.

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| Type | Use For |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no code change |
| `refactor` | Code change that neither fixes nor adds |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `build` | Build system, dependencies, tooling |
| `chore` | Maintenance tasks |

### Scope

Project-specific scopes:

| Scope | Use For |
|-------|---------|
| `reddit` | PRAW client, authentication, fetching, rate limiting |
| `sentiment` | VADER, TextBlob, transformer models, analysis logic |
| `eda` | Notebooks, exploratory findings, validation work |
| `data` | Data processing, storage schemas, Polars transforms |
| `config` | Environment variables, pyproject.toml, settings |
| `tests` | Test files, fixtures |
| `docs` | README, strategy docs |
| `deps` | Dependency changes |
| `build` | uv setup, project structure |
| `api` | API endpoints (future V1) |
| `infra` | AWS infrastructure (future V1) |

Scope is optional but recommended.

### Subject Rules

- Imperative mood: "add" not "added" or "adds"
- Lowercase first letter
- No period at end
- Max 72 characters

### Body (Optional)

- Explain *what* and *why*, not *how*
- Wrap at 72 characters
- Separate from subject with blank line

---

## Branch Strategy

### Branch Types

```
<type>/<descriptive-name>
```

| Prefix | Use For |
|--------|---------|
| `feature/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring |
| `docs/` | Documentation |
| `chore/` | Maintenance |
| `eda/` | Exploratory analysis work |

### Naming Guidelines

- Lowercase with hyphens
- Descriptive but concise
- Include scope if helpful

**Examples:**
```
feature/reddit-client-auth
feature/vader-sentiment-analysis
eda/player-mention-frequency
fix/rate-limit-handling
docs/update-readme
chore/upgrade-dependencies
```

---

## Example Commits

### Good Examples

```
build(config): initialize project with uv

- Configure pyproject.toml with Python 3.11
- Add core dependencies: praw, polars, vaderSentiment, jupyter
- Create src/ and notebooks/ directory structure
```

```
feat(reddit): implement authenticated PRAW client

- Add Reddit authentication using environment variables
- Configure compliant user-agent string
- Set ratelimit_seconds for graceful backoff
```

```
feat(eda): analyze player mention frequency in r/NBA

- Sample 1000 comments from recent post-game threads
- Calculate mention rate for top 15 players
- Document finding: ~8% of comments reference players
```

```
feat(sentiment): add VADER sentiment baseline

- Implement get_sentiment() wrapper for vaderSentiment
- Add compound score extraction
- Test on sample Reddit comments
```

```
fix(reddit): handle MoreComments objects gracefully

Set replace_more(limit=0) to skip nested comment expansion.
Prevents API quota exhaustion on large threads.
```

```
docs(docs): add EDA findings and go/no-go recommendation
```

### Bad Examples (Avoid)

```
❌ Update stuff
❌ Fixed bug
❌ WIP
❌ Changes
❌ asdfasdf
```

---

## Workflow

### Creating a Branch

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
```

### Committing

```bash
git add .
git commit -m "type(scope): subject"
```

### Pushing

```bash
git push origin feature/your-feature-name
```

### Pull Request Title

Use commit format: `type(scope): subject`

---

## EDA Phase Guidelines

During exploratory analysis, commit frequency can be relaxed:

- Commit at logical checkpoints (not every cell execution)
- Use `eda` scope for notebook-related commits
- Findings and decisions are worth documenting in commit messages
- Perfect commit history matters less than capturing discoveries

**Example EDA commits:**

```
feat(eda): initial Reddit API connection test

Successfully authenticated and pulled 100 comments from r/NBA.
Rate limiting working as expected.
```

```
feat(eda): explore sentiment distribution in post-game threads

VADER shows 55% positive skew - confirms sarcasm detection issue.
Sample of 500 comments from 3 post-game threads.
```

```
docs(eda): document go/no-go recommendation

Green light for V1. Player mentions at 8%, sentiment signal detectable
despite sarcasm noise. Recommend team flair segmentation.
```

---

**Last Updated:** December 2024  
**Project:** NBA Hate Tracker  
**Phase:** EDA Validation
