#!/usr/bin/env python3
"""Verify the WorkBuddy deliverable, not the repository it came from.

`tests/smoke.sh` runs the wrappers out of the checkout. That says nothing about
the copy WorkBuddy will actually load, which is composed (header swapped) and
installed into `~/.workbuddy/skills/latex-automation`. This script installs into
a throwaway directory first and drives that copy through a real project:

    install --check -> doctor -> init -> build -> layout -> repair -> render

It uses WorkBuddy's own bash (PortableGit) when it can find it, because the
wrapper's interpreter discovery and path conversion are exactly what differ
between the two hosts.

Usage:
    python tools/verify_workbuddy.py            # gate: install to a temp dir, run
    python tools/verify_workbuddy.py --keep     # keep the temp tree for inspection
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import install_workbuddy as iw  # noqa: E402

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
PORTABLE_GIT = HOME / ".workbuddy" / "binaries" / "PortableGit" / "versions"
WORKBUDDY_PYTHON = HOME / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "python.exe"

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail else ""))


def find_bash() -> str | None:
    """Return WorkBuddy's bash.exe, if this machine has one."""
    if not PORTABLE_GIT.is_dir():
        return None
    for version in sorted(PORTABLE_GIT.iterdir(), reverse=True):
        candidate = version / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def run(bash: str | None, script: Path, cwd: Path, *args: str, timeout: int = 300):
    argv = [bash, str(script), *args] if bash else ["bash", str(script), *args]
    started = time.time()
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc, int((time.time() - started) * 1000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the WorkBuddy install")
    parser.add_argument("--keep", action="store_true", help="keep the temp tree")
    args = parser.parse_args(argv)

    started = time.time()
    bash = find_bash()
    check("WorkBuddy bash located", bash is not None, bash or "falling back to `bash` on PATH")
    check("WorkBuddy managed Python present", WORKBUDDY_PYTHON.is_file(),
          str(WORKBUDDY_PYTHON) if WORKBUDDY_PYTHON.is_file() else "absent")

    work = Path(tempfile.mkdtemp(prefix="latex-wb-"))
    target = work / "skills" / iw.SKILL_NAME
    project = work / "带 空格 目录"

    try:
        code = iw.install(target, force=True)
        check("install writes the composed skill", code == 0 and (target / "SKILL.md").is_file(),
              f"{len(iw.files_to_write())} files")

        code = iw.check(target)
        check("install matches the repository", code == 0, str(target))

        installed = (target / "SKILL.md").read_text(encoding="utf-8")
        check(
            "installed SKILL.md has the WorkBuddy header",
            installed.startswith("---\nname: latex-automation\n") and "allowed-tools:" in installed,
            "name + allowed-tools present",
        )
        check(
            "installed SKILL.md keeps the shared body",
            installed.endswith(iw.split_skill_md()[1]),
            "body byte-identical to SKILL.md",
        )

        doctor = target / "bin" / "latex-doctor"
        proc, ms = run(bash, doctor, work)
        ok = proc.returncode == 0 and "0 fail" in proc.stdout
        check("doctor runs from the install", ok, f"{ms} ms, rc={proc.returncode}")

        project.mkdir(parents=True, exist_ok=True)
        proc, ms = run(bash, target / "bin" / "latex-init", project, ".", "--template", "zh",
                       "--title", "WorkBuddy gate")
        check("init scaffolds from a Chinese+space path", proc.returncode == 0,
              f"{(project / 'main.tex').is_file()}")

        proc, ms = run(bash, target / "bin" / "latex-build", project, ".")
        report_path = project / "latex-out" / "build-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        check(
            "build produces a PDF",
            proc.returncode == 0 and report.get("status") == "success",
            f"{report.get('engine')} / {ms} ms",
        )
        check(
            "build passes the outdir relative to dodge putenv",
            any("putenv" in w or "relative" in w for w in report.get("warnings", [])),
            "; ".join(report.get("warnings", [])) or "no warning (fine outside CJK+space)",
        )

        proc, ms = run(bash, target / "bin" / "latex-layout", project, ".")
        check("layout reads the built PDF", proc.returncode == 0 and "page(s)" in proc.stdout,
              f"{ms} ms")

        broken = work / "broken"
        broken.mkdir()
        (broken / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nBad \\undefinedmacro{x} here.\n\\end{document}\n",
            encoding="utf-8",
        )
        proc, ms = run(bash, target / "bin" / "latex-repair", broken, ".")
        check(
            "repair stops on a defect it cannot verify",
            proc.returncode != 0 and "needs-human" in proc.stdout,
            f"{ms} ms",
        )
        check(
            "repair leaves the source untouched",
            "\\undefinedmacro" in (broken / "main.tex").read_text(encoding="utf-8"),
            "file unchanged",
        )

        proc, ms = run(bash, target / "bin" / "latex-render", project, ".")
        pages = list((project / "latex-out" / "pages").glob("*.png"))
        check("render writes page images", proc.returncode == 0 and pages, f"{len(pages)} png")

        proc, ms = run(bash, target / "bin" / "latex-check", project, ".")
        check("check runs chktex", proc.returncode == 0, f"{ms} ms")
    finally:
        if args.keep:
            print(f"\nkept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    failed = [name for ok, name, _ in RESULTS if not ok]
    elapsed = time.time() - started
    print()
    print(f"summary: {len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"  failed: {name}")
        return 1
    print(f"elapsed: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
