"""Turn a parsed log into a minimal fix, and run a bounded repair loop.

The design rule is that a suggestion must be *checkable*: either it is a build
flag (switch the engine) whose effect the next compile proves, or it is a
single-line source edit whose context is shown to the caller.  Anything that
needs a network install, a new font, or human judgement is reported and the
loop stops there instead of guessing.

Only one edit is applied per round, and only files inside the project that
decode as UTF-8 are ever rewritten -- writing back a CP936 file as UTF-8 would
silently corrupt it, which is worse than not fixing anything.
"""

from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .engine import BuildOptions, BuildReport, compile_project, discover_toolchain
from .logparse import Diagnostic, LogReport
from .packages import resolve_many
from .paths import iter_project_files, read_text, sha256_text

# Macros that need no definition of their own; keeps the "undefined" report
# focused on tokens the author actually has to do something about.
BUILTIN_MACROS = frozenset(
    """
    begin end documentclass usepackage documentstyle item textbf textit emph
    texttt textrm textsf textsc underline footnote label ref pageref cite
    citep citet section subsection subsubsection paragraph chapter part
    includegraphics caption title author date maketitle tableofcontents
    newpage clearpage newline linebreak hline vspace hspace quad qquad
    frac sqrt sum int prod lim infty alpha beta gamma delta epsilon lambda mu
    pi sigma omega theta phi psi partial nabla times cdot cdots ldots dots
    left right big Big bigg Bigg text mathrm mathbf mathit mathcal
    newcommand renewcommand def let newenvironment renewenvironment
    DeclareMathOperator newtheorem setlength addtolength setcounter
    centering raggedright noindent indent par smallskip medskip bigskip
    hfill vfill hrulefill dotfill input include verbatim
    """.split()
)

DEFINE_RE = re.compile(
    r"\\(?:(?:re)?newcommand|providecommand|DeclareMathOperator|DeclareRobustCommand)"
    r"\*?\s*\{?\s*\\([A-Za-z@]+)"
)
DEF_RE = re.compile(r"\\def\s*\\([A-Za-z@]+)")
NEWENV_RE = re.compile(r"\\newenvironment\s*\{(\w+)\}")
NEWTHEOREM_RE = re.compile(r"\\newtheorem\s*\{(\w+)\}")

USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}")

# Commands whose presence means the author is writing math, so a stray `_` or
# `^` outside a math group is almost certainly the missing-$ case.
MATH_SIGNAL_RE = re.compile(r"\\(?:frac|sum|int|alpha|beta|gamma|sqrt|cdot|times|infty)\b")

MACRO_TOKEN_RE = re.compile(r"\\([A-Za-z@]+)")

IMAGE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".ps")


