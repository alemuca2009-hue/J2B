"""Composing Java model rotations into something Bedrock can actually store.

Bedrock gives a cube exactly one rotation — ``[x, y, z]`` about a single
``pivot``. Java models routinely need two at once: the element carries its own
``rotation`` (a cog tilted 22.5°, a shaft laid on its side) *and* the blockstate
variant turns the whole model (``y: 90`` to face the player). Baking only the
variant used to throw the element rotation away, which is why tilted machinery
came out as plain slabs.

The way out is that the composition of two rotations is still a rotation, so it
has a single axis, a single angle and a single fixed point. Most of the time
that axis is *not* a coordinate axis — but the two factors are ``Ry(90)`` and
``Rx(22.5)``, and a quarter turn is a permutation of the axes. So any rotation
of the form ``P·S`` — a signed permutation followed by a single-axis turn — can
be written exactly in Bedrock: permute the box's corners and faces by ``P``,
then hand Bedrock the axis turn ``S`` about the mapped pivot.

That covers every combination a blockstate can produce, because blockstate
rotations are always multiples of 90° and element rotations are always a single
axis. The only genuinely unrepresentable case is a model rotated by a
*non*-quarter turn at two different points, and that one is reported with the
measured error in degrees instead of being silently approximated.

Conventions match Java's, so the numbers here agree with ``variants._rotate_point``:
``+x`` is east, ``+y`` up, ``+z`` south, angles right-handed about their axis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import permutations
from typing import Any, Iterable

AXES = {"x": 0, "y": 1, "z": 2}
EPS = 1e-6

Matrix = list[list[float]]


# --------------------------------------------------------------------------
# small 3x3 linear algebra
# --------------------------------------------------------------------------
def identity() -> Matrix:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def mat_mul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(m: Matrix, v: Iterable[float]) -> list[float]:
    x, y, z = v
    return [
        m[0][0] * x + m[0][1] * y + m[0][2] * z,
        m[1][0] * x + m[1][1] * y + m[1][2] * z,
        m[2][0] * x + m[2][1] * y + m[2][2] * z,
    ]


def det(m: Matrix) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def transpose(m: Matrix) -> Matrix:
    return [[m[j][i] for j in range(3)] for i in range(3)]


def max_abs_diff(a: Matrix, b: Matrix) -> float:
    return max(abs(a[i][j] - b[i][j]) for i in range(3) for j in range(3))


def axis_matrix(axis: str | int, degrees: float) -> Matrix:
    """Rotation by ``degrees`` about a coordinate axis.

    The sign convention is Java's, and matches ``variants._rotate_point``:
    ``y: 90`` sends ``+x`` (east) to ``+z`` (south), ``x: 90`` sends ``+y`` (up)
    to ``-z`` (north). Both are what an in-game blockstate does.
    """
    index = AXES[axis] if isinstance(axis, str) else axis
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    if index == 0:
        return [[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]]
    if index == 1:
        return [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]
    return [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]


def _clean(m: Matrix) -> Matrix:
    return [[0.0 if abs(value) < 1e-12 else value for value in row] for row in m]


# --------------------------------------------------------------------------
# reading a matrix back as an angle about a coordinate axis
# --------------------------------------------------------------------------
def as_coordinate_rotation(m: Matrix, tolerance: float = 1e-9) -> tuple[int, float] | None:
    """Return ``(axis index, degrees)`` when ``m`` turns about one coordinate axis.

    ``None`` means Bedrock's single-axis rotation field cannot hold it.

    The angle is recovered by reconstruction rather than from one ``atan2`` term:
    the three planes do not share a sign convention (``y`` reads ``(x, z)`` while
    ``x`` reads ``(y, z)``), so the candidate that actually rebuilds ``m`` is the
    one that gets returned.
    """
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        basis = [0.0, 0.0, 0.0]
        basis[axis] = 1.0
        image = mat_vec(m, basis)
        if abs(image[axis] - 1.0) > tolerance:
            continue
        if any(abs(image[i]) > tolerance for i in others):
            continue
        a, b = others[0], others[1]
        for degrees in (math.degrees(math.atan2(m[b][a], m[a][a])),
                        math.degrees(math.atan2(-m[b][a], m[a][a]))):
            angle = _normalise_angle(degrees)
            if max_abs_diff(axis_matrix(axis, angle), m) <= max(tolerance, 1e-7):
                return axis, angle
    return None


def _normalise_angle(degrees: float) -> float:
    value = math.fmod(degrees, 360.0)
    if value <= -180.0:
        value += 360.0
    if value > 180.0:
        value -= 360.0
    return 0.0 if abs(value) < 1e-9 else round(value, 9)


def rotation_angle(m: Matrix) -> float:
    """Total turn of the matrix, in degrees, ignoring which axis it is about."""
    trace = m[0][0] + m[1][1] + m[2][2]
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return math.degrees(math.acos(cosine))


def best_coordinate_rotation(m: Matrix) -> tuple[int, float, float]:
    """Nearest single-axis rotation: ``(axis, degrees, residual degrees)``.

    Used only when the rotation genuinely cannot be expressed; the third value
    is how far the approximation is from the real transform, in degrees, so the
    report can state it instead of claiming success.
    """
    best: tuple[int, float, float] | None = None
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        a, b = others[0], others[1]
        for degrees in (math.degrees(math.atan2(m[b][a], m[a][a])),
                        math.degrees(math.atan2(-m[b][a], m[a][a]))):
            angle = _normalise_angle(degrees)
            error = _angle_between(axis_matrix(axis, angle), m)
            if best is None or error < best[2] - 1e-9:
                best = (axis, angle, error)
    assert best is not None
    return best


def _angle_between(a: Matrix, b: Matrix) -> float:
    """Angle of the rotation taking ``a`` to ``b``, in degrees."""
    relative = mat_mul(transpose(a), b)
    return rotation_angle(relative)


# --------------------------------------------------------------------------
# signed permutations: the quarter-turn part
# --------------------------------------------------------------------------
def as_permutation(m: Matrix, tolerance: float = 1e-9) -> Matrix | None:
    """Return the integer matrix when ``m`` only swaps/flips axes, else ``None``."""
    rounded = [[float(round(value)) for value in row] for row in m]
    if max_abs_diff(rounded, m) > tolerance:
        return None
    for row in rounded:
        values = [abs(value) for value in row]
        if sorted(values) != [0.0, 0.0, 1.0]:
            return None
    for column in range(3):
        values = sorted(abs(rounded[row][column]) for row in range(3))
        if values != [0.0, 0.0, 1.0]:
            return None
    if det(rounded) < 0.5:  # a mirror is not a rotation
        return None
    return rounded


def _permutations() -> list[Matrix]:
    out: list[Matrix] = []
    for order in permutations(range(3)):
        for signs in ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, 1), (-1, 1, -1), (-1, -1, 1), (-1, -1, -1)):
            m = [[0.0, 0.0, 0.0] for _ in range(3)]
            for row in range(3):
                m[row][order[row]] = float(signs[row])
            if det(m) > 0.5:
                out.append(m)
    return out


PERMUTATIONS: list[Matrix] = _permutations()


def split_permutation(m: Matrix, tolerance: float = 1e-9) -> tuple[Matrix, int, float] | None:
    """Write ``m`` as ``permutation · rotation-about-one-axis``.

    Returns ``(permutation, axis, degrees)`` when such a split exists, which is
    the case for every rotation a blockstate can build: its own quarter turns
    are permutations, and element rotations are single-axis. ``None`` when the
    composition is genuinely a compound turn.
    """
    # A pure quarter turn is best baked whole: sending it to Bedrock's rotation
    # field instead would work, but the geometry is then readable and matches
    # what the blockstate actually says.
    whole = as_permutation(m, tolerance)
    if whole is not None:
        return whole, 0, 0.0
    # More than one permutation usually works (a 90° turn bundled with a tilt
    # can be read several ways). The one leaving the smallest residual angle is
    # the readable one: the permutation keeps the quarter turns, the axis turn
    # keeps only the authored tilt.
    best: tuple[Matrix, int, float] | None = None
    for perm in PERMUTATIONS:
        residual = mat_mul(transpose(perm), m)
        found = as_coordinate_rotation(residual, tolerance)
        if found is None:
            continue
        _axis, degrees = found
        if best is None or abs(degrees) < abs(best[2]) - 1e-9:
            best = (perm, _axis, degrees)
    return best


# --------------------------------------------------------------------------
# placements: a matrix plus the point it turns about
# --------------------------------------------------------------------------
@dataclass
class Placement:
    """A rotation about a point, in Java model space (0..16)."""

    matrix: Matrix = field(default_factory=identity)
    pivot: list[float] = field(default_factory=lambda: [8.0, 8.0, 8.0])

    @classmethod
    def about(cls, axis: str | int, degrees: float, pivot: Iterable[float] | None = None) -> "Placement":
        point = list(pivot) if pivot is not None else [8.0, 8.0, 8.0]
        return cls(axis_matrix(axis, degrees), point)

    @property
    def is_identity(self) -> bool:
        return max_abs_diff(self.matrix, identity()) < EPS

    def apply(self, point: Iterable[float]) -> list[float]:
        return _apply_affine(self, point)

    def then(self, outer: "Placement") -> "Placement":
        """This transform applied first, then ``outer``."""
        return compose(self, outer)


def _translation(placement: Placement) -> list[float]:
    """``t`` such that the map is ``x -> M x + t``."""
    p = placement.pivot
    mp = mat_vec(placement.matrix, p)
    return [p[i] - mp[i] for i in range(3)]


def _apply_affine(placement: Placement, point: Iterable[float]) -> list[float]:
    t = _translation(placement)
    mp = mat_vec(placement.matrix, point)
    return [mp[i] + t[i] for i in range(3)]


def _fixed_point(m: Matrix, t: list[float], hint: list[float]) -> list[float]:
    """Solve ``(I - m) p = t`` for the rotation's own fixed point."""
    n = [[(1.0 if i == j else 0.0) - m[i][j] for j in range(3)] for i in range(3)]
    if max_abs_diff(m, identity()) < EPS:
        return list(hint)
    # (I-m)^T (I-m) == (2-2cos) * (I - a a^T), so the pseudo-inverse on the plane
    # perpendicular to the axis is (I-m)^T / (2-2cos); along the axis it is zero.
    trace = m[0][0] + m[1][1] + m[2][2]
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    scale = 2.0 - 2.0 * cosine
    if scale < 1e-9:
        return list(hint)
    nt = transpose(n)
    solved = [sum(nt[i][j] * t[j] for j in range(3)) / scale for i in range(3)]
    axis = _rotation_axis(m)
    if axis is None:
        return solved
    along = sum(solved[i] * axis[i] for i in range(3))
    keep = sum(hint[i] * axis[i] for i in range(3))
    return [solved[i] + (keep - along) * axis[i] for i in range(3)]


