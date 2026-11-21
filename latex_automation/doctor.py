"""Environment self-check: what this machine can and cannot do with LaTeX."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import packages
from .engine import ENGINES, discover_toolchain, find_master, detect_engine, detect_backend
from .paths import has_cjk, read_text, risky_absolute_outdir
from .proc import probe_version, run

REQUIRED = ("latexmk", "pdflatex", "xelatex")
RECOMMENDED = ("biber", "bibtex", "kpsewhich", "pdftoppm", "pdfinfo", "chktex", "latexindent")
OPTIONAL = ("lualatex", "dvisvgm", "pdftotext", "latexdiff", "lacheck")


@dataclass
class CheckItem:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""
    hint: str = ""

    def as_dict(self) -> dict:
        data = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.hint:
            data["hint"] = self.hint
        return data


@dataclass
class DoctorReport:
    items: list[CheckItem] = field(default_factory=list)
    toolchain: dict = field(default_factory=dict)
    version: dict = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str = "", hint: str = "") -> None:
        self.items.append(CheckItem(name=name, status=status, detail=detail, hint=hint))

    @property
    def ok(self) -> bool:
        return not any(item.status == "fail" for item in self.items)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "counts": {
                status: sum(1 for item in self.items if item.status == status)
                for status in ("ok", "warn", "fail", "skip")
            },
            "items": [item.as_dict() for item in self.items],
            "toolchain": self.toolchain,
            "version": self.version,
        }

    def summary(self) -> str:
        counts = {status: 0 for status in ("ok", "warn", "fail", "skip")}
        for item in self.items:
            counts[item.status] += 1
        head = "ready" if self.ok else "not ready"
        return (
            f"environment {head}: {counts['ok']} ok, {counts['warn']} warn, "
            f"{counts['fail']} fail, {counts['skip']} skip"
        )


def check_environment(project: Path | None = None) -> DoctorReport:
    report = DoctorReport()
    chain = discover_toolchain()
    report.toolchain = chain.as_dict()
    report.version["python"] = sys.version.split()[0]
    report.version["platform"] = sys.platform

    missing_required = [name for name in REQUIRED if not _tool_path(chain, name)]
    found_required = [name for name in REQUIRED if _tool_path(chain, name)]
    if missing_required:
        report.add(
            "engines",
            "fail",
            f"missing: {', '.join(missing_required)} (found: {', '.join(found_required) or 'none'})",
            hint="install a TeX distribution and put its bin directory on PATH",
        )
    else:
        report.add("engines", "ok", "latexmk + pdflatex + xelatex present")

    for name in ("pdflatex", "xelatex", "lualatex", "latexmk", "biber", "bibtex"):
        path = getattr(chain, name, None) or chain.engines.get(name)
        if path:
            version = probe_version(path, ("--version",), timeout=25)
            report.version[name] = version
            if not version:
                report.add(name, "warn", f"found at {path} but --version produced no output")
        elif name in ("biber", "bibtex", "lualatex"):
            report.add(name, "warn", "not found", hint="bibliography or Lua builds will be unavailable")

    if chain.latexmk:
        if chain.perl:
            report.add("perl", "ok", chain.perl)
        else:
            report.add(
                "perl",
                "ok",
                "latexmk will use its bundled interpreter",
                hint="a system perl is optional on TeX Live",
            )

    for name in RECOMMENDED:
        path = getattr(chain, name, None)
        if path:
            version = probe_version(path, ("--version",), timeout=20)
            if version:
                report.version[name] = version
            report.add(name, "ok", path)
        else:
            report.add(name, "warn", "not found", hint=_hint_for(name))

    for name in OPTIONAL:
        path = _tool_path(chain, name)
        if path:
            report.add(name, "ok", path)

    tl = packages.index_stats()
    if tl.get("available"):
        report.add(
            "tlpdb",
            "ok",
            f"{tl['entries']} filename entries from {tl['path']}",
            hint="offline package resolution works without the network",
        )
    else:
        report.add(
            "tlpdb",
            "warn",
            "texlive.tlpdb not found",
            hint="missing-package diagnosis will fall back to kpsewhich only",
        )

    # Network-free tlmgr check: this machine cannot reach a mirror, and tlmgr
    # exits 0 even when it fails, so it must not be trusted as a probe.
    report.add(
        "tlmgr-offline",
        "ok",
        "not used by this toolkit",
        hint="tlmgr search/info need the network on this machine; the toolkit resolves "
             "packages from texlive.tlpdb instead",
    )

    if project is not None and project.is_dir():
        _check_project(report, project, chain)
    return report


def _tool_path(chain, name: str) -> str | None:
    """Resolve a tool path from either the flat fields or the engines map."""
    return getattr(chain, name, None) or chain.engines.get(name)


def _hint_for(name: str) -> str:
    return {
        "biber": "biblatex with backend=biber will not build",
        "bibtex": "classic bibliography builds will not work",
        "kpsewhich": "package lookups and missing-file diagnosis degrade",
        "pdftoppm": "page rendering and visual checks need poppler",
        "pdfinfo": "PDF page counts will be read from the log instead",
        "chktex": "static style checking is unavailable",
        "latexindent": "source formatting is unavailable",
    }.get(name, "")


def _check_project(report: DoctorReport, project: Path, chain) -> None:
    masters = [p for p in project.glob("*.tex") if "\\documentclass" in read_text(p, 200_000)]
    if not masters:
        report.add("project", "warn", f"no master .tex with \\documentclass under {project}")
        return
    master = find_master(project)
    engine, reason = detect_engine(master)
    backend = detect_backend(master)
    report.add("master", "ok", f"{master.name} -> {engine} ({reason}), backend={backend or 'none'}")

    project_text = str(project.resolve())
    if has_cjk(project_text):
        if risky_absolute_outdir(project.resolve() / "latex-out"):
            report.add(
                "cjk-outdir",
                "warn",
                "project path contains CJK text next to a space",
                hint="the toolkit writes to a relative output directory, so builds still work; "
                     "never pass an absolute -output-directory by hand here",
            )
        else:
            report.add("cjk-outdir", "ok", "CJK path with a safe layout")

    if engine == "xelatex" and not chain.engines.get("xelatex"):
        report.add("engine-available", "fail", "document needs XeLaTeX but xelatex is missing")


def print_doctor(report: DoctorReport, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        return 0 if report.ok else 1
    print(report.summary())
    for item in report.items:
        marker = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[fail]", "skip": "[skip]"}[item.status]
        line = f"{marker} {item.name}"
        if item.detail:
            line += f": {item.detail}"
        print(line)
        if item.hint and item.status in ("warn", "fail"):
            print(f"       -> {item.hint}")
    return 0 if report.ok else 1
