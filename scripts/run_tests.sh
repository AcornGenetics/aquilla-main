#!/usr/bin/env bash
# Run tests outside Docker containers on the device.
# Usage:
#   ./scripts/run_tests.sh              # safe tests (unit, contract, state)
#   ./scripts/run_tests.sh hardware     # hardware tests (stops containers first)
#   ./scripts/run_tests.sh all          # all non-hardware tests

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv-test"
MODE="${1:-safe}"

cd "$REPO_ROOT"

# Create venv and install test deps if not already done
if [ ! -f "$VENV/bin/pytest" ]; then
  echo "Setting up test venv..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -r requirements-test.txt
fi

run_pytest() {
  "$VENV/bin/pytest" "$@"
}

case "$MODE" in
  hardware)
    echo "Stopping containers to release GPIO..."
    sudo docker stop aquila-app aquila-backend 2>/dev/null || true
    run_pytest -m hardware -v
    echo "Restarting containers..."
    sudo docker start aquila-backend aquila-app 2>/dev/null || true
    ;;
  all)
    run_pytest -m "unit or contract or state or integration" -v
    ;;
  safe|*)
    run_pytest -m "unit or contract or state" -v
    ;;
esac
