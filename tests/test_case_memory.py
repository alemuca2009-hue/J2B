"""Case memory: the store of what previous conversions did.

The behaviour under test is not "it stores rows" -- it is that storing 2 890
rows does not open 2 890 connections. The old implementation used
``with self._connect() as connection`` per row: ``sqlite3.Connection.__exit__``
commits but does *not* close, so every feature leaked a file handle and paid
for its own fsync. On Create 6.0.10 that was 3.2 s of an 18 s conversion.

These tests pin the two things that regressed: one connection per instance, and
rows buffered until a single flush.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from j2b.knowledge.base import CaseMemory
from j2b.models import Feature


def _feature(name: str, status: str = "converted", kind: str = "block") -> Feature:
    feature = Feature(id=f"minecraft:{name}", kind=kind, name=name, source="test")
    feature.set_result(status, 0.8, "cube")
    return feature


class CaseMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "cases.sqlite3"
        self.memory = CaseMemory(self.path)

    def tearDown(self) -> None:
        self.memory.close()
        self._tmp.cleanup()

    def test_rows_are_buffered_until_flush(self) -> None:
        self.memory.record(_feature("ruby_block"), "rubytest")
        self.assertEqual(self.memory.flush(), 1)

    def test_flush_is_idempotent(self) -> None:
        self.memory.record(_feature("ruby_block"), "rubytest")
        self.assertEqual(self.memory.flush(), 1)
        self.assertEqual(self.memory.flush(), 0)

    def test_stats_sees_buffered_rows(self) -> None:
        # stats() used to query the table directly, so it reported 0 cases for
        # rows still held in the buffer.
        self.memory.record(_feature("ruby_block"), "rubytest")
        self.assertEqual(self.memory.stats()["cases"], 1)

    def test_repeat_records_increment_seen(self) -> None:
        feature = _feature("ruby_block")
        self.memory.record(feature, "rubytest")
        self.memory.record(feature, "rubytest")
        self.memory.flush()
        row = self.memory.precedent(_feature("other_block"))
        self.assertIsNotNone(row)
        self.assertEqual(row["record"]["seen"], 2)

    def test_pending_features_are_not_recorded(self) -> None:
        feature = Feature(id="minecraft:pending", kind="block", name="pending", source="test")
        self.memory.record(feature, "rubytest")
        self.assertEqual(self.memory.flush(), 0)

    def test_one_connection_for_many_rows(self) -> None:
        # The regression this file exists for. Count real sqlite3.connect calls
        # rather than trusting the implementation to be tidy.
        opened: list[int] = []
        original = sqlite3.connect

        def counting_connect(*args, **kwargs):
            opened.append(1)
            return original(*args, **kwargs)

        sqlite3.connect = counting_connect
        try:
            memory = CaseMemory(self.path)
            for index in range(500):
                memory.record(_feature(f"block_{index}"), "rubytest")
            memory.flush()
            memory.stats()
            memory.close()
        finally:
            sqlite3.connect = original

        # Exactly one: the connection opened in __init__ serves all 500 rows,
        # the flush and the stats query. The old code opened one per record().
        self.assertEqual(len(opened), 1)

    def test_corrupt_database_disables_memory_without_raising(self) -> None:
        broken = Path(self._tmp.name) / "broken.sqlite3"
        broken.write_bytes(b"this is not a database file")
        memory = CaseMemory(broken)
        self.assertFalse(memory.available)
        memory.record(_feature("ruby_block"), "rubytest")
        self.assertEqual(memory.flush(), 0)
        self.assertEqual(memory.stats(), {"available": False, "cases": 0})
        self.assertIsNone(memory.precedent(_feature("x")))

    def test_context_manager_closes(self) -> None:
        with CaseMemory(self.path) as memory:
            memory.record(_feature("ruby_block"), "rubytest")
        self.assertIsNone(memory._conn)

    def test_close_is_idempotent(self) -> None:
        memory = CaseMemory(self.path)
        memory.close()
        memory.close()


if __name__ == "__main__":
    unittest.main()
