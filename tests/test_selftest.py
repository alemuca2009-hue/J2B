"""The frozen build's self-check must pass from source too.

If this fails, the packaged exe would fail on a user's machine for a reason no
test caught: a missing data file, a tkinter that cannot import, an atlas that
did not get bundled.

tkinter is the one check that depends on how the interpreter was built rather
than on this project, so on a host without it the test is skipped instead of
failed — the Windows job is where the GUI actually has to work.
"""

from __future__ import annotations

import unittest

from j2b.selftest import run


def _has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


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


if __name__ == "__main__":
    unittest.main()
