"""``sounds.json`` + ``.ogg`` -> Bedrock ``sound_definitions.json`` + ``sounds/``.

Sound is the part of a Java mod that converts completely. There is no code to
recover and nothing to approximate: a ``sounds.json`` entry names files, and
Bedrock wants a definition that names files. The two formats differ in spelling,
not in capability, which is why this module invents nothing.

Two mappings are not one-to-one and are reported rather than guessed:

* A Java entry of ``type: "event"`` points at *another sound event* (usually
  ``minecraft:entity.generic.eat``). Bedrock's ``sounds`` array lists audio
  files, not definitions, so there is no equivalent and the entry is skipped --
  with the name of the event in the report, because a human can substitute the
  Bedrock file by hand in seconds.
* Java subtitles (``subtitle``) have no Bedrock counterpart at all.

The file names matter more than they look. Bedrock resolves ``"name":
"sounds/create/whistle"`` to ``resource_pack/sounds/create/whistle.ogg``, so a
definition that keeps Java's ``create:whistle`` form loads in the pack and stays
silent forever -- the exact failure this module exists to prevent.
"""

from __future__ import annotations

from typing import Any

from ..models import Feature
from .context import ConversionContext

#: Bedrock's ``category`` enum (the Blockception schema for
#: ``sound_definitions``). Anything outside it is written as ``neutral``.
CATEGORIES = {
    "ambient",
    "block",
    "bottle",
    "bucket",
    "hostile",
    "music",
    "neutral",
    "player",
    "ui",
    "weather",
}

#: Java category names Bedrock does not have. Copying ``master`` or ``record``
#: verbatim writes a definition that fails the schema, so they are folded onto
#: the Bedrock category that means the same thing.
CATEGORY_ALIASES = {
    "master": "neutral",
    "record": "music",
    "blocks": "block",
    "players": "player",
    "records": "music",
    "voice": "neutral",
}

#: Bedrock identifiers are ``[a-z0-9_.]``; a stray ``:`` or ``/`` makes the
#: definition load and never play.
_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789_.")


def _identifier(namespace: str, name: str) -> str:
    raw = f"{namespace}.{name}".lower()
    cleaned = "".join(char if char in _SAFE else "_" for char in raw)
    return cleaned.strip("._") or "sound"


def _split(name: str, default_namespace: str) -> tuple[str, str]:
    """``create:whistle`` -> ``("create", "whistle")``; bare names use the file's namespace."""
    if ":" in name:
        namespace, _, rest = name.partition(":")
        return namespace.strip() or default_namespace, rest.strip()
    return default_namespace, name.strip()