@dataclass
class Suggestion:
    """One proposed fix for one root cause."""

    category: str
    kind: str  # install | switch-engine | edit | manual
    summary: str
    detail: str = ""
    file: str = ""
    line: int | None = None
    engine: str | None = None
    package: str = ""
    command: str = ""
    old: str = ""
    new: str = ""
    confidence: float = 0.5
    applied: bool = False

    def as_dict(self) -> dict:
        data = {
            "category": self.category,
            "kind": self.kind,
            "summary": self.summary,
            "confidence": round(self.confidence, 2),
            "applied": self.applied,
        }
        for key in ("detail", "file", "engine", "package", "command", "old", "new"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.line is not None:
            data["line"] = self.line
        return data


def _source_line(path: Path, line: int | None) -> str:
    if not path.is_file() or not line or line < 1:
        return ""
    try:
        text = read_text(path)
    except OSError:
        return ""
    lines = text.splitlines()
    if line <= len(lines):
        return lines[line - 1]
    return ""


def _is_utf8(path: Path) -> bool:
    """True when the file decodes as UTF-8.

    Deliberately strict: a source that only decodes because of ``surrogateescape``
    or a lenient codec is still a file whose rewrite would destroy it.
    """
    try:
        path.read_bytes().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def project_macros(root: Path) -> dict[str, str]:
    """Map every macro/environment the project defines to the file defining it."""
    found: dict[str, str] = {}
    root = root.resolve()
    for path in iter_project_files(root):
        if path.suffix.lower() not in (".tex", ".sty", ".cls"):
            continue
        try:
            text = read_text(path)
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        for regex in (DEFINE_RE, DEF_RE):
            for name in regex.findall(text):
                found.setdefault(name, rel)
        for name in NEWENV_RE.findall(text):
            found.setdefault(name, rel)
        for name in NEWTHEOREM_RE.findall(text):
            found.setdefault(name, rel)
    return found


def _image_candidates(root: Path, missing: str) -> list[str]:
    stem = Path(missing).stem.lower()
    out: list[str] = []
    for path in iter_project_files(root):
        if path.suffix.lower() in IMAGE_SUFFIXES and path.stem.lower() == stem:
            out.append(str(path.relative_to(root)).replace("\\", "/"))
    return out


def _brace_balance(text: str) -> tuple[int, int | None]:
    """Return ``(depth, line_of_first_negative)`` scanning escaped braces safely."""
    depth = 0
    line = 1
    first_negative: int | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            line += 1
        elif char == "\\":
            index += 2
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0 and first_negative is None:
                first_negative = line
                depth = 0  # keep scanning for a useful total
        index += 1
    return depth, first_negative


def suggest(root: Path, report: LogReport, engine: str) -> Suggestion | None:
    """Propose the single most useful fix for ``report.root_cause``."""
    diag = report.root_cause
    if diag is None:
        return None
    cat = diag.category or "generic"
    message = diag.message or ""
    lower = message.lower()
    source = (root / diag.file) if diag.file else None

    # A package the machine simply does not have: give the install command.
    if cat in ("missing_package",):
        name = diag.package or ""
        hit = resolve_many([name])[0] if name else None
        if hit and hit.package:
            return Suggestion(
                category=cat,
                kind="install",
                package=hit.package,
                command=hit.suggestion,
                summary=f"install TeX Live package '{hit.package}'",
                detail=f"{name} is not installed but TeX Live package {hit.package} provides it",
                file=diag.file,
                line=diag.line,
                confidence=0.95,
            )
        return Suggestion(
            category=cat,
            kind="manual",
            summary=f"'{name}' is not provided by any installed TeX Live package",
            detail="check the spelling, or install the package that ships this file",
            file=diag.file,
            line=diag.line,
            confidence=0.6,
        )

    # Engine/package mismatch: the fix is a build flag, not an edit.
    if "requires either xetex or luatex" in lower or "fontspec" in lower:
        return Suggestion(
            category="engine_mismatch",
            kind="switch-engine",
            engine="xelatex",
            summary="rebuild with xelatex: fontspec needs XeTeX or LuaTeX",
            detail="the engine was forced to a pdfTeX-compatible one; fontspec cannot run there",
            file=diag.file,
            line=diag.line,
            confidence=0.95,
        )
    if "cjk" in lower and engine == "pdflatex":
        return Suggestion(
            category="engine_mismatch",
            kind="switch-engine",
            engine="xelatex",
            summary="rebuild with xelatex: this document needs CJK support",
            confidence=0.8,
        )

    # A missing input that exists under another extension is a naming fix.
    if cat == "missing_file":
        name = diag.package or ""
        candidates = _image_candidates(root, name) if name else []
        if len(candidates) == 1:
            old_name = name
            new_name = Path(candidates[0]).name
            return Suggestion(
                category=cat,
                kind="edit",
                summary=f"point the reference at {new_name}",
                detail=f"'{old_name}' is missing but {candidates[0]} exists",
                file=diag.file or "",
                line=diag.line,
                old=old_name,
                new=new_name,
                confidence=0.85,
            )
        if candidates:
            return Suggestion(
                category=cat,
                kind="manual",
                summary=f"'{name}' is missing; candidates: {', '.join(candidates)}",
                confidence=0.6,
            )

    # An undefined control sequence: name the token, offer a typo fix.
    if cat == "undefined_macro":
        text = _source_line(source, diag.line) if source else ""
        defined = project_macros(root)
        tokens = [
            token
            for token in MACRO_TOKEN_RE.findall(text)
            if token not in BUILTIN_MACROS and token not in defined
        ]
        if tokens:
            offender = tokens[-1]
            near = difflib.get_close_matches(offender, sorted(defined), n=1, cutoff=0.8)
            if near:
                return Suggestion(
                    category=cat,
                    kind="edit",
                    summary=f"rename \\{offender} to \\{near[0]}",
                    detail=f"\\{near[0]} is defined in {defined[near[0]]}; \\{offender} is defined nowhere",
                    file=diag.file or "",
                    line=diag.line,
                    old="\\" + offender,
                    new="\\" + near[0],
                    confidence=0.7,
                )
            return Suggestion(
                category=cat,
                kind="manual",
                summary=f"\\{offender} is not defined anywhere in the project",
                detail="define it (\\newcommand) or load the package that provides it",
                file=diag.file or "",
                line=diag.line,
                confidence=0.65,
            )

    # Missing $ or a stray brace: both are mechanically locatable.
    if cat == "math_or_brace":
        text = _source_line(source, diag.line) if source else ""
        if "missing $ inserted" in lower and text:
            dollars = text.count("$") - text.count("\\$")
            if dollars % 2 == 1:
                return Suggestion(
                    category=cat,
                    kind="edit",
                    summary="close the unterminated math group on this line",
                    detail=f"this line has an odd number of unescaped $ ({dollars})",
                    file=diag.file or "",
                    line=diag.line,
                    old=text,
                    new=text + " $",
                    confidence=0.55,
                )
            if MATH_SIGNAL_RE.search(text) and "$" not in text:
                return Suggestion(
                    category=cat,
                    kind="manual",
                    summary="math command used outside a math group",
                    detail="wrap the maths in $...$ (or \\[...\\]) on this line",
                    file=diag.file or "",
                    line=diag.line,
                    confidence=0.7,
                )
        if "extra }" in lower and source and source.is_file():
            try:
                text = read_text(source)
            except OSError:
                text = ""
            if text:
                _, negative_at = _brace_balance(text)
                return Suggestion(
                    category=cat,
                    kind="manual",
                    summary="a closing brace has no opening partner",
                    detail=(
                        f"brace depth first goes negative at line {negative_at}"
                        if negative_at
                        else "the file closes more braces than it opens"
                    ),
                    file=diag.file or "",
                    line=negative_at or diag.line,
                    confidence=0.7,
                )

    if cat == "unbalanced_argument" and diag.file and diag.file.endswith(".tex"):
        match = re.search(r"use of \\([A-Za-z@]+)", message)
        command = match.group(1) if match else ""
        if command:
            return Suggestion(
                category=cat,
                kind="manual",
                summary=f"\\{command} is missing an argument or a closing brace",
                detail="scan forward from the reported line for an unbalanced { } or a missing argument",
                file=diag.file,
                line=diag.line,
                confidence=0.65,
            )

    if cat == "encoding":
        # Two different faults share this category and only one of them is an
        # engine problem. If the file itself is not UTF-8, no engine will read it
        # correctly, and switching to XeLaTeX only trades one error for another:
        # convert the bytes first, and never do that automatically, because the
        # original encoding cannot be inferred from a broken log line.
        if source is not None and source.is_file() and not _is_utf8(source):
            name = diag.file or source.name
            return Suggestion(
                category=cat,
                kind="manual",
                summary=f"{name} is not UTF-8 encoded",
                detail=(
                    f"convert it, then rebuild: iconv -f gb18030 -t utf-8 '{name}' "
                    f"> '{name}.utf8' && mv '{name}.utf8' '{name}'"
                ),
                file=diag.file,
                line=diag.line,
                confidence=0.9,
            )
        if engine == "pdflatex":
            return Suggestion(
                category=cat,
                kind="switch-engine",
                engine="xelatex",
                summary="rebuild with xelatex: pdflatex cannot typeset this character",
                detail=message,
                confidence=0.85,
            )
        return Suggestion(
            category=cat,
            kind="manual",
            summary="a character is missing from the current font",
            detail="pick a font that covers it (\\setCJKmainfont / \\setmainfont)",
            confidence=0.6,
        )

    if cat == "capacity":
        return Suggestion(
            category=cat,
            kind="manual",
            summary="TeX ran out of memory or a recursion limit",
            detail="lualatex has dynamic memory; or restructure the offending macro",
            confidence=0.5,
        )

    if cat == "preamble_placement":
        return Suggestion(
            category=cat,
            kind="move-to-preamble",
            summary="move this \\usepackage above \\begin{document}",
            detail="the reported line is the first body line after a preamble-only command",
            file=diag.file or "",
            line=diag.line,
            confidence=0.8,
        )

    if cat == "undefined_environment":
        return Suggestion(
            category=cat,
            kind="manual",
            summary="an environment is undefined or its \\begin/\\end do not match",
            detail=message,
            file=diag.file or "",
            line=diag.line,
            confidence=0.6,
        )

    if report.missing_chars:
        return Suggestion(
            category="missing_char",
            kind="manual",
            summary=f"font has no glyph for {report.missing_chars[0].detail or 'some characters'}",
            detail="switch to xelatex with ctex/xeCJK, or choose a font that covers the text",
            confidence=0.75,
        )

    return Suggestion(
        category=cat,
        kind="manual",
        summary=f"no mechanical fix for: {message}",
        detail="read the log around the reported line",
        file=diag.file or "",
        line=diag.line,
        confidence=0.2,
    )


def _apply_edit(root: Path, suggestion: Suggestion, backup_dir: Path) -> tuple[bool, str]:
    """Rewrite one line. Returns ``(applied, note)``."""
    if not suggestion.file:
        return False, "no file to edit"
    target = (root / suggestion.file).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False, "refusing to edit outside the project"

    raw = target.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False, "file is not UTF-8; rewriting it could corrupt the encoding"

    lines = text.splitlines(keepends=True)
    index = (suggestion.line or 1) - 1
    if index < 0 or index >= len(lines):
        return False, "reported line is outside the file"
    line_text = lines[index]
    if suggestion.old and suggestion.old not in line_text:
        return False, "the reported line no longer contains the expected text"

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / target.name)

    lines[index] = line_text.replace(suggestion.old, suggestion.new, 1)
    target.write_bytes("".join(lines).encode("utf-8"))
    return True, f"edited {suggestion.file}:{suggestion.line}"


