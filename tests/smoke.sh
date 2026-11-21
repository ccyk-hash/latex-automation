#!/usr/bin/env bash
# End-to-end smoke suite for the latex-automation skill.
#
# Runs the eight cases from docs/00-research-plan.md against a scratch
# directory, so nothing here touches the caller's workspace. Two of them are
# the Windows putenv regressions: an absolute -output-directory whose path has
# a CJK run immediately followed by a space makes pdflatex/xelatex die with
# `fatal: putenv(TEXMF_OUTPUT_DIRECTORY=...)`. The skill must survive both.
#
# Usage: bash tests/smoke.sh [--keep]
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Windows Python does not understand MSYS paths such as /d/dsh/..., so anything
# handed to PYTHONPATH has to be converted first.
HERE_WIN="$(cygpath -w "$HERE" 2>/dev/null || true)"
[ -n "$HERE_WIN" ] || HERE_WIN="$HERE"

PY="${LATEX_SKILL_PYTHON:-python}"
WORK="$HERE/.smoke"
WORK_WIN="$(cygpath -w "$WORK" 2>/dev/null || true)"
[ -n "$WORK_WIN" ] || WORK_WIN="$WORK"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export PYTHONPATH="$HERE_WIN${PYTHONPATH:+;$PYTHONPATH}"

PASS=0
FAIL=0
FAILED_CASES=()

say() { printf '%s\n' "$*"; }
hr() { printf '%s\n' "------------------------------------------------------------"; }

# run_case <name> <cwd> <command...>
run_case() { _run_case pass "$@"; }

# run_case_fail <name> <cwd> <command...> — the command must exit non-zero,
# which is the correct contract for a genuinely broken document.
run_case_fail() { _run_case fail "$@"; }

_run_case() {
    local expect="$1"; shift
    local name="$1"; shift
    local dir="$1"; shift
    say ""
    hr
    say "CASE: $name"
    local rc=0
    ( cd "$dir" 2>/dev/null || { say "  [cwd fallback: $dir missing]"; cd "$HERE"; }; "$@" ) >"$WORK/log-$name.txt" 2>&1 || rc=$?
    local good=0
    if [ "$expect" = pass ] && [ "$rc" -eq 0 ]; then good=1; fi
    if [ "$expect" = fail ] && [ "$rc" -ne 0 ]; then good=1; fi
    if [ "$good" -eq 1 ]; then
        say "  PASS  $name"
        PASS=$((PASS + 1))
    else
        say "  FAIL  $name   (rc=$rc, see .smoke/log-$name.txt)"
        tail -n 12 "$WORK/log-$name.txt" | sed 's/^/      /'
        FAIL=$((FAIL + 1))
        FAILED_CASES+=("$name")
    fi
}

py() { "$PY" -m latex_automation "$@"; }

rm -rf "$WORK"
mkdir -p "$WORK"

# ------------------------------------------------------- repair / layout checks --
# These live as functions because the assertions need real parsing, and piling
# escaped quotes into `sh -c` strings hides the intent.
check_repair_moved() {
    "$PY" - "$WORK/repair-preamble/main.tex" <<'PYEOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
use = next(i for i, line in enumerate(lines) if "usepackage" in line)
begin = next(i for i, line in enumerate(lines) if "begin{document}" in line)
if use > begin:
    sys.exit("usepackage was not moved into the preamble")
PYEOF
}

check_repair_backup() {
    test -f "$WORK/repair-preamble/latex-out/repair/round-1/main.tex"
}

check_repair_diag() {
    test -f "$WORK/repair-preamble/latex-out/round-1.diag.json"
}

check_layout_report() {
    "$PY" - "$WORK/layout-box/layout.json" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
if not data.get("pages"):
    sys.exit("layout report has no pages")
# Geometry cannot see a box that fits on the paper but tears the measure, so the
# log is the only witness for some defects; either source counts as reported.
counts = data.get("counts", {})
if not counts.get("issues") and not counts.get("log_overfull"):
    sys.exit("layout report recorded no issue for an overfull box")
PYEOF
}

say "latex-automation smoke suite"
say "package : $HERE_WIN"
say "python  : $($PY -c 'import sys; print(sys.version.split()[0], sys.executable)')"
say "scratch : $WORK_WIN"

