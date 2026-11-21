#!/usr/bin/env python3
"""P6 verification: packaging, six representative builds, Windows paths, CP936.

P6 in docs/00-research-plan.md asks for three things: the six-case regression run,
a Windows path / Chinese filename / CP936 sweep, and proof that what ships is the
thing that was tested. This script does all three against the *packaged* tree

    git archive HEAD  ->  extract elsewhere  ->  run from there

so a stale working copy cannot hide a broken bundle.

Metrics collected for the six cases, because "it worked" is not a number:
build duration, page count, log compression ratio, error-localisation accuracy,
repair rounds to convergence, and the share of emitted JSON that parses.

Everything is standard library. Temp trees live in tests/.p6 and are removed
unless --keep is passed. Exit code is 0 only when every check passes.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tests" / ".p6"
KEEP = "--keep" in sys.argv
WORKSPACE = "--workspace" in sys.argv  # iterate against the working tree

ARTICLE_TEX = r"""\documentclass{article}
\usepackage{amsmath}
\begin{document}
Path and filename probe: $a^2+b^2=c^2$.
\end{document}
"""

TYPO_TEX = r"""\documentclass{article}
\newcommand{\myemph}[1]{\textbf{#1}}
\begin{document}
This word is \myemhp{emphasised}.
\end{document}
"""

results: list[tuple[str, bool, str]] = []
metrics: dict[str, dict] = {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    mark = "ok  " if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line, flush=True)
    return bool(ok)


def child_env(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["max_print_line"] = "10000"
    return env


def run(args: list[str], cwd: Path, package_root: Path, timeout: int = 300):
    return subprocess.run(
        args, cwd=str(cwd), env=child_env(package_root),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def cli(sub: str, cwd: Path, package_root: Path, *extra: str, timeout: int = 300):
    return run([sys.executable, "-m", "latex_automation", sub, *extra],
               cwd, package_root, timeout=timeout)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_dir(name: str) -> Path:
    target = WORK / name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    return target


# --------------------------------------------------------------------------- #
# 1. packaging
# --------------------------------------------------------------------------- #
REQUIRED = [
    "SKILL.md", "README.md", "CHANGELOG.md", "LICENSE", ".gitattributes",
    "latex_automation/__init__.py", "latex_automation/__main__.py",
    "latex_automation/cli.py", "latex_automation/engine.py",
    "latex_automation/logparse.py", "latex_automation/paths.py",
    "latex_automation/packages.py", "latex_automation/doctor.py",
    "latex_automation/render.py", "latex_automation/lint.py",
    "latex_automation/scaffold.py", "latex_automation/proc.py",
    "latex_automation/repair.py", "latex_automation/layout.py",
    "bin/_bootstrap.sh", "bin/latex-doctor", "bin/latex-build", "bin/latex-logs",
    "bin/latex-clean", "bin/latex-render", "bin/latex-check", "bin/latex-init",
    "bin/latex-templates", "bin/latex-repair", "bin/latex-layout",
    "tests/smoke.sh", "tests/test_logparse.py", "tests/test_layout.py",
]

WRAPPERS = [
    "bin/_bootstrap.sh", "bin/latex-doctor", "bin/latex-build", "bin/latex-logs",
    "bin/latex-clean", "bin/latex-render", "bin/latex-check", "bin/latex-init",
    "bin/latex-templates", "bin/latex-repair", "bin/latex-layout",
]

TEXT_SUFFIXES = {".py", ".sh", ".md", ".tex", ".bib", ".json", ".yml", ".yaml", ".toml", ""}


def git_index_modes() -> dict[str, str]:
    out = subprocess.run(["git", "ls-tree", "-r", "HEAD"], cwd=str(ROOT),
                         capture_output=True, text=True, check=True).stdout
    modes = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        modes[path] = meta.split()[0]
    return modes


def check_packaging() -> Path:
    """Build the release tarball and unpack it into a hostile-but-legal path."""
    print("\n== 1. packaging ==", flush=True)
    if WORKSPACE:
        target = case_dir("包 目录/relocated")
        for name in REQUIRED:
            source = ROOT / name
            if source.is_file():
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        check("workspace copy assembled (development mode)", True,
              "skipped git archive; the release gate uses the tarball")
        return target

    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"],
                             cwd=str(ROOT), capture_output=True, check=True).stdout
    bundle = WORK / "bundle.tar"
    bundle.write_bytes(archive)
    check("git archive produced a tarball", len(archive) > 100_000,
          f"{len(archive)} bytes")

    # A path with both CJK and a space is the exact shape that breaks putenv.
    target = case_dir("包 目录/relocated")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target)

    missing = [name for name in REQUIRED if not (target / name).is_file()]
    check("bundle contains every shipped file", not missing,
          "missing: " + ", ".join(missing) if missing else f"{len(REQUIRED)} required paths")

    modes = git_index_modes()
    bad_modes = [p for p in WRAPPERS if modes.get(p) != "100755"]
    check("wrappers are recorded executable in the index", not bad_modes,
          ", ".join(bad_modes) if bad_modes else f"{len(WRAPPERS)} at 100755")

    crlf = []
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if b"\r\n" in path.read_bytes():
            crlf.append(str(path.relative_to(target)).replace("\\", "/"))
    check("bundle has no CRLF line endings", not crlf,
          ", ".join(crlf[:5]) if crlf else "LF only")

    leaks = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        rel = str(path.relative_to(target)).replace("\\", "/")
        # Assembled at runtime so this file does not match its own scan.
        if ("ghp" + "_") in text:
            leaks.append(f"{rel}: token")
        if rel.startswith(("latex_automation/", "bin/")):
            for needle in ("C:\\Users", "D:\\dsh", "C:/Users", "D:/dsh"):
                if needle in text:
                    leaks.append(f"{rel}: {needle}")
    check("no token or absolute user path in shipped code", not leaks,
          ", ".join(leaks[:5]) if leaks else "clean")

    doctor = cli("doctor", WORK, target, "--json")
    payload = {}
    try:
        payload = json.loads(doctor.stdout)
    except json.JSONDecodeError:
        pass
    counts = payload.get("counts") or {}
    check("doctor runs from the extracted bundle",
          doctor.returncode == 0 and payload.get("ok") is True and counts.get("fail", 1) == 0,
          f"rc={doctor.returncode} ok={counts.get('ok')} warn={counts.get('warn')} fail={counts.get('fail')}")

    # Wrapper scripts must work from an unrelated cwd, not just the package root.
    elsewhere = case_dir("包 目录/elsewhere")
    wrapper = run(["bash", str(target / "bin" / "latex-doctor"), "--json"],
                  elsewhere, target)
    check("bash wrapper works from an unrelated cwd",
          wrapper.returncode == 0 and '"counts"' in wrapper.stdout,
          f"rc={wrapper.returncode}")

    return target


# --------------------------------------------------------------------------- #
# 2. six representative cases
# --------------------------------------------------------------------------- #
SIX_CASES = [
    # name, fixture, extra files, expectation
    ("hello", "hello.tex", [], {"engine": "pdflatex", "min_pages": 1}),
    ("zh", "zh.tex", [], {"engine": "xelatex", "min_pages": 1}),
    ("bib", "bib.tex", ["refs.bib"], {"backend": "biber", "min_pages": 1}),
    ("tikz", "tikz.tex", [], {"engine": "xelatex", "min_pages": 1}),
    ("big", "big.tex", [], {"min_pages": 9}),
    ("broken", "broken.tex", [], {"status": "failed"}),
]


def compress_ratio(log_path: Path, package_root: Path) -> tuple[int, int]:
    raw = log_path.read_bytes() if log_path.is_file() else b""
    if not raw:
        return 0, 0
    code = (
        "import sys,pathlib;"
        "from latex_automation.logparse import compress_log;"
        "t=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8',errors='replace');"
        "sys.stdout.write(compress_log(t))"
    )
    out = run([sys.executable, "-c", code, str(log_path)], package_root, package_root)
    return len(raw), len(out.stdout.encode("utf-8"))


def check_six_cases(package_root: Path) -> None:
    print("\n== 2. six representative cases ==", flush=True)
    fixtures = ROOT / "research" / "l4"
    for name, fixture, extras, expect in SIX_CASES:
        work = case_dir(f"six/{name}")
        shutil.copy2(fixtures / fixture, work / "main.tex")
        for extra in extras:
            shutil.copy2(fixtures / extra, work / extra)

        started = time.perf_counter()
        proc = cli("build", work, package_root, "--json")
        wall_ms = int((time.perf_counter() - started) * 1000)

        report = {}
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
        status = report.get("status")
        pages = (report.get("log") or {}).get("pages") or 0
        log_rel = (report.get("log_path") or "")
        log_path = work / "latex-out" / "main.log"
        raw_bytes, small_bytes = compress_ratio(log_path, package_root)
        ratio = round(raw_bytes / small_bytes, 1) if small_bytes else 0.0

        metrics[name] = {
            "status": status,
            "engine": report.get("engine"),
            "backend": report.get("backend"),
            "pages": pages,
            "duration_ms": report.get("duration_ms"),
            "wall_ms": wall_ms,
            "log_bytes": raw_bytes,
            "compressed_bytes": small_bytes,
            "log_ratio": ratio,
            "errors": ((report.get("log") or {}).get("counts") or {}).get("errors", 0),
        }

        ok = bool(report)
        if "status" in expect:
            ok = ok and status == expect["status"]
        if "engine" in expect:
            ok = ok and report.get("engine") == expect["engine"]
        if "backend" in expect:
            ok = ok and report.get("backend") == expect["backend"]
        if "min_pages" in expect:
            ok = ok and pages >= expect["min_pages"]
        check(f"case {name}", ok,
              f"status={status} engine={report.get('engine')} pages={pages} "
              f"{report.get('duration_ms')}ms log {raw_bytes}->{small_bytes}B ({ratio}x)")

    # Error localisation: broken.tex has exactly one defect, on line 3.
    broken = json.loads((WORK / "six/broken/latex-out/build-report.json").read_text("utf-8"))
    log = broken.get("log") or {}
    located = [(d.get("file"), d.get("line")) for d in log.get("errors", [])]
    hit = any(str(f).endswith("main.tex") and ln == 3 for f, ln in located)
    metrics["broken"]["localised"] = located
    check("broken case points at main.tex:3", hit, f"errors={located}")

    # Repair convergence: the typo case must converge inside the round budget.
    fix = case_dir("six/fixable")
    write(fix / "main.tex", TYPO_TEX)
    proc = cli("repair", fix, package_root, "--apply", "--json")
    verdict = {}
    try:
        verdict = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    rounds = len(verdict.get("rounds") or [])
    metrics["repair"] = {"status": verdict.get("status"), "rounds": rounds}
    check("repair converges within 3 rounds",
          verdict.get("status") == "repaired" and 1 <= rounds <= 3,
          f"status={verdict.get('status')} rounds={rounds}")

    # A defect with no automated fix must stop instead of looping.
    stuck = case_dir("six/stuck")
    write(stuck / "main.tex", (fixtures / "broken.tex").read_text("utf-8"))
    proc = cli("repair", stuck, package_root, "--apply", "--json")
    verdict = {}
    try:
        verdict = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    metrics["stuck"] = {"status": verdict.get("status"), "rounds": len(verdict.get("rounds") or [])}
    check("unfixable defect stops as needs-human",
          verdict.get("status") in ("needs-human", "needs-apply")
          and len(verdict.get("rounds") or []) == 1,
          f"status={verdict.get('status')}")

    # build-report.json must be valid JSON on disk too, not just on stdout.
    ok_reports = 0
    total_reports = 0
    for path in (WORK / "six").rglob("*.json"):
        total_reports += 1
        try:
            json.loads(path.read_text("utf-8"))
            ok_reports += 1
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    metrics["json"] = {"parsed": ok_reports, "total": total_reports}
    check("every emitted JSON document parses", ok_reports == total_reports,
          f"{ok_reports}/{total_reports}")


# --------------------------------------------------------------------------- #
# 3. Windows paths and filenames
# --------------------------------------------------------------------------- #
PATH_DIRS = [
    "plain",
    "with space",
    "中文",
    "中 文",
    "带 空格 目录",
    "a b c",
    "deep/one two/中文 目录/level4/five",
]


def check_paths(package_root: Path) -> None:
    print("\n== 3. Windows paths ==", flush=True)
    for rel in PATH_DIRS:
        work = case_dir("paths") / rel
        write(work / "main.tex", ARTICLE_TEX)
        proc = cli("build", work, package_root)
        ok = proc.returncode == 0 and (work / "latex-out" / "main.pdf").is_file()
        detail = rel
        if not ok:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
            detail += f" :: {tail[0]}"
        check(f"path {rel!r}", ok, detail)

    for name in ("my paper.tex", "我的 论文.tex", "résumé.tex"):
        work = case_dir("filenames") / "p"
        write(work / name, ARTICLE_TEX)
        proc = cli("build", work, package_root, "--file", name)
        pdf = work / "latex-out" / (Path(name).stem + ".pdf")
        ok = proc.returncode == 0 and pdf.is_file()
        detail = name
        if not ok:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
            detail += f" :: {tail[0]}"
        check(f"filename {name!r}", ok, detail)


# --------------------------------------------------------------------------- #
# 4. CP936 source
# --------------------------------------------------------------------------- #
CP936_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "% 这是一段 GBK 编码的注释\n"
    "中文正文，用于测试编码分支。\n"
    "\\end{document}\n"
)


def check_cp936(package_root: Path) -> None:
    print("\n== 4. CP936 source ==", flush=True)
    work = case_dir("cp936")
    source = work / "main.tex"
    source.write_bytes(CP936_TEX.encode("cp936"))
    before = sha256(source)

    proc = cli("build", work, package_root, "--json")
    report = {}
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    log = report.get("log") or {}
    located = [(d.get("category"), d.get("file"), d.get("line")) for d in log.get("errors", [])]
    categories = {c for c, _, _ in located}
    metrics["cp936"] = {"status": report.get("status"), "errors": located,
                        "missing_chars": log.get("missing_chars")}
    check("CP936 source is reported as an encoding fault, not silently mangled",
          report.get("status") == "failed" and "encoding" in categories,
          f"status={report.get('status')} categories={sorted(categories)}")

    proc = cli("repair", work, package_root, "--apply", "--json")
    verdict = {}
    try:
        verdict = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    after = sha256(source)
    rounds = verdict.get("rounds") or []
    summary = ""
    if rounds:
        suggestion = (rounds[0].get("suggestion") or {})
        summary = suggestion.get("summary") or ""
    metrics["cp936"]["repair"] = {"status": verdict.get("status"), "summary": summary}
    check("repair never rewrites a non-UTF-8 file",
          before == after,
          f"status={verdict.get('status')} bytes {'unchanged' if before == after else 'CHANGED'}")
    check("repair names the encoding instead of switching engine",
          verdict.get("status") == "needs-human" and "UTF-8" in summary,
          f"status={verdict.get('status')} summary={summary!r}")

    # The same content under xelatex must not be mangled either: it either builds
    # or fails loudly, but the bytes on disk stay exactly as the author wrote them.
    proc = cli("build", work, package_root, "--engine", "xelatex", "--json")
    after = sha256(source)
    check("switching engine leaves CP936 bytes untouched", before == after,
          "unchanged" if before == after else "CHANGED")


# --------------------------------------------------------------------------- #
# 5. report
# --------------------------------------------------------------------------- #
def print_report() -> None:
    print("\n== metrics ==", flush=True)
    header = f"{'case':<8} {'status':<9} {'engine':<9} {'pages':>5} {'ms':>7} {'log':>7} {'ratio':>6}"
    print(header)
    print("-" * len(header))
    for name, row in metrics.items():
        if name in ("repair", "stuck", "json", "cp936", "broken"):
            continue
        print(f"{name:<8} {str(row.get('status')):<9} {str(row.get('engine')):<9} "
              f"{row.get('pages'):>5} {str(row.get('duration_ms')):>7} "
              f"{row.get('log_bytes'):>7} {row.get('log_ratio'):>6}x")
    if "repair" in metrics:
        print(f"repair   {metrics['repair'].get('status')} in {metrics['repair'].get('rounds')} round(s)")
    if "json" in metrics:
        print(f"json     {metrics['json']['parsed']}/{metrics['json']['total']} parsed")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\nsummary: {passed} passed, {total - passed} failed")
    report_path = WORK / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(
        {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in results],
         "metrics": metrics}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {report_path}")


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    started = time.perf_counter()
    try:
        bundle = check_packaging()
        check_six_cases(bundle)
        check_paths(bundle)
        check_cp936(bundle)
    finally:
        print_report()
        print(f"elapsed: {time.perf_counter() - started:.1f}s")
        if not KEEP:
            shutil.rmtree(WORK, ignore_errors=True)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
