"""PDF inspection and page rendering.

``pdfinfo`` on a CP936 console returns mojibake for localized fields such as
``CreationDate``; parsing therefore looks only at ASCII keys it understands and
ignores anything it cannot decode.  Rendering uses poppler's ``pdftoppm``,
which is present on this machine (0.74 s for nine 100 dpi pages).
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .proc import run, which

PDF_MAGIC = b"%PDF-"

INFO_KEYS = ("Pages", "Page size", "File size", "PDF version", "Encrypted", "Optimized")


@dataclass
class PdfInfo:
    path: str
    pages: int | None = None
    page_width_pt: float | None = None
    page_height_pt: float | None = None
    file_size: int | None = None
    pdf_version: str = ""
    encrypted: bool = False
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "pages": self.pages,
            "page_size_pt": (
                [self.page_width_pt, self.page_height_pt]
                if self.page_width_pt and self.page_height_pt
                else None
            ),
            "file_size": self.file_size,
            "pdf_version": self.pdf_version,
            "encrypted": self.encrypted,
            "error": self.error or None,
        }


def read_pdfinfo(pdf: Path, pdfinfo: str | None = None) -> PdfInfo:
    info = PdfInfo(path=str(pdf))
    if not pdf.is_file():
        info.error = "file not found"
        return info
    info.file_size = pdf.stat().st_size
    with pdf.open("rb") as handle:
        if handle.read(5) != PDF_MAGIC:
            info.error = "not a PDF (missing %PDF- header)"
            return info

    exe = pdfinfo or which("pdfinfo")
    if not exe:
        info.error = "pdfinfo not found"
        return info
    result = run([exe, str(pdf)], cwd=pdf.parent, timeout=60)
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "Pages":
            try:
                info.pages = int(value.split()[0])
            except (ValueError, IndexError):
                pass
        elif key == "Page size":
            parts = value.split()
            try:
                info.page_width_pt = float(parts[0])
                info.page_height_pt = float(parts[2])
            except (ValueError, IndexError):
                pass
        elif key == "PDF version":
            info.pdf_version = value
        elif key == "Encrypted":
            info.encrypted = value.lower().startswith("yes")
    return info


@dataclass
class RenderResult:
    pdf: str
    outdir: str
    dpi: int
    pages: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "outdir": self.outdir,
            "dpi": self.dpi,
            "pages": self.pages,
            "duration_ms": self.duration_ms,
            "error": self.error or None,
        }


def render_pdf(
    pdf: Path,
    outdir: Path,
    dpi: int = 120,
    fmt: str = "png",
    first: int | None = None,
    last: int | None = None,
    pdftoppm: str | None = None,
) -> RenderResult:
    """Render pages to ``outdir`` with poppler's ``pdftoppm``."""
    result = RenderResult(pdf=str(pdf), outdir=str(outdir), dpi=dpi)
    if not pdf.is_file():
        result.error = "PDF not found"
        return result
    exe = pdftoppm or which("pdftoppm")
    if not exe:
        result.error = "pdftoppm not found; install poppler to render pages"
        return result

    outdir.mkdir(parents=True, exist_ok=True)
    stem = pdf.stem
    argv = [exe, "-r", str(dpi)]
    if fmt == "jpeg":
        argv.append("-jpeg")
    elif fmt == "png":
        argv.append("-png")
    if first:
        argv.extend(["-f", str(first)])
    if last:
        argv.extend(["-l", str(last)])
    argv.extend([str(pdf), str(outdir / stem)])

    import time

    started = time.time()
    proc_result = run(argv, cwd=pdf.parent, timeout=240)
    result.duration_ms = int((time.time() - started) * 1000)
    if proc_result.returncode != 0:
        result.error = proc_result.stderr.strip() or f"pdftoppm exited {proc_result.returncode}"
        return result
    pattern = f"{stem}-*.{('jpg' if fmt == 'jpeg' else fmt)}"
    result.pages = sorted(str(p) for p in outdir.glob(pattern))
    if not result.pages:
        result.error = "pdftoppm produced no pages"
    return result


def contact_sheet_note(pages: list[str]) -> str:
    """Human-readable pointer to the rendered pages."""
    if not pages:
        return "no pages rendered"
    return f"{len(pages)} page image(s), first at {pages[0]}"
