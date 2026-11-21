"""Process execution helpers with Windows/CP936-safe decoding.

Every subprocess in this toolkit goes through here so that:

* argv is always an array (never a shell string),
* output is decoded with the caller's preferred encoding and never raises,
* a timeout kills the whole process tree instead of leaking a child,
* the two ``Initial Win CP ...`` noise lines printed by TeX Live's runscript
  wrapper are dropped before anyone tries to parse the text.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

RUNSCRIPT_NOISE = re.compile(
    r"^(Initial Win CP for \(console input, console output, system\)|"
    r"I changed them all to )"
)

#: Encodings tried in order when decoding captured bytes.
DECODE_CHAIN = ("utf-8", "cp936", "cp1252", "latin-1")


@dataclass
class Result:
    """Outcome of one external command."""

    command: list[str]
    cwd: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    started: float = 0.0

    @property
    def combined(self) -> str:
        if not self.stderr:
            return self.stdout
        if not self.stdout:
            return self.stderr
        return f"{self.stdout}\n{self.stderr}"

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "stdout_bytes": len(self.stdout.encode("utf-8", "replace")),
            "stderr_bytes": len(self.stderr.encode("utf-8", "replace")),
        }


def decode(raw: bytes, encodings: Sequence[str] = DECODE_CHAIN) -> str:
    """Decode captured bytes without ever raising.

    TeX tools on a localized Windows console mix UTF-8 and CP936 in a single
    stream, so a strict single-pass decode fails on real logs. Try each
    encoding strictly, then fall back to a lossy decode.
    """
    if not raw:
        return ""
    for name in encodings:
        try:
            return raw.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode(encodings[0] if encodings else "utf-8", "replace")


def strip_noise(text: str) -> str:
    """Drop TeX Live runscript banner lines and stray NULs."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    lines = [ln for ln in text.splitlines() if not RUNSCRIPT_NOISE.match(ln)]
    return "\n".join(lines)


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run(
    command: Sequence[str],
    cwd: str | Path,
    timeout: float = 180.0,
    env: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> Result:
    """Run one command, capturing decoded stdout/stderr.

    ``extra`` is merged into the inherited environment; it is the usual way to
    raise ``max_print_line`` or prepend a TeX bin directory to ``PATH``.
    """
    argv = [str(part) for part in command]
    workdir = Path(cwd)
    environ = dict(os.environ)
    if extra:
        environ.update({k: str(v) for k, v in extra.items()})
    if env:
        environ.update({k: str(v) for k, v in env.items()})
    environ.setdefault("max_print_line", "10000")
    environ.setdefault("PYTHONIOENCODING", "utf-8")

    started = time.time()
    popen_kwargs: dict = {
        "cwd": str(workdir),
        "env": environ,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(argv, **popen_kwargs)
    except FileNotFoundError:
        return Result(
            command=argv,
            cwd=str(workdir),
            returncode=127,
            stdout="",
            stderr=f"executable not found: {argv[0]}",
            duration_ms=int((time.time() - started) * 1000),
            started=started,
        )
    except OSError as exc:
        return Result(
            command=argv,
            cwd=str(workdir),
            returncode=126,
            stdout="",
            stderr=f"cannot execute {argv[0]}: {exc}",
            duration_ms=int((time.time() - started) * 1000),
            started=started,
        )

    timed_out = False
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out_b, err_b = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            out_b, err_b = b"", b""

    return Result(
        command=argv,
        cwd=str(workdir),
        returncode=proc.returncode,
        stdout=strip_noise(decode(out_b or b"")),
        stderr=strip_noise(decode(err_b or b"")),
        duration_ms=int((time.time() - started) * 1000),
        timed_out=timed_out,
        started=started,
    )


def which(name: str, extra_dirs: Iterable[str] = ()) -> str | None:
    """Locate an executable on PATH or in one of ``extra_dirs``."""
    for directory in extra_dirs:
        if not directory:
            continue
        for candidate in (name, f"{name}.exe", f"{name}.bat", f"{name}.cmd"):
            path = Path(directory) / candidate
            if path.is_file():
                return str(path)
    found = shutil.which(name)
    return found


def probe_version(executable: str, args: Sequence[str] = ("--version",), timeout: float = 20.0) -> str:
    """First non-empty output line of ``executable args``, or empty string."""
    if not executable:
        return ""
    result = run([executable, *args], cwd=Path.cwd(), timeout=timeout)
    for line in result.combined.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def argv_display(command: Sequence[str]) -> str:
    """Render an argv array for humans, quoting only when needed."""
    parts = []
    for part in command:
        if not part or any(ch in part for ch in ' "\t'):
            parts.append('"' + part.replace('"', '\\"') + '"')
        else:
            parts.append(part)
    return " ".join(parts)


def is_windows() -> bool:
    return os.name == "nt"


def python_exe() -> str:
    return sys.executable or "python"
