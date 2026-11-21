#!/usr/bin/env python3
"""Install this skill into WorkBuddy's skill directory.

The Python package and the bash wrappers are already platform-neutral, so the
only real difference between the two deliverables is the SKILL.md header:
DeepSeek Harness reads license/allowed-tools/metadata, WorkBuddy reads a
narrower set. Rather than keeping two bodies in sync by hand, this script writes
the WorkBuddy header from `workbuddy/frontmatter.yaml` and reuses the body of
`SKILL.md` byte for byte -- there is exactly one body in the repository.

Usage:
    python tools/install_workbuddy.py                # install to the default path
    python tools/install_workbuddy.py --dry-run      # list what would be copied
    python tools/install_workbuddy.py --check        # compare an existing install
    python tools/install_workbuddy.py --force        # replace an existing install
    python tools/install_workbuddy.py --target DIR   # install somewhere else
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "latex-automation"
FRONTMATTER = ROOT / "workbuddy" / "frontmatter.yaml"

# Provenance only: the research fixtures are 3 MB and no runtime path reads them.
EXCLUDED_DIRS = {"research", "workbuddy", ".git", "__pycache__", ".p6", ".smoke", "latex-out"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def default_target() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / ".workbuddy" / "skills" / SKILL_NAME


def tracked_files() -> list[Path]:
    """Return repository files relative to ROOT, honouring .gitignore when possible.

    `git ls-files` keeps build scratch out of the install for free; a plain walk
    is the fallback for a copy of the skill that is not a git checkout.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        files = [ROOT / line for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = sorted(p for p in ROOT.rglob("*") if p.is_file())
    return [p for p in files if p.is_file() and _keep(p)]


def _keep(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    return path.suffix not in EXCLUDED_SUFFIXES


def split_skill_md() -> tuple[str, str]:
    """Return (dsh_frontmatter, body) for SKILL.md.

    The body starts after the closing `---` of the first frontmatter block, so a
    `---` that appears later in the document is not mistaken for it.
    """
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit("SKILL.md does not start with a frontmatter block")
    lines = text.splitlines(keepends=True)
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[: index + 1]), "".join(lines[index + 1 :])
    raise SystemExit("SKILL.md frontmatter block is not closed")


def composed_skill_md() -> str:
    header = FRONTMATTER.read_text(encoding="utf-8").rstrip("\n")
    _, body = split_skill_md()
    return f"{header}\n{body}"


def files_to_write() -> dict[str, bytes]:
    """Map install-relative POSIX path -> bytes, with SKILL.md composed last."""
    payload: dict[str, bytes] = {}
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ("SKILL.md", "workbuddy/frontmatter.yaml"):
            continue
        payload[rel] = path.read_bytes()
    payload["SKILL.md"] = composed_skill_md().encode("utf-8")
    return payload


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install(target: Path, force: bool) -> int:
    if target.exists() and any(target.iterdir()) and not force:
        print(f"target already exists and is not empty: {target}", file=sys.stderr)
        print("pass --force to replace it", file=sys.stderr)
        return 2

    payload = files_to_write()
    if target.exists() and force:
        shutil.rmtree(target)
    for rel, data in payload.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    # Windows has no executable bit; the wrappers are invoked through bash, which
    # needs them runnable only when called directly, so best effort is enough.
    for rel in payload:
        if rel.startswith("bin/") or rel == "tests/smoke.sh":
            try:
                (target / rel).chmod(0o755)
            except OSError:
                pass

    print(f"installed {len(payload)} files to {target}")
    print(f"SKILL.md: WorkBuddy header ({FRONTMATTER.relative_to(ROOT)}) + shared body")
    print()
    print("verify with the WorkBuddy bash:")
    print(f'  bash "{target / "bin" / "latex-doctor"}"')
    return 0


def check(target: Path) -> int:
    if not target.is_dir():
        print(f"no install at {target}", file=sys.stderr)
        return 2
    payload = files_to_write()
    problems: list[str] = []
    for rel, data in payload.items():
        dest = target / rel
        if not dest.is_file():
            problems.append(f"missing: {rel}")
        elif sha256(dest.read_bytes()) != sha256(data):
            problems.append(f"differs: {rel}")
    installed = {
        p.relative_to(target).as_posix()
        for p in target.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    for rel in sorted(installed - set(payload)):
        problems.append(f"extra: {rel}")
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        print(f"{len(problems)} problem(s) in {target}", file=sys.stderr)
        return 1
    print(f"install matches the repository: {len(payload)} files, {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the skill into WorkBuddy")
    parser.add_argument("--target", default=None, help="destination directory")
    parser.add_argument("--force", action="store_true", help="replace an existing install")
    parser.add_argument("--dry-run", action="store_true", help="list files and stop")
    parser.add_argument("--check", action="store_true", help="compare an existing install")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve() if args.target else default_target()
    if args.dry_run:
        payload = files_to_write()
        for rel in sorted(payload):
            print(f"{len(payload[rel]):>8}  {rel}")
        print(f"{len(payload)} files -> {target}")
        return 0
    if args.check:
        return check(target)
    return install(target, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