def _apply_move_to_preamble(
    root: Path, suggestion: Suggestion, backup_dir: Path
) -> tuple[bool, str]:
    """Relocate a stray ``\\usepackage`` from the body into the preamble."""
    if not suggestion.file:
        return False, "no file to edit"
    target = (root / suggestion.file).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False, "refusing to edit outside the project"
    try:
        text = target.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False, "file is not UTF-8; rewriting it could corrupt the encoding"

    lines = text.splitlines(keepends=True)
    begin_at = next(
        (i for i, line in enumerate(lines) if r"\begin{document}" in line), None
    )
    if begin_at is None:
        return False, "no \\begin{document} to move the command above"

    reported = (suggestion.line or 1) - 1
    # TeX points at the offending line, but tolerate a small offset: look at the
    # reported line first, then a couple of neighbours, for a preamble-only command.
    stray_at = None
    for offset in (0, -1, 1, -2, 2):
        index = reported + offset
        if 0 <= index < len(lines) and "\\usepackage" in lines[index] and index > begin_at:
            stray_at = index
            break
    if stray_at is None:
        return False, "could not locate the misplaced \\usepackage line"

    moved = lines.pop(stray_at)
    begin_at = next(
        (i for i, line in enumerate(lines) if r"\begin{document}" in line), begin_at
    )
    if not moved.endswith("\n"):
        moved += "\n"
    lines.insert(begin_at, moved)

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / target.name)
    target.write_bytes("".join(lines).encode("utf-8"))
    return True, f"moved a \\usepackage above \\begin{{document}} in {suggestion.file}"



