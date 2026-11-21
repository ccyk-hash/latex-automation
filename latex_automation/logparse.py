"""Structured parsing of LaTeX engine, biber and bibtex logs.

Design decisions that came out of the L4 measurements in
``docs/01-research-report.md``:

* **Collect fully, then rank.**  ``-halt-on-error`` truncates a five-error log
  to two, so the toolkit never passes that flag when it wants a diagnosis and
  instead ranks the collected errors for causality.
* **Fold the cascade.**  ``Emergency stop`` and ``Fatal error occurred`` are
  consequences, not causes; they are attached to the root error rather than
  reported as siblings.
* **Missing glyphs are their own class.**  ``Missing character: There is no X in
  font Y`` is the single most useful signal for a Chinese document that renders
  blank boxes, and no general warning regex catches it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# --- lexical patterns -------------------------------------------------------

TEX_FILE_SUFFIXES = "tex|sty|cls|ltx|def|cfg|clo|fd|bib|bbl|aux|dtx|ins|ldf"

FILE_OPEN_RE = re.compile(
    r"\(((?:[A-Za-z]:)?[^()\n]*?\.(?:" + TEX_FILE_SUFFIXES + r"))"
)
FILE_LINE_ERROR_RE = re.compile(
    r"^(?:\./)?((?:[A-Za-z]:)?[^:()\n]+?\.(?:" + TEX_FILE_SUFFIXES + r")):(\d+):\s*(.*)$"
)
BANG_RE = re.compile(r"^!\s?(.*)$")
LINE_NUMBER_RE = re.compile(r"^l\.(\d+)\s?(.*)$")
CONTEXT_LINE_RE = re.compile(r"^<([^<>\n]{1,200})>\s?(.*)$")

WARNING_RE = re.compile(
    r"^(LaTeX|LaTeX Font|Package|Class|Module)\s+(?:(\S+)\s+)?Warning:\s*(.*)$"
)
ERROR_RE = re.compile(
    r"^((?:LaTeX|Package|Class|Module)\s+(?:\S+\s+)?Error):\s*(.*)$"
)
MISSING_CHAR_RE = re.compile(r"^Missing character: There is no (.+?) in font (.+?)!?$")
OUTPUT_RE = re.compile(r"^Output written on (.+?) \((\d+) pages?,\s*(\d+) bytes?\)")
NO_OUTPUT_RE = re.compile(r"^No pages of output")
FATAL_RE = re.compile(r"^!?\s*(Fatal error occurred|Emergency stop)")
OVERFULL_RE = re.compile(
    r"^(Overfull|Underfull)\s+\\[hv]box\s*(?:\(([^)]*)\))?"
    r"\s*(?:in paragraph|in alignment|in table|detected)?"
    r"\s*(?:at lines? (\d+)(?:--(\d+))?)?"
)
UNDEF_REF_RE = re.compile(
    r"LaTeX Warning: Reference [`']([^`']+)[`'](?: on page \d+)? undefined"
)
UNDEF_CITE_RE = re.compile(
    r"(?:LaTeX|Package \w+) Warning: Citation [`']([^`']+)[`'](?: on page \d+)? undefined"
)
FLOAT_TOO_LARGE_RE = re.compile(
    r"LaTeX Warning: Float too large for page by ([0-9.]+)pt"
)
RERUN_RE = re.compile(
    r"(?:Label\(s\) may have changed|Rerun to get|Rerun LaTeX|Please \(re\)run"
    r"|rerunfilecheck|has changed\. Rerun)"
)
INPUT_LINE_RE = re.compile(r"on input line (\d+)")
MISSING_FILE_RE = re.compile(
    r"(?:File [`']([^`']+)[`'] not found|I can't find file [`']([^`']+)[`']"
    r"|Cannot find file [`']([^`']+)[`'])"
)
BIBER_ERROR_RE = re.compile(r"^(ERROR|FATAL)\s*-\s*(.*)$")
BIBER_WARN_RE = re.compile(r"^WARN\s*-\s*(.*)$")
BIB_MISSING_RE = re.compile(r"(?:Cannot find|file)\s+'([^']+\.(?:bib|bst))'", re.IGNORECASE)
BIBTEX_WARN_RE = re.compile(r"^(Warning--.*|I couldn't open .*)$")
BIBTEX_ERROR_RE = re.compile(r"^(.*---line \d+ of file .*)$")

#: Consequence-only lines: never reported as independent errors.
CASCADE_MARKERS = ("Emergency stop", "Fatal error occurred", "No pages of output")

#: Errors that are the real cause even though they mention "not found".
PACKAGE_NOT_FOUND = re.compile(
    r"^LaTeX Error: File [`']([^`']+)[`'] not found"
)

SEVERITY_ORDER = {"error": 0, "layout": 1, "warning": 2, "info": 3}


@dataclass
class Diagnostic:
    severity: str
    message: str
    file: str = ""
    line: int | None = None
    package: str = ""
    tool: str = "engine"
    category: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        data = {"severity": self.severity, "message": self.message, "tool": self.tool}
        if self.file:
            data["file"] = self.file
        if self.line is not None:
            data["line"] = self.line
        if self.package:
            data["package"] = self.package
        if self.category:
            data["category"] = self.category
        if self.detail:
            data["detail"] = self.detail
        return data


@dataclass
class LogReport:
    success: bool = False
    pages: int | None = None
    pdf_bytes: int | None = None
    output_file: str = ""
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    layout: list[Diagnostic] = field(default_factory=list)
    missing_chars: list[Diagnostic] = field(default_factory=list)
    undefined_refs: list[str] = field(default_factory=list)
    undefined_cites: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    missing_packages: list[str] = field(default_factory=list)
    rerun_needed: bool = False
    root_cause: Diagnostic | None = None
    suppressed: int = 0

    @property
    def ok(self) -> bool:
        return self.success and not self.errors

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "pages": self.pages,
            "pdf_bytes": self.pdf_bytes,
            "output_file": self.output_file,
            "counts": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "layout": len(self.layout),
                "missing_chars": len(self.missing_chars),
                "suppressed_cascade": self.suppressed,
            },
            "root_cause": self.root_cause.as_dict() if self.root_cause else None,
            "errors": [d.as_dict() for d in self.errors],
            "warnings": [d.as_dict() for d in self.warnings],
            "layout": [d.as_dict() for d in self.layout],
            "missing_chars": [d.as_dict() for d in self.missing_chars],
            "undefined_refs": self.undefined_refs,
            "undefined_cites": self.undefined_cites,
            "missing_files": self.missing_files,
            "missing_packages": self.missing_packages,
            "rerun_needed": self.rerun_needed,
        }

    def summary_line(self) -> str:
        if self.ok:
            pages = f"{self.pages} page(s)" if self.pages else "PDF"
            return f"build succeeded: {pages}"
        if self.root_cause:
            loc = ""
            if self.root_cause.file:
                loc = f" at {self.root_cause.file}"
                if self.root_cause.line:
                    loc += f":{self.root_cause.line}"
            return f"build failed: {self.root_cause.message}{loc}"
        return "build failed"


PSEUDO_CONTEXT_RE = re.compile(
    r"^(inserted text|output|every par|\\[A-Za-z@]+|.*\.aux|.*\.toc)$"
)


def _normalize_file(raw: str, root: Path) -> str:
    """Make a log-embedded filename relative to the project root when possible."""
    text = raw.strip().strip('"').strip("'")
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    # TeX prints pseudo-frames such as <inserted text> and <output>; they are
    # not real files and must not become a diagnostic location.
    if not text or text == "*" or PSEUDO_CONTEXT_RE.match(text) or text.startswith("inserted"):
        return ""
    # An .aux/.toc/.bbl frame is a derived file: the error belongs to the
    # author's source, and pointing at the aux file misleads the reader.
    if text.lower().endswith((".aux", ".toc", ".lof", ".lot", ".out", ".bbl", ".bcf")):
        return ""
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            absolute = candidate.resolve()
        else:
            absolute = (root / candidate).resolve()
        return absolute.relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return text


def _classify(message: str) -> tuple[str, str]:
    """Return ``(category, package)`` for one error message."""
    lower = message.lower()
    match = PACKAGE_NOT_FOUND.match(message)
    if match:
        return "missing_package", match.group(1)
    missing = MISSING_FILE_RE.search(message)
    if missing:
        name = next(group for group in missing.groups() if group)
        if name.endswith((".sty", ".cls", ".def", ".fd", ".clo")):
            return "missing_package", name
        return "missing_file", name
    if "undefined control sequence" in lower:
        return "undefined_macro", ""
    if "missing $ inserted" in lower or "extra }" in lower or "missing } inserted" in lower:
        return "math_or_brace", ""
    if "runaway argument" in lower or "file ended while scanning" in lower:
        return "unbalanced_argument", ""
    if "environment" in lower and "undefined" in lower:
        return "undefined_environment", ""
    if (
        "unicode character" in lower
        or "not set up for use with latex" in lower
        # A GBK/CP1251 source read as UTF-8 gets here first: pdfTeX reports the
        # bytes, not a character, so the wording differs from the Unicode case.
        or "invalid utf-8 byte sequence" in lower
    ):
        return "encoding", ""
    if "capacity exceeded" in lower:
        return "capacity", ""
    if "can be used only in preamble" in lower or "can only be used in preamble" in lower:
        return "preamble_placement", ""
    if "there's no line here to end" in lower:
        return "layout_command", ""
    if "package" in lower and "error" in lower:
        return "package_error", ""
    return "generic", ""


def _rank_key(diag: Diagnostic) -> tuple:
    """Order errors so the actionable root cause comes first.

    A missing package or a missing file is always the root cause when present;
    otherwise the earliest source line wins, and package-internal errors lose
    to user-file errors because they are usually consequences.
    """
    priority = {
        "missing_package": 0,
        "missing_file": 1,
        "undefined_macro": 2,
        "undefined_environment": 2,
        "unbalanced_argument": 2,
        "math_or_brace": 3,
        "encoding": 4,
        "package_error": 5,
        "preamble_placement": 5,
        "generic": 6,
    }.get(diag.category, 6)
    in_source = 0 if diag.file.endswith(".tex") else 1
    line = diag.line if diag.line is not None else 10**9
    return (priority, in_source, line)


def _advance_file_stack(line: str, stack: list[str], root: Path) -> None:
    """Track TeX's file stack by balancing parentheses.

    A single "last file opened" variable is not enough: an error raised after
    ``size10.clo`` had been opened, but while ``misspkg.tex`` is being read,
    would be attributed to the wrong file.  TeX opens a file with ``(name`` and
    closes it with ``)``, so a character scan with a stack reproduces the real
    nesting closely enough for diagnostics.
    """
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "(":
            match = FILE_OPEN_RE.match(line, index)
            if match:
                stack.append(_normalize_file(match.group(1), root))
                index = match.end()
                continue
            stack.append("")
        elif char == ")":
            if stack:
                stack.pop()
        index += 1
    # Never let a malformed log grow the stack without bound.
    if len(stack) > 200:
        del stack[:-200]


def _current_file(stack: list[str]) -> str:
    for name in reversed(stack):
        if name:
            return name
    return ""


def parse_engine_log(text: str, root: Path, tool: str = "engine") -> LogReport:
    """Parse one engine ``.log`` (or captured stdout used as a fallback)."""
    report = LogReport()
    if not text:
        return report

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    file_stack: list[str] = []
    pending_error: Diagnostic | None = None
    seen_errors: set[tuple] = set()
    seen_warnings: set[tuple] = set()
    seen_layout: set[tuple] = set()
    seen_missing_chars: set[tuple] = set()

    for raw_line in lines:
        line = raw_line.rstrip()
        _advance_file_stack(line, file_stack, root)
        current_file = _current_file(file_stack)
        if not line:
            continue

        output = OUTPUT_RE.match(line)
        if output:
            report.success = True
            report.output_file = _normalize_file(output.group(1), root)
            report.pages = int(output.group(2))
            report.pdf_bytes = int(output.group(3))
            continue

        if NO_OUTPUT_RE.match(line):
            # A consequence of an earlier failure, not a cause of its own.
            report.success = False
            report.suppressed += 1
            continue

        # --- references -----------------------------------------------------
        # Extract undefined refs/cites *before* the generic warning branch,
        # otherwise `LaTeX Warning: Reference ...' is swallowed as a plain
        # warning and the caller never learns which label is broken.
        undef_ref = UNDEF_REF_RE.search(line)
        if undef_ref and undef_ref.group(1) not in report.undefined_refs:
            report.undefined_refs.append(undef_ref.group(1))
        undef_cite = UNDEF_CITE_RE.search(line)
        if undef_cite and undef_cite.group(1) not in report.undefined_cites:
            report.undefined_cites.append(undef_cite.group(1))
        if RERUN_RE.search(line):
            report.rerun_needed = True

        # --- warnings -------------------------------------------------------
        warning = WARNING_RE.match(line)
        if warning:
            kind, package, message = warning.group(1), warning.group(2) or "", warning.group(3)
            key = (kind, package, message[:120])
            if key not in seen_warnings:
                seen_warnings.add(key)
                report.warnings.append(
                    Diagnostic(
                        severity="warning",
                        message=f"{kind} Warning: {message}".strip(),
                        file=current_file,
                        package=package,
                        tool=tool,
                        category="warning",
                    )
                )
            continue

        # --- layout ---------------------------------------------------------
        overfull = OVERFULL_RE.match(line)
        if overfull:
            kind = overfull.group(1)
            box = overfull.group(2) or ""
            start = overfull.group(3)
            end = overfull.group(4)
            key = (kind, box, start, end)
            if key not in seen_layout:
                seen_layout.add(key)
                line_no = int(start) if start else None
                severity = "warning"
                amount = 0.0
                amount_match = re.search(r"([0-9.]+)pt too (?:wide|high)", box)
                if amount_match:
                    amount = float(amount_match.group(1))
                if kind == "Overfull" and amount >= 5.0:
                    severity = "layout"
                report.layout.append(
                    Diagnostic(
                        severity=severity,
                        message=f"{kind} \\hbox ({box})".strip(),
                        file=current_file,
                        line=line_no,
                        tool=tool,
                        category="overfull" if kind == "Overfull" else "underfull",
                        detail=box,
                    )
                )
            continue

        float_warning = FLOAT_TOO_LARGE_RE.search(line)
        if float_warning:
            key = ("float", float_warning.group(1))
            if key not in seen_layout:
                seen_layout.add(key)
                report.layout.append(
                    Diagnostic(
                        severity="layout",
                        message=f"Float too large for page by {float_warning.group(1)}pt",
                        file=current_file,
                        tool=tool,
                        category="float_too_large",
                    )
                )
            continue

        # --- missing glyphs -------------------------------------------------
        missing_char = MISSING_CHAR_RE.match(line)
        if missing_char:
            char, font = missing_char.group(1), missing_char.group(2)
            key = (char, font)
            if key not in seen_missing_chars:
                seen_missing_chars.add(key)
                report.missing_chars.append(
                    Diagnostic(
                        severity="warning",
                        message=f"missing glyph {char!r} in font {font}",
                        file=current_file,
                        tool=tool,
                        category="missing_char",
                        detail=font,
                    )
                )
            continue

        # --- errors ---------------------------------------------------------
        bang = BANG_RE.match(line)
        reported = ERROR_RE.match(line)
        if bang or reported:
            message = (bang.group(1) if bang else reported.group(2)).strip()
            package = ""
            if reported and not bang:
                head = reported.group(1)
                parts = head.split()
                if len(parts) > 1 and parts[0] not in ("LaTeX",):
                    package = parts[1]
            if any(marker in message for marker in CASCADE_MARKERS):
                report.suppressed += 1
                continue
            category, discovered = _classify(message)
            package = package or discovered
            diag = Diagnostic(
                severity="error",
                message=message,
                file=current_file,
                package=package,
                tool=tool,
                category=category,
            )
            pending_error = diag
            key = (diag.message[:120], diag.file, diag.category)
            if key not in seen_errors:
                seen_errors.add(key)
                report.errors.append(diag)
            if category == "missing_package" and package and package not in report.missing_packages:
                report.missing_packages.append(package)
            if category == "missing_file" and package and package not in report.missing_files:
                report.missing_files.append(package)
            continue

        # Location lines: `file.tex:12: msg` (with -file-line-error) and `l.12`.
        file_line = FILE_LINE_ERROR_RE.match(line)
        if file_line:
            message = file_line.group(3).strip()
            if any(marker in message for marker in CASCADE_MARKERS):
                report.suppressed += 1
                continue
            category, discovered = _classify(message)
            diag = Diagnostic(
                severity="error",
                message=message,
                file=_normalize_file(file_line.group(1), root),
                line=int(file_line.group(2)),
                package=discovered,
                tool=tool,
                category=category,
            )
            key = (diag.message[:120], diag.file, diag.line, diag.category)
            if key not in seen_errors:
                seen_errors.add(key)
                report.errors.append(diag)
            if category == "missing_package" and discovered and discovered not in report.missing_packages:
                report.missing_packages.append(discovered)
            pending_error = diag
            continue

        line_number = LINE_NUMBER_RE.match(line)
        if line_number:
            number = int(line_number.group(1))
            snippet = line_number.group(2).strip()
            if pending_error is not None:
                if pending_error.line is None:
                    pending_error.line = number
                if snippet and not pending_error.detail:
                    pending_error.detail = snippet[:200]
                pending_error = None
            continue

        context = CONTEXT_LINE_RE.match(line)
        if context and pending_error is not None and not pending_error.file:
            pending_error.file = _normalize_file(context.group(1), root)
            continue

        inline_line = INPUT_LINE_RE.search(line)
        if inline_line and pending_error is not None and pending_error.line is None:
            pending_error.line = int(inline_line.group(1))

    # Success must be evidence-based: an "Output written on" line.
    if report.success and report.errors:
        # TeX can emit "Output written" yet have real errors; keep success
        # truthful about the artefact but let `.ok` stay False.
        pass

    report.errors.sort(key=_rank_key)
    if report.errors:
        report.root_cause = report.errors[0]
    elif report.missing_chars and not report.success:
        # A blank-glyph document that produced no PDF is a font problem.
        report.root_cause = report.missing_chars[0]
    return report


def parse_biber_log(text: str, root: Path) -> LogReport:
    report = LogReport()
    report.success = True
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Missing sources are reported on the same line as the error
        # (`ERROR - Cannot find 'refs.bib'!`), so harvest them first.
        missing = BIB_MISSING_RE.search(line)
        if missing and missing.group(1) not in report.missing_files:
            report.missing_files.append(missing.group(1))
        error = BIBER_ERROR_RE.match(line)
        if error:
            report.success = False
            report.errors.append(
                Diagnostic(
                    severity="error",
                    message=error.group(2).strip(),
                    tool="biber",
                    category="bibliography",
                )
            )
            continue
        warn = BIBER_WARN_RE.match(line)
        if warn:
            report.warnings.append(
                Diagnostic(
                    severity="warning",
                    message=warn.group(1).strip(),
                    tool="biber",
                    category="bibliography",
                )
            )
            continue
    report.errors.sort(key=_rank_key)
    if report.errors:
        report.root_cause = report.errors[0]
    return report


def parse_bibtex_log(text: str, root: Path) -> LogReport:
    report = LogReport()
    report.success = True
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if BIBTEX_ERROR_RE.match(line):
            report.success = False
            report.errors.append(
                Diagnostic(
                    severity="error",
                    message=line,
                    tool="bibtex",
                    category="bibliography",
                )
            )
            continue
        if BIBTEX_WARN_RE.match(line):
            if "couldn't open" in line.lower():
                report.success = False
                report.errors.append(
                    Diagnostic(
                        severity="error",
                        message=line,
                        tool="bibtex",
                        category="missing_bib",
                    )
                )
                match = re.search(r"file ([^\s]+)", line)
                if match and match.group(1) not in report.missing_files:
                    report.missing_files.append(match.group(1))
            else:
                report.warnings.append(
                    Diagnostic(
                        severity="warning",
                        message=line,
                        tool="bibtex",
                        category="bibliography",
                    )
                )
    report.errors.sort(key=_rank_key)
    if report.errors:
        report.root_cause = report.errors[0]
    return report


def attribute_missing_locations(report: LogReport, main_hint: str) -> LogReport:
    """Give locationless errors a useful file.

    ``File ended while scanning use of \\frac`` is printed after TeX has already
    unwound its file stack, so it carries no filename.  Leaving the location
    empty makes the diagnostic unactionable; the master document is the honest
    best guess and is labelled as such through ``category`` remaining intact.
    """
    if not main_hint:
        return report
    for diag in report.errors + report.warnings + report.layout:
        if not diag.file:
            diag.file = main_hint
    return report


def parse_log_text(text: str, root: Path, tool: str = "engine") -> LogReport:
    """Dispatch to the right parser for ``tool``."""
    if tool == "biber":
        return parse_biber_log(text, root)
    if tool == "bibtex":
        return parse_bibtex_log(text, root)
    return parse_engine_log(text, root, tool)


def merge_reports(reports: list[LogReport]) -> LogReport:
    """Merge per-step reports into one project-level view."""
    merged = LogReport()
    merged.success = True
    for report in reports:
        if report.errors:
            merged.success = False
        if report.success and report.pages:
            merged.success = True
            merged.pages = report.pages
            merged.pdf_bytes = report.pdf_bytes
            merged.output_file = report.output_file
        for attribute in (
            "errors", "warnings", "layout", "missing_chars",
            "undefined_refs", "undefined_cites", "missing_files",
            "missing_packages",
        ):
            target = getattr(merged, attribute)
            for item in getattr(report, attribute):
                if item not in target:
                    target.append(item)
        merged.rerun_needed = merged.rerun_needed or report.rerun_needed
        merged.suppressed += report.suppressed

    # A build that emitted no PDF never succeeded, whatever the steps said.
    if not merged.pages and not merged.output_file:
        merged.success = False
    merged.errors.sort(key=_rank_key)
    merged.root_cause = merged.errors[0] if merged.errors else None
    if merged.root_cause is None and merged.missing_chars and not merged.success:
        merged.root_cause = merged.missing_chars[0]
    return merged


def compress_log(text: str, keep_context: int = 3, max_lines: int = 120) -> str:
    """Reduce a full log to the lines a reader actually needs."""
    lines = text.replace("\r\n", "\n").split("\n")
    interesting: list[int] = []
    for index, line in enumerate(lines):
        if (
            BANG_RE.match(line)
            or ERROR_RE.match(line)
            or WARNING_RE.match(line)
            or OVERFULL_RE.match(line)
            or MISSING_CHAR_RE.match(line)
            or FILE_LINE_ERROR_RE.match(line)
            or OUTPUT_RE.match(line)
            or NO_OUTPUT_RE.match(line)
        ):
            interesting.append(index)

    keep: set[int] = set()
    for index in interesting:
        for offset in range(-keep_context, keep_context + 1):
            candidate = index + offset
            if 0 <= candidate < len(lines):
                keep.add(candidate)
    ordered = sorted(keep)[:max_lines]
    return "\n".join(lines[index] for index in ordered)
