"""Validation and safe parsing for level JSON files (an input boundary).

Level files are external data (shipped and, eventually, community-made), so
they are validated before any game state is touched. This module is pure
Python — no pygame or unitary imports — so it can be unit-tested standalone
and so a malformed file fails fast with a clear message instead of executing
arbitrary code via eval()/getattr().
"""

import json

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
        raise LevelError(
            f"{filename}: missing required key(s): {', '.join(missing)}"
        )

    starts = 0
    ends = 0

    for pos_str, tile_type in level_data["tiles"].items():
        check_pos(pos_str)

        if tile_type not in VALID_TILES:
            raise LevelError(
                f"{filename}: unknown tile type {tile_type!r} at {pos_str}"
            )

        if tile_type == "START":
            starts += 1
        elif tile_type == "END":
            ends += 1

    if starts != 1:
        raise LevelError(
            f"{filename}: exactly one START tile required, found {starts}"
        )

    if ends != 1:
        raise LevelError(
            f"{filename}: exactly one END tile required, found {ends}"
        )

    tile_positions = {
        parse_pos(pos_str)
        for pos_str in level_data["tiles"]
    }

    object_positions = set()
    for pos_str, item in level_data["objects"].items():
        check_pos(pos_str)
        parsed = parse_pos(pos_str)
        if parsed in object_positions:
            raise LevelError(
                f"{filename}: duplicate object position {pos_str}"
            )
        object_positions.add(parsed)

        if item not in VALID_GATES:
            raise LevelError(
                f"{filename}: unknown item {item!r} at {pos_str}"
            )

    pillar_positions = set()
    for pos_str in level_data["quantum_objects"]:
        check_pos(pos_str)
        parsed = parse_pos(pos_str)

        if parsed in pillar_positions:
            raise LevelError(
                f"{filename}: duplicate quantum object position {pos_str}"
            )

        if parsed in object_positions:
            raise LevelError(
                f"{filename}: position {pos_str} contains both "
                "a quantum object and a gate pickup"
            )

        pillar_positions.add(parsed)

    for position in object_positions | pillar_positions:
        if position not in tile_positions:
            raise LevelError(
                f"{filename}: object at {position} is not on a tile"
            )

    for gate, count in level_data["gates"].items():
        if gate not in VALID_GATES:
            raise LevelError(
                f"{filename}: unknown gate {gate!r} in hotbar"
            )

        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise LevelError(
                f"{filename}: gate count for {gate!r} must be a "
                "non-negative integer"
            )

    for entry in level_data["effects"]:
        if "position" not in entry or "effect" not in entry:
            raise LevelError(
                f"{filename}: effect entry missing "
                f"'position'/'effect': {entry}"
            )

        check_pos(entry["position"])
        source = parse_pos(entry["position"])

        if entry["effect"] not in VALID_EFFECTS:
            raise LevelError(
                f"{filename}: unknown effect "
                f"{entry['effect']!r} at {entry['position']}"
            )

        if source not in pillar_positions:
            raise LevelError(
                f"{filename}: effect {entry['effect']!r} is attached to "
                f"{entry['position']}, which is not a quantum object"
            )

        if "target" in entry:
            check_pos(entry["target"])
            target = parse_pos(entry["target"])

            if entry["effect"] not in {"Flip", "Superposition"}:
                raise LevelError(
                    f"{filename}: effect {entry['effect']!r} cannot have a target"
                )

            if target not in pillar_positions:
                raise LevelError(
                    f"{filename}: effect target {entry['target']} is not "
                    "a quantum object"
                )

            if target == source:
                raise LevelError(
                    f"{filename}: effect target cannot equal its source "
                    f"at {entry['position']}"
                )


def read_level(filename):
    """Read, parse and validate a level file, returning its data.

    The one way to turn a level file into level data, so every caller - the
    game's loader and the menu's level previews - fails on the same bad file
    in the same way (LevelError, naming the file) instead of each crashing on
    its own missing key or unreadable path.
    """
    try:
        with open(filename, "r", encoding="utf-8") as file:
            level_data = json.load(file)
    except OSError as err:
        raise LevelError(f"{filename}: cannot be read: {err}")
    except ValueError as err:
        raise LevelError(f"{filename}: is not valid JSON: {err}")

    validate_level(level_data, filename)
    return level_data