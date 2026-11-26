"""Entry point for the frozen Windows executable.

A windowed build has no console, so it must not fall into the CLI: printing to
a stream that does not exist is how a frozen GUI app "does nothing" when you
double-click it. With no arguments the GUI starts; with arguments the CLI runs,
which is what a shortcut with a file dropped on it needs.
"""

from __future__ import annotations

import io
import sys


def _ensure_streams() -> None:
    """Give the process usable stdout/stderr when Windows froze it without a console."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if not kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    except Exception:
        # No console to attach to (or not Windows): a sink keeps print() from
        # raising. The exit code still carries the result.
        sys.stdout = sys.stdout or io.StringIO()
        sys.stderr = sys.stderr or io.StringIO()


def main() -> int:
    _ensure_streams()

    if "--j2b-selftest" in sys.argv:
        from j2b.selftest import _report_path_from_argv, run

        return run(_report_path_from_argv(sys.argv[1:]))

    if len(sys.argv) > 1:
        from j2b.cli import main as cli_main

        return cli_main()

    from j2b.gui import launch

    return launch()


if __name__ == "__main__":
    sys.exit(main())
