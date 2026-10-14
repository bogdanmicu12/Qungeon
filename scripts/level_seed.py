"""Deterministic seed-based level generation for Qungeon.

A seed is a 64-bit unsigned integer. The same seed always produces the same
valid level data, so it can be shared without sharing the JSON file.

If a generated candidate fails validation, another deterministic candidate is
generated using the same seed plus an attempt number. This preserves the
property that the same seed always produces the same final level.
"""

from __future__ import annotations

import hashlib
import random

from scripts.level_validation import validate_level, LevelError


COLS = 11
ROWS = 10
MASK64 = (1 << 64) - 1
PREFIX = "QG-"

MAX_ATTEMPTS = 100

GATES = ("X", "H", "Z", "RotY", "CNOT", "CHAD", "SWAP")
EFFECTS = ("Flip", "Superposition", "Phase")


def seed_from_text(value: str) -> int:
    """Convert a decimal/hex seed or arbitrary share text to a 64-bit seed."""
    text = value.strip()

    if not text:
        raise ValueError("Seed cannot be empty")

    if text.upper().startswith(PREFIX):
        text = text[len(PREFIX):]

    # Accept the canonical 16-digit hexadecimal form.
    try:
        if text.lower().startswith("0x"):
            return int(text, 16) & MASK64

        if (
            all(c in "0123456789abcdefABCDEF" for c in text)
            and len(text) <= 16
        ):
            return int(text, 16) & MASK64

        if text.isdigit():
            return int(text, 10) & MASK64

    except ValueError:
        pass

    # Friendly fallback: any text can be used as a stable seed.
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def format_seed(seed: int) -> str:
    """Return the short share code shown to players."""
    return f"{PREFIX}{seed & MASK64:016X}"


def _pos(x: int, y: int) -> str:
    """Format a board position."""
    return f"({x}, {y})"


def _maze(rng: random.Random):
    """Create a connected maze-like walkable region on the 11x10 board."""

    # Start with all cells as walls, then carve a DFS maze on odd coordinates.
    walls = {
        (x, y)
        for y in range(ROWS)
        for x in range(COLS)
    }

    start = (1, 1)

    visited = {start}
    stack = [start]

    walls.remove(start)

    while stack:
        x, y = stack[-1]

        choices = []

        for dx, dy in (
            (2, 0),
            (-2, 0),
            (0, 2),
            (0, -2),
        ):
            nx, ny = x + dx, y + dy

            if (
                1 <= nx < COLS - 1
                and 1 <= ny < ROWS - 1
                and (nx, ny) not in visited
            ):
                choices.append(
                    (nx, ny, dx // 2, dy // 2)
                )

        if not choices:
            stack.pop()
            continue

        nx, ny, wx, wy = rng.choice(choices)

        visited.add((nx, ny))

        walls.discard((x + wx, y + wy))
        walls.discard((nx, ny))

        stack.append((nx, ny))

    return walls


def _generate_level_attempt(seed: int, attempt: int) -> dict:
    """Generate one deterministic candidate level.

    The attempt number changes the RNG stream while keeping generation
    deterministic for the original seed.
    """

    seed &= MASK64
    attempt &= MASK64

    # Derive a unique deterministic RNG seed for this attempt.
    #
    # Using a tuple would not work with random.Random on all Python versions,
    # so we derive a 64-bit integer explicitly.
    attempt_seed = (
        seed + ((attempt + 1) * 0x9E3779B97F4A7C15)
    ) & MASK64

    rng = random.Random(attempt_seed)

    walls = _maze(rng)

    # Ensure start/end are open and reasonably separated.
    start = (1, 1)

    candidates = [
        (x, y)
        for y in range(1, ROWS, 2)
        for x in range(1, COLS, 2)
        if (x, y) != start and (x, y) not in walls
    ]

    end = max(
        candidates,
        key=lambda p: (
            abs(p[0] - start[0])
            + abs(p[1] - start[1])
        ),
    )

    walls.discard(start)
    walls.discard(end)

    # Build tile map.
    tiles = {}

    for y in range(ROWS):
        for x in range(COLS):
            kind = (
                "WALL"
                if (x, y) in walls
                else "EMPTY"
            )

            tiles[_pos(x, y)] = kind

    tiles[_pos(*start)] = "START"
    tiles[_pos(*end)] = "END"

    # Find usable floor positions.
    floor = [
        (x, y)
        for y in range(ROWS)
        for x in range(COLS)
        if (x, y) not in walls
        and (x, y) not in {start, end}
    ]

    rng.shuffle(floor)

    # A modest number of pillars and pickups keeps generated levels useful
    # in the existing editor/game without making every seed extremely crowded.
    pillar_count = 2 + rng.randrange(3)
    pickup_count = 1 + rng.randrange(3)

    quantum_objects = floor[:pillar_count]

    pickup_positions = floor[
        pillar_count:pillar_count + pickup_count
    ]

    # Quantum object effects.
    effects = []

    for pos in quantum_objects:
        effect = rng.choice(EFFECTS)

        effects.append(
            {
                "position": _pos(*pos),
                "effect": effect,
            }
        )

    # Gate pickups.
    objects = {}

    for pos in pickup_positions:
        objects[_pos(*pos)] = rng.choice(GATES)

    # Give the player a small, deterministic starting toolkit.
    gate_counts = {}

    for gate in rng.sample(GATES, k=2):
        gate_counts[gate] = 1 + rng.randrange(2)

    return {
        "seed": seed,
        "tiles": tiles,
        "objects": objects,
        "quantum_objects": [
            _pos(*p)
            for p in quantum_objects
        ],
        "gates": gate_counts,
        "effects": effects,
    }


def generate_level(seed: int) -> dict:
    """Generate a deterministic, validation-safe level.

    The same seed will always produce the same final level.

    If an individual generated candidate fails the level validator, another
    deterministic candidate is generated. This continues until a valid level
    is found or MAX_ATTEMPTS is reached.
    """

    seed &= MASK64

    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        data = _generate_level_attempt(
            seed,
            attempt,
        )

        try:
            validate_level(
                data,
                f"seed:{format_seed(seed)}"
            )

            return data

        except LevelError as error:
            last_error = error

    raise LevelError(
        f"seed:{format_seed(seed)} could not produce a valid "
        f"level after {MAX_ATTEMPTS} attempts. "
        f"Last validation error: {last_error}"
    )


def generate_level_from_text(value: str) -> tuple[int, dict]:
    """Convert share text into a seed and generate its level."""

    seed = seed_from_text(value)

    return seed, generate_level(seed)