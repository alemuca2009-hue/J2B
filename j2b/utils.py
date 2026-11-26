"""Small helpers shared across the package."""

from __future__ import annotations

import re
from datetime import datetime, timezone

_SLUG = re.compile(r"[^a-z0-9_]+")


def split_id(identifier: str) -> tuple[str, str]:
    """``"testmod:ruby_ore"`` -> ``("testmod", "ruby_ore")``."""
    if ":" in identifier:
        namespace, _, name = identifier.partition(":")
        return namespace, name
    return "minecraft", identifier


def slugify(value: str, fallback: str = "unnamed") -> str:
    slug = _SLUG.sub("_", str(value).lower().replace("-", "_").replace(" ", "_")).strip("_")
    return slug or fallback


def file_stem(identifier: str) -> str:
    namespace, name = split_id(identifier)
    return slugify(f"{namespace}_{name}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def read_json(archive, name: str) -> dict | None:
    """Read a JSON file out of an open archive, tolerating malformed input."""
    raw = archive.read(name)
    if raw is None:
        return None
    import json

    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