def _float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def convert_sound_feature(feature: Feature, ctx: ConversionContext) -> None:
    """Write one ``sounds.json`` as a Bedrock sound definition file."""
    namespace = str(feature.data.get("namespace") or feature.id.split(":")[0])
    entries: dict[str, Any] = feature.data.get("sounds") or {}
    if not isinstance(entries, dict) or not entries:
        feature.set_result("skipped", 0.0, "empty_sounds_json")
        return

    definitions: dict[str, Any] = {}
    played_files: list[tuple[str, str]] = []
    used: set[str] = set()
    skipped_events: list[str] = []
    missing: list[str] = []

    for java_name in sorted(entries):
        spec = entries[java_name]
        if not isinstance(spec, dict):
            continue
        sound_list = spec.get("sounds")
        if not isinstance(sound_list, list):
            continue

        variants: list[dict[str, Any]] = []
        for entry in sound_list:
            if not isinstance(entry, dict):
                # Java allows a bare string here; the converter upstream
                # normalises it, but a hand-edited file can still hold one.
                entry = {"name": entry}
            kind = str(entry.get("type") or "file").lower()
            raw_name = str(entry.get("name") or "").strip()
            if not raw_name:
                continue
            if kind == "event":
                skipped_events.append(f"{java_name} -> {raw_name}")
                continue

            file_namespace, file_name = _split(raw_name, namespace)
            if not file_name:
                continue
            # Java keeps every sound of a namespace flat under
            # `assets/<ns>/sounds/<name>.ogg` -- no second namespace directory.
            # The pack does fold it into one, because Bedrock's definition names
            # `sounds/<folder>/<file>` and a flat folder would collide the moment
            # two namespaces ship a `click.ogg`.
            source = f"assets/{file_namespace}/sounds/{file_name}.ogg"
            if not ctx.archive.exists(source):
                # A missing file is worth saying out loud: the definition would
                # otherwise be a silent stub that looks converted.
                missing.append(f"{raw_name} (expected {source})")
                continue
            relative = f"sounds/{file_namespace}/{file_name}.ogg"

            variant: dict[str, Any] = {"name": f"sounds/{file_namespace}/{file_name}"}
            volume = _float(entry.get("volume"), 1.0)
            pitch = _float(entry.get("pitch"), 1.0)
            if abs(volume - 1.0) > 1e-9:
                variant["volume"] = round(volume, 4)
            if abs(pitch - 1.0) > 1e-9:
                variant["pitch"] = round(pitch, 4)
            if entry.get("stream"):
                variant["stream"] = True
            # Both formats pick a variant at random in proportion to an integer
            # weight; leaving it out would flatten a "rare" variant to common.
            weight = entry.get("weight")
            if isinstance(weight, int) and not isinstance(weight, bool) and weight > 1:
                variant["weight"] = weight
            variants.append(variant)
            played_files.append((source, relative))

        if not variants:
            continue

        identifier = _identifier(namespace, java_name)
        suffix = 2
        unique = identifier
        while unique in used:
            unique = f"{identifier}_{suffix}"
            suffix += 1
        used.add(unique)

        category = str(spec.get("category") or "").lower()
        category = CATEGORY_ALIASES.get(category, category)
        definition: dict[str, Any] = {
            "category": category if category in CATEGORIES else "neutral",
            "sounds": variants,
        }
        definitions[unique] = definition

    if not definitions:
        feature.set_result("unsupported", 0.0, "sound_events_only")
        for line in skipped_events:
            feature.add_limitation(f"`{line}` references another Java sound event; Bedrock definitions list audio files, so it was not written.")
        for line in missing:
            feature.add_limitation(f"`{line}` is declared in sounds.json but no such .ogg is in the jar.")
        feature.add_issue(
            "warning",
            "SOUND_EVENT_UNRESOLVED",
            "Every entry in this sounds.json points at another sound event or at a missing file.",
            "Nothing was written: a definition with no playable audio is a silent stub.",
        )
        return

    # Merge into whatever a previous namespace already wrote, so a mod with two
    # `sounds.json` files does not lose the first one to the second.
    accumulated = getattr(ctx, "_sound_definitions", None)
    if not isinstance(accumulated, dict):
        accumulated = {}
        setattr(ctx, "_sound_definitions", accumulated)
    accumulated.update(definitions)
    definitions = accumulated

    ctx.writer.write_rp("sounds/sound_definitions.json", {
        "format_version": "1.14.0",
        "sound_definitions": definitions,
    })

    copied = 0
    for source, relative in sorted(set(played_files)):
        data = ctx.archive.read(source)
        if data is None:
            continue
        # `sounds/<namespace>/<name>.ogg` -- and the definition above references
        # exactly that path without the extension, which is how Bedrock resolves it.
        ctx.writer.write_rp_bytes(relative, data)
        copied += 1

    ctx.count("sound_definitions", len(definitions))
    ctx.count("sound_files", copied)

    if copied:
        feature.add_assumption(
            f"{len(definitions)} sound definitions and {copied} .ogg files were carried across unchanged. "
            "Bedrock reads the same Vorbis files the mod shipped."
        )
    if skipped_events:
        feature.add_limitation(
            f"{len(skipped_events)} entr{'y' if len(skipped_events) == 1 else 'ies'} pointed at another sound event "
            f"and were skipped: {', '.join(skipped_events[:5])}"
            + (" and more." if len(skipped_events) > 5 else ".")
        )
    if missing:
        feature.add_limitation(f"{len(missing)} declared .ogg files are not in the jar and could not be copied.")
    feature.add_limitation(
        "Java sound categories live in code, not in sounds.json; every definition is written as `neutral` "
        "unless the file states a category Bedrock also has."
    )
    feature.set_result("converted", 0.95 if not (skipped_events or missing) else 0.8, "sound_definitions")
