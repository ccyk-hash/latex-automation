"""Path handling that survives Windows TeX Live.

The one hard rule this module enforces: **never hand TeX an absolute
``-output-directory``**.  On Windows TeX Live 2026, ``pdflatex`` and
``xelatex`` call ``putenv(TEXMF_OUTPUT_DIRECTORY=<abs path>)`` and abort with

    pdflatex.exe: fatal: putenv(TEXMF_OUTPUT_DIRECTORY=D:\\...\\中 文\\o6).

whenever the absolute path contains a CJK run followed by a space.  ``lualatex``
and ``latexmk`` are unaffected, but the toolkit cannot rely on that: the outdir
is therefore always expressed relative to the directory TeX runs in, and
``latexmk`` receives a single ``-outdir=<relative>`` argv token.

See ``docs/01-research-report.md`` section 3.1 for the reproduction matrix.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

#: Directory names the toolkit writes into; never treated as project sources.
GENERATED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "latex-out",
    "build",
    "dist",
    "out",
}

#: Files removed by ``clean`` unless the caller overrides the list.
AUX_SUFFIXES = (
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk",
    ".synctex.gz", ".synctex", ".xdv", ".dvi", ".bbl", ".blg", ".bcf",
    ".run.xml", ".nav", ".snm", ".vrb", ".idx", ".ind", ".ilg", ".glo",
    ".gls", ".glg", ".acn", ".acr", ".alg", ".loa", ".lol", ".spl",
    ".bcf-SAVE-ERROR", ".synctex(busy)",
)

SOURCE_SUFFIXES = {".tex", ".bib", ".cls", ".sty", ".bst", ".ltx", ".dtx"}

#: Matches a CJK code point, used only for diagnostics and warnings.
CJK_RE = re.compile(
    "[\u2e80-\u2eff\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf"
    "\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)

MAX_SCAN_FILES = 5000
MAX_SOURCE_BYTES = 2_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def relative_outdir(source_dir: Path, outdir: Path) -> tuple[Path, str]:
    """Return ``(absolute_outdir, relative_token)`` safe for TeX.

    ``outdir`` is resolved against ``source_dir`` when relative.  The returned
    token is what goes on the command line: it never contains a drive letter,
    and when the directory sits outside the source tree the caller gets a
    ``ValueError`` instead of a silently broken build.
    """
    source_dir = source_dir.resolve()
    target = outdir if outdir.is_absolute() else (source_dir / outdir)
    target = target.resolve()
    try:
        relative = target.relative_to(source_dir)
    except ValueError as exc:
        # The command line only ever carries a relative token, because an
        # absolute one is what trips the Windows putenv bug. Reaching here
        # means the caller asked for something outside the tree it builds in.
        raise ValueError(
            f"output directory {target} is outside the project directory {source_dir}; "
            "the outdir must live inside the project so TeX can be given a relative "
            "-output-directory (absolute paths containing CJK-then-space break "
            "pdflatex/xelatex on Windows)"
        ) from exc
    token = relative.as_posix()
    if not token:
        raise ValueError("output directory must be a subdirectory of the project, not the project itself")
    return target, token


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def risky_absolute_outdir(path: Path) -> bool:
    """True when handing ``path`` to TeX as an absolute outdir is known-unsafe."""
    text = str(path)
    if not has_cjk(text):
        return False
    # The failure needs a CJK run followed by a space; be conservative and
    # warn on any CJK+space combination.
    for match in CJK_RE.finditer(text):
        tail = text[match.end():]
        if tail.startswith(" "):
            return True
    return False


def iter_project_files(root: Path, limit: int = MAX_SCAN_FILES) -> list[Path]:
    """Shallow-ish recursive scan that skips generated and VCS directories."""
    root = root.resolve()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in GENERATED_DIRS and not d.startswith(".")]
        for name in filenames:
            if len(found) >= limit:
                return found
            found.append(Path(dirpath) / name)
    return found


def read_text(path: Path, limit: int = MAX_SOURCE_BYTES) -> str:
    data = path.read_bytes()[:limit]
    for encoding in ("utf-8", "utf-8-sig", "cp936", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def in_generated_dir(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return any(part in GENERATED_DIRS for part in relative.parts[:-1])
