"""Read-only view over a mod jar/zip.

Namespaces are derived from the archive layout before metadata is parsed, so
Fabric/Forge metadata can be validated against the resources that actually
exist.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Iterator

from ..models import ModMetadata

from .toml import first_mod, minecraft_version, parse_toml


class ModArchive:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise OSError(f"Mod archive not found: {self.path}")
        try:
            self._zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"{self.path.name} is not a valid jar/zip: {exc}") from exc
        self._names = [name for name in self._zip.namelist() if not name.endswith("/")]
        self.namespaces = sorted(
            {
                name.split("/")[1]
                for name in self._names
                if name.startswith("assets/") and name.count("/") >= 2
            }
        )
        self.metadata = self._read_metadata()

    # -- io ---------------------------------------------------------------
    def __enter__(self) -> "ModArchive":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    def read(self, name: str) -> bytes | None:
        try:
            return self._zip.read(name)
        except KeyError:
            return None

    def exists(self, name: str) -> bool:
        return name in self._names

    def names(self, prefix: str = "") -> list[str]:
        return [name for name in self._names if name.startswith(prefix)]

    def iter_files(self, prefix: str, suffix: str = "") -> Iterator[str]:
        for name in self._names:
            if name.startswith(prefix) and name.endswith(suffix):
                yield name

    def json(self, name: str) -> dict | None:
        raw = self.read(name)
        if raw is None:
            return None
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    # -- metadata ---------------------------------------------------------
    def _read_metadata(self) -> ModMetadata:
        """Pick the reader from the file's own format.

        ``mods.toml`` and ``neoforge.mods.toml`` are TOML. Trying to parse them as
        JSON always failed, and the fallback then reported ``unknown / 0.0.0``.
        """
        for candidate, loader, kind in (
            ("fabric.mod.json", "fabric", "json"),
            ("quilt.mod.json", "quilt", "json"),
            ("META-INF/neoforge.mods.toml", "neoforge", "toml"),
            ("META-INF/mods.toml", "forge", "toml"),
        ):
            if not self.exists(candidate):
                continue
            if kind == "json":
                payload = self.json(candidate)
                if payload:
                    return self._from_fabric(payload, loader)
                continue
            metadata = self._from_toml(candidate, loader)
            if metadata is not None:
                return metadata
        return self._fallback()

    def _from_fabric(self, payload: dict, loader: str) -> ModMetadata:
        inner = payload.get("quilt_loader") if loader == "quilt" else payload
        if not isinstance(inner, dict):
            inner = payload
        meta = inner.get("metadata") if isinstance(inner.get("metadata"), dict) else {}
        mod_id = str(inner.get("id") or meta.get("id") or "unknown")
        name = str(inner.get("name") or meta.get("name") or mod_id)
        version = str(inner.get("version") or meta.get("version") or "0.0.0")
        description = str(inner.get("description") or meta.get("description") or "")
        authors_raw = inner.get("authors") or meta.get("contributors") or []
        authors: list[str] = []
        for author in authors_raw if isinstance(authors_raw, list) else []:
            if isinstance(author, str):
                authors.append(author)
            elif isinstance(author, dict) and author.get("name"):
                authors.append(str(author["name"]))
        depends = inner.get("depends") if isinstance(inner.get("depends"), dict) else {}
        minecraft = str(depends.get("minecraft") or "")
        return ModMetadata(
            name=name,
            mod_id=_clean_id(mod_id),
            version=version,
            loader=loader,
            description=description,
            authors=authors,
            minecraft_version=minecraft,
        )

    def _from_toml(self, name: str, loader: str) -> ModMetadata | None:
        raw = self.read(name) or b""
        text = raw.decode("utf-8", errors="replace")
        payload = parse_toml(text)
        if not payload:
            return None
        entry = first_mod(payload)
        if not entry:
            return None
        mod_id = str(entry.get("modId") or (self.namespaces[0] if self.namespaces else "unknown"))
        version = str(entry.get("version") or "0.0.0")
        description = str(entry.get("description") or "")
        if description.startswith("${") and description.endswith("}"):
            description = ""
        authors = [
            str(item.get("name"))
            for item in (payload.get("authors") or [])
            if isinstance(item, dict) and item.get("name")
        ] if isinstance(payload.get("authors"), list) else []
        return ModMetadata(
            name=str(entry.get("displayName") or mod_id),
            mod_id=_clean_id(mod_id),
            version=version,
            loader=loader,
            description=description,
            authors=authors,
            minecraft_version=minecraft_version(payload, mod_id),
        )

    def _fallback(self) -> ModMetadata:
        mcmeta = self.json("pack.mcmeta")
        description = ""
        if mcmeta and isinstance(mcmeta.get("pack"), dict):
            description = str(mcmeta["pack"].get("description") or "")
        mod_id = self.namespaces[0] if self.namespaces else _clean_id(self.path.stem)
        return ModMetadata(
            name=self.path.stem,
            mod_id=mod_id,
            version="0.0.0",
            loader="unknown",
            description=description,
        )


def _clean_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    return cleaned or "unknown"
