"""Validation and safe parsing for level JSON files (an input boundary).

Level files are external data (shipped and, eventually, community-made), so
they are validated before any game state is touched. This module is pure
Python — no pygame or unitary imports — so it can be unit-tested standalone
and so a malformed file fails fast with a clear message instead of executing
arbitrary code via eval()/getattr().
"""

import json
import math


REQUIRED_KEYS = ("tiles", "objects", "quantum_objects", "gates", "effects")
EDITOR_LEVEL_KEY = "editor_created"
PILLAR_STATES_KEY = "pillar_states"

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
    """Validate parsed level JSON.

    Raises LevelError naming the file and problematic field on any problem.
    Call this before clean_up() so a bad file never clobbers the currently
    loaded game.
    """

    def check_pos(pos_str):
        """parse_pos, but re-raise with the filename so every error names it."""
        try:
            parse_pos(pos_str)
        except LevelError as err:
            raise LevelError(f"{filename}: {err}")

    # Validate top-level structure before accessing any fields.
    if not isinstance(level_data, dict):
        raise LevelError(f"{filename}: top level must be a JSON object")

    missing = [k for k in REQUIRED_KEYS if k not in level_data]
    if missing:
        raise LevelError(
            f"{filename}: missing required key(s): {', '.join(missing)}"
        )

    # Checked before anything is read out of them, so a file whose "tiles" is a
    # list still fails as a LevelError instead of an AttributeError that no
    # caller catches - the level-select previews walk every file in ./levels.
    for key in ("tiles", "objects", "gates"):
        if not isinstance(level_data[key], dict):
            raise LevelError(f"{filename}: {key!r} must be a JSON object")

    for key in ("quantum_objects", "effects"):
        if not isinstance(level_data[key], list):
            raise LevelError(f"{filename}: {key!r} must be a list")

    starts = 0
    ends = 0

    # Validate tiles.
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

    # Validate gate/object pickups.
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

    # Validate quantum objects / pillars.
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

    # Every object must occupy an actual tile.
    for position in object_positions | pillar_positions:
        if position not in tile_positions:
            raise LevelError(
                f"{filename}: object at {position} is not on a tile"
            )

    # Validate hotbar gate counts.
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

    # Validate explicit pillar states used by editor-created levels.
    pillar_states = level_data.get(PILLAR_STATES_KEY, {})

    if not isinstance(pillar_states, dict):
        raise LevelError(
            f"{filename}: pillar_states must be an object"
        )

    state_positions = set()

    for pos_str, state in pillar_states.items():
        check_pos(pos_str)
        parsed = parse_pos(pos_str)

        if parsed in state_positions:
            raise LevelError(
                f"{filename}: duplicate pillar state at {pos_str}"
            )

        if parsed not in pillar_positions:
            raise LevelError(
                f"{filename}: pillar state at {pos_str} is not a quantum object"
            )

        if not isinstance(state, dict) or set(state) != {"x", "y"}:
            raise LevelError(
                f"{filename}: pillar state at {pos_str} must contain "
                "only 'x' and 'y'"
            )

        def amplitude(value, label):
            """Validate and return a complex amplitude as (real, imag)."""
            # JSON has no complex-number type, so editor states store each
            # amplitude as {"real": ..., "imag": ...}. Keep plain real
            # numbers readable/compatible for older levels.
            if isinstance(value, dict):
                if set(value) != {"real", "imag"}:
                    raise LevelError(
                        f"{filename}: invalid {label} amplitude at {pos_str}"
                    )

                real, imag = value["real"], value["imag"]
            else:
                real, imag = value, 0.0

            if (
                isinstance(real, bool)
                or not isinstance(real, (int, float))
                or not math.isfinite(real)
                or isinstance(imag, bool)
                or not isinstance(imag, (int, float))
                or not math.isfinite(imag)
            ):
                raise LevelError(
                    f"{filename}: invalid {label} amplitude at {pos_str}"
                )

            return float(real), float(imag)

        xr, xi = amplitude(state["x"], "x")
        yr, yi = amplitude(state["y"], "y")

        norm = xr * xr + xi * xi + yr * yr + yi * yi

        if not math.isclose(
            norm,
            1.0,
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise LevelError(
                f"{filename}: amplitudes at {pos_str} must satisfy "
                "|x|² + |y|² = 1"
            )

        state_positions.add(parsed)

    # Editor-created levels use explicit pillar amplitudes instead of effects.
    if level_data.get(EDITOR_LEVEL_KEY) and level_data.get("effects"):
        raise LevelError(
            f"{filename}: editor-created levels must use pillar amplitudes, "
            "not effects"
        )

    # Every pillar in an editor-created level must have exactly one state.
    if level_data.get(EDITOR_LEVEL_KEY) and state_positions != pillar_positions:
        missing = pillar_positions - state_positions
        extra = state_positions - pillar_positions

        details = []

        if missing:
            details.append(f"missing states at {sorted(missing)}")

        if extra:
            details.append(f"extra states at {sorted(extra)}")

        raise LevelError(
            f"{filename}: editor-created levels require one state for every "
            f"pillar ({'; '.join(details)})"
        )

    # Validate quantum effects.
    for entry in level_data["effects"]:
        if not isinstance(entry, dict):
            raise LevelError(
                f"{filename}: effect entry must be a JSON object: {entry}"
            )

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

    The one way to turn a level file into level data, so every caller — the
    game's loader and the menu's level previews — fails on the same bad file
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