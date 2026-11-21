"""Measure page layout from a PDF, so "does this look right" becomes numbers.

Two kinds of evidence are combined:

* **Hard geometry** from ``pdftotext -bbox-layout``: every word carries exact
  coordinates, so text that runs past the page edge or past the document's own
  right margin is a fact, not an opinion.
* **Heuristics** for typographic trouble that geometry alone cannot name —
  a vertical hole where a float failed to place, a single carried-over line
  (widow/orphan).  These are reported with a confidence below 1.0 so a reader
  can tell them apart from the hard facts.

Nothing here needs Ghostscript, ImageMagick, or a Python PDF library: the
machine has poppler, so poppler does the measuring.
"""

from __future__ import annotations

import statistics
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .proc import run, which

NS = "{http://www.w3.org/1999/xhtml}"

# Past the trim edge at all -> text is being clipped by the paper.
EDGE_TOLERANCE_PT = 1.0
# Past the document's own right margin -> inconsistent measure, worth a look.
MARGIN_TOLERANCE_PT = 2.0
# A vertical gap this many times the normal leading reads as a hole.  Normal
# typography already spends 2.5-3x the leading around a section heading, so the
# factor has to sit above that or every heading becomes a false positive.
GAP_FACTOR = 4.0
# A line filling less than this share of the measure cannot be a full line.
SHORT_LINE_RATIO = 0.6


@dataclass
class LayoutLine:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ""

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def as_dict(self) -> dict:
        data = {
            "page": self.page,
            "bbox": [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)],
            "width": round(self.width, 2),
        }
        if self.text:
            data["text"] = self.text
        return data


@dataclass
class LayoutIssue:
    kind: str  # overflow-edge | overflow-margin | hole | widow-orphan | sparse-page
    page: int
    severity: str  # error | layout | warning
    detail: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None

    def as_dict(self) -> dict:
        data = {
            "kind": self.kind,
            "page": self.page,
            "severity": self.severity,
            "detail": self.detail,
            "confidence": round(self.confidence, 2),
        }
        if self.bbox:
            data["bbox"] = [round(value, 2) for value in self.bbox]
        return data


@dataclass
class PageLayout:
    index: int
    width: float
    height: float
    lines: list[LayoutLine] = field(default_factory=list)
    words: int = 0
    text_left: float | None = None
    text_right: float | None = None
    text_top: float | None = None
    text_bottom: float | None = None
    leading: float | None = None
    fill_ratio: float = 0.0
    issues: list[LayoutIssue] = field(default_factory=list)
    # A running header/footer sits far from the body block; measuring the body
    # height without removing it would report the margin as a vertical hole.
    header: list[LayoutLine] = field(default_factory=list)
    footer: list[LayoutLine] = field(default_factory=list)

    @property
    def body_lines(self) -> list[LayoutLine]:
        excluded = {id(line) for line in self.header} | {id(line) for line in self.footer}
        return [line for line in self.lines if id(line) not in excluded]

    def as_dict(self) -> dict:
        return {
            "page": self.index,
            "size_pt": [round(self.width, 2), round(self.height, 2)],
            "lines": len(self.lines),
            "words": self.words,
            "measure_pt": (
                round(self.text_right - self.text_left, 2)
                if self.text_left is not None and self.text_right is not None
                else None
            ),
            "leading_pt": round(self.leading, 2) if self.leading else None,
            "fill_ratio": round(self.fill_ratio, 3),
            "header_lines": len(self.header),
            "footer_lines": len(self.footer),
            "issues": [issue.as_dict() for issue in self.issues],
        }


