---
paths:
  - "tests/**/*.py"
  - "pipeline/**/*.py"
  - "utils/**/*.py"
---
# Testing Conventions

## TDD Workflow

Follow red-green-refactor:

1. **Red:** Write a failing test that defines expected behavior
2. **Green:** Write minimal code to make the test pass
3. **Refactor:** Clean up while keeping tests green

```bash
uv run pytest tests/unit/test_new_feature.py -x  # Confirm red
# Write implementation
uv run pytest tests/unit/test_new_feature.py -x  # Confirm green
```

## Critical Rule

**Never modify tests to make implementation pass.**

If a test fails, fix the implementation — not the test. Do not:
- Comment out assertions
- Add `@pytest.mark.skip`
- Weaken assertions to match broken behavior
- Delete tests that are inconvenient

The only exception: if the test itself has a bug (wrong expected value, incorrect setup).

## Test Organization

```
tests/
├── conftest.py          # Shared fixtures
├── unit/                # Fast, isolated tests
│   ├── test_processors.py
│   ├── test_formatting.py
│   └── test_arctic_shift.py
└── integration/         # End-to-end, may touch files/network
    └── test_pipeline.py
```

Mirror the source structure:
- `pipeline/arctic_shift.py` → `tests/unit/test_arctic_shift.py`
- `utils/formatting.py` → `tests/unit/test_formatting.py`

## Naming

```python
# Test files
test_<module>.py

# Test functions: test_<function>_<scenario>
def test_filter_by_length_rejects_short_comments():
    ...

def test_filter_by_length_accepts_long_comments():
    ...

def test_fetch_comments_handles_rate_limit():
    ...
```

## Test Structure

Use Arrange-Act-Assert:

```python
def test_format_duration_handles_hours():
    """
    Verify hours are formatted correctly.
    """
    # Arrange
    seconds = 3661  # 1 hour, 1 minute, 1 second
    
    # Act
    result = format_duration(seconds)
    
    # Assert
    assert result == "1h 1m 1s"
```

## Parametrized Tests

Use `@pytest.mark.parametrize` for testing multiple inputs:

```python
import pytest

@pytest.mark.parametrize("seconds,expected", [
    (0, "0.0s"),
    (59, "59.0s"),
    (61, "1m 1s"),
    (3661, "1h 1m 1s"),
])
def test_format_duration(seconds: int, expected: str):
    """
    Verify duration formatting across various inputs.
    """
    assert format_duration(seconds) == expected
```

Prefer this over multiple similar test functions.

## Fixtures

Define in `conftest.py` for shared fixtures:

```python
# tests/conftest.py
import pytest

@pytest.fixture
def sample_comment() -> dict:
    """
    Standard comment for testing processors.
    """
    return {
        "id": "abc123",
        "body": "LeBron is the GOAT",
        "author": "user123",
        "author_flair_text": "Lakers",
        "subreddit": "nba",
        "created_utc": 1709251200,
        "link_id": "t3_post123",
    }

@pytest.fixture
def sample_comments(sample_comment) -> list[dict]:
    """
    List of comments for batch testing.
    """
    return [sample_comment] * 10
```

## Mocking

Mock external dependencies (API calls, file I/O):

```python
from unittest.mock import Mock, patch

def test_fetch_comments_handles_api_error():
    """
    Verify graceful handling of API failures.
    """
    client = ArcticShiftClient()
    
    with patch.object(client.session, "get") as mock_get:
        mock_get.side_effect = requests.RequestException("Connection failed")
        
        with pytest.raises(RuntimeError, match="Failed to fetch"):
            client.fetch_comments("nba", after=0, before=100)

def test_fetch_comments_paginates():
    """
    Verify pagination through multiple API pages.
    """
    client = ArcticShiftClient()
    
    mock_responses = [
        Mock(json=lambda: {"data": [{"id": "1"}]}),
        Mock(json=lambda: {"data": [{"id": "2"}]}),
        Mock(json=lambda: {"data": []}),  # Empty = done
    ]
    
    with patch.object(client.session, "get", side_effect=mock_responses):
        results = client.fetch_comments("nba", after=0, before=100)
    
    assert len(results) == 2
```

## What to Test

| Component | Test Focus |
|-----------|------------|
| `pipeline/` | Core logic, edge cases, error handling |
| `utils/` | Pure functions with various inputs |
| `scripts/` | Skip (thin wrappers, tested via integration) |

## When Tests Are Optional

Not everything needs unit tests. Skip tests for:

- **Throwaway scripts** — One-time data downloads, migrations
- **Thin CLI wrappers** — Scripts that just parse args and call pipeline code
- **Exploratory code** — Notebooks, one-off analysis

Focus testing effort on:

- **Reusable pipeline components** — `ArcticShiftClient`, `CommentPipeline`
- **Pure utility functions** — `format_duration`, `filter_by_length`
- **Complex logic** — Anything with branching, edge cases, or error handling

## Running Tests

```bash
uv run pytest                        # All tests
uv run pytest tests/unit/            # Unit only
uv run pytest -x                     # Stop on first failure
uv run pytest -v                     # Verbose output
uv run pytest --tb=short             # Shorter tracebacks
uv run pytest -k "arctic"            # Run tests matching pattern
```

## Integration Tests

Use for end-to-end validation that unit tests can't cover:

```python
# tests/integration/test_pipeline.py
def test_full_comment_processing(tmp_path):
    """
    Verify complete pipeline from raw input to filtered output.
    """
    # Arrange
    input_file = tmp_path / "input.jsonl"
    input_file.write_text('{"id": "1", "body": "LeBron is great"}\n')
    output_file = tmp_path / "output.jsonl"
    
    # Act
    process_comments(input_file, output_file)
    
    # Assert
    assert output_file.exists()
    result = output_file.read_text()
    assert "LeBron" in result
```

Integration tests can:
- Touch the filesystem (use `tmp_path` fixture)
- Take longer to run
- Test component interactions

Keep them minimal — most coverage should come from unit tests.