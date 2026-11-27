"""Resolution of Java block/item models.

A blockstate points at a model, and that model may inherit from a parent one or
more levels up. Classifying a block by the *name* of its parent throws away the
geometry that is sitting in the file, so this module walks the whole chain and
returns the model that actually declares ``elements``.

Four kinds of parent are handled separately, because they have different
levels of certainty:

``resolved``
    Every file was found inside the jar. The elements are the mod's own.
``vanilla``
    The chain lands on a vanilla model that is not in the mod, but a reference
    jar was supplied and the model was read from it. This is the exact Mojang
    geometry, so it is treated as authoritative.
``template``
    The chain lands on a vanilla model file that is not in the jar. A curated
    template with the documented shape is used and flagged as such.
``missing``
    Nothing could be found. The caller must report it; nothing is invented.

Passing a reference jar (a vanilla client jar, or any zip holding
``assets/minecraft/models/*.json``) is the biggest fidelity lever for mods that
inherit from vanilla shapes: the templates encode the common cases, but only the
jar knows every model Mojang ships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .mod_archive import ModArchive

MODELS = "assets/{namespace}/models/{path}.json"

# Textures a vanilla template expects, in the order they should be consulted.
TEMPLATE_TEXTURE_KEYS = ("particle",)


@dataclass
class ResolvedModel:
    """The outcome of walking a model's inheritance chain."""

    identifier: str
    chain: list[str] = field(default_factory=list)
    elements: list[dict[str, Any]] | None = None
    textures: dict[str, str] = field(default_factory=dict)
    raw_textures: dict[str, str] = field(default_factory=dict)
    element_source: str = ""
    template: str = ""
    missing_parents: list[str] = field(default_factory=list)
    cycles: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    ambient_occlusion: bool = True
    gui_light: str = ""
    display: dict[str, Any] = field(default_factory=dict)
    texture_size: tuple[int, int] = (16, 16)

    @property
    def resolved(self) -> bool:
        return bool(self.elements)

    @property
    def is_full_cube(self) -> bool:
        if not self.elements:
            return False
        if len(self.elements) != 1:
            return False
        element = self.elements[0]
        if element.get("rotation"):
            return False
        low = element.get("from") or []
        high = element.get("to") or []
        if len(low) != 3 or len(high) != 3:
            return False
        try:
            return all(
                abs(min(low[i], high[i]) - 0.0) < 1e-6 and abs(max(low[i], high[i]) - 16.0) < 1e-6
                for i in range(3)
            )
        except TypeError:
            return False

    def face_texture(self, element: dict[str, Any], face: str) -> str:
        faces = element.get("faces") if isinstance(element.get("faces"), dict) else {}
        entry = faces.get(face) if isinstance(faces, dict) else None
        if isinstance(entry, dict):
            ref = entry.get("texture")
            if isinstance(ref, str):
                return ref
        return "#particle"

    def describe_source(self) -> str:
        if self.template:
            return f"vanilla template {self.template}"
        if self.element_source.startswith("vanilla:"):
            return f"vanilla model {self.element_source[len('vanilla:'):]}"
        if self.element_source:
            return self.element_source
        return "unresolved"


def normalise(model_ref: str, default_namespace: str) -> tuple[str, str]:
    """``""" + 'block/shaft' + """`` -> ``("minecraft", "block/shaft")``."""
    ref = str(model_ref or "").strip()
    if not ref:
        return default_namespace, ""
    if ref.startswith("models/"):
        ref = ref[len("models/") :]
    if ref.endswith(".json"):
        ref = ref[:-5]
    if ":" in ref:
        namespace, _, path = ref.partition(":")
        return namespace or default_namespace, path.lstrip("/")
    return default_namespace, ref.lstrip("/")