@dataclass
class DocumentLayout:
    pdf: str
    page_size: tuple[float, float] | None = None
    right_margin_pt: float | None = None
    left_margin_pt: float | None = None
    median_leading_pt: float | None = None
    pages: list[PageLayout] = field(default_factory=list)
    issues: list[LayoutIssue] = field(default_factory=list)
    error: str = ""
    # How the measure was established.  Geometry alone cannot find a right edge
    # on a page with one or two full lines, so say so instead of guessing.
    measure_source: str = "unknown"
    log_overfull: list[dict] = field(default_factory=list)

    @property
    def overflow_pages(self) -> list[int]:
        return sorted({i.page for i in self.issues if i.kind.startswith("overflow")})

    def as_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "page_size_pt": [round(v, 2) for v in self.page_size] if self.page_size else None,
            "margins_pt": {
                "left": round(self.left_margin_pt, 2) if self.left_margin_pt else None,
                "right": round(self.right_margin_pt, 2) if self.right_margin_pt else None,
            },
            "measure_source": self.measure_source,
            "median_leading_pt": (
                round(self.median_leading_pt, 2) if self.median_leading_pt else None
            ),
            "counts": {
                "pages": len(self.pages),
                "issues": len(self.issues),
                "overflow": len([i for i in self.issues if i.kind.startswith("overflow")]),
                "holes": len([i for i in self.issues if i.kind == "hole"]),
                "widow_orphan": len([i for i in self.issues if i.kind == "widow-orphan"]),
                "log_overfull": len(self.log_overfull),
            },
            "issues": [issue.as_dict() for issue in self.issues],
            "log_overfull": self.log_overfull,
            "pages": [page.as_dict() for page in self.pages],
            "error": self.error or None,
        }

    def summary(self) -> str:
        if self.error:
            return f"layout: unavailable ({self.error})"
        pages = len(self.pages)
        parts = []
        for kind, label in (
            ("overflow-edge", "past the page edge"),
            ("overflow-margin", "past the right margin"),
            ("hole", "vertical hole"),
            ("widow-orphan", "possible widow/orphan"),
            ("sparse-page", "mostly empty page"),
        ):
            count = len([i for i in self.issues if i.kind == kind])
            if count:
                parts.append(f"{count} {label}")
        head = f"layout: {pages} page(s)"
        if not parts and not self.log_overfull and self.measure_source == "geometry":
            return f"{head}, no geometry issues"
        if parts:
            head += ", " + ", ".join(parts)
        if self.log_overfull:
            head += f", {len(self.log_overfull)} overfull box(es) in the log"
        if self.measure_source == "unknown":
            head += " (right margin not measurable: too few full lines)"
        return head


def _bbox(element: ET.Element) -> tuple[float, float, float, float]:
    return (
        float(element.get("xMin", 0.0)),
        float(element.get("yMin", 0.0)),
        float(element.get("xMax", 0.0)),
        float(element.get("yMax", 0.0)),
    )


def extract_boxes(pdf: Path, pdftotext: str | None = None) -> tuple[str, str]:
    """Run ``pdftotext -bbox-layout`` and return ``(xml_text, error)``."""
    exe = pdftotext or which("pdftotext")
    if not exe:
        return "", "pdftotext not found"
    with tempfile.TemporaryDirectory(prefix="latex-layout-") as tmp:
        target = Path(tmp) / "boxes.xml"
        result = run(
            [exe, "-bbox-layout", str(pdf), str(target)],
            cwd=pdf.parent,
            timeout=120,
        )
        if result.returncode != 0:
            return "", result.stderr.strip() or f"pdftotext exited {result.returncode}"
        if not target.is_file():
            return "", "pdftotext produced no output"
        # The XML declares UTF-8; read bytes so a CP936 console cannot mangle it.
        return target.read_bytes().decode("utf-8", "replace"), ""


def _page_lines(root: ET.Element, index: int) -> list[LayoutLine]:
    """Prefer ``<line>`` boxes; rebuild from words when poppler omits them."""
    lines: list[LayoutLine] = []
    for element in root.iter(NS + "line"):
        x0, y0, x1, y1 = _bbox(element)
        text = " ".join(
            (word.text or "").strip() for word in element.iter(NS + "word")
        ).strip()
        lines.append(LayoutLine(index, x0, y0, x1, y1, text))
    if lines:
        return sorted(lines, key=lambda line: (round(line.y0, 1), line.x0))

    # Fall back to grouping words by their baseline.
    groups: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for word in root.iter(NS + "word"):
        x0, y0, x1, y1 = _bbox(word)
        groups.setdefault(int(round(y0, 0)), []).append(
            (x0, y0, x1, y1, (word.text or "").strip())
        )
    for bucket in groups.values():
        bucket.sort(key=lambda item: item[0])
        lines.append(
            LayoutLine(
                index,
                min(item[0] for item in bucket),
                min(item[1] for item in bucket),
                max(item[2] for item in bucket),
                max(item[3] for item in bucket),
                " ".join(item[4] for item in bucket).strip(),
            )
        )
    return sorted(lines, key=lambda line: (round(line.y0, 1), line.x0))


