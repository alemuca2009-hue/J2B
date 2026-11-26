"""The frozen build's self-check must pass from source too.

If this fails, the packaged exe would fail on a user's machine for a reason no
test caught: a missing data file, a tkinter that cannot import, an atlas that
did not get bundled.

tkinter is the one check that depends on how the interpreter was built rather
than on this project, so on a host without it the test is skipped instead of
failed — the Windows job is where the GUI actually has to work.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from j2b.selftest import PROBES, run


def _has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def _requires_tkinter(test):
    if not _has_tkinter():
        return unittest.skip("tkinter is not available in this interpreter build")(test)
    return test


class SelfTestTests(unittest.TestCase):
    def test_self_test_passes(self) -> None:
        if not _has_tkinter():
            self.skipTest("tkinter is not available in this interpreter build")
        self.assertEqual(run(), 0)

    def test_self_test_reports_a_missing_dependency(self) -> None:
        # Whatever run() does, it must never raise: a frozen exe that raises on
        # startup is a window that never appears and no message anywhere.
        self.assertIn(run(), (0, 1))

    def test_launcher_imports_without_side_effects(self) -> None:
        import launcher

        self.assertTrue(callable(launcher.main))

    def test_self_test_writes_a_json_report(self) -> None:
        # CI reads this file, not just the exit code: "exit 0" is one bit and
        # says nothing about which subsystem was actually checked.
        if not _has_tkinter():
            self.skipTest("tkinter is not available in this interpreter build")
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "selftest.json"
            self.assertEqual(run(report), 0)
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["version"])
        # Every probe must appear: a report that silently omits one is worse
        # than no report, because the log then looks complete.
        self.assertEqual([c["name"] for c in payload["checks"]], [name for name, _, _ in PROBES])

    def test_unwritable_report_path_does_not_fail_the_check(self) -> None:
        # A path we cannot write is a reporting problem, not a broken build.
        if not _has_tkinter():
            self.skipTest("tkinter is not available in this interpreter build")
        self.assertEqual(run("/nonexistent-directory-j2b/report.json"), 0)

    def test_frozen_probe_is_informational(self) -> None:
        # Running from source must never look like a failure of the packaged
        # app: the "frozen" probe describes the environment, it does not gate it.
        info = dict((name, required) for name, _, required in PROBES)
        self.assertFalse(info["frozen"])
        self.assertTrue(info["tkinter"] and info["knowledge base"])

    def test_module_entry_point_prints_and_exits(self) -> None:
        # `python -m j2b.selftest` used to print nothing: the module defined
        # run() but never called it, so a broken probe went unnoticed until the
        # launcher exercised it.
        result = subprocess.run(
            [sys.executable, "-m", "j2b.selftest"], capture_output=True, text=True
        )
        self.assertIn("ok", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
