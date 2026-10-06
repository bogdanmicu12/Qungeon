"""Exact, compact share codes for Qungeon levels.

QG-... codes are procedural seeds. QGL-... codes contain a compact binary
snapshot of the exact level, so hand-built editor levels can be shared without
sending the JSON file.
"""
from __future__ import annotations

import base64
import struct

from scripts.level_validation import LevelError, parse_pos, validate_level

PREFIX = "QGL-"
MAGIC = b"QGL3"
PREVIOUS_MAGIC = b"QGL2"
LEGACY_MAGIC = b"QGL1"
MAX_CODE_LENGTH = 4096
MAX_PAYLOAD_BYTES = 2048
COLS = 11
ROWS = 10
MAX_POS = COLS * ROWS

TILE_CODES = {"EMPTY": 0, "WALL": 1, "START": 2, "END": 3}
TILES_BY_CODE = {value: key for key, value in TILE_CODES.items()}
GATES = ("X", "H", "Z", "RotY", "CNOT", "CHAD", "SWAP")
GATE_CODES = {gate: i for i, gate in enumerate(GATES)}
EFFECTS = ("Flip", "Superposition", "Phase")
EFFECT_CODES = {effect: i for i, effect in enumerate(EFFECTS)}


def _pos_code(pos):
    x, y = pos
    if not (0 <= x < COLS and 0 <= y < ROWS):
        raise ValueError(f"Position out of bounds: {pos}")
    return y * COLS + x


def _decode_pos(value):
    if not 0 <= value < MAX_POS:
        raise ValueError("Invalid position in share code")
    return value % COLS, value // COLS


def _u8(value, label):
    if not 0 <= value <= 255:
        raise ValueError(f"{label} is out of range")
    return value


def encode_level(level_data: dict) -> str:
    """Encode an exact validated level into a compact QGL share code."""
    validate_level(level_data, "share code")

    tiles = sorted((parse_pos(pos), kind) for pos, kind in level_data["tiles"].items())
    objects = sorted((parse_pos(pos), gate) for pos, gate in level_data["objects"].items())
    quantum = sorted(parse_pos(pos) for pos in level_data["quantum_objects"])
    effects = sorted((parse_pos(e["position"]), e["effect"]) for e in level_data["effects"])
    pillar_states = sorted((parse_pos(pos), state) for pos, state in level_data.get("pillar_states", {}).items())

    if any(kind not in TILE_CODES for _, kind in tiles):
        raise ValueError("Unknown tile in share code")
    if any(gate not in GATE_CODES for _, gate in objects):
        raise ValueError("Unknown gate in share code")
    if any(effect not in EFFECT_CODES for _, effect in effects):
        raise ValueError("Unknown effect in share code")

    payload = bytearray(MAGIC)
    seed = level_data.get("seed")
    flags = (1 if seed is not None else 0) | (2 if level_data.get("editor_created") else 0)
    payload.append(flags)
    if seed is not None:
        payload.extend(struct.pack(">Q", int(seed) & ((1 << 64) - 1)))

    payload.append(_u8(len(tiles), "tile count"))
    for pos, kind in tiles:
        payload.extend((_pos_code(pos), TILE_CODES[kind]))

    payload.append(_u8(len(objects), "object count"))
    for pos, gate in objects:
        payload.extend((_pos_code(pos), GATE_CODES[gate]))

    payload.append(_u8(len(quantum), "pillar count"))
    for pos in quantum:
        payload.append(_pos_code(pos))

    payload.append(_u8(len(effects), "effect count"))
    for pos, effect in effects:
        payload.extend((_pos_code(pos), EFFECT_CODES[effect]))

    payload.append(_u8(len(pillar_states), "pillar state count"))
    for pos, state in pillar_states:
        payload.append(_pos_code(pos))
        x = state["x"]
        y = state["y"]
        def parts(value):
            if isinstance(value, dict):
                return float(value["real"]), float(value["imag"])
            return float(value), 0.0
        xr, xi = parts(x)
        yr, yi = parts(y)
        payload.extend(struct.pack(">dddd", xr, xi, yr, yi))

    for gate in GATES:
        payload.append(_u8(int(level_data["gates"].get(gate, 0)), f"{gate} count"))

    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Level is too large to encode as a share code")

    encoded = base64.urlsafe_b64encode(bytes(payload)).decode("ascii").rstrip("=")
    code = PREFIX + encoded
    if len(code) > MAX_CODE_LENGTH:
        raise ValueError("Level is too large to encode as a share code")
    return code


