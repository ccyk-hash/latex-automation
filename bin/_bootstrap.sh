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

# `pwd` here yields a POSIX path (/d/dsh/...) that a native python.exe cannot
# resolve on PYTHONPATH. Convert it: cygpath is authoritative where it exists,
# `pwd -W` covers MSYS bash, and a POSIX path means no conversion is needed.
PACKAGE_ROOT_WIN="$(cygpath -w "$PACKAGE_ROOT" 2>/dev/null)"
PATH_JOIN_SEP=';'
if [ -z "$PACKAGE_ROOT_WIN" ]; then
  PACKAGE_ROOT_WIN="$(cd "$PACKAGE_ROOT" && pwd -W 2>/dev/null)"
fi
if [ -z "$PACKAGE_ROOT_WIN" ]; then
  PACKAGE_ROOT_WIN="$PACKAGE_ROOT"
  PATH_JOIN_SEP=':'
fi

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

# WorkBuddy ships a managed interpreter that is guaranteed to exist there while
# the system `python` may not; try it before falling back to PATH names.
WORKBUDDY_PYTHON="${WORKBUDDY_PYTHON:-$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"

if [ -z "$PYTHON_BIN" ]; then
  # `_python_works` runs the candidate, so it doubles as the existence test and
  # as the "does it actually execute" test.
  for candidate in python "$WORKBUDDY_PYTHON" python3 py; do
    if _python_works "$candidate"; then
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

export PYTHONPATH="$PACKAGE_ROOT_WIN${PYTHONPATH:+$PATH_JOIN_SEP$PYTHONPATH}"

latex_skill_main() {
  local module="$1"
  shift
  exec "$PYTHON_BIN" -m "$module" "$@"
}
