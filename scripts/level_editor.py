"""In-game level editor for Qungeon."""

import json
import os
import math
import copy
from pathlib import Path

import pygame

from scripts.common_functions import font
from scripts.level_validation import validate_level, LevelError, parse_pos
from scripts.level_share import encode_level, decode_level, PREFIX as SHARE_PREFIX
from scripts.level_check_job import LevelCheckJob


BG = (17, 19, 30)
PANEL = (26, 29, 43)
EDGE = (58, 63, 83)
INK = (238, 235, 225)
MUTED = (154, 158, 177)
ACCENT = (182, 164, 242)
MINT = (161, 220, 189)
RED = (233, 149, 159)


STATE_DEFAULT = {
    "x": {"real": 1.0, "imag": 0.0},
    "y": {"real": 0.0, "imag": 0.0},
}


TILE_TOOLS = (
    "EMPTY",
    "WALL",
    "START",
    "END",
    "ERASE",
)


EFFECTS = (
    "Flip",
    "Superposition",
    "Phase",
)


GATES = (
    "X",
    "H",
    "Z",
    "RotY",
    "CNOT",
    "CHAD",
    "SWAP",
)


# -------------------------------------------------------------
# Grid settings.
#
# The actual game grid remains 11 x 10.
#
# The level editor hides:
#   - first column: x = 0
#   - first row:    y = 0
#   - last row:     y = 9
#
# The remaining cells keep their original coordinates.
# -------------------------------------------------------------

CELL = 38
GRID_X, GRID_Y = 28, 92
COLS, ROWS = 11, 10

HIDDEN_FIRST_COL = 0
HIDDEN_FIRST_ROW = 0
HIDDEN_LAST_ROW = ROWS - 1


