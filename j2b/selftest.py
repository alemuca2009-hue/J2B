"""Startup self-check for the frozen build.

A windowed executable has no stdout, so the usual "run it and look at the
console" verification does not work — and a GUI that fails to import tkinter
just vanishes. This prints what it can and, more importantly, exits non-zero
when something the packaged build depends on is missing, which is what a CI
runner can actually check.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _report(name: str, ok: bool, detail: str = "") -> bool:
    line = f"{'ok  ' if ok else 'FAIL'} {name}"
    if detail:
        line += f": {detail}"
    try:
        print(line)
    except Exception:  # no console attached; the exit code is the real signal
        pass
    return ok


def run() -> int:
    results: list[bool] = []

    results.append(_report("python", True, sys.version.split()[0]))

    try:
        from .version import __version__

        results.append(_report("version", bool(__version__), __version__))
    except Exception as error:  # pragma: no cover - packaging failure
        results.append(_report("version", False, repr(error)))

    try:
        import tkinter

        results.append(_report("tkinter", True, str(tkinter.TkVersion)))
    except Exception as error:
        results.append(_report("tkinter", False, repr(error)))

    try:
        from .knowledge import base

        path = Path(base.__file__).with_name("data") / "entries.jsonl"
        count = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
        results.append(_report("knowledge base", count > 0, f"{count} entries at {path}"))
    except Exception as error:
        results.append(_report("knowledge base", False, repr(error)))

    try:
        from .id_map import official_tiles

        tiles = official_tiles()
        results.append(_report("vanilla atlas", len(tiles) > 1000, f"{len(tiles)} tiles"))
    except Exception as error:
        results.append(_report("vanilla atlas", False, repr(error)))

    try:
        from .gui import launch  # noqa: F401  (import only: do not open a window)

        results.append(_report("gui module", True))
    except Exception as error:
        results.append(_report("gui module", False, repr(error)))

    return 0 if all(results) else 1