@dataclass
class RepairRound:
    index: int
    status: str
    root_cause: str
    suggestion: Suggestion | None
    engine: str
    duration_ms: int
    applied: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "round": self.index,
            "status": self.status,
            "engine": self.engine,
            "root_cause": self.root_cause,
            "duration_ms": self.duration_ms,
            "applied": self.applied,
            "note": self.note,
            "suggestion": self.suggestion.as_dict() if self.suggestion else None,
        }


@dataclass
class RepairReport:
    status: str = "unknown"
    rounds: list[RepairRound] = field(default_factory=list)
    stopped_reason: str = ""
    final: BuildReport | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "stopped_reason": self.stopped_reason,
            "rounds": [r.as_dict() for r in self.rounds],
            "final": self.final.as_dict() if self.final else None,
        }


def repair_project(
    options: BuildOptions,
    max_rounds: int = 3,
    apply_edits: bool = False,
    backup_dir: Path | None = None,
) -> RepairReport:
    """Compile, suggest, optionally repair, and recompile — at most ``max_rounds`` times.

    Stops early when the fix needs a human (install / manual judgement), when the
    same root cause repeats without progress, or when an edit would have to
    rewrite a file that is not UTF-8.
    """
    root = options.source.resolve().parent
    # Anchor the default next to the artifacts, not next to the caller's cwd:
    # options.outdir may be relative to the project root, and a backup written
    # to the wrong tree is worse than no backup at all.
    project_root = Path(options.project_root).resolve() if options.project_root else root
    outdir = Path(options.outdir)
    if not outdir.is_absolute():
        outdir = project_root / outdir
    backup_root = backup_dir or (outdir.resolve() / "repair")
    report = RepairReport()
    seen: set[str] = set()

    for index in range(1, max_rounds + 1):
        build = compile_project(options)
        engine = build.engine
        cause = build.log.root_cause
        signature = ""
        if cause is not None:
            signature = f"{cause.category}|{cause.file}|{cause.line}|{cause.message}"

        entry = RepairRound(
            index=index,
            status=build.status,
            root_cause=build.log.summary_line(),
            suggestion=None,
            engine=engine,
            duration_ms=build.duration_ms,
        )
        report.rounds.append(entry)
        report.final = build

        if build.status == "success" and build.log.ok:
            report.status = "repaired" if index > 1 else "already-ok"
            report.stopped_reason = "build succeeded"
            return report

        suggestion = suggest(root, build.log, engine)
        entry.suggestion = suggestion
        if suggestion is None:
            report.status = "failed"
            report.stopped_reason = "no root cause to act on"
            return report

        # The engine switch is a build flag, so it needs no source edit and no
        # confirmation: the next round proves whether it helped.
        if suggestion.kind == "switch-engine":
            if not suggestion.engine or suggestion.engine == engine:
                report.status = "failed"
                report.stopped_reason = f"engine {engine} is already the suggested one"
                return report
            entry.applied = True
            entry.note = f"engine {engine} -> {suggestion.engine}"
            suggestion.applied = True
            options.engine = suggestion.engine
            continue

        if suggestion.kind == "move-to-preamble":
            if not apply_edits:
                report.status = "needs-apply"
                report.stopped_reason = "a preamble move is proposed; rerun with --apply to try it"
                return report
            if signature in seen:
                report.status = "failed"
                report.stopped_reason = "the same root cause survived the previous fix"
                return report
            seen.add(signature)
            applied, note = _apply_move_to_preamble(root, suggestion, backup_root / f"round-{index}")
            entry.note = note
            if not applied:
                report.status = "needs-human"
                report.stopped_reason = note
                return report
            entry.applied = True
            suggestion.applied = True
            continue

        if suggestion.kind == "edit":
            if not apply_edits:
                report.status = "needs-apply"
                report.stopped_reason = "a source edit is proposed; rerun with --apply to try it"
                return report
            if signature in seen:
                report.status = "failed"
                report.stopped_reason = "the same root cause survived the previous fix"
                return report
            seen.add(signature)
            applied, note = _apply_edit(root, suggestion, backup_root / f"round-{index}")
            entry.note = note
            if not applied:
                report.status = "needs-human"
                report.stopped_reason = note
                return report
            entry.applied = True
            suggestion.applied = True
            continue

        report.status = "needs-human"
        report.stopped_reason = suggestion.summary
        return report

    report.status = "exhausted"
    report.stopped_reason = f"still failing after {max_rounds} round(s)"
    return report


def render_rounds(report: RepairReport) -> str:
    """Human-readable transcript of a repair session."""
    lines: list[str] = []
    for entry in report.rounds:
        head = f"round {entry.index}: {entry.status} [{entry.engine}]"
        if entry.applied:
            head += "  (fix applied)"
        lines.append(head)
        lines.append(f"  {entry.root_cause}")
        sug = entry.suggestion
        if sug is not None:
            lines.append(f"  -> {sug.summary}  (confidence {sug.confidence:.2f}, {sug.kind})")
            if sug.detail:
                lines.append(f"     {sug.detail}")
            if sug.command:
                lines.append(f"     run: {sug.command}")
            if sug.kind == "edit" and sug.old:
                lines.append(f"     - {sug.old}")
                lines.append(f"     + {sug.new}")
        if entry.note:
            lines.append(f"  note: {entry.note}")
    if report.stopped_reason:
        lines.append(f"stopped: {report.stopped_reason}")
    lines.append(f"result: {report.status}")
    return "\n".join(lines)
