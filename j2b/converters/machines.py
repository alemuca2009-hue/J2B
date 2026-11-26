"""Create-style machine recipes → Bedrock custom crafting stations.

Create ships ~830 recipes that run on its own blocks (millstone, crushing
wheel, press, mixer, deployer, spout, saw…). Bedrock has no schema for a
custom recipe *type*, so those recipes used to be dropped as unsupported.

There is one honest mechanism that carries them across: a block can declare
``minecraft:crafting_table`` with a custom ``crafting_tags`` list, and recipes
tagged with that name then only run when the player uses **that block**. So the
machine keeps its identity — you still walk up to the millstone and put wheat
in it — while the process itself becomes a hand craft.

What is genuinely lost, and is reported as a limitation on every recipe:

* kinetic stress, rotation speed and the shaft network;
* processing time (the craft is instant);
* byproducts rolled by chance (a 25 % flint drop cannot be expressed);
* fluids consumed or produced by spouts and mixers.

Nothing here invents an output: only items the Java recipe actually declares
are written, and a recipe whose inputs cannot all be resolved is skipped
rather than shipped half-empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Machine:
    """One Create block that owns a family of processing recipes."""

    recipe_type: str
    block_id: str
    label: str
    grid: int = 3

    @property
    def tag(self) -> str:
        """Recipe tag; must match ``crafting_tags`` on the block component."""
        return "j2b_" + self.block_id.split(":")[-1]


#: Java recipe type -> the block that runs it. Only blocks the analyzer really
#: sees in the jar are useful here; a type whose block is missing from the pack
#: falls back to a plain workbench recipe (opt-in) or to the manual list.
MACHINES: tuple[Machine, ...] = (
    Machine("create:milling", "create:millstone", "Millstone"),
    Machine("create:crushing", "create:crushing_wheel", "Crushing Wheel"),
    Machine("create:pressing", "create:mechanical_press", "Mechanical Press"),
    Machine("create:compacting", "create:basin", "Basin"),
    Machine("create:mixing", "create:mechanical_mixer", "Mechanical Mixer"),
    Machine("create:splashing", "create:encased_fan", "Encased Fan"),
    Machine("create:haunting", "create:encased_fan", "Encased Fan"),
    Machine("create:filling", "create:spout", "Spout"),
    Machine("create:emptying", "create:spout", "Spout"),
    Machine("create:deploying", "create:deployer", "Deployer"),
    Machine("create:item_application", "create:deployer", "Deployer"),
    Machine("create:cutting", "create:mechanical_saw", "Mechanical Saw"),
)

_BY_TYPE: dict[str, Machine] = {}
_BY_BLOCK: dict[str, Machine] = {}
for _machine in MACHINES:
    _BY_TYPE.setdefault(_machine.recipe_type, _machine)
    _BY_BLOCK.setdefault(_machine.block_id, _machine)


def station_for_type(recipe_type: str) -> Machine | None:
    return _BY_TYPE.get(recipe_type)


def station_for_block(block_id: str) -> Machine | None:
    return _BY_BLOCK.get(block_id)


#: Types that cannot be carried at all, with the reason a human needs to hear.
INEXPRESSIBLE: dict[str, str] = {
    "create:sequenced_assembly": (
        "Sequenced assembly is a chain of deployer/press/spout steps over one "
        "in-progress item; Bedrock has no multi-stage machine state."
    ),
    "create:mechanical_crafting": (
        "Mechanical crafting uses a grid larger than 3x3."
    ),
    "create:item_copying": (
        "Item copying duplicates a schematic's own contents; there is no Bedrock item to copy."
    ),
    "create:toolbox_dyeing": (
        "Toolbox dyeing mutates an item's colour component; Bedrock items are static definitions."
    ),
}


# ---------------------------------------------------------------------------
# payload parsing
# ---------------------------------------------------------------------------
def _ingredient_list(payload: dict[str, Any]) -> list[Any]:
    """Every item ingredient of a Create processing recipe, in order.

    ``item_application`` keeps its tool in ``ingredients`` and its subject in
    ``targets``; both have to be in the grid or the recipe is wrong.
    """
    raw: list[Any] = []
    for key in ("targets", "ingredients", "ingredient"):
        value = payload.get(key)
        if isinstance(value, list):
            raw.extend(value)
        elif isinstance(value, (str, dict)) and value:
            raw.append(value)
    return [entry for entry in raw if not is_fluid(entry)]


def is_fluid(value: Any) -> bool:
    """A Create fluid stack is not an item and can never fill a recipe slot."""
    if not isinstance(value, dict):
        return False
    kind = str(value.get("type") or "")
    return kind in ("fluid_stack", "fluid_tag", "fluid") or (
        "fluid" in value and "item" not in value and "id" not in value
    )


@dataclass
class Output:
    item: str
    count: int
    chance: float


def _read_outputs(payload: dict[str, Any]) -> list[Output]:
    from ..id_map import map_block_id

    raw = payload.get("results")
    if raw is None:
        raw = payload.get("result") or payload.get("output")
    if not isinstance(raw, list):
        raw = [raw] if raw else []

    outputs: list[Output] = []
    for entry in raw:
        if not isinstance(entry, dict):
            if isinstance(entry, str):
                item, _note = map_block_id(entry, is_item=True)
                if item:
                    outputs.append(Output(item, 1, 1.0))
            continue
        identifier = entry.get("id") or entry.get("item") or entry.get("name")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        item, _note = map_block_id(identifier, is_item=True)
        if not item:
            continue
        count = entry.get("count")
        amount = int(count) if isinstance(count, (int, float)) and count > 0 else 1
        chance = entry.get("chance")
        probability = float(chance) if isinstance(chance, (int, float)) else 1.0
        outputs.append(Output(item, amount, max(0.0, min(1.0, probability))))
    return outputs


def primary_outputs(outputs: list[Output]) -> tuple[list[Output], bool]:
    """Guaranteed results only; if there are none, the likeliest one is kept.

    The returned flag says whether a chance-rolled byproduct had to be promoted
    to a guaranteed output, which the caller reports instead of hiding.
    """
    certain = [entry for entry in outputs if entry.chance >= 1.0]
    if certain:
        return certain, False
    if not outputs:
        return [], False
    best = max(outputs, key=lambda entry: entry.chance)
    return [best], True
