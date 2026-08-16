---
paths:
  - "**/*.py"
---
# Python Conventions

**Style enforcement:** `ruff` handles formatting automatically. These rules cover what ruff cannot enforce.

## Imports

**Order:** Standard library → Third-party → Local (ruff enforces this)

Always use absolute imports.

```python
from pipeline.arctic_shift import ArcticShiftClient
from utils.constants import REQUIRED_FIELDS
```

## Type Hints

Required on all function signatures. Use modern syntax (Python 3.11+).

```python
# Good
def fetch_comments(self, subreddit: str, after: int, before: int) -> list[dict]:
    ...

def process(self, comment: dict) -> dict | None:
    ...

# Avoid
def fetch_comments(self, subreddit, after, before):  # Missing hints
    ...
```

## Docstrings

Google style. Required for all functions and classes.

```python
def has_valid_body(comment: dict) -> dict | None:
    """
    Check if comment has a valid, non-empty body.

    Args:
        comment: Comment dictionary with optional 'body' field.

    Returns:
        Original comment if body is valid, None otherwise.
    """
```

Skip docstrings only for obvious one-liners where the name says it all.

## Comments

Code explains itself; a comment carries the *why* the code can't. Keep them
short — a contract or section comment is a few lines, not a paragraph.

- **No links to doc sections.** `see docs/data-model.md §2` is a staleness
  time-bomb: sections move, get renumbered, or stop being about the thing.
  If the reasoning matters at the call site, state it in a sentence; if it's
  conceptual, the doc is where a reader goes anyway.
- **Ticket references only when the why is too long to summarize** — `(#84)`
  next to a value whose derivation lives in a ticket is fine; a ticket number
  as a substitute for saying what the code does is not.
- **Decisions and rejected alternatives live in tickets, not comments.** The
  comment says what the code does and the one non-obvious reason; the ticket
  keeps the debate.

```python
# Good
COMMENT_SAMPLES_MIN_CONFIDENCE = 0.9  # pos/neg only; neu is exempt

# Avoid
# The floor applies to pos/neg only. Neutral rows sit at a conventional
# 0.5 (see docs/data-model.md §1 and ticket #84's amendment of 2026-08-15,
# which considered and rejected a uniform 0.85 floor because ...)
```

## Testing

See `.claude/rules/testing.md` for testing conventions and TDD workflow.

## Error Handling

**Raise specific exceptions with context:**
```python
# Good
raise ValueError(f"Invalid subreddit: {subreddit!r}")
raise requests.RequestException(f"API failed after {retries} retries: {response.status_code}")

# Avoid
raise Exception("Something went wrong")
raise ValueError("Invalid input")
```

**Preserve exception chains:**
```python
try:
    response = self.session.get(url)
    response.raise_for_status()
except requests.RequestException as e:
    raise RuntimeError(f"Failed to fetch {url}") from e
```

**Log warnings for non-fatal issues:**
```python
if not comment.get("body"):
    logger.warning(f"Empty body for comment {comment.get('id')}")
    return None
```

## Logging

Use module-level logger. Configure in script entry points only.

```python
import logging

logger = logging.getLogger(__name__)

# In scripts (entry points), configure once:
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
```

**Log levels:**
| Level | Use For |
|-------|---------|
| `DEBUG` | Verbose details (pagination progress, individual records) |
| `INFO` | Key milestones (start/complete, totals) |
| `WARNING` | Recoverable issues (empty body, rate limit approached) |
| `ERROR` | Failures that stop processing |

## Module Structure

| Directory | Contains | Pattern |
|-----------|----------|---------|
| `scripts/` | CLI entry points | Thin wrappers, `if __name__ == "__main__":` |
| `pipeline/` | Processing logic | Classes with clear responsibilities |
| `utils/` | Shared helpers | Pure functions, stateless |

**Scripts are thin:**
```python
# scripts/download_comments.py
from pipeline.arctic_shift import ArcticShiftClient

def main():
    client = ArcticShiftClient()
    client.fetch_comments(...)

if __name__ == "__main__":
    main()
```

**Classes for stateful components (API clients), functions for stateless transforms:**
```python
# pipeline/arctic_shift.py
class ArcticShiftClient:
    """Handles all Arctic Shift API interactions."""
    
    def __init__(self, base_url: str = ARCTIC_SHIFT_BASE_URL, delay: float = 0.5):
        self.base_url = base_url
        self.delay = delay
        self.session = requests.Session()
    
    def fetch_comments(self, ...) -> list[dict]:
        ...
    
    def fetch_posts(self, ...) -> list[dict]:
        ...
```

**Utils are pure functions:**
```python
# utils/formatting.py
def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    ...

def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string. """
    ...
```

## Dataclasses

Use for data containers with minimal behavior.

```python
from dataclasses import dataclass

@dataclass
class ProcessingStats:
    """Track processing statistics."""
    
    total_processed: int = 0
    accepted: int = 0
    rejected_body: int = 0
    
    @property
    def acceptance_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.accepted / self.total_processed
```

Prefer `@dataclass` over plain classes when the primary purpose is holding data.

## Constants

System constants (field schemas, API config) live in `utils/constants.py`. Domain config (dates, thresholds, player lists) lives in YAML under `config/`. No magic strings in code.

```python
# Good
from utils.constants import REQUIRED_FIELDS, ARCTIC_SHIFT_BASE_URL

# Avoid
fields = ["id", "body", "author", "subreddit"]  # Magic list in random file
```

## Paths

Use `utils/paths.py` functions — never construct data paths with hardcoded strings.

```python
from utils.paths import get_filtered_dir

# Good
output_path = get_filtered_dir() / "cleaned.jsonl"

# Avoid
output_path = Path("data/filtered") / "cleaned.jsonl"  # Bypasses DATA_DIR env var
output_path = "data/filtered/" + "cleaned.jsonl"
```