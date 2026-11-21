"""Offline resolution of package / file names to TeX Live packages.

``tlmgr search`` and ``tlmgr info`` require the network; on this machine they
fail with

    TLPDB::from_file could not get texlive.tlpdb from:
    https://mirror.ctan.org/systems/texlive/tlnet/tlpkg/texlive.tlpdb

and still exit 0, so they cannot even be used as a boolean.  TeX Live ships the
same database locally at ``<TEXDIR>/tlpkg/texlive.tlpdb``; scanning it builds a
filename → package index in about 0.09 s for ~14k keys.  That index answers the
only question the skill needs: *which package provides `foo.sty`?*
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .proc import run, which

INDEXABLE_SUFFIXES = (".sty", ".cls", ".def", ".fd", ".clo", ".cfg")

_TLPDB_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


@dataclass
class PackageHit:
    filename: str
    package: str | None
    installed_path: str | None
    suggestion: str | None

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "package": self.package,
            "installed_path": self.installed_path,
            "suggestion": self.suggestion,
            "installed": self.installed_path is not None,
        }


def texdir_from_kpsewhich(kpsewhich: str | None = None) -> Path | None:
    """Derive the TeX Live root from ``kpsewhich``'s location."""
    exe = kpsewhich or which("kpsewhich")
    if not exe:
        return None
    path = Path(exe).resolve()
    # .../texlive/2026/bin/windows/kpsewhich.exe -> .../texlive/2026
    for parent in path.parents:
        if (parent / "tlpkg" / "texlive.tlpdb").is_file():
            return parent
    return None


def tlpdb_path() -> Path | None:
    """Locate ``texlive.tlpdb`` without hardcoding a TeX version."""
    candidates: list[Path] = []
    for env_name in ("TEXDIR", "TEXMFDIST", "TEXMFROOT"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value) / "tlpkg" / "texlive.tlpdb")
    root = texdir_from_kpsewhich()
    if root:
        candidates.append(root / "tlpkg" / "texlive.tlpdb")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_index(db_path: Path | None = None) -> dict[str, str]:
    """Map bare filename → TeX Live package name.

    The database is CRLF-formatted; ``splitlines()`` handles that.  Package
    blocks start with ``name <pkg>`` and their file list is indented by one
    space.
    """
    path = db_path or tlpdb_path()
    if not path or not path.is_file():
        return {}
    stamp = path.stat().st_mtime
    key = str(path)
    cached = _TLPDB_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]

    index: dict[str, str] = {}
    package = None
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            if line.startswith("name "):
                package = line[5:].strip()
                continue
            if not package or not line.startswith(" "):
                continue
            entry = line.strip()
            if not entry.endswith(INDEXABLE_SUFFIXES):
                continue
            bare = entry.rsplit("/", 1)[-1]
            index.setdefault(bare, package)
    _TLPDB_CACHE[key] = (stamp, index)
    return index


def resolve(filename: str, kpsewhich: str | None = None) -> PackageHit:
    """Answer where ``filename`` lives and which package would provide it."""
    bare = filename.strip().strip("'\"").rsplit("/", 1)[-1]
    installed: str | None = None
    exe = kpsewhich or which("kpsewhich")
    if exe:
        result = run([exe, bare], cwd=Path.cwd(), timeout=30)
        first = next((ln.strip() for ln in result.stdout.splitlines() if ln.strip()), "")
        if result.returncode == 0 and first:
            installed = first
    if installed:
        return PackageHit(filename=bare, package=None, installed_path=installed, suggestion=None)

    index = build_index()
    package = index.get(bare)
    suggestion = f"tlmgr install {package}" if package else None
    return PackageHit(filename=bare, package=package, installed_path=None, suggestion=suggestion)


def resolve_many(names: list[str], kpsewhich: str | None = None) -> list[PackageHit]:
    seen: set[str] = set()
    hits: list[PackageHit] = []
    for name in names:
        bare = name.strip().strip("'\"").rsplit("/", 1)[-1]
        if not bare or bare in seen:
            continue
        seen.add(bare)
        hits.append(resolve(bare, kpsewhich=kpsewhich))
    return hits


def index_stats() -> dict:
    path = tlpdb_path()
    if not path:
        return {"available": False}
    index = build_index(path)
    return {
        "available": True,
        "path": str(path),
        "entries": len(index),
        "size_bytes": path.stat().st_size,
    }