def _robust_leading(deltas: list[float]) -> float | None:
    """Estimate normal leading without letting holes inflate it.

    A plain median fails on a short page: four lines with a 430pt float hole in
    the middle put the median *on* the hole.  Paragraph-internal leading is the
    most common spacing in any real document, so a low quantile of the whole
    document's deltas recovers it even when holes are the largest values.
    """
    values = sorted(value for value in deltas if value > 0)
    if not values:
        return None
    if len(values) < 4:
        # Too few samples to rank; the smallest gap is the safest guess.
        return values[0]
    position = (len(values) - 1) * 0.2
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _split_furniture(page: PageLayout, limit: float) -> None:
    """Separate a running header/footer from the body block.

    Furniture lives in the margin, so it is recognised by position first (a
    page number sits in the bottom margin, not at the paper edge) and by
    isolation second (a clear gap above it).  Requiring both is what keeps a
    real mid-body hole — an unplaced float — classified as a hole instead of
    silently absorbed into "footer".
    """
    lines = page.lines
    if len(lines) < 2 or not page.height:
        return
    # A page number on A4 sits around 83% of the page height, so the band has to
    # start well inside the bottom margin rather than at the paper edge.
    footer_zone = page.height * 0.78
    header_zone = page.height * 0.12

    def looks_numeric(line: LayoutLine) -> bool:
        text = line.text.strip()
        return bool(text) and all(character.isdigit() or character in "-–—/ " for character in text)

    cut = len(lines)
    while cut > 1:
        candidate = lines[cut - 1]
        previous = lines[cut - 2]
        isolated = candidate.y0 - previous.y0 > limit
        if not isolated:
            break
        # A lone number deep in the page is still a page number; anything else
        # must sit in the bottom band to count as furniture rather than as text
        # that follows a real hole.
        if candidate.y0 < footer_zone and not looks_numeric(candidate):
            break
        cut -= 1
    if cut < len(lines):
        page.footer = lines[cut:]
        body = lines[:cut]
    else:
        body = lines

    start = 0
    while start < len(body) - 1:
        candidate = body[start]
        following = body[start + 1]
        if following.y0 - candidate.y0 <= limit:
            break
        if candidate.y0 > header_zone and not looks_numeric(candidate):
            break
        start += 1
    # Never absorb so much that a single line is left as the body: one isolated
    # line above a lone line is far more likely a real hole than a header, and
    # eating it would silence the very defect this module exists to report.
    if 0 < start < len(body) and len(body) - start >= 2:
        page.header = body[:start]


def measure_layout(pdf: Path, pdftotext: str | None = None) -> DocumentLayout:
    """Compute per-page geometry and flag overflow, holes, and carried-over lines."""
    layout = DocumentLayout(pdf=str(pdf))
    if not pdf.is_file():
        layout.error = "PDF not found"
        return layout
    xml_text, error = extract_boxes(pdf, pdftotext)
    if error:
        layout.error = error
        return layout
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        layout.error = f"could not parse pdftotext XML: {exc}"
        return layout

    page_elements = list(root.iter(NS + "page"))
    if not page_elements:
        layout.error = "no pages in pdftotext output"
        return layout

    all_deltas: list[float] = []
    for index, element in enumerate(page_elements, start=1):
        width = float(element.get("width", 0.0))
        height = float(element.get("height", 0.0))
        lines = _page_lines(element, index)
        page = PageLayout(index=index, width=width, height=height, lines=lines)
        page.words = len(list(element.iter(NS + "word")))
        layout.pages.append(page)
        for position in range(len(lines) - 1):
            delta = lines[position + 1].y0 - lines[position].y0
            if delta > 0:
                all_deltas.append(delta)

    # One document-wide leading estimate, computed before any per-page work, so
    # a short page cannot mistake its own float hole for normal spacing.
    leading = _robust_leading(all_deltas)
    layout.median_leading_pt = leading
    gap_limit = leading * GAP_FACTOR if leading else 0.0

    for page in layout.pages:
        if page.lines:
            _split_furniture(page, gap_limit)
        body = page.body_lines or page.lines
        if body:
            page.text_left = min(line.x0 for line in body)
            page.text_right = max(line.x1 for line in body)
            page.text_top = min(line.y0 for line in body)
            page.text_bottom = max(line.y1 for line in body)
            if page.height:
                page.fill_ratio = (page.text_bottom - page.text_top) / page.height
            page.leading = leading

    sizes = [(page.width, page.height) for page in layout.pages if page.width]
    if sizes:
        layout.page_size = sizes[0]

    # The measure is the modal line end, not a median of page maxima: see
    # _measure_edge for why a median collapses when a page is short.
    layout.right_margin_pt = _measure_edge(layout)
    layout.measure_source = "geometry" if layout.right_margin_pt else "unknown"
    lefts = [page.text_left for page in layout.pages if page.text_left is not None]
    if lefts:
        layout.left_margin_pt = min(lefts)

    _flag_overflow(layout)
    _flag_holes(layout)
    _flag_carried_lines(layout)
    _flag_sparse(layout)
    layout.issues = flatten_issues(layout)
    return layout


