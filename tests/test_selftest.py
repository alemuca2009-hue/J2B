"""The self-test is the only thing standing between a broken .exe and a user.

It runs inside the frozen binary, where there is no console and no traceback to
read, so its own behaviour has to be pinned: a probe that raises must be
reported as a failed probe (not crash the process), an informational probe must
never fail the run, and the JSON report must agree with the exit code.

The conversion probe is the important one. Earlier versions only imported
modules, which is exactly the check that passes on a build that cannot write a
pack. These tests assert that a real conversion happens and that a conversion
which produces nothing is caught.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from j2b import selftest


class ProbeTests(unittest.TestCase):
    def test_raising_probe_is_reported_not_raised(self) -> None:
        def broken() -> tuple[bool, str]:
            raise RuntimeError("no tkinter here")

        record = selftest._check("tkinter", broken)
        self.assertFalse(record["ok"])
        self.assertIn("no tkinter here", str(record["detail"]))

    def test_informational_probe_never_fails_the_run(self) -> None:
        def broken() -> tuple[bool, str]:
            raise RuntimeError("not frozen")

        record = selftest._check("frozen", broken, required=False)
        self.assertTrue(record["ok"])

    def test_conversion_probe_converts_the_fixture(self) -> None:
        ok, detail = selftest._conversion()
        self.assertTrue(ok, detail)
        self.assertIn("converted", detail)
        self.assertIn("bundle", detail)

    def test_conversion_probe_rejects_a_pack_writer_that_writes_nothing(self) -> None:
        # Simulate the frozen-build failure this probe exists for: the pipeline
        # runs, reports features, and produces no file.
        class EmptyPacks:
            mcaddon = None

            class bp:  # noqa: N801 - stand-in object
                pass

        class EmptyResult:
            features: list[object] = []
            packs = EmptyPacks()
            mcaddon = None

        class FakeConverter:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def convert(self, _jar):
                return EmptyResult()

        with mock.patch("j2b.converter.Converter", FakeConverter):
            ok, detail = selftest._conversion()
        self.assertFalse(ok)
        self.assertIn(".mcaddon", detail)


class RunTests(unittest.TestCase):
    def test_every_probe_is_named_and_ordered(self) -> None:
        names = [name for name, _fn, _required in selftest.PROBES]
        self.assertIn("conversion", names)
        self.assertEqual(names[0], "python")

    def test_run_writes_a_report_that_matches_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "selftest.json"
            code = selftest.run(report)
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["checks"]), len(selftest.PROBES))
        self.assertTrue(all(check["ok"] for check in payload["checks"]))
        self.assertEqual({check["name"] for check in payload["checks"]}, {n for n, _f, _r in selftest.PROBES})

    def test_report_failure_does_not_change_the_exit_code(self) -> None:
        # An unwritable report path is a failure to report, not a failed build.
        code = selftest.run("/nonexistent-directory/that/cannot/exist/report.json")
        self.assertEqual(code, 0)

    def test_report_path_from_argv(self) -> None:
        self.assertEqual(
            selftest._report_path_from_argv(["--j2b-selftest", "--j2b-selftest-report=C:/tmp/r.json"]),
            "C:/tmp/r.json",
        )
        self.assertIsNone(selftest._report_path_from_argv(["--j2b-selftest"]))


if __name__ == "__main__":
    unittest.main()
