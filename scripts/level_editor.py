"""In-game level editor for Qungeon."""
import json
import os
from pathlib import Path

import pygame

from scripts.common_functions import font
from scripts.level_validation import validate_level, LevelError, parse_pos
from scripts.game_objects import gates as GAME_GATES

BG = (17, 19, 30)
PANEL = (26, 29, 43)
EDGE = (58, 63, 83)
INK = (238, 235, 225)
MUTED = (154, 158, 177)
ACCENT = (182, 164, 242)
MINT = (161, 220, 189)
RED = (233, 149, 159)

TILE_TOOLS = ("EMPTY", "WALL", "START", "END", "ERASE")
EFFECTS = ("Flip", "Superposition", "Phase")
GATES = ("X", "H", "Z", "RotY", "CNOT", "CHAD", "SWAP")
CELL = 38
GRID_X, GRID_Y = 28, 92
COLS, ROWS = 11, 10

class LevelEditor:
    """Mouse-driven editor which writes the same JSON format the game loads."""
    def __init__(self, game):
        self.game = game
        self.images = {
            name: pygame.image.load(f"./assets/{name}.png").convert_alpha()
            for name in ("tile", "wall", "end_tile", "character", "box", "pillar")
        }
        self.tiles = {}
        self.objects = {}
        self.quantum_objects = set()
        self.effects = []
        self.gates = {}
        self.tool = "EMPTY"
        self.effect_tool = None
        self.selected = None
        self.level_text = str(self.next_level_number())
        self.text_active = False
        self.status = "New level"
        self.status_time = 0
        self.dragging_paint = False
        self.reset()

    def next_level_number(self):
        levels_dir = Path("./levels")
        nums = [int(p.stem) for p in levels_dir.glob("*.json") if p.stem.isdigit()]
        return max(nums, default=0) + 1

    def reset(self):
        self.tiles = {}
        self.objects = {}
        self.quantum_objects = set()
        self.effects = []
        self.gates = {}
        self.tool = "EMPTY"
        self.effect_tool = None
        self.selected = None
        self.status = "New level"

    def level_number(self):
        try:
            n = int(self.level_text)
            return n if n > 0 else None
        except ValueError:
            return None

    def key(self, pos):
        return f"{pos[0]},{pos[1]}"

    def pos_at(self, mouse):
        x = (mouse[0] - GRID_X) // CELL
        y = (mouse[1] - GRID_Y) // CELL
        if 0 <= x < COLS and 0 <= y < ROWS:
            return (x, y)
        return None

    def pos_in_level(self, pos):
        return f"({pos[0]}, {pos[1]})"

    def clear_at(self, pos):
        self.tiles.pop(pos, None)
        self.objects.pop(self.key(pos), None)
        self.quantum_objects.discard(self.key(pos))

        # Remove any effect attached to this position.
        # I use parse_pos() so "(3,5)" and "(3, 5)" are treated the same.
        self.effects = [
            e for e in self.effects
            if parse_pos(e["position"]) != pos
        ]

        if self.selected == pos:
            self.selected = None

    def set_tile(self, pos, kind):
        self.clear_at(pos)
        self.tiles[pos] = kind
        if kind in ("START", "END"):
            for other, value in list(self.tiles.items()):
                if other != pos and value == kind:
                    self.tiles[other] = "EMPTY"
        self.selected = pos

    def add_pillar(self, pos):
        self.tiles.setdefault(pos, "EMPTY")
        self.objects.pop(self.key(pos), None)
        self.quantum_objects.add(self.key(pos))
        self.selected = pos

    def add_gate_pickup(self, pos, gate):
        self.tiles.setdefault(pos, "EMPTY")
        self.quantum_objects.discard(self.key(pos))
        self.effects = [
            e for e in self.effects
            if parse_pos(e["position"]) != pos
        ]
        self.objects[self.key(pos)] = gate
        self.selected = pos

    def apply_effect(self, effect):
        if self.selected is None or self.key(self.selected) not in self.quantum_objects:
            self.status = "Select a pillar first"
            return
        position = self.pos_in_level(self.selected)
        if effect == "Clear":
            self.effects = [
                e for e in self.effects
                if parse_pos(e["position"]) != self.selected
            ]
        else:
            self.effects.append({"position": position, "effect": effect})
        self.status = f"{effect} added to {position}"

    def buttons(self):
        result = []

        # Tool buttons
        labels = [
            ("EMPTY", "Empty"),
            ("WALL", "Wall"),
            ("START", "Start"),
            ("END", "End"),
            ("ERASE", "Erase"),
            ("PILLAR", "Pillar"),
        ]

        for i, (action, label) in enumerate(labels):
            col, row = i % 2, i // 2
            result.append((
                action,
                pygame.Rect(492 + col * 142,101 + row * 39, 134, 32),
                label
            ))

        # Gate pickup buttons
        for i, gate in enumerate(GATES):
            col, row = i % 2, i // 2
            result.append((
                "GATE:" + gate,
                pygame.Rect(492 + col * 142, 235 + row * 34, 134, 28),
                gate + " pickup"
            ))

        # Initial effects
        for i, effect in enumerate(EFFECTS):
            result.append((
                "EFFECT:" + effect,
                pygame.Rect(492 + i * 91, 385, 84, 28),
                effect
            ))

        result += [
            ("EFFECT:Clear", pygame.Rect(674, 410, 84, 28), "Clear effects"),

            # File controls
            ("NEW", pygame.Rect(492, 450, 82, 34), "New"),
            ("LOAD", pygame.Rect(581, 450, 82, 34), "Load"),
            ("SAVE", pygame.Rect(670, 450, 82, 34), "Save"),

            ("BACK", pygame.Rect(492, 489, 82, 34), "Back"),
            ("TEST", pygame.Rect(581, 489, 171, 34), "Save & test"),
        ]

        return result

    def button_at(self, pos):
        for action, rect, label in self.buttons():
            if rect.collidepoint(pos):
                return action
        return None

    def set_status(self, text):
        self.status = text
        self.status_time = pygame.time.get_ticks()

    def activate(self, action):
        if action in ("EMPTY", "WALL", "START", "END", "ERASE"):
            self.tool = action
            self.effect_tool = None
            return
        if action == "PILLAR":
            self.tool = action
            self.effect_tool = None
            return
        if action.startswith("GATE:"):
            self.tool = action
            self.effect_tool = None
            return
        if action.startswith("EFFECT:"):
            effect = action.split(":", 1)[1]
            self.apply_effect(effect)
            return
        if action == "NEW":
            self.reset()
            self.level_text = str(self.next_level_number())
            self.set_status("New level")
        elif action == "LOAD":
            self.load()
        elif action == "SAVE":
            self.save(False)
        elif action == "TEST":
            if self.save(False):
                n = self.level_number()
                self.game.available_levels = self.game.find_levels()
                self.game.start_level(n, "single")
        elif action == "BACK":
            self.game.menu.open("main")

    def paint(self, pos):
        if self.tool == "PILLAR":
            self.add_pillar(pos)
        elif self.tool.startswith("GATE:"):
            self.add_gate_pickup(pos, self.tool.split(":", 1)[1])
        elif self.tool == "ERASE":
            self.clear_at(pos)
        else:
            self.set_tile(pos, self.tool)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if self.text_active:
                if event.key == pygame.K_RETURN:
                    self.text_active = False
                elif event.key == pygame.K_BACKSPACE:
                    self.level_text = self.level_text[:-1]
                elif event.unicode.isdigit() and len(self.level_text) < 4:
                    self.level_text += event.unicode
                return
            if event.key == pygame.K_ESCAPE:
                self.game.menu.open("main")
            elif event.key == pygame.K_s and pygame.key.get_mods() & pygame.KMOD_CTRL:
                self.save(False)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # level number field
            if pygame.Rect(492, 52, 260, 30).collidepoint(event.pos):
                self.text_active = True
                return
            # Gate inventory +/- controls.
            for i, gate in enumerate(GATES):
                x = 492 + (i % 2) * 142
                y = 556 + (i // 2) * 23
                if pygame.Rect(x + 70, y - 2, 18, 19).collidepoint(event.pos):
                    self.gates[gate] = max(0, self.gates.get(gate, 0) - 1)
                    return
                if pygame.Rect(x + 91, y - 2, 18, 19).collidepoint(event.pos):
                    self.gates[gate] = self.gates.get(gate, 0) + 1
                    return
            action = self.button_at(event.pos)
            if action:
                self.activate(action)
                return
            pos = self.pos_at(event.pos)
            if pos:
                self.paint(pos)
                self.dragging_paint = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging_paint = False
        elif event.type == pygame.MOUSEMOTION and self.dragging_paint:
            pos = self.pos_at(event.pos)
            if pos:
                self.paint(pos)

    def data(self):
        quantum_positions = {
            parse_pos(pos) for pos in self.quantum_objects
        }

        valid_effects = [
            e for e in self.effects
            if parse_pos(e["position"]) in quantum_positions
        ]

        return {
            "tiles": {
                self.pos_in_level(pos): kind
                for pos, kind in sorted(self.tiles.items())
            },
            "objects": {
                self.pos_in_level(tuple(map(int, k.split(",")))): v
                for k, v in sorted(self.objects.items())
            },
            "quantum_objects": [
                self.pos_in_level(tuple(map(int, k.split(","))))
                for k in sorted(self.quantum_objects)
            ],
            "gates": {
                gate: count
                for gate, count in self.gates.items()
                if count > 0
            },
            "effects": valid_effects,
        }

    def save(self, quiet=False):
        n = self.level_number()
        if n is None:
            self.set_status("Enter a valid level number")
            return False
        data = self.data()
        try:
            validate_level(data, f"levels/{n}.json")
        except LevelError as err:
            self.set_status(str(err))
            return False
        try:
            os.makedirs("./levels", exist_ok=True)
            with open(f"./levels/{n}.json", "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
        except OSError as err:
            self.set_status(f"Save failed: {err}")
            return False
        self.game.available_levels = self.game.find_levels()
        self.game.menu.previews.pop(n, None)
        self.set_status(f"Saved level {n}")
        return True

    def load(self):
        n = self.level_number()
        if n is None:
            self.set_status("Enter a valid level number")
            return
        try:
            with open(f"./levels/{n}.json", encoding="utf-8") as file:
                data = json.load(file)
            validate_level(data, f"levels/{n}.json")
        except (OSError, json.JSONDecodeError, LevelError) as err:
            self.set_status(f"Load failed: {err}")
            return
        self.reset()
        for pos, kind in data["tiles"].items():
            self.tiles[parse_pos(pos)] = kind
        self.objects = {self.key(parse_pos(pos)): gate for pos, gate in data["objects"].items()}
        self.quantum_objects = {self.key(parse_pos(pos)) for pos in data["quantum_objects"]}
        self.gates = dict(data["gates"])
        self.effects = list(data["effects"])
        self.set_status(f"Loaded level {n}")

    def draw_text(self, text, x, y, size=18, color=INK):
        self.game.screen.blit(font(size).render(str(text), True, color), (x, y))

    def draw(self):
        screen = self.game.screen
        screen.fill(BG)
        self.draw_text("LEVEL EDITOR", 28, 25, 32, ACCENT)
        self.draw_text("Level #", 492, 25, 18, MUTED)
        field = pygame.Rect(492, 50, 260, 31)
        pygame.draw.rect(screen, PANEL, field)
        pygame.draw.rect(screen, ACCENT if self.text_active else EDGE, field, 2)
        self.draw_text(self.level_text, 503, 56, 18)
        self.draw_text("Tools", 492, 84, 17, MUTED)

        # grid
        for y in range(ROWS):
            for x in range(COLS):
                pos = (x, y)
                rect = pygame.Rect(GRID_X + x * CELL, GRID_Y + y * CELL, CELL, CELL)
                kind = self.tiles.get(pos, "EMPTY")
                name = "wall" if kind == "WALL" else ("end_tile" if kind == "END" else "tile")
                image = pygame.transform.scale(self.images[name], (CELL, CELL))
                screen.blit(image, rect)
                if kind == "START":
                    screen.blit(pygame.transform.scale(self.images["character"], (CELL, CELL)), rect)
                key = self.key(pos)
                if key in self.quantum_objects:
                    screen.blit(pygame.transform.scale(self.images["pillar"], (CELL, CELL)), rect)
                if key in self.objects:
                    screen.blit(pygame.transform.scale(self.images["box"], (CELL, CELL)), rect)
                pygame.draw.rect(screen, EDGE, rect, 1)
                if self.selected == pos:
                    pygame.draw.rect(screen, ACCENT, rect, 2)

        # controls
        for action, rect, label in self.buttons():
            active = (action == self.tool) or (action == "EFFECT:Clear" and False)
            fill = ACCENT if active else PANEL
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, INK if active else EDGE, rect, 1)
            self.draw_text(label, rect.x + 8, rect.y + 7, 15, BG if active else INK)

       # Gate pickup heading
        self.draw_text("Gate pickups", 492, 218, 17, MUTED)

        # Initial effects heading
        self.draw_text("Initial effects", 492, 368, 17, MUTED)

        self.draw_text("Initial gates", 215, 480, 16, MUTED)

        for i, gate in enumerate(GATES):
            x = 215 + (i % 2) * 142
            y = 500 + (i // 2) * 23
            count = self.gates.get(gate, 0)
            self.draw_text(f"{gate}: {count}", x, y, 14)
            minus = pygame.Rect(x + 70, y - 2, 18, 19)
            plus = pygame.Rect(x + 91, y - 2, 18, 19)
            pygame.draw.rect(screen, EDGE, minus); pygame.draw.rect(screen, EDGE, plus)
            self.draw_text("-", x + 76, y, 13); self.draw_text("+", x + 97, y, 13)

        # inventory click areas are handled separately below by event logic; show help
        selected = self.pos_in_level(self.selected) if self.selected else "none"

        self.draw_text(
            f"Selected: {selected}",
            28, 480, 16, MUTED
        )

        self.draw_text(
            f"Tool: {self.tool.replace('GATE:', 'gate ')}",
            28, 510, 16, MUTED
        )

        effect_names = [
            e["effect"]
            for e in self.effects
            if self.selected
            and parse_pos(e["position"]) == self.selected
        ]

        self.draw_text(
            "Effects: " + (", ".join(effect_names) if effect_names else "none"),
            28, 540, 16, MUTED
        )

        self.draw_text(
            self.status,
            492,
            580,
            14,
            MINT if "failed" not in self.status.lower() else RED
        )

        pygame.display.update()