def _measure_edge(layout: DocumentLayout) -> float | None:
    """Find the document's real right edge: the line end most lines agree on.

    A column of justified text stops at the measure on every full line, so the
    modal right edge *is* the measure.  A median of per-page maxima cannot work
    — on a short page the overflowing line is part of the sample and drags the
    reference out to meet itself.

    Returns ``None`` when no edge is corroborated by at least two lines: with
    only a handful of lines there is no measure to compare against, and a
    reference derived from one line would flag that line as normal and every
    other as short.
    """
    ends: list[float] = []
    for page in layout.pages:
        for line in page.body_lines or page.lines:
            if line.width > 0:
                ends.append(line.x1)
    if not ends:
        return None
    ends.sort()
    # Cluster ends within half a point.  A cluster needs corroboration: one line
    # agreeing with itself proves nothing, and an overflowing line is usually
    # alone on its page.  Requiring two members is what keeps a single bad box
    # from defining "normal" and then passing its own check.
    clusters: list[list[float]] = [[ends[0]]]
    for value in ends[1:]:
        if value - clusters[-1][-1] <= 0.5:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    confirmed = [cluster for cluster in clusters if len(cluster) >= 2]
    if not confirmed:
        return None
    # Among confirmed ends take the rightmost, not the most populated: a table's
    # column edge can easily be shared by more lines than the measure is, and
    # justified full lines stop exactly at the measure whatever else is on the
    # page.  Anything beyond the rightmost confirmed end is therefore the odd one
    # out — which is the whole point of measuring it.
    best = max(confirmed, key=lambda cluster: cluster[-1])
    return sum(best) / len(best)


def _flag_overflow(layout: DocumentLayout) -> None:
    reference = layout.right_margin_pt
    for page in layout.pages:
        if not page.lines:
            continue
        page_edge = page.width
        for line in page.lines:
            if page_edge and line.x1 > page_edge + EDGE_TOLERANCE_PT:
                overflow = line.x1 - page_edge
                page.issues.append(
                    LayoutIssue(
                        kind="overflow-edge",
                        page=page.index,
                        severity="error",
                        detail=f"text runs {overflow:.1f}pt past the right edge of the paper",
                        confidence=0.99,
                        bbox=(line.x0, line.y0, line.x1, line.y1),
                    )
                )
                continue
            if reference and line.x1 > reference + MARGIN_TOLERANCE_PT:
                over = line.x1 - reference
                page.issues.append(
                    LayoutIssue(
                        kind="overflow-margin",
                        page=page.index,
                        severity="layout",
                        detail=(
                            f"line ends {over:.1f}pt past the document's right margin "
                            f"({reference:.1f}pt); the measure is inconsistent"
                        ),
                        confidence=0.9,
                        bbox=(line.x0, line.y0, line.x1, line.y1),
                    )
                )


def _flag_holes(layout: DocumentLayout) -> None:
    leading = layout.median_leading_pt
    if not leading:
        return
    limit = leading * GAP_FACTOR
    for page in layout.pages:
        body = page.body_lines
        for current, following in zip(body, body[1:]):
            gap = following.y0 - current.y0
            if gap <= limit:
                continue
            page.issues.append(
                LayoutIssue(
                    kind="hole",
                    page=page.index,
                    severity="layout",
                    detail=(
                        f"{gap:.1f}pt of vertical space where {leading:.1f}pt is normal "
                        f"({gap / leading:.1f}x); a float may have been pushed to the next page"
                    ),
                    confidence=0.8,
                    bbox=(current.x0, current.y1, following.x1, following.y0),
                )
            )


