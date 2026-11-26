"""Minimal, defensive Java classfile reader.

Only the class header (constant pool, access flags, this/super class and
interfaces) is parsed. That is enough to classify mod classes (Block, BlockEntity,
Screen, mixin packages, …) without executing any Java code and without external
dependencies such as ASM.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

CLASS_MAGIC = b"\xca\xfe\xba\xbe"


class ClassFileError(ValueError):
    """Raised when a classfile is malformed or uses an unknown pool tag."""


@dataclass
class ClassFile:
    name: str = ""
    super_name: str = ""
    interfaces: list[str] = field(default_factory=list)
    utf8: list[str] = field(default_factory=list)
    access_flags: int = 0


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise ClassFileError("truncated classfile")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u1(self) -> int:
        return self.take(1)[0]

    def u2(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u4(self) -> int:
        return struct.unpack(">I", self.take(4))[0]


def _class_name(pool: list[tuple | None], index: int) -> str:
    if not (0 < index < len(pool)):
        return ""
    entry = pool[index]
    if not entry:
        return ""
    tag, value = entry
    if tag != "class":
        return ""
    if isinstance(value, int) and 0 < value < len(pool):
        utf8_entry = pool[value]
        if utf8_entry and utf8_entry[0] == "utf8":
            return str(utf8_entry[1])
    return ""


def parse_class(data: bytes) -> ClassFile:
    """Parse a classfile header. Raises :class:`ClassFileError` on bad input."""
    if len(data) < 24 or bytes(data[:4]) != CLASS_MAGIC:
        raise ClassFileError("not a Java classfile (bad magic)")
    reader = _Reader(bytes(data))
    reader.pos = 8  # magic + minor + major
    constant_pool_count = reader.u2()
    if constant_pool_count <= 0 or constant_pool_count > 65535:
        raise ClassFileError("invalid constant pool size")

    pool: list[tuple | None] = [None] * constant_pool_count
    utf8_values: list[str] = []
    index = 1
    while index < constant_pool_count:
        tag = reader.u1()
        if tag == 1:  # Utf8
            length = reader.u2()
            value = reader.take(length).decode("utf-8", "replace")
            pool[index] = ("utf8", value)
            utf8_values.append(value)
        elif tag in (3, 4):  # Integer, Float
            reader.take(4)
            pool[index] = ("number", None)
        elif tag in (5, 6):  # Long, Double (two slots)
            reader.take(8)
            pool[index] = ("wide", None)
            index += 1
        elif tag == 7:  # Class
            pool[index] = ("class", reader.u2())
        elif tag == 8:  # String
            reader.take(2)
            pool[index] = ("string", None)
        elif tag in (9, 10, 11, 12, 17, 18):  # refs / descriptors
            reader.take(4)
            pool[index] = ("ref", None)
        elif tag == 15:  # MethodHandle
            reader.take(3)
            pool[index] = ("methodhandle", None)
        elif tag == 16:  # MethodType
            reader.take(2)
            pool[index] = ("methodtype", None)
        elif tag in (19, 20):  # Module, Package
            reader.take(2)
            pool[index] = ("module", None)
        else:
            raise ClassFileError(f"unknown constant pool tag {tag}")
        index += 1

    access_flags = reader.u2()
    this_index = reader.u2()
    super_index = reader.u2()
    interface_count = reader.u2()
    if interface_count > 65535:
        raise ClassFileError("invalid interface count")
    interfaces = [_class_name(pool, reader.u2()) for _ in range(interface_count)]

    return ClassFile(
        name=_class_name(pool, this_index),
        super_name=_class_name(pool, super_index),
        interfaces=interfaces,
        utf8=utf8_values,
        access_flags=access_flags,
    )


# ---------------------------------------------------------------------------
# Heuristic classification (no bytecode execution)
# ---------------------------------------------------------------------------

_KNOWN_SUPERS = {
    "block": {"Block"},
    "block_entity": {"BlockEntity", "BaseContainerBlockEntity"},
    "entity": {
        "Entity", "LivingEntity", "Mob", "Monster", "PathfinderMob", "Animal",
        "TamableAnimal", "WaterAnimal", "FlyingMob", "Raider", "Boss", "AmbientCreature",
    },
    "screen": {"Screen", "ContainerScreen"},
    "menu": {"AbstractContainerMenu"},
    "item": {
        "Item", "BlockItem", "SwordItem", "PickaxeItem", "AxeItem", "ShovelItem",
        "HoeItem", "DiggerItem", "TieredItem", "ArmorItem", "ProjectileItem",
    },
    "tool": {"SwordItem", "PickaxeItem", "AxeItem", "ShovelItem", "HoeItem", "DiggerItem", "TieredItem"},
    "armor": {"ArmorItem"},
    "food": {"FoodItem"},
    "recipe_serializer": {"RecipeSerializer", "RecipeType"},
}

_STRING_FACTS = {
    "mixin": ("org/spongepowered/asm/mixin", "mixinextras"),
    "block_entity": ("blockentity", "block entity"),
    "food": ("foodproperties", "foodproperties.builder", "nutrition"),
    "tool": ("toolmaterial", "tiertier", "tiereditem", "toolitem"),
    "armor": ("armormaterial", "armoritem"),
    "recipe_serializer": ("recipeserializer", "recipetype"),
    "command": ("commandregistrationcallback", "commands.literal", "commanddispatcher"),
    "network": ("payloadtyperegistry", "networkregistry", "packetbytebuf", "custompayload"),
    "event": ("subscribeevent", "eventbus"),
    "config": ("configscreen", "configbuilder", "clothconfig", "modmenu"),
    "gecko": ("software/bernie/geckolib", "geckolib"),
    "screen": ("net/minecraft/client/gui/screens",),
}


def classify_class(parsed: ClassFile, entry_path: str = "") -> set[str]:
    """Return heuristic facts for a class (used only as supporting evidence)."""
    facts: set[str] = set()
    path_lower = entry_path.lower()
    name_lower = parsed.name.lower()
    super_lower = parsed.super_name.lower()
    super_last = super_lower.rsplit("/", 1)[-1]
    strings_lower = " ".join(parsed.utf8).lower()

    if "/mixin/" in path_lower or name_lower.startswith("mixin") or "/mixin." in path_lower:
        facts.add("mixin")
    if super_last == "Block" or super_lower.endswith("/block"):
        facts.add("block")
    if super_last.endswith("BlockEntity") or super_last.endswith("BlockEntityBase"):
        facts.add("block_entity")
    if super_last in _KNOWN_SUPERS["entity"] or (super_lower.find("/entity/") >= 0 and super_last.endswith("Entity")):
        facts.add("entity")
    if super_last in _KNOWN_SUPERS["screen"]:
        facts.add("screen")
    if super_last in _KNOWN_SUPERS["menu"]:
        facts.add("menu")
    if super_last in _KNOWN_SUPERS["item"]:
        facts.add("item")
    if super_last in _KNOWN_SUPERS["tool"]:
        facts.add("tool")
    if super_last in _KNOWN_SUPERS["armor"]:
        facts.add("armor")
    if super_last in _KNOWN_SUPERS["food"]:
        facts.add("food")
    if super_last in _KNOWN_SUPERS["recipe_serializer"]:
        facts.add("recipe_serializer")

    for fact, needles in _STRING_FACTS.items():
        if fact in facts:
            continue
        if any(needle in strings_lower for needle in needles):
            facts.add(fact)
    return facts


def summarize_class(parsed: ClassFile, entry_path: str) -> dict[str, object]:
    facts = classify_class(parsed, entry_path)
    return {
        "name": parsed.name,
        "super": parsed.super_name,
        "path": entry_path,
        "facts": sorted(facts),
    }