def _rotation_axis(m: Matrix) -> list[float] | None:
    """Unit axis of the rotation, or ``None`` when the trace makes it ambiguous."""
    axis = [
        m[2][1] - m[1][2],
        m[0][2] - m[2][0],
        m[1][0] - m[0][1],
    ]
    length = math.sqrt(sum(value * value for value in axis))
    if length < 1e-9:
        return None
    return [value / length for value in axis]


def compose(inner: Placement, outer: Placement) -> Placement:
    """The single rotation equivalent to ``inner`` followed by ``outer``.

    Composition of two rotations about two different points is still a rotation,
    just about a third point — that point is what gets solved for here.
    """
    m = mat_mul(outer.matrix, inner.matrix)
    t_inner = _translation(inner)
    t_outer = _translation(outer)
    rotated = mat_vec(outer.matrix, t_inner)
    t = [rotated[i] + t_outer[i] for i in range(3)]
    pivot = _fixed_point(m, t, inner.pivot)
    return Placement(_clean(m), [round(value, 9) for value in pivot])


# --------------------------------------------------------------------------
# baking a quarter turn into a box
# --------------------------------------------------------------------------
_FACE_NORMALS = {
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
}
_NORMAL_FACES = {value: key for key, value in _FACE_NORMALS.items()}