# ---------------------------------------------------------------- 1. doctor --
run_case doctor "$HERE" "$PY" -m latex_automation doctor

# ------------------------------------------------------------- 2. templates --
for tpl in article zh biblatex beamer tikz; do
    run_case "init-$tpl" "$HERE" \
        "$PY" -m latex_automation init "$WORK/$tpl" --template "$tpl" --title "Smoke $tpl"
done

# ------------------------------------------ 3..7. the five real documents --
run_case build-article "$HERE" "$PY" -m latex_automation build "$WORK/article"
run_case build-zh "$HERE" "$PY" -m latex_automation build "$WORK/zh"
run_case build-biblatex "$HERE" "$PY" -m latex_automation build "$WORK/biblatex"
run_case build-beamer "$HERE" "$PY" -m latex_automation build "$WORK/beamer"
run_case build-tikz "$HERE" "$PY" -m latex_automation build "$WORK/tikz"

# ------------------------------------------- 8..9. putenv regression matrix --
# Both names contain a CJK run followed by a space, which is exactly the shape
# that breaks an absolute -output-directory on Windows TeX Live.
for spaced in "带 空格 目录" "中 文"; do
    target="$WORK/$spaced"
    "$PY" -m latex_automation init "$target" --template zh --title "回归 测试" \
        >"$WORK/log-init-$spaced.txt" 2>&1
    run_case "putenv-$spaced" "$HERE" \
        "$PY" -m latex_automation build "$target"
done

# ------------------------------------------------------ 10. failure paths --
# A failing build must exit non-zero and still leave a report whose root cause
# is classified, not a raw log dump.
# Each failing document gets its own project directory: the outdir has to live
# inside the project so the engine can be handed a relative -output-directory.
for bad in broken misspkg; do
    mkdir -p "$WORK/bad-$bad"
    cp "$HERE/fixtures/$bad.tex" "$WORK/bad-$bad/"
done

run_case_fail build-broken "$HERE" \
    "$PY" -m latex_automation build "$WORK/bad-broken"
run_case_fail build-misspkg "$HERE" \
    "$PY" -m latex_automation build "$WORK/bad-misspkg"

# From the project root, `logs` resolves the log through the master .tex, so it
# does not need the log path spelled out.
run_case_fail logs-broken "$WORK/bad-broken" \
    "$PY" -m latex_automation logs . --json
run_case_fail logs-misspkg "$WORK/bad-misspkg" \
    "$PY" -m latex_automation logs . --json

# ------------------------------------------------------ 11. render / check --
run_case render "$HERE" "$PY" -m latex_automation render "$WORK/zh" --dpi 100
run_case check "$HERE" "$PY" -m latex_automation check "$WORK/article"
run_case clean "$HERE" "$PY" -m latex_automation clean "$WORK/article"

# ------------------------------------------------------- 12. repair loop --
# P4: the loop turns one root cause into one suggestion per round and leaves a
# per-round .diag.json behind.  A clean document converges immediately; a
# document with a single recoverable defect must repair itself in place.
mkdir -p "$WORK/repair-ok"
cat > "$WORK/repair-ok/main.tex" <<'TEXEOF'
\documentclass{article}
\begin{document}
Hello.
\end{document}
TEXEOF
run_case repair-already-ok "$HERE" \
    "$PY" -m latex_automation repair "$WORK/repair-ok" --json

mkdir -p "$WORK/repair-preamble"
cat > "$WORK/repair-preamble/main.tex" <<'TEXEOF'
\documentclass{article}
\begin{document}
\usepackage{amsmath}
Hello.
\end{document}
TEXEOF
run_case repair-preamble "$HERE" \
    "$PY" -m latex_automation repair "$WORK/repair-preamble" --apply
# The repair must have moved the package, and must have kept a backup of the
# file it edited rather than rewriting it in place with no trace.
run_case repair-preamble-moved "$HERE" check_repair_moved
run_case repair-preamble-backup "$HERE" check_repair_backup
run_case repair-diag-json "$HERE" check_repair_diag

