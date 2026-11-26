"""Backwards-compatible shim.

The fixture itself moved to :mod:`j2b.fixtures` so the frozen executable's
self-test can convert the same jar the tests convert. Kept as a module so the
existing ``from tests.make_test_jar import build`` imports keep working.
"""

from __future__ import annotations

from pathlib import Path

from j2b.fixtures import _png, build

__all__ = ["build", "_png", "Path"]


if __name__ == "__main__":  # pragma: no cover - manual use
    print(build(Path("test_mod.jar")))
