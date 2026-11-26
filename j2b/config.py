"""Data locations. Everything the tool remembers lives under one directory."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("J2B_DATA_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".j2b-studio"
    root.mkdir(parents=True, exist_ok=True)
    return root


def knowledge_overlay_path() -> Path:
    return data_dir() / "knowledge_overlay.json"


def knowledge_suggestions_path() -> Path:
    return data_dir() / "knowledge_suggestions.json"


def case_memory_path() -> Path:
    return data_dir() / "case_memory.sqlite3"


def history_path() -> Path:
    return data_dir() / "history.sqlite3"


DEFAULT_IGNORE = (
    "META-INF/",
    "com/mojang/",
    "net/minecraft/",
    ".git",
    "__MACOSX",
)
