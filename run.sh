#!/usr/bin/env bash
# One-step launcher: sets up .venv on first run, then runs the assistant.
#
#   ./run.sh                 start the assistant (extra args pass through, e.g. ./run.sh --reset)
#   ./run.sh test            offline unit tests (no login needed)
#   ./run.sh demo            scripted demo with canned replies + checks (no login needed)
#   ./run.sh demo-live       scripted demo against the real model + checks, written to a temp dir
#
# Needs Python 3.11+. Set PYTHON=/path/to/python to pick a specific interpreter.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
STAMP="$VENV/.installed"

find_python() {
    local candidates=("${PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3)
    for py in "${candidates[@]}"; do
        [ -n "$py" ] && command -v "$py" >/dev/null 2>&1 || continue
        if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            echo "$py"
            return
        fi
    done
    echo "Python 3.11 or newer is required but was not found." >&2
    echo "Install it (e.g. 'brew install python@3.13') or set PYTHON=/path/to/python3.11+." >&2
    exit 1
}

# (Re)install when the venv is missing or pyproject.toml changed since the last install.
if [ ! -f "$STAMP" ] || [ pyproject.toml -nt "$STAMP" ]; then
    py=$(find_python)
    echo "Setting up $VENV with $("$py" --version) (first run only)..."
    "$py" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --disable-pip-version-check -e '.[dev]'
    touch "$STAMP"
fi

case "${1:-}" in
    test)
        shift
        exec "$VENV/bin/pytest" -q "$@"
        ;;
    demo)
        shift
        exec "$VENV/bin/python" scripts/demo.py --fake --check "$@"
        ;;
    demo-live)
        shift
        out=$(mktemp -d)
        echo "Writing demo data and transcript to $out"
        exec "$VENV/bin/python" scripts/demo.py --check \
            --data-dir "$out/data" --transcript "$out/transcript.md" "$@"
        ;;
    *)
        exec "$VENV/bin/startup-assistant" "$@"
        ;;
esac