def _flag_carried_lines(layout: DocumentLayout) -> None:
    """Flag a paragraph line stranded alone across a page break.

    Shortness alone is not enough: a paragraph ends with a short line, so on a
    document of ordinary paragraphs some short line lands at a page edge all
    the time and flagging each one buries the real defects.  The deciding signal
    is indentation — TeX indents only a paragraph's *first* line, so a short
    line at the top of a page that starts at the left margin is a paragraph's
    tail carried over alone (a widow), while an indented short line there is
    simply a new paragraph beginning.
    """
    if len(layout.pages) < 2:
        return
    left = layout.left_margin_pt
    for previous, page in zip(layout.pages, layout.pages[1:]):
        previous_body = previous.body_lines
        body = page.body_lines
        if not previous_body or not body or left is None:
            continue
        measure = None
        if layout.right_margin_pt is not None:
            measure = layout.right_margin_pt - left
        if not measure or measure <= 0:
            continue

        def is_short(line: LayoutLine) -> bool:
            return 0 < line.width < measure * SHORT_LINE_RATIO

        def is_indented(line: LayoutLine) -> bool:
            # TeX's paragraph indent is 15-20pt; allow for optical margin kerning.
            return line.x0 > left + 3.0

        first = body[0]
        if is_short(first) and not is_indented(first):
            page.issues.append(
                LayoutIssue(
                    kind="widow-orphan",
                    page=page.index,
                    severity="warning",
                    detail=(
                        "page opens with a short, unindented line — the last line of a "
                        "paragraph was carried over alone (widow)"
                    ),
                    confidence=0.7,
                    bbox=(first.x0, first.y0, first.x1, first.y1),
                )
            )

        # Orphan: the page's last line is indented, so it opened a paragraph, and
        # nothing of that paragraph follows it here — the rest is on the next
        # page.  A page that merely ends at a paragraph's *last* line is normal
        # and must not be flagged.
        last = previous_body[-1]
        continues = not is_indented(body[0])
        if is_indented(last) and continues:
            previous.issues.append(
                LayoutIssue(
                    kind="widow-orphan",
                    page=previous.index,
                    severity="warning",
                    detail=(
                        "page ends on a paragraph's first (indented) line — it stands "
                        "alone at the bottom of the page (orphan)"
                    ),
                    confidence=0.7,
                    bbox=(last.x0, last.y0, last.x1, last.y1),
                )
            )


def _flag_sparse(layout: DocumentLayout) -> None:
    if len(layout.pages) < 2:
        return
    fills = [page.fill_ratio for page in layout.pages if page.lines]
    if not fills:
        return
    typical = statistics.median(fills)
    if typical <= 0:
        return
    for page in layout.pages:
        # The final page is allowed to be short — that is where a document ends.
        if page.index == len(layout.pages):
            continue
        if page.lines and page.fill_ratio < typical * 0.35:
            page.issues.append(
                LayoutIssue(
                    kind="sparse-page",
                    page=page.index,
                    severity="warning",
                    detail=(
                        f"only {page.fill_ratio:.0%} of the page height is used "
                        f"(comparable pages use {typical:.0%})"
                    ),
                    confidence=0.6,
                )
            )


def flatten_issues(layout: DocumentLayout) -> list[LayoutIssue]:
    """All issues in page order, which is the order a reader checks them."""
    issues: list[LayoutIssue] = []
    for page in layout.pages:
        issues.extend(page.issues)
    return issues


def attach_log_overfull(layout: DocumentLayout, log_report) -> None:
    """Fold the log's overfull boxes into the layout verdict.

    Geometry only sees what the page shows.  A short page can hide a box that
    is wider than the measure but still inside the paper, and a page with one
    line gives no measure to compare against.  The log knows the box exceeded
    its allotted width regardless of geometry, so it supplies the verdict those
    pages cannot produce on their own.
    """
    if log_report is None:
        return
    entries: list[dict] = []
    for item in getattr(log_report, "layout", []):
        detail = getattr(item, "detail", "") or ""
        if "pt too wide" not in detail:
            continue
        entries.append(
            {
                "file": getattr(item, "file", "") or "",
                "line": getattr(item, "line", None),
                "detail": detail,
                "source": "log",
            }
        )
    layout.log_overfull = entries
    if entries and layout.measure_source == "unknown":
        layout.measure_source = "log"


def page_verdicts(layout: DocumentLayout) -> list[str]:
    """One line per page that has something worth saying."""
    lines: list[str] = []
    for page in layout.pages:
        if not page.issues:
            lines.append(f"page {page.index}: ok ({len(page.lines)} line(s))")
            continue
        head = f"page {page.index}: {len(page.issues)} issue(s)"
        hard = [i for i in page.issues if i.confidence >= 0.9]
        soft = [i for i in page.issues if i.confidence < 0.9]
        if hard:
            head += f", {len(hard)} certain"
        if soft:
            head += f", {len(soft)} suspected"
        lines.append(head)
        for issue in page.issues:
            marker = "!" if issue.confidence >= 0.9 else "?"
            lines.append(f"  {marker} [{issue.kind}] {issue.detail}")
    return lines