def _permute_corners(
    low: list[float],
    high: list[float],
    perm: Matrix,
    pivot: Iterable[float] = (0.0, 0.0, 0.0),
) -> tuple[list[float], list[float]]:
    """The box a quarter turn about ``pivot`` maps it to."""
    ox, oy, oz = pivot
    corners = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                moved = mat_vec(perm, [x - ox, y - oy, z - oz])
                corners.append([moved[0] + ox, moved[1] + oy, moved[2] + oz])
    new_low = [round(min(corner[axis] for corner in corners), 9) for axis in range(3)]
    new_high = [round(max(corner[axis] for corner in corners), 9) for axis in range(3)]
    return new_low, new_high


def permute_face(face: str, perm: Matrix) -> str:
    """The face a quad ends up on once its box is permuted."""
    vector = _FACE_NORMALS.get(face)
    if vector is None:
        return face
    moved = mat_vec(perm, vector)
    key = tuple(int(round(value)) for value in moved)
    return _NORMAL_FACES.get(key, face)


@dataclass
class BakedElement:
    """One element after a rotation has been applied to it."""

    low: list[float]
    high: list[float]
    faces: dict[str, Any]
    #: Rotation Bedrock still has to perform, in Java model space.
    residual_angle: float = 0.0
    residual_axis: str | None = None
    residual_pivot: list[float] | None = None
    exact: bool = True
    error_degrees: float = 0.0
    note: str | None = None


