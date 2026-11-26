"""Writes Bedrock packs and packages them.

Bedrock needs two packs: behaviour (data) and resources (textures, models,
lang). Both get manifests with deterministic UUIDs derived from the mod id, so
re-running a conversion produces the same pack identity instead of a new one.
"""

from __future__ import annotations

import json
import shutil
import struct
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Any

from ..models import ModMetadata, PackPaths
from ..utils import slugify


def make_icon_png(size: int = 64, rgb: tuple[int, int, int] = (196, 48, 84)) -> bytes:
    """Tiny solid-colour PNG so the pack has a valid icon without extra deps."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


class PackWriter:
    def __init__(
        self,
        output_root: str | Path,
        mod: ModMetadata,
        pack_name: str = "",
        min_engine_version: tuple[int, int, int] = (1, 20, 80),
        make_mcaddon: bool = True,
    ) -> None:
        self.mod = mod
        self.name = pack_name or f"{mod.name} (Bedrock)"
        self.slug = slugify(mod.name or mod.mod_id)
        self.min_engine_version = list(min_engine_version)
        root = Path(output_root).expanduser().resolve() / self.slug
        self.root = root
        self.bp = root / "behavior_pack"
        self.rp = root / "resource_pack"
        # Start from empty pack folders. Re-converting into the same directory used
        # to leave blocks from the previous run inside the new .mcaddon.
        for folder in (self.bp, self.rp):
            if folder.is_dir():
                shutil.rmtree(folder)
            folder.mkdir(parents=True, exist_ok=True)
        self.make_mcaddon = make_mcaddon
        self._bp_lang: dict[str, str] = {}
        self._rp_lang: dict[str, str] = {}
        self._terrain_textures: dict[str, str] = {}
        self._item_textures: dict[str, str] = {}
        self._written: list[str] = []
        self._bp_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"j2b:{mod.mod_id}:bp"))
        self._rp_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"j2b:{mod.mod_id}:rp"))
        self.mcpack_paths: list[Path] = []

    # -- json -------------------------------------------------------------
    def _write_json(self, base: Path, rel: str, payload: dict[str, Any], label: str) -> None:
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._written.append(f"{label}/{rel}")

    def write_bp(self, rel: str, payload: dict[str, Any]) -> None:
        self._write_json(self.bp, rel, payload, "behavior_pack")

    def write_rp(self, rel: str, payload: dict[str, Any]) -> None:
        self._write_json(self.rp, rel, payload, "resource_pack")

    # -- binary / text ----------------------------------------------------
    def write_rp_bytes(self, rel: str, data: bytes) -> None:
        target = self.rp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self._written.append(f"resource_pack/{rel}")

    def add_bp_lang(self, key: str, value: str) -> None:
        self._bp_lang[key] = value

    def add_rp_lang(self, key: str, value: str) -> None:
        self._rp_lang[key] = value

    def add_terrain_texture(self, key: str, path: str) -> None:
        self._terrain_textures[key] = path

    def add_item_texture(self, key: str, path: str) -> None:
        self._item_textures[key] = path

    @property
    def written(self) -> list[str]:
        return list(self._written)

    # -- pack metadata ----------------------------------------------------
    def _manifest(
        self,
        kind: str,
        header_uuid: str,
        module_uuid: str,
        module_type: str,
        name: str,
        dependencies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "format_version": 2,
            "header": {
                "name": name,
                "description": f"Converted from the Java mod {self.mod.name} by J2B Studio",
                "uuid": header_uuid,
                "version": [1, 0, 0],
                "min_engine_version": self.min_engine_version,
            },
            "modules": [
                {
                    "type": module_type,
                    "uuid": module_uuid,
                    "version": [1, 0, 0],
                }
            ],
            "metadata": {
                "authors": ["J2B Studio"],
                "license": "See the original mod",
                "product_type": "addon",
                "source_mod": self.mod.mod_id,
            },
        }
        if dependencies:
            manifest["dependencies"] = dependencies
        return manifest

    def finalize(self) -> PackPaths:
        # A behaviour pack whose blocks reference resource-pack geometry and
        # textures must declare the resource pack, or Minecraft will happily
        # activate it alone and render every block as a missing texture.
        self.write_bp(
            "manifest.json",
            self._manifest(
                "data",
                self._bp_uuid,
                str(uuid.uuid5(uuid.UUID(self._bp_uuid), "module")),
                "data",
                f"{self.name} [BP]",
                dependencies=[{"uuid": self._rp_uuid, "version": [1, 0, 0]}],
            ),
        )
        self.write_rp(
            "manifest.json",
            self._manifest("resources", self._rp_uuid, str(uuid.uuid5(uuid.UUID(self._rp_uuid), "module")), "resources", f"{self.name} [RP]"),
        )

        (self.bp / "pack_icon.png").write_bytes(make_icon_png(64, (196, 48, 84)))
        (self.rp / "pack_icon.png").write_bytes(make_icon_png(64, (48, 96, 196)))

        self.add_bp_lang("pack.name", f"{self.name} [BP]")
        self.add_bp_lang("pack.description", f"Behaviour pack converted from {self.mod.name}")
        self.add_rp_lang("pack.name", f"{self.name} [RP]")
        self.add_rp_lang("pack.description", f"Resources converted from {self.mod.name}")

        for base, entries, label in (
            (self.bp, self._bp_lang, "behavior_pack"),
            (self.rp, self._rp_lang, "resource_pack"),
        ):
            if not entries:
                continue
            target = base / "texts" / "en_US.lang"
            target.parent.mkdir(parents=True, exist_ok=True)
            lines = [f"{key}={value}" for key, value in sorted(entries.items())]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._written.append(f"{label}/texts/en_US.lang")

        if self._terrain_textures:
            self.write_rp(
                "textures/terrain_texture.json",
                {
                    "resource_pack_name": self.slug,
                    "texture_name": "atlas.terrain",
                    "padding": 8,
                    "num_mip_levels": 4,
                    "texture_data": {
                        key: {"textures": path} for key, path in sorted(self._terrain_textures.items())
                    },
                },
            )
        if self._item_textures:
            self.write_rp(
                "textures/item_texture.json",
                {
                    "resource_pack_name": self.slug,
                    "texture_name": "atlas.items",
                    "texture_data": {
                        key: {"textures": path} for key, path in sorted(self._item_textures.items())
                    },
                },
            )

        self.mcpack_paths = []
        mcaddon: Path | None = None
        if self.make_mcaddon:
            # A .mcpack is one pack with manifest.json at its root; a .mcaddon is a
            # zip of pack folders. Shipping both means the add-on can be imported as
            # a whole or each pack can be installed on its own.
            for folder, label in ((self.bp, "BP"), (self.rp, "RP")):
                mcpack = self.root / f"{self.slug}_{label}.mcpack"
                with zipfile.ZipFile(mcpack, "w", zipfile.ZIP_DEFLATED) as archive:
                    for file in sorted(folder.rglob("*")):
                        if file.is_file():
                            archive.write(file, file.relative_to(folder).as_posix())
                self.mcpack_paths.append(mcpack)

            mcaddon = self.root / f"{self.slug}.mcaddon"
            with zipfile.ZipFile(mcaddon, "w", zipfile.ZIP_DEFLATED) as archive:
                for folder in (self.bp, self.rp):
                    for file in sorted(folder.rglob("*")):
                        if file.is_file():
                            archive.write(file, file.relative_to(self.root).as_posix())

        return PackPaths(root=self.root, bp=self.bp, rp=self.rp, mcaddon=mcaddon)