class ModelResolver:
    """Walks model inheritance inside one jar, with a vanilla fallback table."""

    def __init__(self, archive: ModArchive | None, vanilla: ModArchive | None = None) -> None:
        self.archive = archive
        self.vanilla = vanilla
        self._cache: dict[str, ResolvedModel] = {}
        #: Vanilla models actually read from the reference jar.
        self.vanilla_hits: set[str] = set()
        #: Curated templates used because no reference jar supplied the model.
        self.template_hits: set[str] = set()
        self.missing_models: set[str] = set()

    # -- io ---------------------------------------------------------------
    def _load(self, namespace: str, path: str) -> dict[str, Any] | None:
        if not path:
            return None
        relative = MODELS.format(namespace=namespace, path=path)
        if self.archive is not None:
            payload = self.archive.json(relative)
            if isinstance(payload, dict):
                return payload
        if self.vanilla is not None:
            payload = self.vanilla.json(relative)
            if isinstance(payload, dict):
                return payload
        return None

    def _origin(self, namespace: str, path: str) -> str:
        """Where a model file came from: ``mod``, ``vanilla`` or ``\"\"``."""
        relative = MODELS.format(namespace=namespace, path=path)
        if self.archive is not None and self.archive.exists(relative):
            return "mod"
        if self.vanilla is not None and self.vanilla.exists(relative):
            return "vanilla"
        return ""

    # -- public -----------------------------------------------------------
    def resolve(self, model_ref: str, default_namespace: str = "minecraft") -> ResolvedModel:
        namespace, path = normalise(model_ref, default_namespace)
        key = f"{namespace}:{path}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._walk(namespace, path)
        self._cache[key] = result
        return result

    def resolve_for_block(self, model_ref: str, block_namespace: str) -> ResolvedModel:
        """Block models default to the block's own namespace, not ``minecraft``."""
        return self.resolve(model_ref, block_namespace)

    # -- walking ----------------------------------------------------------
    def _walk(self, namespace: str, path: str) -> ResolvedModel:
        result = ResolvedModel(identifier=f"{namespace}:{path}")
        seen: list[str] = []
        textures: dict[str, str] = {}
        current_ns, current_path = namespace, path
        found_elements = False
        found_ao = False

        while True:
            key = f"{current_ns}:{current_path}"
            if key in seen:
                # ``create:block/block`` inherits from ``block/block``, which resolves
                # back to itself. That is a terminating alias, not a broken model: it
                # only matters when nothing further up supplied geometry.
                result.cycles.append(key)
                if not found_elements:
                    result.problems.append(f"Model inheritance loops back to `{key}`.")
                break
            seen.append(key)

            model = self._load(current_ns, current_path)
            if model is None:
                template = VANILLA_TEMPLATES.get(current_path) if current_ns == "minecraft" else None
                if template is not None:
                    result.template = f"{current_ns}:{current_path}"
                    self.template_hits.add(result.template)
                    if not found_elements:
                        result.elements = template["elements"]() if callable(template.get("elements")) else template.get("elements")
                        result.element_source = f"template:{result.template}"
                        found_elements = True
                    for key_name, default in (template.get("textures") or {}).items():
                        textures.setdefault(key_name, default)
                else:
                    self.missing_models.add(f"{current_ns}:{current_path}")
                    result.missing_parents.append(f"{current_ns}:{current_path}")
                break

            result.chain.append(key)
            origin = self._origin(current_ns, current_path)
            if origin == "vanilla":
                self.vanilla_hits.add(key)
            for name, value in (model.get("textures") or {}).items():
                if isinstance(value, str):
                    textures.setdefault(name, value)
            if isinstance(model.get("ambientocclusion"), bool) and not found_ao:
                result.ambient_occlusion = model["ambientocclusion"]
                found_ao = True
            if isinstance(model.get("gui_light"), str) and not result.gui_light:
                result.gui_light = model["gui_light"]
            if isinstance(model.get("display"), dict):
                result.display = {**model["display"], **result.display}
            if isinstance(model.get("elements"), list) and not found_elements:
                result.elements = model["elements"]
                result.element_source = f"vanilla:{key}" if origin == "vanilla" else key
                found_elements = True

            parent = model.get("parent")
            if not isinstance(parent, str) or not parent.strip():
                break
            current_ns, current_path = normalise(parent, "minecraft")

        result.raw_textures = dict(textures)
        result.textures, unresolved = _dereference(textures)
        for name in unresolved:
            result.problems.append(f"Texture variable `#{name}` never reaches a real texture.")
        if result.missing_parents:
            result.problems.append(
                "Model parent(s) not present in the jar: "
                + ", ".join(result.missing_parents)
                + ". Nothing was assumed about their shape."
            )
        return result


