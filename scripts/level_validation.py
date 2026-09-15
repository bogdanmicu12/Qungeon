"""Validation and safe parsing for level JSON files (an input boundary).

Level files are external data (shipped and, eventually, community-made), so
they are validated before any game state is touched. This module is pure
Python — no pygame or unitary imports — so it can be unit-tested standalone
and so a malformed file fails fast with a clear message instead of executing
arbitrary code via eval()/getattr().
"""

REQUIRED_KEYS = ("tiles", "objects", "quantum_objects", "gates", "effects")
VALID_TILES = {"EMPTY", "START", "END", "WALL"}
VALID_GATES = {"X", "H", "Z", "RotY", "CNOT", "CHAD", "SWAP"}
VALID_EFFECTS = {"Flip", "Superposition", "Phase"}


class LevelError(ValueError):
    """Raised when a level file is malformed."""


def parse_pos(pos_str):
    """Parse a "(x, y)" position string into an (int, int) tuple.

    Replaces eval(): accepts only exactly two integers, nothing else.
    """
    try:
        x, y = (int(v) for v in pos_str.strip("() ").split(","))
    except (ValueError, AttributeError):
        raise LevelError(
            f"bad position {pos_str!r}: expected \"(x, y)\" with two integers"
        )
    return (x, y)


def validate_level(level_data, filename):
    """Validate parsed level JSON, raising LevelError (naming the field) on any
    problem. Call this before clean_up() so a bad file never clobbers the
    currently loaded game.
    """
    def check_pos(pos_str):
        """parse_pos, but re-raise with the filename so every error names it."""
        try:
            parse_pos(pos_str)
        except LevelError as err:
            raise LevelError(f"{filename}: {err}")

    missing = [k for k in REQUIRED_KEYS if k not in level_data]
    if missing:
        raise LevelError(f"{filename}: missing required key(s): {', '.join(missing)}")

    starts = 0
    for pos_str, tile_type in level_data["tiles"].items():
        check_pos(pos_str)
        if tile_type not in VALID_TILES:
            raise LevelError(f"{filename}: unknown tile type {tile_type!r} at {pos_str}")
        if tile_type == "START":
            starts += 1
    if starts != 1:
        raise LevelError(f"{filename}: exactly one START tile required, found {starts}")

    for pos_str, item in level_data["objects"].items():
        check_pos(pos_str)
        if item not in VALID_GATES:
            raise LevelError(f"{filename}: unknown item {item!r} at {pos_str}")

    for pos_str in level_data["quantum_objects"]:
        check_pos(pos_str)

    for gate in level_data["gates"]:
        if gate not in VALID_GATES:
            raise LevelError(f"{filename}: unknown gate {gate!r} in hotbar")

    for entry in level_data["effects"]:
        if "position" not in entry or "effect" not in entry:
            raise LevelError(f"{filename}: effect entry missing 'position'/'effect': {entry}")
        check_pos(entry["position"])
        if entry["effect"] not in VALID_EFFECTS:
            raise LevelError(f"{filename}: unknown effect {entry['effect']!r} at {entry['position']}")
        if "target" in entry:
            check_pos(entry["target"])
