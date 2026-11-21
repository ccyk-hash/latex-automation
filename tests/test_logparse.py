"""Log parsing tests that do not need a TeX installation.

The fixtures are trimmed real logs captured on this machine, so the parser is
tested against what the engines actually print rather than against ideals.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from latex_automation.logparse import (  # noqa: E402
    Diagnostic,
    LogReport,
    attribute_missing_locations,
    compress_log,
    merge_reports,
    parse_biber_log,
    parse_bibtex_log,
    parse_engine_log,
)

ROOT = Path("D:/proj").resolve()

CASCADE_LOG = r"""
This is pdfTeX, Version 3.141592653-2.6-1.40.28 (TeX Live 2026)
entering extended mode
(./broken.tex
LaTeX2e <2025-11-01> patch level 1
(/d/Latex/texlive/2026/texmf-dist/tex/latex/base/article.cls
Document Class: article 2025/01/01 v1.4n Standard LaTeX document class
(/d/Latex/texlive/2026/texmf-dist/tex/latex/base/size10.clo))
(./broken.aux)
./broken.tex:4: Undefined control sequence.
l.4 \badcommandA

./broken.tex:5: Undefined control sequence.
l.5 \badcommandB

! File ended while scanning use of \frac .
<inserted text>
                \par
<*> broken.tex

?
! Emergency stop.
<*> broken.tex

No pages of output.
Transcript written on broken.log.
"""

MISSING_PACKAGE_LOG = r"""
entering extended mode
(./misspkg.tex
(/d/Latex/texlive/2026/texmf-dist/tex/latex/base/article.cls
Document Class: article 2025/01/01 v1.4n Standard LaTeX document class
(/d/Latex/texlive/2026/texmf-dist/tex/latex/base/size10.clo))

! LaTeX Error: File `nonexistentpkgxyz.sty' not found.

Type X to quit or <RETURN> to proceed,
or enter new name. (Default extension: sty)

Enter file name:
./misspkg.tex:3: Emergency stop.
<read *>

l.3 \usepackage
               {nonexistentpkgxyz}
?
!  ==> Fatal error occurred, no output PDF file produced!
"""

SUCCESS_LOG = r"""
(./main.tex
LaTeX2e <2025-11-01>
(./main.aux)
LaTeX Warning: Reference `sec:intro' on page 1 undefined on input line 12.

Overfull \hbox (12.34567pt too wide) in paragraph at lines 20--22
[]\OT1/cmr/m/n/10 This line is far too long for the page and sticks out.
Missing character: There is no 中 in font [lmroman10-regular]!
[1] (./main.aux)
Output written on main.pdf (1 page, 82517 bytes).
Transcript written on main.log.
"""

BIBER_LOG = """
INFO - This is Biber 2.21
INFO - Reading 'main.bcf'
WARN - I didn't find a database entry for 'ghost2020'
ERROR - Cannot find 'refs.bib'!
INFO - Wrapping up.
"""

BIBTEX_LOG = """
This is BibTeX, Version 0.99d
The top-level auxiliary file: main.aux
I couldn't open database file refs.bib
---line 3 of file main.aux
 : \\bibdata{refs
 :               }
I'm skipping whatever remains of this command
Warning--I didn't find a database entry for "ghost2020"
(There was 1 error message)
"""


class TestEngineLog(unittest.TestCase):
    def test_cascade_collects_all_and_folds_consequences(self):
        report = parse_engine_log(CASCADE_LOG, ROOT)
        self.assertFalse(report.success)
        self.assertEqual(len(report.errors), 3, [e.message for e in report.errors])
        # Emergency stop and Fatal error are consequences, not causes.
        self.assertEqual(report.suppressed, 2)

    def test_root_cause_is_first_source_error(self):
        report = parse_engine_log(CASCADE_LOG, ROOT)
        self.assertIsNotNone(report.root_cause)
        self.assertEqual(report.root_cause.file, "broken.tex")
        self.assertEqual(report.root_cause.line, 4)
        self.assertEqual(report.root_cause.category, "undefined_macro")

    def test_missing_package_is_detected_and_attributed(self):
        report = parse_engine_log(MISSING_PACKAGE_LOG, ROOT)
        self.assertFalse(report.success)
        self.assertEqual(report.root_cause.category, "missing_package")
        self.assertIn("nonexistentpkgxyz.sty", report.missing_packages)
        # The location must point at the author's file, not at size10.clo.
        self.assertEqual(report.root_cause.file, "misspkg.tex")
        self.assertEqual(report.root_cause.line, 3)

    def test_success_log(self):
        report = parse_engine_log(SUCCESS_LOG, ROOT)
        self.assertTrue(report.success)
        self.assertEqual(report.pages, 1)
        self.assertEqual(report.pdf_bytes, 82517)
        self.assertEqual(report.undefined_refs, ["sec:intro"])
        self.assertEqual(len(report.layout), 1)
        self.assertEqual(report.layout[0].line, 20)
        self.assertEqual(len(report.missing_chars), 1)
        self.assertIn("中", report.missing_chars[0].message)

    def test_attribute_missing_locations(self):
        # TeX pops the file stack before reporting some failures, so an
        # error can arrive with no file at all. Simulate that shape.
        report = LogReport()
        report.errors.append(
            Diagnostic(
                severity="error",
                message="File ended while scanning use of \\frac .",
                file="",
                line=None,
                category="unbalanced_argument",
            )
        )
        orphan = [d for d in report.errors if not d.file]
        self.assertTrue(orphan)
        attribute_missing_locations(report, "broken.tex")
        self.assertTrue(all(d.file for d in report.errors))
        self.assertEqual(report.errors[0].file, "broken.tex")

    def test_compress_log_keeps_relevant_context(self):
        excerpt = compress_log(SUCCESS_LOG, keep_context=1)
        self.assertIn("Output written on main.pdf", excerpt)
        self.assertIn("Missing character", excerpt)
        self.assertLess(len(excerpt.splitlines()), len(SUCCESS_LOG.splitlines()))


GBK_LOG = r"""
This is pdfTeX, Version 3.141592653-2.6-1.40.28 (TeX Live 2026)
entering extended mode
(./main.tex
LaTeX2e <2025-11-01> patch level 1
! LaTeX Error: Invalid UTF-8 byte sequence (\xd6\xd0).

See the LaTeX manual or LaTeX Companion for explanation.
Type  H <return>  for immediate help.
 ...

l.4 \xd6\xd0\xce\xc4

)
No pages of output.
"""


class TestEncoding(unittest.TestCase):
    def test_gbk_bytes_are_an_encoding_fault(self):
        # pdfTeX reports the offending bytes, not a character, so wording differs
        # from the Unicode case; both are encoding, not generic.
        report = parse_engine_log(GBK_LOG, ROOT, "engine")
        self.assertFalse(report.success)
        self.assertTrue(report.errors)
        self.assertEqual(report.errors[0].category, "encoding")


class TestBibLogs(unittest.TestCase):
    def test_biber_error(self):
        report = parse_biber_log(BIBER_LOG, ROOT)
        self.assertFalse(report.success)
        self.assertEqual(report.root_cause.tool, "biber")
        self.assertIn("refs.bib", report.missing_files)
        self.assertTrue(any("ghost2020" in w.message for w in report.warnings))

    def test_bibtex_missing_database(self):
        report = parse_bibtex_log(BIBTEX_LOG, ROOT)
        self.assertFalse(report.success)
        self.assertEqual(report.root_cause.category, "missing_bib")


class TestMerge(unittest.TestCase):
    def test_no_pdf_means_failure(self):
        engine = parse_engine_log(CASCADE_LOG, ROOT)
        merged = merge_reports([engine])
        self.assertFalse(merged.success)
        self.assertFalse(merged.ok)

    def test_success_merge_keeps_pages(self):
        engine = parse_engine_log(SUCCESS_LOG, ROOT)
        merged = merge_reports([engine])
        self.assertTrue(merged.success)
        self.assertEqual(merged.pages, 1)


if __name__ == "__main__":
    unittest.main()
