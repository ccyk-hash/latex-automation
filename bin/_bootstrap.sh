#!/usr/bin/env bash
# Shared bootstrap for every latex-* wrapper.
#
# Responsibilities:
#   * pick a Python interpreter that actually executes, not one that merely
#     exists -- on Windows `python3` resolves to a Microsoft Store alias stub
#     that is found by `command -v` and then silently does nothing,
#   * locate the package relative to this script (never the cwd),
#   * normalise the console encoding so Chinese paths and log text survive,
#   * forward every argument untouched.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# TeX Live and this toolkit both print UTF-8; a CP936 console would mangle it.
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export PYTHONUTF8="${PYTHONUTF8:-1}"
# Widen TeX's log lines so long paths are not wrapped mid-filename.
export max_print_line="${max_print_line:-10000}"

_python_works() {
  # A candidate is usable only if it can print a version without erroring.
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

PYTHON_BIN="${LATEX_SKILL_PYTHON:-}"
if [ -n "$PYTHON_BIN" ] && ! _python_works "$PYTHON_BIN"; then
  echo "latex-skill: LATEX_SKILL_PYTHON=$PYTHON_BIN cannot run Python 3.8+" >&2
  exit 127
fi

if [ -z "$PYTHON_BIN" ]; then
  for candidate in python python3 py; do
    if command -v "$candidate" >/dev/null 2>&1 && _python_works "$candidate"; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "latex-skill: no working Python 3.8+ interpreter found on PATH" >&2
  echo "latex-skill: set LATEX_SKILL_PYTHON to an absolute interpreter path" >&2
  exit 127
fi

export PYTHONPATH="$PACKAGE_ROOT${PYTHONPATH:+:$PYTHONPATH}"

latex_skill_main() {
  local module="$1"
  shift
  exec "$PYTHON_BIN" -m "$module" "$@"
}
