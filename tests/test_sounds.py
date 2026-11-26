"""``sounds.json`` -> Bedrock ``sound_definitions.json``.

Sound is the only part of a mod that converts with no loss and no guessing, so
the tests here are about the two things that would break it silently: a
definition naming a path that does not exist in the pack, and an entry that
disappeared without anyone noticing.

A definition that loads but points at the wrong folder plays nothing, and
nothing in a JSON diff shows it -- which is why the path is asserted as a
string, not just the count.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from j2b.converter import Converter
from j2b.fixtures import build as build_fixture
from j2b.models import ConversionOptions

OGG = b"OggS" + b"\x00" * 64  # enough for a byte-for-byte copy assertion


def _jar_with_sounds(path: Path, extra_writes: dict[str, bytes]) -> Path:
    """The standard fixture plus whatever sound files a test needs."""
    base = build_fixture(path.with_suffix(".base.jar"))
    with zipfile.ZipFile(base) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        for name, content in extra_writes.items():
            target.writestr(name, content)
    base.unlink()
    return path


def _convert(writes: dict[str, bytes], name: str = "sounds") -> tuple:
    tmp = tempfile.TemporaryDirectory()
    os.environ["J2B_DATA_DIR"] = str(Path(tmp.name) / "data")
    jar = _jar_with_sounds(Path(tmp.name) / f"{name}.jar", writes)
    out = Path(tmp.name) / "out"
    result = Converter(options=ConversionOptions(output_dir=str(out), make_mcaddon=False)).convert(jar)
    return tmp, out, result


def _resource_pack(out: Path) -> Path:
    """The pack directory is named after the mod's display name, not its id."""
    found = sorted(out.glob("*/resource_pack"))
    return found[0]


def _definitions(out: Path) -> dict:
    return json.loads((_resource_pack(out) / "sounds" / "sound_definitions.json").read_text())


