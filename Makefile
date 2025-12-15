# NBA Hate Tracker - Development Commands

.PHONY: test test-verbose test-fail-fast lint clean

# Run all tests
test:
	uv run pytest

# Verbose output — see print statements and full tracebacks
test-verbose:
	uv run pytest -v -s

# Stop on first failure — useful during development
test-fail-fast:
	uv run pytest -x

# Run a specific test file: make test-file FILE=tests/unit/test_extract.py
test-file:
	uv run pytest $(FILE) -v

# Lint with ruff
lint:
	uv run ruff check .

# Format with ruff
format:
	uv run ruff format .

# Clean up generated files
clean:
	rm -rf .pytest_cache
	rm -rf __pycache__
	rm -rf htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete