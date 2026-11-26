"""The frozen build's self-check must pass from source too.

If this fails, the packaged exe would fail on a user's machine for a reason no
test caught: a missing data file, a tkinter that cannot import, an atlas that
did not get bundled.
"""

from __future__ import annotations

import unittest

from j2b.selftest import run


class SelfTestTests(unittest.TestCase):
    def test_self_test_passes(self) -> None:
        self.assertEqual(run(), 0)

    def test_launcher_imports_without_side_effects(self) -> None:
        import launcher

        self.assertTrue(callable(launcher.main))


if __name__ == "__main__":
    unittest.main()
