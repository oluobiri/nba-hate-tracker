#!/usr/bin/env bash
# Run one npm script from the web/ package as a pre-commit hook. Node is
# nvm-managed here, so a commit from a shell without nvm loaded gets it
# sourced first; a terminal commit already has it on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v node >/dev/null 2>&1; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    nvm use --silent >/dev/null
  fi
fi
exec npm run --silent "$1"
