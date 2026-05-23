#!/usr/bin/env bash
FILE_PATH=$(jq -r '.tool_input.file_path // .tool_input.path // ""')
BASENAME=$(basename "$FILE_PATH")

if [[ "$BASENAME" == .env* ]]; then
  echo "BLOCKED: .env files must not be read during AI sessions to prevent secret leakage" >&2
  exit 2
fi