def _dereference(textures: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Resolve ``#alias`` chains to concrete resource references."""
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for name in list(textures):
        value = textures.get(name, "")
        seen = {name}
        while isinstance(value, str) and value.startswith("#"):
            target = value[1:]
            if target in seen:
                value = ""
                break
            seen.add(target)
            value = textures.get(target, "")
        if isinstance(value, str) and value and not value.startswith("#"):
            resolved[name] = value
        else:
            unresolved.append(name)
    return resolved, unresolved


# ---------------------------------------------------------------------------
# Vanilla templates
# ---------------------------------------------------------------------------
# Only shapes that can be stated exactly are listed. Each entry returns the
# element list a vanilla model of that name declares; faces use ``#key`` names
# that the block's own ``textures`` map then fills in. A template that is not
# here is *not* guessed at.


def _cube_all() -> list[dict[str, Any]]:
    return [_box((0, 0, 0), (16, 16, 16), {"down": "#all", "up": "#all", "north": "#all", "south": "#all", "west": "#all", "east": "#all"})]


def _cube() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 0, 0),
            (16, 16, 16),
            {"down": "#down", "up": "#up", "north": "#north", "south": "#south", "west": "#west", "east": "#east"},
        )
    ]


def _cube_column() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 0, 0),
            (16, 16, 16),
            {"down": "#end", "up": "#end", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        )
    ]


def _orientable() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 0, 0),
            (16, 16, 16),
            {"down": "#top", "up": "#top", "north": "#front", "south": "#side", "west": "#side", "east": "#side"},
        )
    ]


def _cube_bottom_top() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 0, 0),
            (16, 16, 16),
            {"down": "#bottom", "up": "#top", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        )
    ]


def _slab() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 0, 0),
            (16, 8, 16),
            {"down": "#bottom", "up": "#top", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        )
    ]