def decode_level(code: str) -> dict:
    """Decode and validate a QGL share code into exact level data."""
    text = code.strip()
    if not text.upper().startswith(PREFIX):
        raise ValueError("Not an exact level share code (expected QGL-...)")
    if len(text) > MAX_CODE_LENGTH:
        raise ValueError("Share code is too long")

    try:
        encoded = text[len(PREFIX):]
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError) as err:
        raise ValueError("Invalid level share code") from err

    if len(payload) > MAX_PAYLOAD_BYTES or not (payload.startswith(MAGIC) or payload.startswith(PREVIOUS_MAGIC) or payload.startswith(LEGACY_MAGIC)):
        raise ValueError("Invalid level share code")

    is_legacy = payload.startswith(LEGACY_MAGIC)
    is_previous = payload.startswith(PREVIOUS_MAGIC)
    index = len(LEGACY_MAGIC) if is_legacy else (len(PREVIOUS_MAGIC) if is_previous else len(MAGIC))

    def take(count):
        nonlocal index
        if index + count > len(payload):
            raise ValueError("Incomplete level share code")
        result = payload[index:index + count]
        index += count
        return result

    flags = take(1)[0]
    if flags & ~3 or (is_legacy and flags & 2):
        raise ValueError("Unsupported level share code version")

    data = {}
    if flags & 1:
        data["seed"] = struct.unpack(">Q", take(8))[0]

    tile_count = take(1)[0]
    tiles = {}
    for _ in range(tile_count):
        pos_code, tile_code = take(2)
        if tile_code not in TILES_BY_CODE:
            raise ValueError("Invalid tile in share code")
        x, y = _decode_pos(pos_code)
        tiles[f"({x}, {y})"] = TILES_BY_CODE[tile_code]
    data["tiles"] = tiles

    object_count = take(1)[0]
    objects = {}
    for _ in range(object_count):
        pos_code, gate_code = take(2)
        if gate_code >= len(GATES):
            raise ValueError("Invalid gate in share code")
        x, y = _decode_pos(pos_code)
        objects[f"({x}, {y})"] = GATES[gate_code]
    data["objects"] = objects

    pillar_count = take(1)[0]
    quantum = []
    for _ in range(pillar_count):
        x, y = _decode_pos(take(1)[0])
        quantum.append(f"({x}, {y})")
    data["quantum_objects"] = quantum

    effect_count = take(1)[0]
    effects = []
    for _ in range(effect_count):
        pos_code, effect_code = take(2)
        if effect_code >= len(EFFECTS):
            raise ValueError("Invalid effect in share code")
        x, y = _decode_pos(pos_code)
        effects.append({"position": f"({x}, {y})", "effect": EFFECTS[effect_code]})
    data["effects"] = effects

    if not is_legacy:
        state_count = take(1)[0]
        pillar_states = {}
        for _ in range(state_count):
            x, y = _decode_pos(take(1)[0])
            if is_previous:
                amplitude_x, amplitude_y = struct.unpack(">dd", take(16))
                state = {"x": {"real": amplitude_x, "imag": 0.0},
                         "y": {"real": amplitude_y, "imag": 0.0}}
            else:
                xr, xi, yr, yi = struct.unpack(">dddd", take(32))
                state = {"x": {"real": xr, "imag": xi},
                         "y": {"real": yr, "imag": yi}}
            pillar_states[f"({x}, {y})"] = state
        data["pillar_states"] = pillar_states
        data["editor_created"] = bool(flags & 2)

    counts = take(len(GATES))
    data["gates"] = {gate: count for gate, count in zip(GATES, counts) if count}

    if index != len(payload):
        raise ValueError("Unexpected data in level share code")

    try:
        validate_level(data, "share code")
    except LevelError as err:
        raise ValueError(str(err)) from err
    return data
