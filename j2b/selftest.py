"""Startup self-check for the frozen build.

A windowed executable has no stdout, so the usual "run it and look at the
console" verification does not work -- and a GUI that fails to import tkinter
just vanishes. This exits non-zero when something the packaged build depends on
is missing, which is what a CI runner can check without a console.

Because the exit code is only one bit, the check also writes a JSON report when
asked (``--j2b-selftest-report=PATH``). That turns "the process exited 0" into
"these five subsystems each reported ok on this machine", which is the evidence
worth keeping in a build log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _check(name: str, fn, required: bool = True) -> dict[str, object]:
    """Run one probe; a probe that raises is a failed probe, not a crash.

    ``required=False`` probes describe the environment rather than test it --
    "am I frozen?" is expected to be *no* when running from source, and must
    not turn the self-test red on a developer machine.
    """
    try:
        ok, detail = fn()
    except Exception as error:  # pragma: no cover - packaging failure path
        ok, detail = False, repr(error)
    if not required:
        ok = True
    line = f"{'ok  ' if ok else 'FAIL'} {name}"
    if detail:
        line += f": {detail}"
    try:
        print(line)
    except Exception:  # no console attached; the exit code is the real signal
        pass
    return {"name": name, "ok": bool(ok), "required": required, "detail": str(detail)}


def _python() -> tuple[bool, str]:
    return True, sys.version.split()[0]


def _frozen() -> tuple[bool, str]:
    return bool(getattr(sys, "frozen", False)), (
        str(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else "running from source"
    )


def _version() -> tuple[bool, str]:
    from .version import __version__

    return bool(__version__), __version__


def _tkinter() -> tuple[bool, str]:
    import tkinter

    return True, f"Tk {tkinter.TkVersion}"


def _knowledge() -> tuple[bool, str]:
    from .knowledge import base

    path = Path(base.__file__).with_name("data") / "entries.jsonl"
    count = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    return count > 0, f"{count} entries at {path}"


def _atlas() -> tuple[bool, str]:
    from .id_map import official_tiles

    tiles = official_tiles()
    return len(tiles) > 1000, f"{len(tiles)} tiles"


def _gui() -> tuple[bool, str]:
    from .gui import launch  # noqa: F401  (import only: do not open a window)

    return True, "imported"


def _conversion() -> tuple[bool, str]:
    """Convert the shipped fixture jar inside this process, start to finish.

    Every other probe here proves a module *imports*. This one proves the
    packaged build can do the job it exists for: read a jar, resolve models,
    textures and recipes, and write packs to disk. A frozen build that loses a
    data file -- or that cannot write outside its own bundle -- imports
    perfectly and still produces nothing, and no import probe would notice.

    It runs offline and inside a temporary directory, so it is safe to trigger
    from a user's machine with ``--j2b-selftest``.
    """
    import tempfile

    from .converter import Converter
    from .fixtures import build
    from .models import ConversionOptions

    with tempfile.TemporaryDirectory() as tmp:
        jar = build(Path(tmp) / "fixture.jar")
        out = Path(tmp) / "out"
        options = ConversionOptions(
            output_dir=str(out),
            make_mcaddon=True,
            # Leave no trace in the user's case memory or knowledge overlay.
            record_learning=False,
            report_formats=("json",),
        )
        result = Converter(options).convert(jar)
        converted = sum(1 for feature in result.features if feature.status == "converted")
        paths = result.packs
        if paths is None:
            return False, "conversion produced no pack paths"
        bundle = paths.mcaddon
        if bundle is None or not Path(bundle).is_file():
            return False, f"no .mcaddon was written under {out}"
        size = Path(bundle).stat().st_size
        if size < 2048:
            return False, f"the .mcaddon is {size} bytes -- the pack writer produced an empty zip"
        blocks = list((paths.bp / "blocks").glob("*.json"))
        if not blocks:
            return False, "the behavior pack has no block definitions"
        if converted < 3:
            return False, f"only {converted} features converted from the fixture jar"
        return True, f"{converted} converted, {len(blocks)} blocks, {size // 1024} KB bundle"


#: Probes in reporting order. Kept as data so the report and the exit code can
#: never disagree about what was checked. The second element marks a probe as
#: required; ``frozen`` is informational -- a source checkout is not frozen.
PROBES = (
    ("python", _python, True),
    ("frozen", _frozen, False),
    ("version", _version, True),
    ("tkinter", _tkinter, True),
    ("knowledge base", _knowledge, True),
    ("vanilla atlas", _atlas, True),
    ("gui module", _gui, True),
    ("conversion", _conversion, True),
)


def run(report_path: str | Path | None = None) -> int:
    """Run every probe. Returns 0 only if all required probes pass."""
    records = [_check(name, fn, required) for name, fn, required in PROBES]
    ok = all(record["ok"] for record in records)

    if report_path:
        try:
            payload = {
                "ok": ok,
                "python": sys.version.split()[0],
                "version": next(r["detail"] for r in records if r["name"] == "version"),
                "checks": records,
            }
            Path(report_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except Exception:
            # A report we cannot write is a failure to report, not a failed
            # self-test: the exit code still carries the verdict.
            pass

    return 0 if ok else 1


def _report_path_from_argv(argv: list[str]) -> str | None:
    for arg in argv:
        if arg.startswith("--j2b-selftest-report="):
            return arg.split("=", 1)[1]
    return None


if __name__ == "__main__":  # pragma: no cover - exercised by the CI build
    sys.exit(run(_report_path_from_argv(sys.argv[1:])))