class SoundDefinitionTests(unittest.TestCase):
    SOUNDS = {
        "cardboard_bonk": {"sounds": [{"type": "file", "name": "testmod:cardboard_bonk"}]},
        "chiff": {
            "category": "player",
            "sounds": [
                {"type": "file", "name": "testmod:chiff_1", "volume": 0.8, "pitch": 1.2, "stream": True},
                {"type": "file", "name": "testmod:chiff_2"},
            ],
        },
        "vanilla_alias": {"sounds": [{"type": "event", "name": "minecraft:entity.generic.eat"}]},
        "gone": {"sounds": [{"type": "file", "name": "testmod:missing_file"}]},
    }

    @classmethod
    def setUpClass(cls) -> None:
        writes = {"assets/testmod/sounds.json": json.dumps(cls.SOUNDS)}
        for stem in ("cardboard_bonk", "chiff_1", "chiff_2"):
            writes[f"assets/testmod/sounds/{stem}.ogg"] = OGG
        cls.tmp, cls.out, cls.result = _convert(writes)
        cls.rp = _resource_pack(cls.out)
        cls.document = _definitions(cls.out)
        cls.definitions = cls.document["sound_definitions"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_definitions_land_where_bedrock_looks_for_them(self) -> None:
        self.assertTrue((self.rp / "sounds" / "sound_definitions.json").is_file())
        self.assertEqual(self.document["format_version"], "1.14.0")
        self.assertIn("testmod.cardboard_bonk", self.definitions)

    def test_a_definition_names_the_file_by_its_pack_path(self) -> None:
        # Java's `testmod:cardboard_bonk` is `create:whistle` -> the pack path
        # `sounds/testmod/cardboard_bonk`, extensionless. Anything else is silent.
        variant = self.definitions["testmod.cardboard_bonk"]["sounds"][0]
        self.assertEqual(variant["name"], "sounds/testmod/cardboard_bonk")
        self.assertTrue((self.rp / "sounds" / "testmod" / "cardboard_bonk.ogg").is_file())

    def test_the_ogg_is_copied_byte_for_byte(self) -> None:
        self.assertEqual((self.rp / "sounds" / "testmod" / "cardboard_bonk.ogg").read_bytes(), OGG)

    def test_every_variant_of_an_entry_is_kept_in_order(self) -> None:
        names = [variant["name"] for variant in self.definitions["testmod.chiff"]["sounds"]]
        self.assertEqual(names, ["sounds/testmod/chiff_1", "sounds/testmod/chiff_2"])

    def test_volume_pitch_and_stream_survive(self) -> None:
        first = self.definitions["testmod.chiff"]["sounds"][0]
        self.assertAlmostEqual(first["volume"], 0.8)
        self.assertAlmostEqual(first["pitch"], 1.2)
        self.assertTrue(first["stream"])
        # A default is omitted rather than written as 1.0, so the diff shows
        # only what the author actually changed.
        self.assertNotIn("volume", self.definitions["testmod.chiff"]["sounds"][1])

    def test_a_category_bedrock_has_is_carried_over(self) -> None:
        self.assertEqual(self.definitions["testmod.chiff"]["category"], "player")
        self.assertEqual(self.definitions["testmod.cardboard_bonk"]["category"], "neutral")

    def test_a_vanilla_event_alias_is_skipped_not_faked(self) -> None:
        self.assertNotIn("testmod.vanilla_alias", self.definitions)
        feature = next(f for f in self.result.features if f.kind == "sound")
        self.assertTrue(any("another sound event" in text for text in feature.limitations))

    def test_a_declared_file_that_is_missing_is_reported(self) -> None:
        self.assertNotIn("testmod.gone", self.definitions)
        feature = next(f for f in self.result.features if f.kind == "sound")
        self.assertTrue(any("missing_file" in text or "not in the jar" in text for text in feature.limitations))

    def test_the_feature_is_reported_as_converted(self) -> None:
        feature = next(f for f in self.result.features if f.kind == "sound")
        self.assertEqual(feature.status, "converted")
        self.assertIn("sound_definitions", feature.strategy)

    def test_an_identifier_cannot_keep_characters_bedrock_rejects(self) -> None:
        tmp, out, result = _convert(
            {
                "assets/testmod/sounds.json": json.dumps({"weird/name:here": {"sounds": [{"name": "testmod:x"}]}}),
                "assets/testmod/sounds/x.ogg": OGG,
            },
            name="weird",
        )
        try:
            key = next(iter(_definitions(out)["sound_definitions"]))
            self.assertTrue(key.replace("_", "").replace(".", "").isalnum(), key)
            self.assertNotIn(":", key)
            self.assertNotIn("/", key)
        finally:
            tmp.cleanup()


class SoundEdgeCaseTests(unittest.TestCase):
    def test_a_file_with_only_event_aliases_writes_nothing_and_says_so(self) -> None:
        tmp, out, result = _convert(
            {"assets/testmod/sounds.json": json.dumps({"bell": {"sounds": [{"type": "event", "name": "minecraft:block.note_block.bell"}]}})},
            name="events",
        )
        try:
            feature = next(f for f in result.features if f.kind == "sound")
            self.assertEqual(feature.status, "unsupported")
            self.assertFalse((_resource_pack(out) / "sounds" / "sound_definitions.json").exists())
        finally:
            tmp.cleanup()

    def test_a_bare_string_entry_is_read_as_a_file(self) -> None:
        # Java accepts `"sounds": ["testmod:blip"]`, and real mods use it.
        tmp, out, result = _convert(
            {
                "assets/testmod/sounds.json": json.dumps({"blip": {"sounds": ["testmod:blip"]}}),
                "assets/testmod/sounds/blip.ogg": OGG,
            },
            name="bare",
        )
        try:
            self.assertEqual(_definitions(out)["sound_definitions"]["testmod.blip"]["sounds"][0]["name"], "sounds/testmod/blip")
        finally:
            tmp.cleanup()
