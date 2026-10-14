"""Optional room flavor and decoration. No gameplay or quantum state lives here."""

from dataclasses import dataclass

import pygame


@dataclass(frozen=True)
class Room:
    title: str
    learning_line: str
    completion_line: str
    help_note: str
    marks: tuple


ROOMS = {
    1: Room(
        "The Sealed Room",
        "I'm stuck down here. A pillar in 1 is solid; only a definite 0 lets me through.",
        "I can get through after all. The same arch is carved into the next passage.",
        "Each pillar represents a qubit, with states called 0 and 1. "
        "X swaps these states: a solid pillar in 1 becomes passable in 0.",
        ((3, 3, "hatch"), (6, 3, "arch")),
    ),
    2: Room(
        "The Uncertain Passage",
        "This pillar isn't definitely 0 or 1. I'll need to do more than flip it.",
        "Another lock behind me. Whoever marked these walls knew a way through.",
        "H turns 0 into a superposition: a state with both 0 and 1 components. "
        "Apply H twice and you return to the original state; a superposition still blocks your path.",
        ((4, 3, "pair"), (7, 3, "arch")),
    ),
    3: Room(
        "The Hidden Difference",
        "The same glow, but a different lock. Looks alone won't get me out of here.",
        "A hidden difference, beneath a familiar surface. I'll remember that.",
        "Superpositions can have matching probabilities but different relative phases, "
        "like waves lining up differently. H can turn that hidden difference into 0 or 1.",
        ((4, 3, "reverse"), (7, 3, "arch")),
    ),
    4: Room(
        "The Phase Lock",
        "These gates can change things I can't see. Perhaps another gate will reveal what changed.",
        "Even an invisible change can open a path. The old markings lead further on.",
        "Z reverses the sign of the 1 component without changing its probability. "
        "In a superposition, H can then make the components reinforce or cancel differently: interference.",
        ((4, 3, "waves"), (7, 3, "arch")),
    ),
    5: Room(
        "The Supply Passage",
        "Someone left supplies along the passage. I'd better make them last.",
        "Dusty boxes, but useful gates. This passage must once have led somewhere.",
        "The abandoned boxes hold extra gates, and each use spends one. "
        "Consider which states you can change with the gates left before choosing a route.",
        ((4, 2, "notches"), (9, 2, "arch")),
    ),
    6: Room(
        "The Inner Maze",
        "A maze, and a faint draft. There must be a way through to the surface.",
        "Air from above, and a little light on the stone. I'm getting closer.",
        "Gate order matters: changing phase before H can have a different result than changing it after. "
        "Use the states you recognize to plan a route through the maze.",
        ((4, 2, "notches"), (9, 2, "arch")),
    ),
    7: Room(
        "The Remote Lock",
        "The passage is blocked further ahead. Can I change a pillar from here?",
        "One lock can reach another. Distance doesn't have to keep me trapped.",
        "For CNOT, choose a nearby control first, then a different target anywhere on the map. "
        "A control in 1 flips the target; a control in 0 leaves it alone.",
        ((5, 3, "control"), (8, 4, "arch")),
    ),
    8: Room(
        "The Shared Lock",
        "These pillars seem tied together. I'll have to think about more than one at a time.",
        "Past the linked locks. Beyond them, the air feels warmer.",
        "These pillars start entangled: their joint state cannot be described by a separate pure state for each pillar. "
        "Controlled gates can create or undo entanglement, depending on the starting state.",
        ((3, 2, "shared"), (7, 2, "arch")),
    ),
    9: Room(
        "The Outer Gate",
        "Daylight beyond the last gate. One more room between me and the surface.",
        "The outer lock opens. At last, a passage into daylight.",
        "CHAD means controlled H: a control in 1 applies H to the target, and a control in 0 leaves it alone. "
        "As with CNOT, stand beside the control; the target can be far away.",
        ((3, 3, "control"), (8, 3, "arch")),
    ),
}

ENDING = "Daylight. Fresh air. I found another way out."
STONE = (88, 87, 99)
LIGHT = (230, 220, 185)


