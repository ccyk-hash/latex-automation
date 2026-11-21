#!/usr/bin/env python3
"""Engine detection: the rules that decide pdflatex vs xelatex vs lualatex.

The interesting cases are the ones that look plain but are not: raw CJK in the
body (pdfTeX has no glyphs), CJK only inside a comment (never reaches the engine),
and the legacy CJKutf8 setup that is a deliberate pdfLaTeX choice.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from latex_automation.engine import detect_engine, non_utf8_sources, strip_comments


def detect(body: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "main.tex"
        source.write_bytes(body.encode("utf-8"))
        return detect_engine(source)


class StripCommentsTest(unittest.TestCase):
    def test_removes_a_trailing_comment(self) -> None:
        self.assertEqual(strip_comments(r"\alpha % 中文"), r"\alpha ")

    def test_keeps_an_escaped_percent(self) -> None:
        self.assertEqual(strip_comments(r"50\% 中文"), r"50\% 中文")

    def test_comment_after_an_escaped_percent_still_ends_the_line(self) -> None:
        # `\\%` is a line break followed by a comment, and TeX stops there.
        self.assertEqual(strip_comments("a\\\\% 中文"), "a\\\\")

    def test_a_percent_becomes_a_comment_again_after_an_escape(self) -> None:
        self.assertEqual(strip_comments(r"a\%b % 中文"), r"a\%b ")


class DetectEngineTest(unittest.TestCase):
    def test_ctex_selects_xelatex(self) -> None:
        engine, reason = detect("\\documentclass{ctexart}\n\\begin{document}x\\end{document}\n")
        self.assertEqual(engine, "xelatex")
        self.assertIn("ctex", reason)

    def test_fontspec_selects_xelatex(self) -> None:
        engine, _ = detect("\\documentclass{article}\n\\usepackage{fontspec}\n")
        self.assertEqual(engine, "xelatex")

    def test_raw_cjk_in_the_body_selects_xelatex(self) -> None:
        engine, reason = detect(
            "\\documentclass{article}\n\\begin{document}\n中文标注\n\\end{document}\n"
        )
        self.assertEqual(engine, "xelatex")
        self.assertIn("CJK", reason)

    def test_cjk_only_in_a_comment_stays_pdflatex(self) -> None:
        engine, _ = detect(
            "\\documentclass{article}\n% 这是一段中文注释\n\\begin{document}\nplain\n\\end{document}\n"
        )
        self.assertEqual(engine, "pdflatex")

    def test_legacy_cjk_package_stays_pdflatex(self) -> None:
        engine, _ = detect(
            "\\documentclass{article}\n\\usepackage{CJKutf8}\n"
            "\\begin{document}\n\\begin{CJK}{UTF8}{gbsn}中文\\end{CJK}\n\\end{document}\n"
        )
        self.assertEqual(engine, "pdflatex")

    def test_plain_document_stays_pdflatex(self) -> None:
        engine, reason = detect("\\documentclass{article}\n\\begin{document}hi\\end{document}\n")
        self.assertEqual(engine, "pdflatex")
        self.assertIn("default", reason)

    def test_japanese_kana_also_selects_xelatex(self) -> None:
        engine, _ = detect(
            "\\documentclass{article}\n\\begin{document}\nひらがな\n\\end{document}\n"
        )
        self.assertEqual(engine, "xelatex")


class NonUtf8SourcesTest(unittest.TestCase):
    """The preflight that stops a Unicode engine from typesetting mojibake."""

    def test_flags_a_gbk_master(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_bytes("\\documentclass{article}\n中文\n".encode("cp936"))
            self.assertEqual(non_utf8_sources(root, source), ["main.tex"])

    def test_accepts_a_utf8_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_bytes("\\documentclass{article}\n中文\n".encode("utf-8"))
            (root / "chapter.tex").write_bytes("章节\n".encode("utf-8"))
            self.assertEqual(non_utf8_sources(root, source), [])

    def test_flags_an_included_file_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_bytes(b"\\documentclass{article}\n")
            (root / "gbk.tex").write_bytes("章节\n".encode("gbk"))
            self.assertEqual(non_utf8_sources(root, source), ["gbk.tex"])

    def test_ignores_non_tex_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_bytes(b"\\documentclass{article}\n")
            (root / "notes.txt").write_bytes("章节\n".encode("gbk"))
            self.assertEqual(non_utf8_sources(root, source), [])


if __name__ == "__main__":
    unittest.main()