def _slab_top() -> list[dict[str, Any]]:
    return [
        _box(
            (0, 8, 0),
            (16, 16, 16),
            {"down": "#bottom", "up": "#top", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        )
    ]


def _carpet() -> list[dict[str, Any]]:
    return [
        _box((0, 0, 0), (16, 1, 16), {"down": "#wool", "up": "#wool", "north": "#wool", "south": "#wool", "west": "#wool", "east": "#wool"})
    ]


def _cross() -> list[dict[str, Any]]:
    return [
        _box((0.8, 0, 8), (15.2, 16, 8), {"north": "#cross", "south": "#cross"}, rotation={"origin": [8, 8, 8], "axis": "y", "angle": 45}),
        _box((8, 0, 0.8), (8, 16, 15.2), {"west": "#cross", "east": "#cross"}, rotation={"origin": [8, 8, 8], "axis": "y", "angle": -45}),
    ]


def _pane_post() -> list[dict[str, Any]]:
    return [
        _box(
            (7, 0, 7),
            (9, 16, 9),
            {"down": "#pane", "up": "#pane", "north": "#pane", "south": "#pane", "west": "#pane", "east": "#pane"},
        )
    ]


def _pane_side() -> list[dict[str, Any]]:
    return [
        _box((7, 0, 0), (9, 16, 7), {"west": "#pane", "east": "#pane"}),
        _box((7, 16, 0), (9, 16, 7), {"up": "#pane"}),
    ]


def _fence_post() -> list[dict[str, Any]]:
    return [
        _box((6, 0, 6), (10, 16, 10), {"down": "#texture", "up": "#texture", "north": "#texture", "south": "#texture", "west": "#texture", "east": "#texture"})
    ]


def _fence_side() -> list[dict[str, Any]]:
    return [
        _box((7, 12, 0), (9, 15, 6), {"west": "#texture", "east": "#texture"}),
        _box((7, 6, 0), (9, 9, 6), {"west": "#texture", "east": "#texture"}),
    ]


def _wall_post() -> list[dict[str, Any]]:
    return [
        _box((4, 0, 4), (12, 16, 12), {"down": "#wall", "up": "#wall", "north": "#wall", "south": "#wall", "west": "#wall", "east": "#wall"})
    ]


def _wall_side() -> list[dict[str, Any]]:
    return [
        _box((5, 0, 0), (11, 14, 4), {"down": "#wall", "up": "#wall", "north": "#wall", "south": "#wall", "west": "#wall", "east": "#wall"})
    ]


def _wall_side_tall() -> list[dict[str, Any]]:
    return [
        _box((5, 0, 0), (11, 16, 4), {"down": "#wall", "up": "#wall", "north": "#wall", "south": "#wall", "west": "#wall", "east": "#wall"})
    ]


def _pressure_plate_up() -> list[dict[str, Any]]:
    return [
        _box((1, 0, 1), (15, 1, 15), {"down": "#texture", "up": "#texture", "north": "#texture", "south": "#texture", "west": "#texture", "east": "#texture"})
    ]


def _button() -> list[dict[str, Any]]:
    return [
        _box((5, 6, 1), (11, 10, 2), {"down": "#texture", "up": "#texture", "north": "#texture", "south": "#texture", "west": "#texture", "east": "#texture"})
    ]


def _torch() -> list[dict[str, Any]]:
    return [
        _box((7, 0, 7), (9, 10, 9), {"down": "#torch", "up": "#torch", "north": "#torch", "south": "#torch", "west": "#torch", "east": "#torch"}),
    ]


def _stairs() -> list[dict[str, Any]]:
    """Default stairs orientation: full lower half, upper half on the +x side."""
    return [
        _box(
            (0, 0, 0),
            (16, 8, 16),
            {"down": "#bottom", "up": "#top", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        ),
        _box(
            (8, 8, 0),
            (16, 16, 16),
            {"down": "#bottom", "up": "#top", "north": "#side", "south": "#side", "west": "#side", "east": "#side"},
        ),
    ]


def _door_bottom() -> list[dict[str, Any]]:
    return [
        _box((0, 0, 0), (3, 16, 16), {"north": "#bottom", "south": "#bottom", "west": "#bottom", "east": "#bottom"}),
    ]


def _box(low: tuple[float, float, float], high: tuple[float, float, float], faces: dict[str, str], rotation: dict[str, Any] | None = None) -> dict[str, Any]:
    element: dict[str, Any] = {
        "from": list(low),
        "to": list(high),
        "faces": {name: {"texture": ref} for name, ref in faces.items()},
    }
    if rotation:
        element["rotation"] = rotation
    return element


def _template(elements, textures: dict[str, str] | None = None, exact: bool = True) -> dict[str, Any]:
    return {"elements": elements, "textures": textures or {}, "exact": exact}


VANILLA_TEMPLATES: dict[str, dict[str, Any]] = {
    "block/block": _template(lambda: [], {}),
    "block/cube": _template(_cube, {"particle": "#north"}, exact=False),
    "block/cube_all": _template(_cube_all, {"particle": "#all"}),
    "block/cube_column": _template(_cube_column, {"particle": "#side"}),
    "block/cube_column_horizontal": _template(_cube_column, {"particle": "#side"}),
    "block/cube_bottom_top": _template(_cube_bottom_top, {"particle": "#side"}),
    "block/cube_top": _template(_cube_bottom_top, {"particle": "#side"}),
    "block/cube_directional": _template(_cube, {"particle": "#north"}, exact=False),
    "block/orientable": _template(_orientable, {"particle": "#front"}),
    "block/orientable_with_bottom": _template(_orientable, {"particle": "#front"}),
    "block/orientable_vertical": _template(_orientable, {"particle": "#front"}),
    "block/slab": _template(_slab, {"particle": "#side"}),
    "block/slab_top": _template(_slab_top, {"particle": "#side"}),
    "block/carpet": _template(_carpet, {"particle": "#wool"}),
    "block/cross": _template(_cross, {"particle": "#cross"}),
    "block/tinted_cross": _template(_cross, {"particle": "#cross"}),
    "block/template_glass_pane_post": _template(_pane_post, {"particle": "#pane"}),
    "block/template_glass_pane_side": _template(_pane_side, {"particle": "#pane"}),
    "block/template_glass_pane_noside": _template(_pane_post, {"particle": "#pane"}),
    "block/iron_bars_post": _template(_pane_post, {"particle": "#pane"}),
    "block/iron_bars_side": _template(_pane_side, {"particle": "#pane"}),
    "block/fence_post": _template(_fence_post, {"particle": "#texture"}),
    "block/fence_side": _template(_fence_side, {"particle": "#texture"}),
    "block/wall_post": _template(_wall_post, {"particle": "#wall"}),
    "block/wall_side": _template(_wall_side, {"particle": "#wall"}),
    "block/wall_side_tall": _template(_wall_side_tall, {"particle": "#wall"}),
    "block/pressure_plate_up": _template(_pressure_plate_up, {"particle": "#texture"}),
    "block/pressure_plate_down": _template(_pressure_plate_up, {"particle": "#texture"}),
    "block/button": _template(_button, {"particle": "#texture"}),
    "block/button_pressed": _template(_button, {"particle": "#texture"}),
    "block/torch": _template(_torch, {"particle": "#torch"}),
    "block/template_torch": _template(_torch, {"particle": "#torch"}),
    "block/door_bottom_left": _template(_door_bottom, {"particle": "#bottom"}),
    "block/door_bottom": _template(_door_bottom, {"particle": "#bottom"}),
    "block/air": _template(lambda: [], {"particle": "#particle"}),
    "block/template_wall_post": _template(_wall_post, {"particle": "#wall"}),
    "block/template_wall_side": _template(_wall_side, {"particle": "#wall"}),
    "block/template_wall_side_tall": _template(_wall_side_tall, {"particle": "#wall"}),
    "block/stairs": _template(_stairs, {"particle": "#side"}, exact=False),
    "block/inner_stairs": _template(_stairs, {"particle": "#side"}, exact=False),
    "block/outer_stairs": _template(_stairs, {"particle": "#side"}, exact=False),
    # ``*_alt`` is the same quad/arm mirrored onto the opposite inner face. The
    # shape is symmetric about the pane plane, so the base template is the right
    # geometry; only which face carries the texture differs.
    "block/template_glass_pane_noside_alt": _template(_pane_post, {"particle": "#pane"}, exact=False),
    "block/template_glass_pane_side_alt": _template(_pane_side, {"particle": "#pane"}, exact=False),
}

# Aliases vanilla uses so a block does not have to repeat a parent path.
for _alias, _target in (
    ("block/air", "block/air"),
    ("block/cube_north_mirrored", "block/cube"),
    ("block/cube_mirrored_all", "block/cube_all"),
    ("block/cube_mirrored", "block/cube"),
    ("block/cube_cutout", "block/cube_all"),
    ("block/orientable_with_bottom_and_side", "block/orientable"),
    ("block/leaves", "block/cube_all"),
    ("block/stairs", None),
    ("block/inner_stairs", None),
    ("block/outer_stairs", None),
):
    if _target and _target in VANILLA_TEMPLATES and _alias not in VANILLA_TEMPLATES:
        VANILLA_TEMPLATES[_alias] = VANILLA_TEMPLATES[_target]

#: Templates whose entry is a faithful reproduction of the vanilla model.
EXACT_TEMPLATES = {name for name, spec in VANILLA_TEMPLATES.items() if spec.get("exact", True)}