# A document whose defect no local edit can fix must stop and say so instead of
# burning rounds.
mkdir -p "$WORK/repair-human"
cat > "$WORK/repair-human/main.tex" <<'TEXEOF'
\documentclass{article}
\usepackage{nonexistentpkgxyz}
\begin{document}
Hello.
\end{document}
TEXEOF
run_case_fail repair-needs-human "$HERE" \
    "$PY" -m latex_automation repair "$WORK/repair-human"

# ------------------------------------------------------- 13. layout check --
# P5: geometry is measured from pdftotext boxes.  A conforming document is
# silently fine; a document with a bad box is reported with severity, and the
# exit code follows severity rather than the heuristic confidence.
run_case layout-ok "$HERE" \
    "$PY" -m latex_automation layout "$WORK/zh" --json
mkdir -p "$WORK/layout-box"
cat > "$WORK/layout-box/main.tex" <<'TEXEOF'
\documentclass{article}
\begin{document}
\noindent\rule{470pt}{10pt}

Text after a very wide rule that runs far past the measure of the page.
\end{document}
TEXEOF
"$PY" -m latex_automation build "$WORK/layout-box" >/dev/null 2>&1
run_case_fail layout-overfull "$HERE" \
    "$PY" -m latex_automation layout "$WORK/layout-box"
run_case_fail layout-report "$HERE" \
    "$PY" -m latex_automation layout "$WORK/layout-box" --report "$WORK/layout-box/layout.json" --json
run_case layout-report-written "$HERE" check_layout_report

# ------------------------------------------------- 12. artifact contracts --
check_reports() {
    local ok=0
    "$PY" - "$WORK_WIN" <<'PYCODE' || ok=1
import json, pathlib, sys

work = pathlib.Path(sys.argv[1])

# A healthy build: success, a PDF on disk, and a schema-stable report.
zh = json.loads((work / "zh" / "latex-out" / "build-report.json").read_text(encoding="utf-8"))
assert zh["schema"] >= 4, zh.get("schema")
assert zh["status"] == "success", zh["status"]
for key in ("engine", "source", "outdir", "duration_ms", "pdf_sha256", "steps"):
    assert key in zh, key
assert (work / "zh" / "latex-out" / "main.pdf").is_file(), "no pdf next to report"
assert zh["pdf_sha256"], "pdf hash missing"

# The CJK+space builds must have produced real PDFs too.
for spaced in ("带 空格 目录", "中 文"):
    pdf = work / spaced / "latex-out" / "main.pdf"
    assert pdf.is_file(), f"missing pdf for {spaced}"
    assert pdf.read_bytes()[:5] == b"%PDF-", f"bad magic for {spaced}"

# A broken build: failure recorded, at least one error, cascade folded away.
bad = json.loads((work / "bad-broken" / "latex-out" / "build-report.json").read_text(encoding="utf-8"))
assert bad["status"] == "failed", bad["status"]
assert bad["failure"], "failure message missing"
cats = {e["category"] for e in bad["log"]["errors"]}
assert "undefined_macro" in cats, cats
assert bad["log"]["counts"]["suppressed_cascade"] >= 1, bad["log"]["counts"]

# A missing package: attributed to the author's file, with an install hint.
miss = json.loads((work / "bad-misspkg" / "latex-out" / "build-report.json").read_text(encoding="utf-8"))
assert miss["status"] == "failed", miss["status"]
assert "nonexistentpkgxyz.sty" in miss["log"]["missing_packages"], miss["log"]["missing_packages"]
root = miss["log"]["root_cause"]
assert root["category"] == "missing_package", root
assert root["file"] == "misspkg.tex", root
print("artifact contracts ok")
PYCODE
    return $ok
}
run_case artifact-contracts "$HERE" check_reports

# ------------------------------------------------------------------ verdict --
say ""
hr
say "summary: $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
    say "failed cases:"
    for c in "${FAILED_CASES[@]}"; do say "  - $c"; done
    [ "$KEEP" -eq 0 ] && say "(scratch kept for inspection: $WORK_WIN)"
    exit 1
fi
[ "$KEEP" -eq 0 ] && rm -rf "$WORK"
say "all smoke cases passed"
exit 0