def is_escape(game):
    """Single-room practice and future unknown levels retain ordinary completion."""
    return (game.run_mode == "full" and game.current_level == 9 and 9 in ROOMS
            and not game.has_next_level())


def draw_arch(surface, rect, color, width=2):
    x, y, w, h = rect
    pygame.draw.lines(surface, color, False,
                      [(x, y + h), (x, y + 6), (x + 6, y),
                       (x + w - 6, y), (x + w, y + 6), (x + w, y + h)], width)


def draw_marks(game, block_size):
    """Paint only scenery, behind sprites. Unknown or edited maps fail quietly."""
    room = ROOMS.get(game.current_level)
    if room is None:
        return
    for x, y, symbol in room.marks:
        tile = game.tiles.get((x, y))
        if tile is None or tile.type.name != "WALL":
            continue
        # Stay inside the stone and below the HUD, even on edited maps.
        left, top = x * block_size + 12, y * block_size + 12
        rect = pygame.Rect(left, top, 24, 24)
        if not pygame.Rect(0, 96, 800, 348).contains(rect):
            continue
        color = STONE
        if symbol == "arch":
            draw_arch(game.screen, (left + 3, top, 18, 22), color)
            # Broken early markings gradually resolve into a complete arch.
            if game.current_level <= 3:
                pygame.draw.line(game.screen, (119, 115, 127),
                                 (left + 3, top + 8), (left + 3, top + 12), 2)
        elif symbol == "hatch":
            pygame.draw.rect(game.screen, color, rect.inflate(-4, -2), 2)
            pygame.draw.line(game.screen, color, (left + 3, top + 12), (left + 21, top + 12), 3)
        elif symbol in ("pair", "reverse", "waves"):
            for offset in (4, 16):
                direction = -1 if symbol != "pair" and offset == 16 else 1
                points = [(left, top + offset), (left + 6, top + offset - 3 * direction),
                          (left + 12, top + offset), (left + 18, top + offset + 3 * direction),
                          (left + 24, top + offset)]
                pygame.draw.lines(game.screen, color, False, points, 2)
        elif symbol == "notches":
            for offset in (2, 10, 18):
                pygame.draw.line(game.screen, color, (left + offset, top + 5),
                                 (left + offset + 3, top + 17), 2)
        elif symbol == "control":
            pygame.draw.circle(game.screen, color, (left + 3, top + 12), 3)
            pygame.draw.line(game.screen, color, (left + 6, top + 12), (left + 18, top + 12), 2)
            pygame.draw.rect(game.screen, color, (left + 17, top + 7, 7, 10), 2)
        elif symbol == "shared":
            for offset in (0, 8, 16):
                pygame.draw.rect(game.screen, color, (left + offset, top + 6, 8, 12), 2)

    if game.current_level >= 6:
        for (x, y), tile in game.tiles.items():
            if tile.type.name != "END" or (x + 1, y) in game.tiles:
                continue
            # Light is outside the floor: it never resembles another walkable tile.
            left, top = (x + 1) * block_size + 6, y * block_size + 8
            if not pygame.Rect(0, 96, 800, 348).contains(pygame.Rect(left, top, 32, 32)):
                continue
            color = (86, 82, 72) if game.current_level < 9 else (159, 149, 119)
            for offset in (0, 10, 20):
                pygame.draw.line(game.screen, color, (left, top + offset + 6),
                                 (left + 22, top + offset), 2)


def draw_ending(surface, character):
    """A quiet glimpse of sky in the completion panel's existing symbol space."""
    pygame.draw.polygon(surface, (174, 194, 199),
                        [(372, 160), (372, 116), (380, 108),
                         (420, 108), (428, 116), (428, 160)])
    pygame.draw.rect(surface, LIGHT, (375, 147, 50, 13))
    draw_arch(surface, (370, 106, 60, 54), LIGHT, 3)
    sprite = pygame.transform.scale(character, (24, 24))
    surface.blit(sprite, (388, 136))
