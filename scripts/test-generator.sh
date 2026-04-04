#!/usr/bin/env bash
# Entry point — delegates all logic to Python
set -euo pipefail
exec python3 "$(dirname "$0")/test-generator.py" "$@"
