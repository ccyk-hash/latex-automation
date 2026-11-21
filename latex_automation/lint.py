"""Static checking and formatting via chktex and latexindent.

Two machine-specific rules:

* ``chktex -o <file>`` fails here with
  ``chktex: ERROR -- Could not rename 'nul' to 'nul.bak'.``
  so the toolkit always reads chktex's stdout with ``-f``.
* chktex exits 0 regardless of the number of warnings, so the exit code is
  never used as a verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .proc import run, which

CHKTEX_FORMAT = "%f:%l:%c:%k:%m"
CHKTEX_LINE_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):(?P<kind>[^:]*):(?P<message>.*)$")
CHKTEX_SILENT_RE = re.compile(r"^ChkTeX\s+silently\s+ignor", re.IGNORECASE)


@dataclass
class LintFinding:
    file: str
    line: int
    column: int
    kind: str
    message: str

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "message": self.message,
        }


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)
    error: str = ""
    source: str = ""

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "count": len(self.findings),
            "error": self.error or None,
            "findings": [f.as_dict() for f in self.findings],
        }

    def summary(self) -> str:
        if self.error:
            return f"lint unavailable: {self.error}"
        if not self.findings:
            return "lint clean"
        return f"{len(self.findings)} style warning(s)"


def lint_file(
    source: Path,
    chktex: str | None = None,
    root: Path | None = None,
    extra_args: list[str] | None = None,
) -> LintReport:
    """Run chktex over one .tex file and parse its ``-f`` output."""
    report = LintReport(source=str(source))
    if not source.is_file():
        report.error = "file not found"
        return report
    exe = chktex or which("chktex")
    if not exe:
        report.error = "chktex not found"
        return report

    argv = [exe, "-q", "-f", CHKTEX_FORMAT + "\n"]
    argv.extend(extra_args or [])
    argv.append(source.name)
    result = run(argv, cwd=source.parent, timeout=120)
    root_dir = root or source.parent
    for raw in result.combined.splitlines():
        line = raw.strip()
        if not line or CHKTEX_SILENT_RE.match(line):
            continue
        match = CHKTEX_LINE_RE.match(line)
        if not match:
            continue
        report.findings.append(
            LintFinding(
                file=_relative(match.group("file"), root_dir),
                line=int(match.group("line")),
                column=int(match.group("col")),
                kind=match.group("kind").strip(),
                message=match.group("message").strip().replace("\\n", ""),
            )
        )
    return report


def format_file(
    source: Path,
    latexindent: str | None = None,
    in_place: bool = False,
    overwrite_copy: Path | None = None,
    silent: bool = True,
) -> tuple[bool, str]:
    """Run latexindent; never rewrites the source unless ``in_place``."""
    if not source.is_file():
        return False, "file not found"
    exe = latexindent or which("latexindent")
    if not exe:
        return False, "latexindent not found"
    argv = [exe]
    if silent:
        argv.append("-s")
    if in_place:
        argv.extend(["-w", source.name])
        result = run(argv, cwd=source.parent, timeout=180)
        return result.returncode == 0, (result.stderr or result.stdout).strip()
    argv.append(source.name)
    result = run(argv, cwd=source.parent, timeout=180)
    if overwrite_copy is not None:
        overwrite_copy.write_text(result.stdout, encoding="utf-8")
        return True, str(overwrite_copy)
    return True, result.stdout


def _relative(raw: str, root: Path) -> str:
    text = raw.replace("\\", "/")
    try:
        return (root / text).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return text
