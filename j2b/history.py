"""Conversion history, so repeated runs can be compared."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import history_path
from .models import ConversionResult
from .utils import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    mod_name TEXT,
    mod_id TEXT,
    mod_version TEXT,
    loader TEXT,
    features INTEGER,
    converted INTEGER,
    partial INTEGER,
    manual INTEGER,
    unsupported INTEGER,
    fidelity REAL,
    validation_errors INTEGER,
    output TEXT
);
"""


class ConversionHistory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else history_path()
        self.available = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(SCHEMA)
        except sqlite3.Error:
            self.available = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, result: ConversionResult) -> int | None:
        if not self.available:
            return None
        stats = result.stats or result.compute_stats()
        counts = stats["status_counts"]
        errors = sum(1 for check in result.validation if check.severity == "error")
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """INSERT INTO conversions
                       (at, mod_name, mod_id, mod_version, loader, features, converted, partial,
                        manual, unsupported, fidelity, validation_errors, output)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        now_iso(),
                        result.mod.name,
                        result.mod.mod_id,
                        result.mod.version,
                        result.mod.loader,
                        stats["features_total"],
                        counts.get("converted", 0),
                        counts.get("partial", 0),
                        counts.get("manual", 0),
                        counts.get("unsupported", 0),
                        stats["estimated_fidelity"],
                        errors,
                        str(result.packs.root) if result.packs else "",
                    ),
                )
                return int(cursor.lastrowid or 0)
        except sqlite3.Error:
            self.available = False
            return None

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.available:
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM conversions ORDER BY id DESC LIMIT ?", (int(limit),)
                ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "conversions": 0, "average_fidelity": 0.0}
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS total, AVG(fidelity) AS avg_fidelity, SUM(validation_errors) AS errors "
                    "FROM conversions"
                ).fetchone()
        except sqlite3.Error:
            return {"available": False, "conversions": 0, "average_fidelity": 0.0}
        return {
            "available": True,
            "conversions": int(row["total"] or 0),
            "average_fidelity": round(float(row["avg_fidelity"] or 0.0), 4),
            "validation_errors": int(row["errors"] or 0),
        }
