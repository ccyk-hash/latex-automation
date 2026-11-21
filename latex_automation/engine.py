"""Build orchestration: engine selection, two-phase diagnosis, artefact checks.

Two behaviours here are deliberate corrections to what the reference
implementations do on this machine:

1. **Relative outdir only.** ``pdflatex``/``xelatex`` abort on an absolute
   ``-output-directory`` whose path contains CJK-then-space (the ``putenv``
   failure).  The outdir token is computed by :func:`paths.relative_outdir`, and
   ``latexmk`` receives it as one ``-outdir=<relative>`` argv element.

2. **Diagnose without ``-halt-on-error``.**  Halt truncates a five-error log to
   two, hiding later independent errors.  The first pass therefore omits it;
   ``--stop-on-first-error`` is offered for people who want the old behaviour.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import packages
from .logparse import (
    Diagnostic,
    LogReport,
    attribute_missing_locations,
    merge_reports,
    parse_log_text,
)
from .paths import (
    AUX_SUFFIXES,
    iter_project_files,
    relative_outdir,
    risky_absolute_outdir,
    sha256_file,
    sha256_text,
)
from .proc import Result, argv_display, probe_version, run, which

ENGINES = ("pdflatex", "xelatex", "lualatex")
BACKENDS = ("bibtex", "biber")

DEFAULT_REPORT_NAME = "build-report.json"
SCHEMA_VERSION = 4

#: latexmk exit codes, from its documentation and confirmed on TeX Live 2026.
LATEXMK_EXIT_MEANING = {
    0: "success (or already up to date)",
    11: "no file to process",
    12: "LaTeX reported an error",
    13: "bad command line",
    22: "cannot create output or aux directory",
}

XELATEX_HINTS = re.compile(
    r"\\(?:documentclass|usepackage)\s*(?:\[[^\]]*\])?\{ctex(?:art|rep|book|beamer)?\}"
    r"|\\usepackage\s*(?:\[[^\]]*\])?\{xeCJK\}"
    r"|\\usepackage\s*(?:\[[^\]]*\])?\{fontspec\}"
    r"|\\setmainfont|\\setCJKmainfont|\\setCJKfamilyfont"
)
LUALATEX_HINTS = re.compile(r"\\directlua|\\usepackage\s*(?:\[[^\]]*\])?\{luacode\}|\\fontspec")
# Raw CJK characters in the body are the single most common reason a document
# that "looks plain" cannot be compiled by pdfTeX: it has no glyphs for them and
# inputenc rejects the bytes. Two caveats shaped this rule. Text inside comments
# never reaches pdfTeX, so CJK there must not change the engine; and the legacy
# CJK/CJKutf8 packages are a deliberate pdfLaTeX setup, so honour them.
CJK_TEXT = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff60]"
)
LEGACY_CJK_PKG = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\{CJK(?:utf8|fnt|ec)?\}")


def strip_comments(text: str) -> str:
    """Drop ``%`` comments so declarations are read, not prose.

    An escaped ``\\%`` is part of the text, and ``\\%`` at the start of a line
    still comments the rest of it, so the backslash count decides.
    """
    kept = []
    for line in text.splitlines():
        cut = len(line)
        index = line.find("%")
        while index != -1:
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
            index = line.find("%", index + 1)
        kept.append(line[:cut])
    return "\n".join(kept)


BIBLATEX_RE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\{biblatex\}")
BIBTEX_RE = re.compile(r"\\bibliography\s*\{|\\bibliographystyle\s*\{")
BIBER_BACKEND_RE = re.compile(r"\\usepackage\s*\[[^\]]*backend\s*=\s*biber[^\]]*\]\{biblatex\}")
BIBTEX_BACKEND_RE = re.compile(r"\\usepackage\s*\[[^\]]*backend\s*=\s*bibtex[^\]]*\]\{biblatex\}")


@dataclass
class Toolchain:
    latexmk: str | None = None
    engines: dict[str, str | None] = field(default_factory=dict)
    biber: str | None = None
    bibtex: str | None = None
    kpsewhich: str | None = None
    pdftoppm: str | None = None
    pdfinfo: str | None = None
    chktex: str | None = None
    latexindent: str | None = None
    perl: str | None = None

    def as_dict(self) -> dict:
        return {
            "latexmk": self.latexmk,
            "engines": self.engines,
            "biber": self.biber,
            "bibtex": self.bibtex,
            "kpsewhich": self.kpsewhich,
            "pdftoppm": self.pdftoppm,
            "pdfinfo": self.pdfinfo,
            "chktex": self.chktex,
            "latexindent": self.latexindent,
            "perl": self.perl,
        }


def discover_toolchain() -> Toolchain:
    chain = Toolchain(
        latexmk=which("latexmk"),
        biber=which("biber"),
        bibtex=which("bibtex"),
        kpsewhich=which("kpsewhich"),
        pdftoppm=which("pdftoppm"),
        pdfinfo=which("pdfinfo"),
        chktex=which("chktex"),
        latexindent=which("latexindent"),
        perl=which("perl"),
    )
    chain.engines = {name: which(name) for name in ENGINES}
    return chain


def find_master(root: Path) -> Path | None:
    """Pick the file that most looks like the project master document.

    Preference order: a file named ``main.tex``/``paper.tex``/``thesis.tex``
    (or one with ``\\documentclass``) at the top level, then anywhere in the
    tree.  Files with ``\\documentclass`` beat fragment files.
    """
    from .paths import read_text

    preferred = ("main.tex", "paper.tex", "thesis.tex", "document.tex", "report.tex", "article.tex")
    files = [p for p in iter_project_files(root) if p.suffix.lower() == ".tex"]
    if not files:
        return None

    def score(path: Path) -> tuple:
        try:
            text = read_text(path, limit=200_000)
        except OSError:
            text = ""
        is_master = 1 if "\\documentclass" in text else 0
        named = 1 if path.name.lower() in preferred else 0
        top = 1 if path.parent.resolve() == root.resolve() else 0
        depth = len(path.resolve().relative_to(root.resolve()).parts)
        return (-is_master, -named, -top, depth, path.name.lower())

    return sorted(files, key=score)[0]


def detect_engine(source: Path) -> tuple[str, str]:
    """Choose an engine from the document's own preamble.

    Returns ``(engine, reason)``.  The rules mirror general practice: any
    ``fontspec``/``xeCJK``/``ctex`` usage requires an OpenType-aware engine,
    and ``ctex`` with no explicit font setup is served well by XeLaTeX.
    """
    from .paths import read_text

    text = read_text(source, limit=400_000)
    if XELATEX_HINTS.search(text):
        if LUALATEX_HINTS.search(text) and "\\directlua" in text:
            return "lualatex", "document uses \\directlua"
        return "xelatex", "document loads ctex/xeCJK/fontspec"
    if CJK_TEXT.search(strip_comments(text)) and not LEGACY_CJK_PKG.search(text):
        return "xelatex", "source contains CJK text and loads no CJK package"
    if "\\usepackage{lmodern}" in text or "\\usepackage[T1]{fontenc}" in text:
        return "pdflatex", "pdfTeX-compatible preamble"
    return "pdflatex", "default engine (no OpenType requirement detected)"


def detect_backend(source: Path) -> str | None:
    from .paths import read_text

    text = read_text(source, limit=400_000)
    if BIBER_BACKEND_RE.search(text):
        return "biber"
    if BIBTEX_BACKEND_RE.search(text):
        return "bibtex"
    if BIBLATEX_RE.search(text):
        return "biber"
    if BIBTEX_RE.search(text):
        return "bibtex"
    return None


@dataclass
class BuildOptions:
    source: Path
    outdir: Path
    engine: str = "pdflatex"
    backend: str | None = None
    use_latexmk: bool = True
    outdir_token: str = ""
    jobname: str | None = None
    timeout: float = 300.0
    stop_on_first_error: bool = False
    shell_escape: bool = False
    keep_intermediate: bool = True
    synctex: bool = False
    max_passes: int = 5
    project_root: Path | None = None


@dataclass
class BuildStep:
    tool: str
    result: Result
    report: LogReport
    log_path: str | None = None

    def as_dict(self) -> dict:
        data = self.result.as_dict()
        data.update(
            {
                "tool": self.tool,
                "argv_display": argv_display(self.result.command),
                "log": self.log_path,
                "diagnostics": {
                    "errors": [d.as_dict() for d in self.report.errors],
                    "warnings": [d.as_dict() for d in self.report.warnings][:50],
                },
            }
        )
        return data


@dataclass
class BuildReport:
    status: str = "unknown"
    engine: str = ""
    engine_reason: str = ""
    backend: str | None = None
    source: str = ""
    pdf: str | None = None
    outdir: str = ""
    duration_ms: int = 0
    steps: list[BuildStep] = field(default_factory=list)
    log: LogReport = field(default_factory=LogReport)
    failure: str | None = None
    failed_step: str | None = None
    pdf_sha256: str | None = None
    source_sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "status": self.status,
            "engine": self.engine,
            "engine_reason": self.engine_reason,
            "backend": self.backend,
            "source": self.source,
            "pdf": self.pdf,
            "outdir": self.outdir,
            "duration_ms": self.duration_ms,
            "failure": self.failure,
            "failed_step": self.failed_step,
            "pdf_sha256": self.pdf_sha256,
            "source_sha256": self.source_sha256,
            "warnings": self.warnings,
            "steps": [step.as_dict() for step in self.steps],
            "log": self.log.as_dict(),
        }

    def summary(self) -> str:
        return self.log.summary_line()


def _engine_argv(options: BuildOptions, engine_path: str) -> list[str]:
    argv = [
        engine_path,
        "-no-shell-escape" if not options.shell_escape else "-shell-escape",
        "-interaction=nonstopmode",
        "-file-line-error",
        "-recorder",
        f"-output-directory={options.outdir_token}",
    ]
    if options.stop_on_first_error:
        argv.insert(2, "-halt-on-error")
    if options.synctex:
        argv.append("-synctex=1")
    if options.jobname:
        argv.append(f"-jobname={options.jobname}")
    argv.append(options.source.name)
    return argv


def _latexmk_argv(options: BuildOptions, latexmk_path: str) -> list[str]:
    engine_flag = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}[options.engine]
    argv = [
        latexmk_path,
        engine_flag,
        "-interaction=nonstopmode",
        "-file-line-error",
        f"-outdir={options.outdir_token}",
    ]
    if options.shell_escape:
        # latexmk does not enable shell-escape by default, so the flag only has
        # to be added when explicitly requested. It must go through %O, because
        # `-pdflatex=<args>` *replaces the whole command* rather than appending
        # to it -- passing `-pdflatex=-no-shell-escape` makes latexmk try to run
        # a program literally named `-no-shell-escape`.
        argv.append("-e")
        argv.append("$pdflatex=q/pdflatex %O -shell-escape %S/;"
                    "$xelatex=q/xelatex %O -shell-escape %S/;"
                    "$lualatex=q/lualatex %O -shell-escape %S/")
    if options.jobname:
        argv.append(f"-jobname={options.jobname}")
    # latexmk has no -use-biber / -use-bibtex switch: it inspects the .log/.fls
    # and decides between biber and bibtex itself. Forcing a backend is only
    # meaningful in the direct-engine path below.
    argv.append(options.source.name)
    return argv


def _read_log(outdir: Path, stem: str, engine: str) -> str:
    """Read the engine log, whatever the engine named it."""
    candidates = [outdir / f"{stem}.log"]
    if engine == "lualatex":
        candidates.insert(0, outdir / f"{stem}.log")
    for candidate in candidates:
        if candidate.is_file():
            from .paths import read_text

            return read_text(candidate, limit=4_000_000)
    return ""


def _aux_fingerprint(outdir: Path, stem: str) -> str:
    parts: list[str] = []
    for suffix in (".aux", ".toc", ".out", ".bcf", ".bbl"):
        path = outdir / f"{stem}{suffix}"
        if path.is_file():
            parts.append(f"{suffix}:{sha256_file(path)}")
    return sha256_text("\n".join(parts))


UNICODE_ENGINES = ("xelatex", "lualatex")


def non_utf8_sources(root: Path, source: Path) -> list[str]:
    """List project ``.tex`` files that are not valid UTF-8.

    XeTeX and LuaTeX take their input as UTF-8 and will happily typeset the
    mojibake that a GBK file turns into -- a PDF full of wrong glyphs is worse
    than a failed build, because nothing looks broken. pdfTeX is left out on
    purpose: ``\\usepackage[latin1]{inputenc}`` is a legitimate setup there.
    """
    offenders = []
    seen = {source.resolve()}
    candidates = [source] + [p for p in iter_project_files(root) if p.suffix == ".tex"]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen and path is not source:
            continue
        seen.add(resolved)
        try:
            path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            try:
                offenders.append(str(path.relative_to(root)).replace("\\", "/"))
            except ValueError:
                offenders.append(path.name)
    return offenders


def compile_project(options: BuildOptions) -> BuildReport:
    """Run one full build and return a report describing exactly what happened."""
    chain = discover_toolchain()
    source = options.source
    if not source.is_absolute():
        source = (Path.cwd() / source)
    source = source.resolve()
    root = source.parent

    report = BuildReport(
        source=str(source),
        engine=options.engine,
        backend=options.backend,
    )
    started = time.time()

    try:
        outdir_abs, token = relative_outdir(root, options.outdir)
    except ValueError as exc:
        report.status = "failed"
        report.failure = str(exc)
        return report
    options.outdir_token = token
    options.outdir = outdir_abs
    report.outdir = str(outdir_abs)
    report.source_sha256 = sha256_file(source)

    if risky_absolute_outdir(outdir_abs):
        report.warnings.append(
            "output directory contains CJK text followed by a space; the toolkit passes it "
            "relative to avoid the TeX Live Windows putenv failure"
        )

    outdir_abs.mkdir(parents=True, exist_ok=True)
    stem = options.jobname or source.stem

    # Refuse to feed non-UTF-8 source to a Unicode engine: the build would
    # "succeed" and produce a PDF of wrong glyphs, which is undetectable later.
    if options.engine in UNICODE_ENGINES:
        offenders = non_utf8_sources(root, source)
        if offenders:
            names = ", ".join(offenders[:3])
            report.status = "failed"
            report.failure = f"{names} is not valid UTF-8; {options.engine} reads source as UTF-8"
            report.log = LogReport(success=False)
            report.log.errors.append(
                Diagnostic(
                    severity="error",
                    message=report.failure,
                    file=offenders[0],
                    line=None,
                    tool=options.engine,
                    category="encoding",
                    detail="convert the file to UTF-8; the original encoding cannot be inferred",
                )
            )
            report.log.root_cause = report.log.errors[0]
            report.duration_ms = int((time.time() - started) * 1000)
            return report

    steps: list[BuildStep] = []
    failure: str | None = None
    failed_step: str | None = None

    if options.use_latexmk and chain.latexmk:
        tool = "latexmk"
        argv = _latexmk_argv(options, chain.latexmk)
        # latexmk runs from the project root and changes into the outdir itself.
        result = run(argv, cwd=root, timeout=options.timeout)
        log_text = _read_log(outdir_abs, stem, options.engine)
        log_report = attribute_missing_locations(
            parse_log_text(log_text or result.combined, root, "engine"), source.name
        )
        steps.append(BuildStep(tool=tool, result=result, report=log_report,
                               log_path=str(outdir_abs / f"{stem}.log") if log_text else None))
        if result.returncode not in (0, None) or not log_report.success:
            failure = LATEXMK_EXIT_MEANING.get(
                result.returncode or -1,
                f"latexmk exited with {result.returncode}",
            )
            if log_report.root_cause is not None:
                failure = log_report.root_cause.message
            failed_step = tool
    else:
        engine_path = chain.engines.get(options.engine)
        if not engine_path:
            report.status = "failed"
            report.failure = f"engine {options.engine} was not found on PATH"
            report.duration_ms = int((time.time() - started) * 1000)
            return report
        if options.use_latexmk and not chain.latexmk:
            report.warnings.append("latexmk not found; falling back to direct engine passes")

        passes = 1
        previous = None
        while passes <= options.max_passes:
            argv = _engine_argv(options, engine_path)
            result = run(argv, cwd=root, timeout=options.timeout)
            log_text = _read_log(outdir_abs, stem, options.engine)
            log_report = attribute_missing_locations(
            parse_log_text(log_text or result.combined, root, "engine"), source.name
        )
            steps.append(
                BuildStep(tool=options.engine, result=result, report=log_report,
                          log_path=str(outdir_abs / f"{stem}.log") if log_text else None)
            )
            if log_report.errors:
                failure = log_report.root_cause.message if log_report.root_cause else "engine error"
                failed_step = options.engine
                break
            if options.backend and passes == 1:
                backend_path = chain.biber if options.backend == "biber" else chain.bibtex
                if backend_path:
                    backend_argv = [backend_path, stem]
                    backend_result = run(backend_argv, cwd=outdir_abs, timeout=options.timeout)
                    backend_log = outdir_abs / f"{stem}.blg"
                    backend_text = backend_log.read_text(encoding="utf-8", errors="replace") \
                        if backend_log.is_file() else backend_result.combined
                    backend_report = parse_log_text(backend_text, root, options.backend)
                    steps.append(
                        BuildStep(tool=options.backend, result=backend_result,
                                  report=backend_report,
                                  log_path=str(backend_log) if backend_log.is_file() else None)
                    )
                    if backend_report.errors:
                        failure = backend_report.root_cause.message if backend_report.root_cause else (
                            f"{options.backend} failed"
                        )
                        failed_step = options.backend
                        break
            fingerprint = _aux_fingerprint(outdir_abs, stem)
            if previous is not None and fingerprint == previous and not log_report.rerun_needed:
                passes += 1
                break
            previous = fingerprint
            passes += 1

    pdf_path = outdir_abs / f"{stem}.pdf"
    report.steps = steps
    report.log = merge_reports([step.report for step in steps])
    report.duration_ms = int((time.time() - started) * 1000)

    checks: list[str] = []
    if not pdf_path.is_file():
        checks.append("no PDF was produced")
    else:
        header = pdf_path.open("rb").read(5)
        if header != b"%PDF-":
            checks.append("output file does not start with %PDF-")
        else:
            report.pdf = str(pdf_path)
            report.pdf_sha256 = sha256_file(pdf_path)

    now_source_hash = sha256_file(source)
    if now_source_hash != report.source_sha256:
        checks.append("source file changed during the build")

    if failure or checks:
        report.status = "failed"
        report.failure = failure or "; ".join(checks)
        report.failed_step = failed_step or (steps[-1].tool if steps else None)
    else:
        report.status = "success"

    if report.status == "failed" and report.log.missing_packages:
        report.warnings.extend(_missing_package_hints(report.log.missing_packages, chain.kpsewhich))
    return report


def _missing_package_hints(names: list[str], kpsewhich: str | None) -> list[str]:
    hints: list[str] = []
    for hit in packages.resolve_many(names, kpsewhich=kpsewhich):
        if hit.suggestion:
            hints.append(f"{hit.filename} is provided by package '{hit.package}': {hit.suggestion}")
        else:
            hints.append(f"{hit.filename} is not installed and no TeX Live package claims it")
    return hints


def clean_artifacts(outdir: Path, keep_pdf: bool = True, extra: list[str] | None = None) -> list[str]:
    """Remove intermediate files from one build directory."""
    removed: list[str] = []
    if not outdir.is_dir():
        return removed
    suffixes = list(AUX_SUFFIXES) + list(extra or [])
    for entry in sorted(outdir.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if keep_pdf and name.lower().endswith(".pdf"):
            continue
        if any(name.endswith(suffix) for suffix in suffixes):
            try:
                entry.unlink()
                removed.append(name)
            except OSError:
                pass
    return removed


def write_report(report: BuildReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
