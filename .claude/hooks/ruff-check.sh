#!/usr/bin/env bash
FILE_PATH=$(jq -r '.tool_input.file_path')
uv run ruff check "$FILE_PATH"
