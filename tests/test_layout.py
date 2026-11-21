"""Layout measurements tested against synthetic box data.

The measuring code is pure: feed it the XHTML that ``pdftotext -bbox-layout``
produces and it returns numbers.  Building that XML by hand keeps these tests
fast and lets each case isolate one decision — a real PDF cannot be made to
overflow by exactly 2.4pt on demand, but a fixture can.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from latex_automation.layout import (
    DocumentLayout,
    LayoutIssue,
    LayoutLine,
    PageLayout,
    _measure_edge,
    _robust_leading,
    _split_furniture,
    measure_layout,
    page_verdicts,
)


def page_xml(number, width, height, lines):
    """Render one <page> element; ``lines`` are (x0, y0, x1, y1, text)."""
    body = []
    for x0, y0, x1, y1, text in lines:
        body.append(
            f'<line xMin="{x0}" yMin="{y0}" xMax="{x1}" yMax="{y1}">'
            f'<word xMin="{x0}" yMin="{y0}" xMax="{x1}" yMax="{y1}">{text}</word>'
            "</line>"
        )
    return (
        f'<page width="{width}" height="{height}">'
        f"<flow><block>{''.join(body)}</block></flow></page>"
    )


def document_xml(pages):
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        + "".join(pages)
        + "</body></html>"
    )


def body_lines(count, *, top=100.0, leading=12.0, left=100.0, right=400.0, short_last=False):
    """A column of full lines, optionally ending in a short one."""
    lines = []
    for index in range(count):
        width = right
        if short_last and index == count - 1:
            width = left + 80.0
        lines.append((left, top + index * leading, width, top + index * leading + 9.0, "l"))
    return lines


def measure_xml(xml: str) -> DocumentLayout:
    """Measure a hand-written box layout, bypassing pdftotext.

    The target file still has to exist: ``measure_layout`` refuses a missing PDF
    before it ever looks at boxes, and that check is worth keeping honest in the
    tests rather than working around.
    """
    from latex_automation import layout as layout_module

    with TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        original = layout_module.extract_boxes
        layout_module.extract_boxes = lambda target, pdftotext=None: (xml, "")
        try:
            return layout_module.measure_layout(pdf)
        finally:
            layout_module.extract_boxes = original


class MeasureEdgeTests(unittest.TestCase):
    def test_modal_line_end_is_the_measure(self):
        layout = DocumentLayout(pdf="x")
        layout.pages = [
            PageLayout(index=1, width=612, height=792, lines=[
                LayoutLine(1, 100, 100, 400, 109),
                LayoutLine(1, 100, 112, 400, 121),
                LayoutLine(1, 100, 124, 180, 133),  # short final line
            ])
        ]
        self.assertAlmostEqual(_measure_edge(layout), 400.0, places=1)

    def test_single_line_page_has_no_measurable_edge(self):
        # One line cannot corroborate itself; guessing would make the reference
        # equal to the very line that might be the defect.
        layout = DocumentLayout(pdf="x")
        layout.pages = [
            PageLayout(index=1, width=612, height=792, lines=[
                LayoutLine(1, 100, 100, 560, 109),
            ])
        ]
        self.assertIsNone(_measure_edge(layout))

    def test_overflowing_line_does_not_become_the_reference(self):
        # Two full lines agree at 400; the third runs to 520.  A median of page
        # maxima would return 400 here but a single-line page would not.
        layout = DocumentLayout(pdf="x")
        layout.pages = [
            PageLayout(index=1, width=612, height=792, lines=[
                LayoutLine(1, 100, 100, 400, 109),
                LayoutLine(1, 100, 112, 400, 121),
                LayoutLine(1, 100, 124, 520, 133),
            ])
        ]
        self.assertAlmostEqual(_measure_edge(layout), 400.0, places=1)


class RobustLeadingTests(unittest.TestCase):
    def test_hole_does_not_inflate_the_estimate(self):
        # Four normal gaps and one enormous float hole.  A plain median of five
        # values lands on the hole when the page is short.
        deltas = [12.0, 12.0, 12.0, 12.0, 430.0]
        self.assertAlmostEqual(_robust_leading(deltas), 12.0, places=1)

    def test_all_equal_gaps(self):
        self.assertAlmostEqual(_robust_leading([12.0] * 10), 12.0, places=1)

    def test_too_few_samples_falls_back_to_the_smallest(self):
        self.assertAlmostEqual(_robust_leading([12.0, 400.0]), 12.0, places=1)

    def test_empty(self):
        self.assertIsNone(_robust_leading([]))


class FurnitureTests(unittest.TestCase):
    def test_page_number_is_split_off_as_footer(self):
        page = PageLayout(index=1, width=595, height=842, lines=[
            LayoutLine(1, 100, 100, 400, 109),
            LayoutLine(1, 100, 112, 400, 121),
            LayoutLine(1, 300, 695, 305, 704, "1"),
        ])
        _split_furniture(page, 48.0)
        self.assertEqual(len(page.footer), 1)
        self.assertEqual(page.footer[0].text, "1")
        self.assertEqual(len(page.body_lines), 2)

    def test_mid_body_text_after_a_gap_is_not_furniture(self):
        # The gap is real text displacement, not a footer: the following line is
        # body text sitting mid-page, so it must stay in the body and let the
        # hole detector see it.
        page = PageLayout(index=1, width=595, height=842, lines=[
            LayoutLine(1, 100, 100, 400, 109),
            LayoutLine(1, 100, 500, 400, 509, "after the gap"),
        ])
        _split_furniture(page, 48.0)
        self.assertEqual(page.footer, [])
        self.assertEqual(len(page.body_lines), 2)


class OverflowTests(unittest.TestCase):
    def test_overflow_past_paper_edge_is_certain(self):
        xml = document_xml([page_xml(1, 612, 792, [
            (100, 100, 400, 109, "a"),
            (100, 112, 400, 121, "b"),
            (100, 124, 620, 133, "too far"),
        ])])
        measured = measure_xml(xml)
        kinds = [issue.kind for issue in measured.issues]
        self.assertIn("overflow-edge", kinds)
        edge = [i for i in measured.issues if i.kind == "overflow-edge"][0]
        self.assertEqual(edge.severity, "error")
        self.assertEqual(measured.overflow_pages, [1])

    def test_overflow_past_margin_but_on_paper_is_layout(self):
        # 480 is inside the 612pt paper but 80pt past the 400pt measure, so this
        # is a bad box, not a catastrophe: severity "layout", not "error".
        xml = document_xml([page_xml(1, 612, 792, [
            (100, 100, 400, 109, "a"),
            (100, 112, 400, 121, "b"),
            (100, 124, 480, 133, "past the margin"),
        ])])
        measured = measure_xml(xml)
        margin = [i for i in measured.issues if i.kind == "overflow-margin"]
        self.assertEqual(len(margin), 1)
        self.assertEqual(margin[0].severity, "layout")
        self.assertIn("80.0pt past", margin[0].detail)

    def test_conforming_page_has_no_issues(self):
        xml = document_xml([page_xml(1, 612, 792, body_lines(10, short_last=True))])
        measured = measure_xml(xml)
        self.assertEqual(measured.issues, [])
        self.assertEqual(measured.measure_source, "geometry")


class HoleTests(unittest.TestCase):
    def test_float_gap_is_reported(self):
        lines = [
            (100, 100, 400, 109, "before"),
            (100, 112, 400, 121, "before"),
            (100, 550, 400, 559, "after"),
            (100, 562, 400, 571, "after"),
        ]
        measured = measure_xml(document_xml([page_xml(1, 612, 792, lines)]))
        holes = [i for i in measured.issues if i.kind == "hole"]
        self.assertEqual(len(holes), 1)
        self.assertEqual(holes[0].severity, "layout")
        # 438pt across a 12pt leading is 36.5x; the ratio is what makes the
        # message actionable, so pin it rather than the raw points.
        self.assertIn("36.5x", holes[0].detail)

    def test_section_spacing_is_not_a_hole(self):
        # A 2.5x gap before a heading is ordinary typography; only a gap above
        # the 4x factor is worth reporting.
        lines = [
            (100, 100, 400, 109, "before"),
            (100, 112, 400, 121, "before"),
            (100, 142, 200, 151, "heading"),
            (100, 154, 400, 163, "after"),
        ]
        measured = measure_xml(document_xml([page_xml(1, 612, 792, lines)]))
        self.assertEqual([i for i in measured.issues if i.kind == "hole"], [])


class WidowOrphanTests(unittest.TestCase):
    def test_unindented_short_line_at_page_top_is_a_widow(self):
        page_one = page_xml(1, 612, 792, body_lines(20, short_last=True))
        # Page two opens short and flush left: the paragraph's tail.
        page_two = page_xml(2, 612, 792, [
            (100, 100, 180, 109, "tail"),
            (100, 112, 400, 121, "next paragraph"),
            (100, 124, 400, 133, "more"),
        ] + body_lines(10)[3:])
        measured = measure_xml(document_xml([page_one, page_two]))
        widows = [i for i in measured.issues if i.kind == "widow-orphan" and i.page == 2]
        self.assertEqual(len(widows), 1)
        self.assertIn("widow", widows[0].detail)

    def test_indented_line_at_page_top_is_a_new_paragraph(self):
        page_one = page_xml(1, 612, 792, body_lines(20, short_last=True))
        page_two = page_xml(2, 612, 792, [
            (115, 100, 400, 109, "indented new paragraph"),
            (100, 112, 400, 121, "continues"),
            (100, 124, 400, 133, "more"),
        ] + body_lines(10)[3:])
        measured = measure_xml(document_xml([page_one, page_two]))
        self.assertEqual(
            [i for i in measured.issues if i.kind == "widow-orphan" and i.page == 2], []
        )


class VerdictTests(unittest.TestCase):
    def test_page_verdicts_use_markers(self):
        layout = DocumentLayout(pdf="x")
        page = PageLayout(index=1, width=612, height=792, lines=body_lines(3))
        page.issues.append(LayoutIssue("overflow-edge", 1, "error", "certain", 0.99))
        page.issues.append(LayoutIssue("widow-orphan", 1, "warning", "maybe", 0.5))
        layout.pages = [page]
        lines = page_verdicts(layout)
        self.assertIn("2 issue(s)", lines[0])
        self.assertTrue(any(line.startswith("  ! ") for line in lines))
        self.assertTrue(any(line.startswith("  ? ") for line in lines))

    def test_summary_mentions_unmeasurable_margin(self):
        layout = DocumentLayout(pdf="x", measure_source="unknown")
        layout.pages = [PageLayout(index=1, width=612, height=792, lines=body_lines(3))]
        self.assertIn("right margin not measurable", layout.summary())


if __name__ == "__main__":
    unittest.main()
