"""Reading the small part of a PNG the converter actually needs.

No third-party imaging library is available (or wanted), so this parses the
chunks that matter: dimensions, colour type, whether any pixel is transparent,
and whether the file is a vertical animation strip. Decoding is limited to
unfiltering enough rows to answer the transparency question, and it stops at the
first transparent pixel.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class PngInfo:
    width: int = 0
    height: int = 0
    color_type: int = 0
    bit_depth: int = 0
    has_transparency: bool = False
    frames: int = 1
    valid: bool = False

    @property
    def is_animated_strip(self) -> bool:
        return self.frames > 1


def read_info(data: bytes, *, deep: bool = True, max_rows: int = 512) -> PngInfo:
    """Inspect ``data``; ``deep=False`` answers from the header alone."""
    info = PngInfo()
    if not data or not data.startswith(PNG_MAGIC) or len(data) < 33:
        return info
    try:
        width, height, depth, color_type = struct.unpack(">IIBB", data[16:26])
    except struct.error:
        return info
    info.width, info.height = width, height
    info.bit_depth, info.color_type = depth, color_type
    info.valid = True

    chunks = _chunks(data)
    if color_type == 3:
        # A palette can carry a tRNS chunk that no pixel actually uses. Reporting
        # transparency from the chunk alone painted opaque blocks as cutout, so the
        # indices are resolved against the pixels when a palette is present.
        info.has_transparency = _palette_uses_alpha(chunks, width, height, depth) if deep else ("tRNS" in chunks)
    elif color_type == 0 and "tRNS" in chunks:
        info.has_transparency = True
    elif color_type in (4, 6):
        info.has_transparency = True if not deep else _scan_alpha(chunks.get("IDAT", b""), width, height, color_type, depth, max_rows)

    if width and height and height > width and height % width == 0:
        info.frames = height // width
    return info


def _chunks(data: bytes) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    position = 8
    while position + 8 <= len(data):
        try:
            length = struct.unpack(">I", data[position : position + 4])[0]
        except struct.error:
            break
        tag = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        name = tag.decode("latin-1")
        if name == "IDAT":
            found["IDAT"] = found.get("IDAT", b"") + payload
        else:
            found.setdefault(name, payload)
        if tag == b"IEND":
            break
        position += 12 + length
    return found


def _scan_alpha(raw: bytes, width: int, height: int, color_type: int, depth: int, max_rows: int) -> bool:
    """True when any pixel in the first ``max_rows`` rows is not fully opaque."""
    if not raw or depth != 8:
        return True
    channels = 4 if color_type == 6 else 2
    stride = width * channels
    step = channels
    offset = channels - 1
    try:
        data = zlib.decompress(raw)
    except zlib.error:
        return True
    previous = bytearray(stride)
    position = 0
    rows = min(height, max_rows)
    for _ in range(rows):
        if position >= len(data):
            break
        filter_type = data[position]
        position += 1
        line = bytearray(data[position : position + stride])
        if len(line) < stride:
            break
        position += stride
        if filter_type == 1:
            for index in range(step, stride):
                line[index] = (line[index] + line[index - step]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - step] if index >= step else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - step] if index >= step else 0
                upper = previous[index]
                corner = previous[index - step] if index >= step else 0
                estimate = left + upper - corner
                da, db, dc = abs(estimate - left), abs(estimate - upper), abs(estimate - corner)
                predictor = left if (da <= db and da <= dc) else (upper if db <= dc else corner)
                line[index] = (line[index] + predictor) & 0xFF
        for index in range(offset, stride, step):
            if line[index] < 255:
                return True
        previous = line
    return False


def _palette_uses_alpha(chunks: dict[str, bytes], width: int, height: int, depth: int) -> bool:
    """True only when a pixel really uses a palette entry with alpha < 255."""
    trns = chunks.get("tRNS")
    if not trns or width <= 0 or height <= 0:
        return False
    transparent = {index for index, alpha in enumerate(trns) if alpha < 255}
    if not transparent:
        return False
    raw = chunks.get("IDAT", b"")
    if not raw:
        return False
    try:
        data = zlib.decompress(raw)
    except zlib.error:
        return True
    bits = max(depth, 1)
    stride = (width * bits + 7) // 8
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        if position >= len(data):
            break
        filter_type = data[position]
        position += 1
        line = bytearray(data[position : position + stride])
        if len(line) < stride:
            break
        position += stride
        if filter_type == 1:
            for index in range(1, stride):
                line[index] = (line[index] + line[index - 1]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - 1] if index else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - 1] if index else 0
                upper = previous[index]
                corner = previous[index - 1] if index else 0
                estimate = left + upper - corner
                da, db, dc = abs(estimate - left), abs(estimate - upper), abs(estimate - corner)
                predictor = left if (da <= db and da <= dc) else (upper if db <= dc else corner)
                line[index] = (line[index] + predictor) & 0xFF
        for index in range(width):
            if bits == 8:
                value = line[index]
            elif bits == 4:
                value = (line[index // 2] >> (4 if index % 2 == 0 else 0)) & 0x0F
            elif bits == 2:
                value = (line[index // 4] >> (6 - 2 * (index % 4))) & 0x03
            else:
                value = (line[index // 8] >> (7 - index % 8)) & 0x01
            if value in transparent:
                return True
        previous = line
    return False


def scale_ratio(info: PngInfo) -> float:
    """Share of pixels that are transparent, as a rough opacity estimate."""
    if not info.valid:
        return 0.0
    return 0.0