class LevelEditor:
    """Mouse-driven editor which writes the same JSON format the game loads."""

    def __init__(self, game):
        self.game = game

        self.images = {
            name: pygame.image.load(
                f"./assets/{name}.png"
            ).convert_alpha()
            for name in (
                "tile",
                "wall",
                "end_tile",
                "character",
                "box",
                "pillar",
            )
        }

        self.tiles = {}
        self.objects = {}
        self.quantum_objects = set()
        self.pillar_states = {}
        self.effects = []
        self.gates = {}

        self.tool = "EMPTY"
        self.selected = None
        self.state_x_text = "1"
        self.state_y_text = "0"
        self.state_field = None
        self.state_select_all = False

        self.level_text = str(
            self.next_level_number()
        )

        # The only shareable level code is the exact QGL snapshot
        # produced by this editor.
        self.share_code = ""

        self.text_active = False

        self.status = "New level"
        self.status_error = False
        self.status_time = 0

        self.dragging_paint = False
        self.validation = None
        self.validation_job = None
        self.validation_drawn = False
        self.checker_prepared = False
        self.pillar_previews = {}
        self.pressed_action = None
        self.pressed_at = 0

        self.reset()

    def next_level_number(self):
        levels_dir = Path("./levels")

        nums = [
            int(p.stem)
            for p in levels_dir.glob("*.json")
            if p.stem.isdigit()
        ]

        return max(nums, default=0) + 1

    def reset(self):
        self.cancel_validation()
        self.checker_prepared = False
        self.pillar_previews.clear()
        self.tiles = {}
        self.objects = {}
        self.quantum_objects = set()
        self.pillar_states = {}
        self.effects = []
        self.gates = {}

        self.tool = "EMPTY"
        self.selected = None
        self.state_x_text = "1"
        self.state_y_text = "0"
        self.state_field = None
        self.state_select_all = False

        self.share_code = ""

        self.status = "New level"
        self.status_error = False

    def level_number(self):
        try:
            n = int(
                self.level_text.strip()
            )

            return n if n > 0 else None

        except ValueError:
            return None

    def key(self, pos):
        return f"{pos[0]},{pos[1]}"

    def pos_at(self, mouse):
        x = (
            mouse[0] - GRID_X
        ) // CELL

        y = (
            mouse[1] - GRID_Y
        ) // CELL

        # ---------------------------------------------------------
        # The first column, first row, and last row are hidden
        # and cannot be selected or edited.
        #
        # IMPORTANT:
        # Coordinates are NOT shifted.
        # A visible cell is still its original level coordinate.
        # ---------------------------------------------------------

        if (
            0 <= x < COLS
            and 0 <= y < ROWS
            and x != HIDDEN_FIRST_COL
            and y != HIDDEN_FIRST_ROW
            and y != HIDDEN_LAST_ROW
        ):
            return (x, y)

        return None

    def pos_in_level(self, pos):
        return f"({pos[0]}, {pos[1]})"

    def clear_at(self, pos):
        self.tiles.pop(
            pos,
            None,
        )

        self.objects.pop(
            self.key(pos),
            None,
        )

        self.quantum_objects.discard(
            self.key(pos)
        )

        self.pillar_states.pop(
            self.key(pos),
            None,
        )

        self.effects = [
            e
            for e in self.effects
            if parse_pos(
                e["position"]
            ) != pos
        ]

        if self.selected == pos:
            self.selected = None

    def set_tile(self, pos, kind):
        self.clear_at(pos)

        self.tiles[pos] = kind

        if kind in ("START", "END"):
            for other, value in list(
                self.tiles.items()
            ):
                if (
                    other != pos
                    and value == kind
                ):
                    self.tiles[other] = "EMPTY"

        self.selected = pos

    def add_pillar(self, pos):
        self.tiles.setdefault(
            pos,
            "EMPTY",
        )

        self.objects.pop(
            self.key(pos),
            None,
        )

        self.quantum_objects.add(
            self.key(pos)
        )

        self.pillar_states.setdefault(
            self.key(pos),
            dict(STATE_DEFAULT),
        )

        self.select_pillar_state(pos)

        self.selected = pos

    def add_gate_pickup(self, pos, gate):
        self.tiles.setdefault(
            pos,
            "EMPTY",
        )

        self.quantum_objects.discard(
            self.key(pos)
        )

        self.pillar_states.pop(
            self.key(pos),
            None,
        )

        self.effects = [
            e
            for e in self.effects
            if parse_pos(
                e["position"]
            ) != pos
        ]

        self.objects[
            self.key(pos)
        ] = gate

        self.selected = pos

    def select_pillar_state(self, pos):
        state = self.pillar_states.get(
            self.key(pos),
            STATE_DEFAULT,
        )

        self.state_x_text = self.format_amplitude(
            state["x"]
        )

        self.state_y_text = self.format_amplitude(
            state["y"]
        )

        self.state_field = None
        self.state_select_all = False

    @staticmethod
    def amplitude_parts(value):
        if isinstance(value, dict):
            return (
                float(value.get("real", 0.0)),
                float(value.get("imag", 0.0)),
            )

        if isinstance(value, complex):
            return (
                float(value.real),
                float(value.imag),
            )

        return float(value), 0.0

    @classmethod
    def format_amplitude(cls, value):
        real, imag = cls.amplitude_parts(value)

        if abs(imag) < 1e-12:
            return f"{real:.8g}"

        sign = "+" if imag >= 0 else "-"

        return (
            f"{real:.8g}"
            f"{sign}"
            f"{abs(imag):.8g}i"
        )

    @staticmethod
    def parse_amplitude(text):
        cleaned = (
            text
            .strip()
            .lower()
            .replace(" ", "")
            .replace("i", "j")
        )

        if not cleaned:
            raise ValueError(
                "empty amplitude"
            )

        value = complex(cleaned)

        if not (
            value.real == value.real
            and value.imag == value.imag
        ):
            raise ValueError(
                "non-finite amplitude"
            )

        if (
            abs(value.real)
            == float("inf")
            or abs(value.imag)
            == float("inf")
        ):
            raise ValueError(
                "non-finite amplitude"
            )

        return value

    @classmethod
    def state_json(cls, x, y):
        return {
            "x": {
                "real": x.real,
                "imag": x.imag,
            },
            "y": {
                "real": y.real,
                "imag": y.imag,
            },
        }

    def apply_state(self):
        if (
            self.selected is None
            or self.key(self.selected)
            not in self.quantum_objects
        ):
            self.set_status(
                "Select a pillar first"
            )
            return

        try:
            x = self.parse_amplitude(
                self.state_x_text
            )

            y = self.parse_amplitude(
                self.state_y_text
            )

        except ValueError:
            self.set_status(
                "Amplitudes must be valid complex numbers, "
                "e.g. 0.707+0.707i"
            )
            return

        norm = (
            abs(x) ** 2
            + abs(y) ** 2
        )

        if norm <= 0:
            self.set_status(
                "At least one amplitude must be non-zero"
            )
            return

        scale = norm ** -0.5

        x *= scale
        y *= scale

        self.pillar_states[
            self.key(self.selected)
        ] = self.state_json(x, y)

        self.state_x_text = (
            self.format_amplitude(x)
        )

        self.state_y_text = (
            self.format_amplitude(y)
        )
        self.state_field = None
        self.state_select_all = False

        self.mark_modified()
        self.refresh_share_code()

        self.set_status(
            f"State {self.format_amplitude(x)}|0> + "
            f"{self.format_amplitude(y)}|1> set"
        )

    def pillar_preview(self, pos):
        """Render the applied amplitudes without importing the quantum stack."""
        state = self.pillar_states.get(self.key(pos), STATE_DEFAULT)
        xr, xi = self.amplitude_parts(state["x"])
        yr, yi = self.amplitude_parts(state["y"])
        key = (xr, xi, yr, yi)
        if key not in self.pillar_previews:
            zero, one = xr * xr + xi * xi, yr * yr + yi * yi
            total = zero + one
            zero, one = (zero / total, one / total) if total else (1.0, 0.0)
            color = (int(255 * zero), 0, int(255 * one))
            alpha_value = 255
            if zero >= 1.0 - 1e-9:
                color, alpha_value = (255, 255, 255), 150
            image = pygame.transform.scale(self.images["pillar"], (CELL, CELL)).convert_alpha()
            image.fill((*color, alpha_value), special_flags=pygame.BLEND_RGBA_MULT)
            self.pillar_previews[key] = (image, zero, one)
        return self.pillar_previews[key]

    def buttons(self):
        result = [
            (
                "COPY_SHARE",
                pygame.Rect(
                    492,
                    63,
                    260,
                    30,
                ),
                "Copy share code",
            ),
        ]

        labels = [
            ("EMPTY", "Empty"),
            ("WALL", "Wall"),
            ("START", "Start"),
            ("END", "End"),
            ("ERASE", "Erase"),
            ("PILLAR", "Pillar"),
        ]

        for i, (action, label) in enumerate(
            labels
        ):
            col = i % 3
            row = i // 3

            result.append(
                (
                    action,
                    pygame.Rect(
                        492 + col * 89,
                        128 + row * 39,
                        84,
                        32,
                    ),
                    label,
                )
            )

        for i, gate in enumerate(
            GATES
        ):
            col = i % 3
            row = i // 3

            result.append(
                (
                    "GATE:" + gate,
                    pygame.Rect(
                        492 + col * 89,
                        235 + row * 34,
                        84,
                        28,
                    ),
                    gate + " pickup",
                )
            )

        result += [
            ("STATE_ZERO", pygame.Rect(690, 365, 62, 32), "Use |0>"),
            ("STATE_ONE", pygame.Rect(690, 404, 62, 32), "Use |1>"),
            ("STATE_APPLY", pygame.Rect(492, 445, 160, 30), "Set state"),
            ("STATE_CLEAR", pygame.Rect(662, 445, 90, 30), "Reset"),
        ]
        result += [
            (action, pygame.Rect(492 + index * 66, 497, 62, 34), label)
            for index, (action, label) in enumerate((
                ("NEW", "New"), ("LOAD", "Load"), ("SAVE", "Save"), ("BACK", "Back"),
            ))
        ]
        result += [
            ("SAVE_EXIT", pygame.Rect(492, 536, 171, 34), "Save & exit"),
            ("TEST", pygame.Rect(670, 536, 82, 34), "Test"),
        ]
        return result

    def copy_share(self):
        """Copy the current exact editor share code to the clipboard."""
        self.request_validation("COPY_SHARE")

    def copy_validated_share(self, code):
        import sys
        if sys.platform == "emscripten":
            import asyncio
            from js import window

            async def copy_to_browser():
                try:
                    await window.navigator.clipboard.writeText(code)
                    self.set_status("Share code copied to clipboard")
                except Exception:
                    self.set_status("Clipboard unavailable. Your validated share code is ready.")

            asyncio.create_task(copy_to_browser())
            return

        if os.name == "nt":
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        "$v = [Console]::In.ReadToEnd(); "
                        "Set-Clipboard -Value $v",
                    ],
                    input=code,
                    text=True,
                    capture_output=True,
                    timeout=2,
                    check=False,
                )

                if result.returncode == 0:
                    self.set_status(
                        "Share code copied to clipboard"
                    )
                    return

            except (
                OSError,
                subprocess.SubprocessError,
            ):
                pass

        try:
            pygame.scrap.init()

            pygame.scrap.put(
                pygame.SCRAP_TEXT,
                code.encode("utf-8"),
            )

            self.set_status(
                "Share code copied to clipboard"
            )

            return

        except Exception:
            pass

        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()

            root.clipboard_clear()
            root.clipboard_append(code)

            root.update()
            root.destroy()

            self.set_status(
                "Share code copied to clipboard"
            )

        except Exception:
            self.set_status(
                "Could not access clipboard"
            )

    def button_at(self, pos):
        for action, rect, label in self.buttons():
            if rect.collidepoint(pos):
                return action

        return None

    def set_status(self, text, error=False):
        self.status = text
        self.status_error = error
        self.status_time = (
            pygame.time.get_ticks()
        )

    def mark_modified(self):
        """A hand edit switches to an exact QGL share code."""

        self.share_code = ""

    def refresh_share_code(self):
        """Update the exact share code for the current editor state."""

        try:
            self.share_code = encode_level(
                self.data()
            )

        except (
            ValueError,
            LevelError,
        ):
            self.share_code = ""

    def load_share_code(self, text):
        text = text.strip()

        if not text:
            self.set_status(
                "Paste a QGL share code first"
            )
            return False

        if not text.upper().startswith(
            SHARE_PREFIX
        ):
            self.set_status(
                "Only QGL- editor share codes can be loaded"
            )
            return False

        try:
            data = decode_level(text)

        except ValueError as err:
            self.set_status(
                str(err)
            )
            return False

        if not data.get("editor_created"):
            self.set_status(
                "This code was not created by the level editor"
            )
            return False

        self.reset()

        self.level_text = str(
            self.next_level_number()
        )

        self.tiles = {
            parse_pos(pos): kind
            for pos, kind
            in data["tiles"].items()
        }

        self.objects = {
            self.key(parse_pos(pos)): gate
            for pos, gate
            in data["objects"].items()
        }

        self.quantum_objects = {
            self.key(parse_pos(pos))
            for pos in data["quantum_objects"]
        }

        self.pillar_states = {
            self.key(parse_pos(pos)): dict(state)
            for pos, state
            in data["pillar_states"].items()
        }

        self.effects = []

        self.gates = dict(
            data["gates"]
        )

        self.share_code = encode_level(
            data
        )

        self.set_status(
            "Loaded editor level share code"
        )

        if self.quantum_objects:
            first = sorted(
                self.quantum_objects
            )[0]

            self.selected = tuple(
                map(
                    int,
                    first.split(","),
                )
            )

            self.select_pillar_state(
                self.selected
            )

        return True

    def activate(self, action):
        self.pressed_action = action
        self.pressed_at = pygame.time.get_ticks()
        if action in (
            "EMPTY",
            "WALL",
            "START",
            "END",
            "ERASE",
        ):
            self.tool = action
            self.effect_tool = None
            return

        if action == "PILLAR":
            self.tool = action
            self.effect_tool = None
            return

        if action.startswith(
            "GATE:"
        ):
            self.tool = action
            self.effect_tool = None
            return

        if action in ("STATE_ZERO", "STATE_ONE"):
            if self.selected is None or self.key(self.selected) not in self.quantum_objects:
                self.set_status("Select a pillar first")
                return
            one = action == "STATE_ONE"
            self.state_x_text, self.state_y_text = ("0", "1") if one else ("1", "0")
            self.state_field = None
            self.state_select_all = False
            self.set_status(f"Selected |{int(one)}>. Click Set state to apply.")
            return

        if action == "STATE_APPLY":
            self.apply_state()
            return

        if action == "STATE_CLEAR":
            if (
                self.selected
                and self.key(self.selected)
                in self.quantum_objects
            ):
                self.state_x_text = "1"
                self.state_y_text = "0"
                self.apply_state()

            else:
                self.set_status(
                    "Select a pillar first"
                )

            return

        if action == "COPY_SHARE":
            self.copy_share()

        elif action == "NEW":
            self.reset()

            self.level_text = str(
                self.next_level_number()
            )

            self.set_status(
                "New level"
            )

        elif action == "LOAD":
            self.load()

        elif action == "SAVE":
            self.save(False)

        elif action == "SAVE_EXIT":
            self.request_validation("SAVE_EXIT")

        elif action == "TEST":
            self.request_validation("TEST")

        elif action == "BACK":
            self.cancel_validation()
            self.game.menu.open(
                "main"
            )

    def paint(self, pos):
        # Extra safety: even if paint() is called directly,
        # never allow editing of the hidden cells.
        x, y = pos

        if (
            x == HIDDEN_FIRST_COL
            or y == HIDDEN_FIRST_ROW
            or y == HIDDEN_LAST_ROW
        ):
            return

        self.mark_modified()

        if self.tool == "PILLAR":
            self.add_pillar(pos)

        elif self.tool.startswith(
            "GATE:"
        ):
            self.add_gate_pickup(
                pos,
                self.tool.split(
                    ":",
                    1,
                )[1],
            )

        elif self.tool == "ERASE":
            self.clear_at(pos)

        else:
            self.set_tile(
                pos,
                self.tool,
            )

        self.refresh_share_code()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:

            if self.state_field:
                attribute = "state_x_text" if self.state_field == "x" else "state_y_text"
                if event.key == pygame.K_a and getattr(event, "mod", 0) & (pygame.KMOD_CTRL | pygame.KMOD_META):
                    self.state_select_all = True
                    return
                if event.key in (
                    pygame.K_RETURN,
                    pygame.K_KP_ENTER,
                ):
                    self.state_field = None
                    return

                if event.key == pygame.K_ESCAPE:
                    self.state_field = None
                    return

                if event.key == pygame.K_BACKSPACE:
                    if self.state_select_all:
                        setattr(self, attribute, "")
                        self.state_select_all = False
                        return
                    if self.state_field == "x":
                        self.state_x_text = (
                            self.state_x_text[:-1]
                        )
                    else:
                        self.state_y_text = (
                            self.state_y_text[:-1]
                        )

                    return

                if (
                    event.unicode and event.unicode
                    in "0123456789.-+ijIJ()eE"
                    and (self.state_select_all or len(
                        self.state_x_text
                        if self.state_field == "x"
                        else self.state_y_text
                    ) < 16)
                ):
                    if self.state_select_all:
                        setattr(self, attribute, event.unicode)
                        self.state_select_all = False
                        return
                    if self.state_field == "x":
                        self.state_x_text += (
                            event.unicode
                        )
                    else:
                        self.state_y_text += (
                            event.unicode
                        )

                    return

                return

            if self.text_active:
                if event.key in (
                    pygame.K_RETURN,
                    pygame.K_KP_ENTER,
                ):
                    self.text_active = False
                    self.load()

                elif event.key == pygame.K_BACKSPACE:
                    self.level_text = (
                        self.level_text[:-1]
                    )

                elif (
                    event.unicode.isdigit()
                    and len(self.level_text) < 4
                ):
                    self.level_text += (
                        event.unicode
                    )

                return

            if event.key == pygame.K_ESCAPE:
                self.cancel_validation()
                self.game.menu.open(
                    "main"
                )

            elif (
                event.key == pygame.K_s
                and pygame.key.get_mods()
                & pygame.KMOD_CTRL
            ):
                self.save(False)

            return

        if (
            event.type
            == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            # Level number input.
            input_rect = pygame.Rect(
                492,
                25,
                260,
                31,
            )

            if input_rect.collidepoint(
                event.pos
            ):
                self.text_active = True
                self.state_field = None
                self.state_select_all = False
                return

            self.text_active = False

            # -----------------------------------------------------
            # Pillar amplitude fields.
            # -----------------------------------------------------
            for field_id, rect in (
                (
                    "x",
                    pygame.Rect(
                        492,
                        365,
                        185,
                        32,
                    ),
                ),
                (
                    "y",
                    pygame.Rect(
                        492,
                        404,
                        185,
                        32,
                    ),
                ),
            ):
                if rect.collidepoint(
                    event.pos
                ):
                    self.state_field = field_id
                    self.state_select_all = True
                    return

            self.state_field = None
            self.state_select_all = False

            # Initial gate +/- controls.
            for i, gate in enumerate(
                GATES
            ):
                x = (
                    215
                    + (i % 2) * 142
                )

                y = (
                    500
                    + (i // 2) * 23
                )

                minus = pygame.Rect(
                    x + 70,
                    y - 2,
                    18,
                    19,
                )

                plus = pygame.Rect(
                    x + 91,
                    y - 2,
                    18,
                    19,
                )

                if minus.collidepoint(
                    event.pos
                ):
                    self.mark_modified()

                    self.gates[gate] = max(
                        0,
                        self.gates.get(
                            gate,
                            0,
                        ) - 1,
                    )

                    self.refresh_share_code()
                    return

                if plus.collidepoint(
                    event.pos
                ):
                    self.mark_modified()

                    self.gates[gate] = (
                        self.gates.get(
                            gate,
                            0,
                        ) + 1
                    )

                    self.refresh_share_code()
                    return

            action = self.button_at(
                event.pos
            )

            if action:
                self.activate(
                    action
                )
                return

            pos = self.pos_at(
                event.pos
            )

            if pos:
                self.paint(pos)
                self.dragging_paint = True

        elif (
            event.type
            == pygame.MOUSEBUTTONUP
            and event.button == 1
        ):
            self.dragging_paint = False

        elif (
            event.type
            == pygame.MOUSEMOTION
            and self.dragging_paint
        ):
            pos = self.pos_at(
                event.pos
            )

            if pos:
                self.paint(pos)

    def data(self):
        quantum_positions = {
            parse_pos(pos)
            for pos in self.quantum_objects
        }

        valid_effects = [
            e
            for e in self.effects
            if parse_pos(
                e["position"]
            ) in quantum_positions
        ]

        data = {
            "tiles": {
                self.pos_in_level(pos): kind
                for pos, kind
                in sorted(
                    self.tiles.items()
                )
            },

            "objects": {
                self.pos_in_level(
                    tuple(
                        map(
                            int,
                            k.split(","),
                        )
                    )
                ): v
                for k, v
                in sorted(
                    self.objects.items()
                )
            },

            "quantum_objects": [
                self.pos_in_level(
                    tuple(
                        map(
                            int,
                            k.split(","),
                        )
                    )
                )
                for k in sorted(
                    self.quantum_objects
                )
            ],

            "pillar_states": {
                self.pos_in_level(
                    tuple(
                        map(
                            int,
                            k.split(","),
                        )
                    )
                ): dict(
                    self.pillar_states[k]
                )
                for k in sorted(
                    self.quantum_objects
                )
            },

            "editor_created": True,

            "gates": {
                gate: count
                for gate, count
                in self.gates.items()
                if count > 0
            },

            "effects": [],
        }

        return data

    def save(self, quiet=False):
        """Queue a checked save; completion is handled on a later frame."""
        self.request_validation("SAVE")

    def request_validation(self, action):
        if self.validation is not None:
            return
        n = self.level_number()
        if n is None and action != "COPY_SHARE":
            self.set_status(
                "Enter a valid level number"
            )
            return
        self.validation = {"action": action, "number": n, "data": copy.deepcopy(self.data())}
        self.validation_drawn = False
        self.set_status("Checking level validity")

    def cancel_validation(self):
        if self.validation_job is not None:
            self.validation_job.cancel()
        self.validation = None
        self.validation_job = None
        self.validation_drawn = False

    def update_validation(self):
        if self.validation is None or not self.validation_drawn:
            return
        if self.game.menu.page != "editor":
            self.cancel_validation()
            return
        try:
            if self.validation_job is None:
                self.validation_job = LevelCheckJob(self.validation["data"])
                return
            result = self.validation_job.poll()
            if result is None:
                phase = getattr(self.validation_job, "phase", "checking")
                self.set_status(
                    "Preparing level checker (first use; downloading Python and quantum libraries)"
                    if phase == "preparing" else "Checking level validity (searching for a solution)"
                )
                return
        except Exception as error:
            self.cancel_validation()
            self.set_status(f"Level check failed: {error}")
            return
        pending = self.validation
        self.cancel_validation()
        if pending["data"] != self.data() or pending["number"] != self.level_number():
            self.set_status("Level changed during check. Please check again.")
            return
        if result["solvable"] is not True:
            self.set_status(result["message"], error=True)
            return
        code = encode_level(pending["data"])
        if pending["action"] == "COPY_SHARE":
            self.share_code = code
            self.copy_validated_share(code)
            return
        if self.save_validated(pending["number"], pending["data"]):
            if pending["action"] == "SAVE_EXIT":
                self.game.menu.open("main")
            elif pending["action"] == "TEST":
                self.game.menu.activate(f"level:{pending['number']}")

    def save_validated(self, n, data):
        try:
            os.makedirs(
                "./levels",
                exist_ok=True,
            )

            with open(
                f"./levels/{n}.json",
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    data,
                    file,
                    indent=2,
                )

        except OSError as err:
            self.set_status(
                f"Save failed: {err}"
            )
            return False

        self.game.available_levels = (
            self.game.find_levels()
        )

        self.game.menu.previews.pop(
            n,
            None,
        )

        self.share_code = encode_level(
            data
        )

        self.set_status(
            f"Saved level {n} · share code ready"
        )

        return True

    def load(self):
        n = self.level_number()

        if n is None:
            self.set_status(
                "Enter a valid level number"
            )
            return

        try:
            with open(
                f"./levels/{n}.json",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

            validate_level(
                data,
                f"levels/{n}.json",
            )

        except (
            OSError,
            json.JSONDecodeError,
            LevelError,
        ):
            self.set_status(
                f"Load failed: level {n} not found"
            )
            return

        self.reset()

        for pos, kind in data[
            "tiles"
        ].items():
            self.tiles[
                parse_pos(pos)
            ] = kind

        self.objects = {
            self.key(
                parse_pos(pos)
            ): gate
            for pos, gate
            in data["objects"].items()
        }

        self.quantum_objects = {
            self.key(
                parse_pos(pos)
            )
            for pos
            in data["quantum_objects"]
        }

        self.pillar_states = {
            self.key(
                parse_pos(pos)
            ): dict(state)
            for pos, state
            in data.get(
                "pillar_states",
                {},
            ).items()
        }

        for key in self.quantum_objects:
            self.pillar_states.setdefault(
                key,
                dict(STATE_DEFAULT),
            )

        self.gates = dict(
            data["gates"]
        )

        self.effects = list(
            data["effects"]
        )

        data["editor_created"] = True

        data["pillar_states"] = {
            self.pos_in_level(
                tuple(
                    map(
                        int,
                        key.split(",")
                    )
                )
            ): dict(state)
            for key, state
            in self.pillar_states.items()
        }

        self.share_code = encode_level(
            self.data()
        )

        self.set_status(
            f"Loaded level {n}"
        )

    def draw_text(
        self,
        text,
        x,
        y,
        size=18,
        color=INK,
    ):
        self.game.screen.blit(
            font(size).render(
                str(text),
                True,
                color,
            ),
            (x, y),
        )

    def draw(self):
        screen = self.game.screen

        screen.fill(BG)

        # ---------------------------------------------------------
        # Header.
        # ---------------------------------------------------------
        self.draw_text(
            "LEVEL EDITOR",
            28,
            25,
            32,
            ACCENT,
        )

        self.draw_text(
            "Level #",
            442,
            31,
            18,
            MUTED,
        )

        field = pygame.Rect(
            492,
            25,
            260,
            31,
        )

        pygame.draw.rect(
            screen,
            PANEL,
            field,
        )

        pygame.draw.rect(
            screen,
            (
                ACCENT
                if self.text_active
                else EDGE
            ),
            field,
            2,
        )

        self.draw_text(
            self.level_text,
            503,
            31,
            18,
        )

        # ---------------------------------------------------------
        # Grid rendering.
        #
        # The first column, first row, and last row are skipped.
        #
        # IMPORTANT:
        # We do NOT shift the coordinates.
        # A visible cell at (1, 1) is still (1, 1).
        # ---------------------------------------------------------
        for y in range(ROWS):
            for x in range(COLS):

                if (
                    x == HIDDEN_FIRST_COL
                    or y == HIDDEN_FIRST_ROW
                    or y == HIDDEN_LAST_ROW
                ):
                    continue

                pos = (x, y)

                rect = pygame.Rect(
                    GRID_X + x * CELL,
                    GRID_Y + y * CELL,
                    CELL,
                    CELL,
                )

                kind = self.tiles.get(
                    pos
                )

                if kind is None:
                    pygame.draw.rect(
                        screen,
                        (0, 0, 0),
                        rect,
                    )

                else:
                    name = (
                        "wall"
                        if kind == "WALL"
                        else (
                            "end_tile"
                            if kind == "END"
                            else "tile"
                        )
                    )

                    image = pygame.transform.scale(
                        self.images[name],
                        (CELL, CELL),
                    )

                    screen.blit(
                        image,
                        rect,
                    )

                if kind == "START":
                    screen.blit(
                        pygame.transform.scale(
                            self.images[
                                "character"
                            ],
                            (CELL, CELL),
                        ),
                        rect,
                    )

                key = self.key(pos)

                if key in self.quantum_objects:
                    pillar_img, _, _ = self.pillar_preview(pos)
                    screen.blit(pillar_img, rect)

                if key in self.objects:
                    screen.blit(
                        pygame.transform.scale(
                            self.images["box"],
                            (CELL, CELL),
                        ),
                        rect,
                    )

                pygame.draw.rect(
                    screen,
                    EDGE,
                    rect,
                    1,
                )

                if self.selected == pos:
                    pygame.draw.rect(
                        screen,
                        ACCENT,
                        rect,
                        2,
                    )

        # ---------------------------------------------------------
        # UI buttons.
        # ---------------------------------------------------------
        for action, rect, label in self.buttons():
            active = (
                action == self.tool
            )
            pressed = action == self.pressed_action and pygame.time.get_ticks() - self.pressed_at < 300

            fill = MINT if pressed else ACCENT if active else PANEL

            pygame.draw.rect(
                screen,
                fill,
                rect,
            )

            pygame.draw.rect(
                screen,
                (
                    INK
                    if active or pressed
                    else EDGE
                ),
                rect,
                1,
            )

            checking = self.validation is not None and self.validation["action"] == action
            if checking:
                center = (rect.x + 12, rect.centery)
                angle = pygame.time.get_ticks() / 160
                pygame.draw.arc(screen, ACCENT,
                                pygame.Rect(center[0] - 5, center[1] - 5, 10, 10),
                                angle, angle + math.pi * 1.5, 2)
            progress = "Checking level validity" if rect.width >= 171 else "Checking" if rect.width >= 82 else "..."
            self.draw_text(
                progress if checking else label,
                rect.x + (24 if checking else 8),
                rect.y + 7,
                13 if checking else 15,
                (
                    BG
                    if active or pressed
                    else INK
                ),
            )

        # ---------------------------------------------------------
        # Section headings.
        # ---------------------------------------------------------
        self.draw_text(
            "Tools",
            492,
            110,
            17,
            MUTED,
        )

        self.draw_text(
            "Gate pickups",
            492,
            215,
            17,
            MUTED,
        )

        # ---------------------------------------------------------
        # Pillar state.
        # ---------------------------------------------------------
        self.draw_text(
            "Amplitudes: |0>, |1>",
            492,
            348,
            17,
            MUTED,
        )

        x_rect = pygame.Rect(
            492,
            365,
            185,
            32,
        )

        pygame.draw.rect(
            screen,
            PANEL,
            x_rect,
        )

        pygame.draw.rect(
            screen,
            (
                ACCENT
                if self.state_field == "x"
                else EDGE
            ),
            x_rect,
            2,
        )

        if self.state_field == "x" and self.state_select_all and self.state_x_text:
            width, height = font(15).size(self.state_x_text)
            pygame.draw.rect(screen, ACCENT,
                             (x_rect.x + 6, x_rect.y + 5, min(width + 4, x_rect.width - 12), height + 4))
        self.draw_text(
            self.state_x_text,
            x_rect.x + 8,
            x_rect.y + 7,
            15,
            BG if self.state_field == "x" and self.state_select_all else INK,
        )

        y_rect = pygame.Rect(
            492,
            404,
            185,
            32,
        )

        pygame.draw.rect(
            screen,
            PANEL,
            y_rect,
        )

        pygame.draw.rect(
            screen,
            (
                ACCENT
                if self.state_field == "y"
                else EDGE
            ),
            y_rect,
            2,
        )

        if self.state_field == "y" and self.state_select_all and self.state_y_text:
            width, height = font(15).size(self.state_y_text)
            pygame.draw.rect(screen, ACCENT,
                             (y_rect.x + 6, y_rect.y + 5, min(width + 4, y_rect.width - 12), height + 4))
        self.draw_text(
            self.state_y_text,
            y_rect.x + 8,
            y_rect.y + 7,
            15,
            BG if self.state_field == "y" and self.state_select_all else INK,
        )

        self.draw_text("Use presets or edit amplitudes, then Set state.", 492, 480, 13, MUTED)

        # ---------------------------------------------------------
        # Initial gates.
        # ---------------------------------------------------------
        self.draw_text(
            "Initial gates",
            215,
            480,
            16,
            MUTED,
        )

        for i, gate in enumerate(
            GATES
        ):
            x = (
                215
                + (i % 2) * 142
            )

            y = (
                500
                + (i // 2) * 23
            )

            count = self.gates.get(
                gate,
                0,
            )

            self.draw_text(
                f"{gate}: {count}",
                x,
                y,
                14,
            )

            minus = pygame.Rect(
                x + 70,
                y - 2,
                18,
                19,
            )

            plus = pygame.Rect(
                x + 91,
                y - 2,
                18,
                19,
            )

            pygame.draw.rect(
                screen,
                EDGE,
                minus,
            )

            pygame.draw.rect(
                screen,
                EDGE,
                plus,
            )

            self.draw_text(
                "-",
                x + 76,
                y,
                13,
            )

            self.draw_text(
                "+",
                x + 97,
                y,
                13,
            )

        # ---------------------------------------------------------
        # Selection information.
        # ---------------------------------------------------------
        selected = (
            self.pos_in_level(
                self.selected
            )
            if self.selected
            else "none"
        )

        self.draw_text(
            f"Selected: {selected}",
            28,
            480,
            16,
            MUTED,
        )

        self.draw_text(
            "Tool: "
            + self.tool.replace(
                "GATE:",
                "gate ",
            ),
            28,
            510,
            16,
            MUTED,
        )

        if self.selected and self.key(self.selected) in self.quantum_objects:
            preview, zero, one = self.pillar_preview(self.selected)
            screen.blit(pygame.transform.scale(preview, (24, 24)), (724, 341))
            self.draw_text(f"P(0): {zero:.0%}  P(1): {one:.0%}", 28, 540, 14, MUTED)

        # ---------------------------------------------------------
        # Status.
        # ---------------------------------------------------------
        self.draw_text(
            self.status,
            28,
            580,
            14,
            (
                ACCENT if self.validation is not None else
                RED if self.status_error or any(word in self.status.lower() for word in
                           ("failed", "not valid", "could not", "search limit", "changed")) else MINT
            ),
        )

        pygame.display.update()
        if not self.checker_prepared:
            try:
                LevelCheckJob.prepare()
                self.checker_prepared = True
            except Exception:
                # A failed warmup is retried when the player requests a check.
                pass
        if self.validation is not None:
            self.validation_drawn = True
