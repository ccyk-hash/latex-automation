"""The WorkBuddy deliverable is a header swap on shared code, so test the swap.

Two deliverables must not drift into two bodies: `tools/install_workbuddy.py`
composes the WorkBuddy SKILL.md from `workbuddy/frontmatter.yaml` plus the body
of the DSH `SKILL.md`. These tests pin that contract, and pin that the body
documents every subcommand the CLI actually defines.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import install_workbuddy as iw  # noqa: E402
from latex_automation.cli import build_parser  # noqa: E402


def subcommands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and "build" in choices:
            return set(choices)
    raise AssertionError("no subparsers found")


class SplitTest(unittest.TestCase):
    def test_body_starts_after_the_first_closed_block(self):
        header, body = iw.split_skill_md()
        self.assertTrue(header.startswith("---"))
        self.assertEqual(header.count("---"), 2)
        self.assertTrue(body.lstrip().startswith("# "))

    def test_body_keeps_the_document(self):
        _, body = iw.split_skill_md()
        self.assertGreater(body.count("\n"), 200)
        # A `---` further down must not be mistaken for a second frontmatter block.
        self.assertIn("## ", body)


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.text = iw.composed_skill_md()
        self.header, self.body = iw.split_skill_md()

    def test_composed_starts_with_the_workbuddy_header(self):
        frontmatter = iw.FRONTMATTER.read_text(encoding="utf-8")
        self.assertTrue(self.text.startswith(frontmatter.rstrip("\n")))

    def test_body_is_reused_verbatim(self):
        self.assertTrue(self.text.endswith(self.body))

    def test_name_matches_the_skill_directory(self):
        self.assertIn(f"name: {iw.SKILL_NAME}", self.text)

    def test_description_carries_trigger_words(self):
        front = self.text.split("---")[1]
        self.assertIn("description:", front)
        self.assertIn("LaTeX", front)
        self.assertIn("触发词", front)

    def test_workbuddy_header_declares_bash(self):
        front = self.text.split("---")[1]
        self.assertIn("allowed-tools:", front)
        self.assertIn("Bash", front)

    def test_composed_frontmatter_is_a_single_closed_block(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertIn("---", lines[1:])
        closing = lines.index("---", 1)
        # Everything before the closing marker is `key: value`, nothing else.
        for line in lines[1:closing]:
            self.assertFalse(line.startswith("#"), line)

    def test_every_subcommand_is_documented(self):
        for name in subcommands():
            self.assertIn(f"`{name}", self.body, f"{name} missing from the body")


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.payload = iw.files_to_write()

    def test_skill_md_is_composed_not_copied(self):
        self.assertIn("SKILL.md", self.payload)
        self.assertNotIn("workbuddy/frontmatter.yaml", self.payload)
        self.assertEqual(self.payload["SKILL.md"].decode("utf-8"), iw.composed_skill_md())

    def test_wrappers_are_included(self):
        wrappers = [k for k in self.payload if k.startswith("bin/")]
        self.assertEqual(len(wrappers), 11)

    def test_research_fixtures_are_left_out(self):
        self.assertFalse([k for k in self.payload if k.startswith("research/")])

    def test_payload_is_lf_only(self):
        crlf = [k for k, v in self.payload.items() if b"\r\n" in v]
        self.assertEqual(crlf, [])

    def test_payload_has_no_bytecode(self):
        self.assertFalse([k for k in self.payload if k.endswith(".pyc")])


class DryRunTest(unittest.TestCase):
    def test_dry_run_lists_and_exits_zero(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = iw.main(["--dry-run", "--target", str(ROOT / "build" / "dry")])
        self.assertEqual(code, 0)
        self.assertIn("SKILL.md", buffer.getvalue())

    def test_refuses_to_overwrite_without_force(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "placeholder.txt").write_text("x", encoding="utf-8")
            import contextlib
            import io

            with contextlib.redirect_stderr(io.StringIO()):
                code = iw.main(["--target", str(target)])
            self.assertEqual(code, 2)
            self.assertTrue((target / "placeholder.txt").is_file())


if __name__ == "__main__":
    unittest.main()
