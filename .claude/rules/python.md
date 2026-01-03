---
paths:
  - "**/*.py"
---
# Python Conventions

**Style enforcement:** `ruff` handles formatting automatically. These rules cover what ruff cannot enforce.

## Imports

**Order:** Standard library → Third-party → Local (ruff enforces this)

**Relative vs absolute:**
- Within a package: use relative (`from .arctic_shift import ArcticShiftClient`)
- Cross-package: use absolute (`from utils.formatting import format_duration`)

```python
# In pipeline/processors.py
from .arctic_shift import ArcticShiftClient  # Same package: relative
from utils.constants import FIELDS_TO_KEEP   # Different package: absolute
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
def filter_by_length(comment: dict, min_length: int = 20) -> dict | None:
    """
    Filter comments below minimum character length.

    Args:
        comment: Comment dict with 'body' field.
        min_length: Minimum character count. Defaults to 20.

    Returns:
        Original comment if passes filter, None otherwise.
    """
```

Skip docstrings only for obvious one-liners where the name says it all.

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

**Pipeline classes own their domain:**
```python
# pipeline/arctic_shift.py
class ArcticShiftClient:
    """Handles all Arctic Shift API interactions."""
    
    def __init__(self, base_url: str = ARCTIC_SHIFT_URL, delay: float = 0.5):
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

Centralize in `utils/constants.py`. No magic strings in code.

```python
# Good
from utils.constants import FIELDS_TO_KEEP, ARCTIC_SHIFT_URL

# Avoid
fields = ["id", "body", "author", "subreddit"]  # Magic list in random file
```

## Paths

Use `pathlib.Path`, not string concatenation.

```python
from pathlib import Path

# Good
output_path = Path("data/filtered") / "cleaned.jsonl"

# Avoid
output_path = "data/filtered/" + "cleaned.jsonl"
```