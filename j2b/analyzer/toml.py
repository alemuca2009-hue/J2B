"""Minimal TOML reading for Forge / NeoForge metadata.

`mods.toml` and `neoforge.mods.toml` are TOML, not JSON. Feeding them to a JSON
parser always fails, which is why loader and version used to come out as
``unknown`` / ``0.0.0``.

Python 3.11+ ships :mod:`tomllib`, and it is used when present. The fallback
below is deliberately small: it understands sections, arrays of tables,
basic/literal strings, integers, floats, booleans and single-line arrays —
enough for a mod manifest, and it never invents a value it did not read.
"""

from __future__ import annotations

import re
from typing import Any

_SECTION = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\-\"']+)\s*\]?\]\s*$")
_PAIR = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*=\s*(.+?)\s*$")
_STRING = re.compile(r'^(?:"((?:[^"\\]|\\.)*)"|\'([^\']*)\')')
_BARE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _split_key(raw: str) -> list[str]:
    return [part.strip().strip("\"'") for part in raw.split(".") if part.strip()]


def _value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("["):
        inner = text[1 : text.rfind("]")] if "]" in text else text[1:]
        items = [_value(piece) for piece in _split_top(inner)]
        return [item for item in items if item != ""]
    if text.startswith("{"):
        return {}  # inline tables are not needed for mod metadata
    match = _STRING.match(text)
    if match:
        return match.group(1) if match.group(1) is not None else match.group(2)
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_top(inner: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    return [part for part in parts if part.strip()]


def _fallback_parse(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("#"):
            continue
        section = _SECTION.match(line)
        if section:
            keys = _split_key(section.group(1))
            is_array = line.startswith("[[")
            node: Any = root
            for key in keys[:-1]:
                nxt = node.get(key)
                if isinstance(nxt, list) and nxt:
                    nxt = nxt[-1]
                if not isinstance(nxt, dict):
                    nxt = {}
                    node[key] = nxt
                node = nxt
            last = keys[-1]
            if is_array:
                bucket = node.setdefault(last, [])
                if not isinstance(bucket, list):
                    bucket = []
                    node[last] = bucket
                entry: dict[str, Any] = {}
                bucket.append(entry)
                current = entry
            else:
                existing = node.get(last)
                if not isinstance(existing, dict):
                    existing = {}
                    node[last] = existing
                current = existing
            continue
        pair = _PAIR.match(line)
        if pair:
            current[pair.group(1)] = _value(pair.group(2))
    return root


def parse_toml(text: str) -> dict[str, Any]:
    """Parse TOML ``text``; returns ``{}`` when nothing usable could be read."""
    try:  # Python 3.11+
        import tomllib

        try:
            parsed = tomllib.loads(text)
        except Exception:  # noqa: BLE001 - malformed TOML falls back to the lenient reader
            parsed = None
        if isinstance(parsed, dict) and parsed:
            return parsed
    except ImportError:
        pass
    try:
        parsed = _fallback_parse(text)
    except Exception:  # noqa: BLE001 - never let a manifest break the scan
        return {}
    return parsed if isinstance(parsed, dict) else {}


def first_mod(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the first ``[[mods]]`` entry of a Forge/NeoForge manifest."""
    mods = payload.get("mods")
    if isinstance(mods, list) and mods and isinstance(mods[0], dict):
        return mods[0]
    if isinstance(mods, dict):
        return mods
    return {}


def minecraft_version(payload: dict[str, Any], mod_id: str) -> str:
    """Best-effort Minecraft version from a ``[[dependencies.<id>]]`` block."""
    deps = payload.get("dependencies")
    if not isinstance(deps, dict):
        return ""
    for key in (mod_id, "minecraft", "neoforge", "forge"):
        entries = deps.get(key)
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("modId") == "minecraft":
                    version = entry.get("versionRange") or entry.get("version")
                    if isinstance(version, str) and version:
                        return version.strip("[](), )")
    return ""


def is_bare_version(value: Any) -> bool:
    return isinstance(value, str) and bool(_BARE.match(value))