def bake_box(
    low: list[float],
    high: list[float],
    faces: dict[str, Any],
    placement: Placement,
) -> BakedElement:
    """Apply ``placement`` to an axis-aligned box.

    Splits the transform into the quarter-turn part, which is folded into the
    box's corners and face names, and the fractional part, which Bedrock keeps
    as a ``rotation`` about a ``pivot``. When the transform cannot be split that
    way the nearest single-axis turn is used and the error is measured.
    """
    base_out = BakedElement(low=list(low), high=list(high), faces=dict(faces))

    if placement.is_identity:
        return base_out

    split = split_permutation(placement.matrix)
    perm = identity()
    remaining = placement

    if split is not None:
        perm, _axis, _degrees = split
        if max_abs_diff(perm, identity()) > EPS:
            base_out.low, base_out.high = _permute_corners(low, high, perm, placement.pivot)
            remapped: dict[str, Any] = {}
            for face, spec in base_out.faces.items():
                moved = permute_face(face, perm)
                # A permutation never mirrors, so UVs travel untouched.
                if moved in remapped:
                    moved = face
                remapped[moved] = spec
            base_out.faces = remapped
        # Folding ``perm`` into the box leaves a turn about the *same* pivot:
        # with ``M = A·S`` the residual is ``A·S·A⁻¹`` — still a coordinate axis
        # turn — and it turns about the point the whole transform turned about.
        remaining = Placement(mat_mul(placement.matrix, transpose(perm)), placement.pivot)
    else:
        axis, degrees, error = best_coordinate_rotation(placement.matrix)
        base_out.exact = False
        base_out.error_degrees = error
        base_out.note = (
            f"rotation combines two axes at different points; the nearest single-axis turn "
            f"({degrees:g}° about {'xyz'[axis]}) is used and differs from the real transform by {error:.1f}°."
        )
        remaining = Placement(axis_matrix(axis, degrees), placement.pivot)

    found = as_coordinate_rotation(remaining.matrix)
    if found is not None:
        axis, degrees = found
        if abs(degrees) > 1e-9:
            base_out.residual_axis = "xyz"[axis]
            base_out.residual_angle = degrees
            base_out.residual_pivot = [round(value, 6) for value in remaining.pivot]
    return base_out


def element_placement(element: dict[str, Any]) -> Placement | None:
    """Read a Java element ``rotation`` block."""
    spec = element.get("rotation")
    if not isinstance(spec, dict):
        return None
    axis = str(spec.get("axis") or "").lower()
    if axis not in AXES:
        return None
    try:
        angle = float(spec.get("angle") or 0.0)
    except (TypeError, ValueError):
        return None
    if angle == 0.0:
        return None
    origin = spec.get("origin")
    pivot = [8.0, 8.0, 8.0]
    if isinstance(origin, (list, tuple)) and len(origin) == 3:
        try:
            pivot = [float(value) for value in origin]
        except (TypeError, ValueError):
            pivot = [8.0, 8.0, 8.0]
    return Placement.about(axis, angle, pivot)


def blockstate_placement(x_deg: float, y_deg: float, centre: Iterable[float] = (8.0, 8.0, 8.0)) -> Placement:
    """Java's blockstate ``x`` then ``y``, both about the block centre."""
    placed = Placement.about("x", x_deg, centre).then(Placement.about("y", y_deg, centre))
    return placed
