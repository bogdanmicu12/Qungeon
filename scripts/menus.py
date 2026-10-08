"""Pygame menus shared by the desktop and browser builds."""

import json
import math
from pathlib import Path

import pygame
from scripts.common_functions import font
from scripts.level_validation import LevelError, parse_pos, read_level
from scripts.quantum_menu import QuantumMenu
from scripts.scroll_view import ScrollView


BG = (17, 19, 30)
PANEL = (26, 29, 43)
EDGE = (58, 63, 83)
INK = (238, 235, 225)
MUTED = (154, 158, 177)
ACCENT = (182, 164, 242)
MINT = (161, 220, 189)
RED = (233, 149, 159)

DEFAULT_SETTINGS = {
    "decoherence": False,
    "entanglement_guides": True,
    "stuck_warning": True,
    "full_run_completion": True,
    "auto_quantum_runs": False,
}

SETTINGS_PATH = Path(".qungeon-settings.json")


def normalize_settings(value):
    """Ignore unknown keys and malformed saved preferences."""
    value = value if isinstance(value, dict) else {}
    return {
        key: value[key] if type(value.get(key)) is bool else default
        for key, default in DEFAULT_SETTINGS.items()
    }


def load_settings():
    try:
        return normalize_settings(
            json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    try:
        SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


WORDMARK = {
    "Q": ("01110", "11011", "11011", "11011", "11111", "01110", "00011"),
    "U": ("11011", "11011", "11011", "11011", "11011", "11011", "01110"),
    "N": ("11001", "11101", "11101", "10111", "10111", "10011", "10011"),
    "G": ("01111", "11000", "11000", "11011", "11011", "11011", "01110"),
    "E": ("11111", "11000", "11000", "11110", "11000", "11000", "11111"),
    "O": ("01110", "11011", "11011", "11011", "11011", "11011", "01110"),
}


class MenuUI:
    def __init__(self, game):
        self.game = game
        self.page = "main"
        self.return_page = "main"
        self.help_return = "main"
        self.focus = 0
        self.pressed = None

        # Level choices waiting for the quantum/gameplay stack to be ready.
        self.pending = None
        self.loading_from = "main"
        self.loading_drawn = False

        self.previews = {}
        self.settings_saved = True

        # Custom QGL level input.
        self.seed_text = ""
        self.seed_active = False
        self.seed_error = ""

        self.quantum = QuantumMenu(self)
        self.level_scroll = ScrollView(
            (60, 207, 680, 276),
            (680, 0),
        )

        self.images = {
            name: pygame.image.load(f"./assets/{name}.png")
            for name in (
                "tile",
                "wall",
                "pillar",
                "character",
                "end_tile",
                "box",
            )
        }

        self.images["pillar"].fill(
            (*ACCENT, 255),
            special_flags=pygame.BLEND_RGBA_MULT,
        )

        self.scene_images = {
            name: pygame.transform.scale(
                image,
                (48, 60 if name == "pillar" else 48),
            )
            for name, image in self.images.items()
        }

        self.background = self.make_background()
        self.veil = pygame.Surface((800, 600), pygame.SRCALPHA)
        self.veil.fill((8, 10, 18, 205))

    def text(self, text, x, y, size=24, color=INK, center=False):
        image = font(size).render(str(text), True, color)
        rect = (
            image.get_rect(midtop=(x, y))
            if center
            else image.get_rect(topleft=(x, y))
        )
        self.game.screen.blit(image, rect)

    def make_background(self):
        surface = pygame.Surface((800, 600))
        surface.fill(BG)

        for x in range(0, 800, 32):
            for y in range(0, 600, 32):
                pygame.draw.rect(
                    surface,
                    (28, 31, 45),
                    (x, y, 2, 2),
                )

        pygame.draw.line(
            surface,
            EDGE,
            (40, 552),
            (760, 552),
        )

        return surface

    def open(self, page):
        self.quantum.cancel_scroll_drag()
        self.level_scroll.drag = None

        if page == "levels":
            self.level_scroll.y = 0

        if self.page == "playing":
            self.game.cancel_dragging()

        self.page = page
        self.focus = 0
        self.pressed = None
        self.game.last_tick = pygame.time.get_ticks()

    def buttons(self):
        """Return (action, rectangle, label, supporting text) for this page."""

        if self.page in (
            "quantum",
            "quantum_history",
            "quantum_map",
            "quantum_circuit",
        ):
            return self.quantum.buttons()

        if self.page == "complete":
            actions = [
                ("quantum_run", "Run on Quantum Computer"),
                (
                    "next_level",
                    "Continue to next level",
                )
                if self.game.has_next_level()
                else (
                    "retry_run",
                    "Play again",
                ),
                ("main", "Return to menu"),
            ]

            return [
                (
                    action,
                    pygame.Rect(180, 320 + i * 57, 440, 44),
                    label,
                    "",
                )
                for i, (action, label) in enumerate(actions)
            ]

        if self.page == "main":
            return [
                (
                    action,
                    pygame.Rect(
                        60,
                        300 + index * 50,
                        326,
                        40,
                    ),
                    label,
                    hint,
                )
                for index, (action, label, hint) in enumerate(
                    (
                        ("play", "Play", ""),
                        ("levels", "Level select", "02"),
                        ("editor", "Level editor", "03"),
                        ("settings", "Settings", "04"),
                        ("help", "How to play", "05"),
                    )
                )
            ] + [
                (
                    "quantum_history",
                    pygame.Rect(
                        482,
                        500,
                        258,
                        40,
                    ),
                    "Hardware runs",
                    "",
                )
            ]

        if self.page == "play":
            return [
                (
                    "normal_levels",
                    pygame.Rect(60, 245, 680, 58),
                    "Normal levels",
                    "Play the built-in levels in order.",
                ),
                (
                    "custom_seed",
                    pygame.Rect(60, 319, 680, 58),
                    "Custom level code",
                    "Paste a QGL share code copied from the level editor.",
                ),
                (
                    "back",
                    pygame.Rect(60, 491, 200, 44),
                    "Back",
                    "",
                ),
            ]

        if self.page == "custom_seed":
            return [
                (
                    "load_seed",
                    pygame.Rect(486, 360, 254, 48),
                    "Play custom level",
                    "",
                ),
                (
                    "back",
                    pygame.Rect(60, 491, 200, 44),
                    "Back",
                    "",
                ),
            ]

        if self.page in ("settings", "setup"):
            options = [
                (
                    "decoherence",
                    "Decoherence time mode",
                    "Coming soon. Preference saved.",
                ),
                (
                    "entanglement_guides",
                    "Entanglement guides",
                    "Show connections when you hover over a pillar.",
                ),
                (
                    "stuck_warning",
                    "Stuck detection",
                    "Offer a restart when the level can no longer be completed.",
                ),
                (
                    "full_run_completion",
                    "Level completion screens",
                    "Full runs: pause after each level. The final summary always stays.",
                ),
            ]

            if not self.game.settings["full_run_completion"]:
                options.append(
                    (
                        "auto_quantum_runs",
                        "Queue levels on Quantum Inspire",
                        "Run compatible circuits automatically: up to 1,024 shots per level.",
                    )
                )

            result = [
                (
                    "toggle:" + key,
                    pygame.Rect(
                        60,
                        196 + index * 54,
                        680,
                        50,
                    ),
                    title,
                    description,
                )
                for index, (key, title, description) in enumerate(options)
            ]

            result.append(
                (
                    "back",
                    pygame.Rect(
                        60,
                        499,
                        200,
                        42,
                    ),
                    "Back",
                    "",
                )
            )

            if self.page == "setup":
                result.append(
                    (
                        "start",
                        pygame.Rect(
                            486,
                            499,
                            254,
                            42,
                        ),
                        "Begin run",
                        "",
                    )
                )

            return result

        if self.page == "levels":
            result = []

            view = self.level_scroll
            rows = -(-len(self.game.available_levels) // 4)

            view.resize(
                (
                    view.rect.width,
                    max(0, rows * 128 - 16 + 4),
                )
            )

            for index, level in enumerate(
                self.game.available_levels
            ):
                result.append(
                    (
                        f"level:{level}",
                        pygame.Rect(
                            60 + (index % 4) * 174,
                            round(
                                view.rect.y
                                + (index // 4) * 128
                                - view.y
                            ),
                            158,
                            112,
                        ),
                        f"Level {level:02}",
                        "",
                    )
                )

            return result + [
                (
                    "back",
                    pygame.Rect(
                        60,
                        491,
                        200,
                        44,
                    ),
                    "Back",
                    "",
                )
            ]

        if self.page == "help":
            return [
                (
                    "back",
                    pygame.Rect(
                        60,
                        491,
                        200,
                        44,
                    ),
                    "Back",
                    "",
                )
            ]

        actions = {
            "paused": (
                ("resume", "Resume"),
                ("retry", "Restart level"),
                ("help", "How to play"),
                ("main", "Return to menu"),
            ),
            "failed": (
                ("retry", "Restart level"),
                ("settings", "Settings"),
                ("main", "Return to menu"),
            ),
            "complete": (
                ("retry_run", "Play again"),
                ("main", "Return to menu"),
            ),
        }.get(self.page, ())

        top = {
            "paused": 253,
            "failed": 306,
        }.get(self.page, 339)

        return [
            (
                action,
                pygame.Rect(
                    244,
                    top + index * 53,
                    312,
                    42,
                ),
                label,
                "",
            )
            for index, (action, label) in enumerate(actions)
        ]

    def update(self):
        """Start a pending gameplay action after the loading screen is drawn.

        Importing/loading the quantum stack may block for several seconds, so
        the selection is held until a loading frame has actually been shown.
        """

        if self.pending is None or not self.loading_drawn:
            return

        if not self.game.gameplay_downloaded():
            return

        action, self.pending = self.pending, None
        self.loading_drawn = False

        # The actual action runs here, after the loading screen has reached
        # the display.
        self.activate(action, released=True)

        if self.page == "loading":
            # The action failed to load the selected level.
            self.open(self.loading_from)

        # Drop input that piled up while the blocking load was running, but
        # leave QUIT events alone so the window can still close.
        pygame.event.clear(
            (
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEBUTTONUP,
                pygame.MOUSEMOTION,
                pygame.KEYDOWN,
                pygame.KEYUP,
            )
        )

    def back(self):
        if self.page in (
            "quantum",
            "quantum_history",
            "quantum_map",
            "quantum_circuit",
        ):
            self.quantum.back()

        elif self.page == "paused":
            self.open("playing")

        elif self.page == "loading":
            # The stack may never arrive in the browser. Drop the held
            # selection rather than leaving the player stranded here.
            self.pending = None
            self.loading_drawn = False
            self.open(self.loading_from)

        elif self.page in ("help", "settings"):
            self.open(
                self.return_page
                if self.page == "settings"
                else self.help_return
            )

        elif self.page in (
            "setup",
            "play",
            "custom_seed",
            "levels",
            "editor",
        ):
            self.open("main")

    def activate(self, action, released=False):
        """Activate a menu action.

        Gameplay actions are delayed until the quantum stack is ready so the
        loading screen can be displayed before a blocking import/download.
        """

        gameplay_actions = {
            "start",
            "normal_levels",
            "load_seed",
        }

        if not released and (action in gameplay_actions or action.startswith("level:")):
            if not self.game.gameplay_ready():
                self.pending = action
                self.loading_from = self.page
                self.loading_drawn = False
                self.open("loading")
                return

        if action == "play":
            self.open("play")

        elif action == "normal_levels":
            if self.game.available_levels:
                self.game.start_level(
                    self.game.available_levels[0],
                    "full",
                )

        elif action == "custom_seed":
            # Start with a fresh input each time so the previous code never
            # needs to be deleted character by character.
            self.seed_text = ""
            self.seed_active = True
            self.seed_error = ""
            self.open("custom_seed")
            self.seed_active = True

        elif action == "load_seed":
            self.seed_error = ""

            if self.game.start_seed_level(self.seed_text):
                self.seed_active = False

        elif action.startswith("quantum"):
            self.quantum.activate(action)

        elif action == "next_level":
            self.game.next_level()

        elif action.startswith("toggle:"):
            key = action.split(":", 1)[1]

            self.game.settings[key] = not self.game.settings[key]

            self.settings_saved = (
                self.game.persist_settings(
                    self.game.settings
                ) is not False
            )

        elif action.startswith("level:"):
            self.game.start_level(
                int(action.split(":", 1)[1]),
                "single",
            )

        elif action == "editor":
            self.game.open_editor()

        elif action == "start":
            self.game.start_level(
                self.game.available_levels[0],
                "full",
            )

        elif action == "retry":
            self.game.restart_level()

        elif action == "retry_run":
            if self.game.run_mode == "full":
                self.open("setup")
            else:
                self.game.restart_level()

        elif action == "resume":
            self.open("playing")

        elif action in ("help", "settings"):
            if action == "help":
                self.help_return = self.page
            else:
                self.return_page = self.page

            self.open(action)

        elif action == "back":
            self.back()

        elif action == "main":
            self.game.return_to_menu()

        else:
            self.open(action)

    def handle_event(self, event):
        # ------------------------------------------------------------
        # Custom seed text input
        # ------------------------------------------------------------
        if self.page == "custom_seed":
            if event.type == pygame.KEYDOWN and self.seed_active:
                # Press Enter to play the pasted/typed seed.
                if event.key in (
                    pygame.K_RETURN,
                    pygame.K_KP_ENTER,
                ):
                    self.activate("load_seed")
                    return

                # Ctrl+V = paste seed from clipboard.
                if (
                    event.key == pygame.K_v
                    and pygame.key.get_mods() & pygame.KMOD_CTRL
                ):
                    try:
                        pygame.scrap.init()
                        pasted = pygame.scrap.get(
                            pygame.SCRAP_TEXT
                        )

                        if pasted:
                            if isinstance(pasted, bytes):
                                pasted = pasted.decode(
                                    "utf-8",
                                    errors="ignore",
                                )

                            pasted = pasted.replace(
                                "\x00",
                                "",
                            ).strip()

                            self.seed_text = pasted[:4096]
                            self.seed_error = ""

                    except Exception:
                        try:
                            import tkinter as tk

                            root = tk.Tk()
                            root.withdraw()

                            pasted = root.clipboard_get()

                            root.destroy()

                            if pasted:
                                self.seed_text = pasted.strip()[:4096]
                                self.seed_error = ""

                        except Exception:
                            self.seed_error = (
                                "Could not access clipboard"
                            )

                    return

                if event.key == pygame.K_BACKSPACE:
                    self.seed_text = self.seed_text[:-1]
                    self.seed_error = ""
                    return

                if event.key == pygame.K_ESCAPE:
                    self.seed_active = False
                    self.back()
                    return

                if (
                    event.unicode.isprintable()
                    and len(self.seed_text) < 4096
                ):
                    self.seed_text += event.unicode
                    self.seed_error = ""
                    return

            # Click inside the seed input field.
            if (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
            ):
                seed_rect = pygame.Rect(
                    60,
                    255,
                    680,
                    60,
                )

                clear_rect = pygame.Rect(
                    700,
                    255,
                    40,
                    60,
                )

                if clear_rect.collidepoint(event.pos):
                    self.seed_text = ""
                    self.seed_error = ""
                    self.seed_active = True
                    self.focus = 0
                    return

                if seed_rect.collidepoint(event.pos):
                    self.seed_active = True
                    self.focus = 0
                    return

        # ------------------------------------------------------------
        # ESC must work on loading and normal menu pages.
        # ------------------------------------------------------------
        if (
            event.type == pygame.KEYDOWN
            and event.key == pygame.K_ESCAPE
        ):
            self.back()
            return

        # ------------------------------------------------------------
        # Quantum menu gets first chance to handle its own events.
        # ------------------------------------------------------------
        if self.quantum.handle_event(event):
            self.pressed = None
            return

        # ------------------------------------------------------------
        # Level selector scroll view.
        # ------------------------------------------------------------
        if (
            self.page == "levels"
            and event.type != pygame.KEYDOWN
            and self.level_scroll.handle_event(event)
        ):
            self.pressed = None
            return

        buttons = self.buttons()

        if not buttons:
            return

        self.focus = min(
            self.focus,
            len(buttons) - 1,
        )

        # ------------------------------------------------------------
        # Keyboard navigation
        # ------------------------------------------------------------
        if event.type == pygame.KEYDOWN:
            if event.key in (
                pygame.K_TAB,
                pygame.K_DOWN,
                pygame.K_s,
                pygame.K_d,
                pygame.K_RIGHT,
            ):
                step = (
                    -1
                    if (
                        event.key == pygame.K_TAB
                        and getattr(event, "mod", 0) & pygame.KMOD_SHIFT
                    )
                    else 1
                )

                self.focus = (
                    self.focus + step
                ) % len(buttons)

                self.reveal_level_focus()

            elif event.key in (
                pygame.K_UP,
                pygame.K_w,
                pygame.K_a,
                pygame.K_LEFT,
            ):
                self.focus = (
                    self.focus - 1
                ) % len(buttons)

                self.reveal_level_focus()

            elif event.key in (
                pygame.K_RETURN,
                pygame.K_SPACE,
            ):
                self.activate(
                    buttons[self.focus][0]
                )

        # ------------------------------------------------------------
        # Mouse hover
        # ------------------------------------------------------------
        elif event.type == pygame.MOUSEMOTION:
            for index, (
                action,
                rect,
                _,
                _,
            ) in enumerate(buttons):
                if self.button_hit_rect(
                    action,
                    rect,
                ).collidepoint(event.pos):
                    self.focus = index
                    break

        # ------------------------------------------------------------
        # Mouse button pressed
        # ------------------------------------------------------------
        elif (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
        ):
            self.pressed = next(
                (
                    action
                    for action, rect, _, _ in buttons
                    if self.button_hit_rect(
                        action,
                        rect,
                    ).collidepoint(event.pos)
                ),
                None,
            )

        # ------------------------------------------------------------
        # Mouse button released
        # ------------------------------------------------------------
        elif (
            event.type == pygame.MOUSEBUTTONUP
            and event.button == 1
        ):
            action = next(
                (
                    action
                    for action, rect, _, _ in buttons
                    if self.button_hit_rect(
                        action,
                        rect,
                    ).collidepoint(event.pos)
                ),
                None,
            )

            if action and action == self.pressed:
                self.activate(action)

            self.pressed = None

    def button_view(self, action):
        """The scroll view a button lives in, or None for a fixed button."""
        if (
            self.page == "quantum_history"
            and action.startswith("quantum:history:")
        ):
            return self.quantum.history_scroll

        if action.startswith("level:"):
            return self.level_scroll

        return None

    def button_hit_rect(self, action, rect):
        view = self.button_view(action)
        return rect.clip(view.rect) if view else rect

    def reveal_level_focus(self):
        """Scroll the level grid so the focused card is fully visible."""
        if self.page != "levels":
            return

        action, rect, _, _ = self.buttons()[self.focus]

        if not action.startswith("level:"):
            return

        view = self.level_scroll

        if rect.top < view.rect.top:
            view.move(
                dy=rect.top - view.rect.top
            )

        elif rect.bottom + 4 > view.rect.bottom:
            view.move(
                dy=rect.bottom + 4 - view.rect.bottom
            )

    def draw_buttons(self):
        """Draw page buttons, clipping buttons that live inside scroll views."""
        screen = self.game.screen

        for index, button in enumerate(self.buttons()):
            view = self.button_view(button[0])

            if view is None:
                self.draw_button(button, index)
                continue

            if not button[1].colliderect(view.rect):
                continue

            clip = screen.get_clip()

            screen.set_clip(
                clip.clip(view.rect)
            )

            self.draw_button(
                button,
                index,
            )

            screen.set_clip(clip)

        if self.page == "levels":
            self.level_scroll.draw(screen)

    def draw_button(self, button, index):
        action, rect, label, hint = button

        if action.startswith("quantum:pillar:"):
            return

        disabled = (
            action == "quantum:refresh_history"
            and self.quantum.history.busy
        )

        focused = index == self.focus and not disabled

        primary = (
            action in (
                "setup",
                "start",
                "resume",
                "quantum_run",
                "quantum:submit",
                "quantum:retry",
            )
            or (
                action == "retry"
                and self.page == "failed"
            )
        )

        fill = (
            ACCENT
            if primary
            else (
                (43, 44, 64)
                if focused
                else PANEL
            )
        )

        # Slight pressed-button offset.
        draw_rect = rect

        if self.pressed == action and not disabled:
            draw_rect = rect.move(0, 2)

        pygame.draw.rect(
            self.game.screen,
            (8, 10, 17),
            draw_rect.move(0, 4),
        )

        pygame.draw.rect(
            self.game.screen,
            fill,
            draw_rect,
        )

        pygame.draw.rect(
            self.game.screen,
            INK
            if focused
            else (
                ACCENT
                if primary
                else EDGE
            ),
            draw_rect,
            2 if focused else 1,
        )

        color = (
            MUTED
            if disabled
            else (
                BG
                if primary
                else INK
            )
        )

        if action.startswith("toggle:"):
            self.text(
                label,
                draw_rect.x + 18,
                draw_rect.y + 6,
                23,
            )

            self.text(
                hint,
                draw_rect.x + 18,
                draw_rect.y + 29,
                17,
                MUTED,
            )

            value = self.game.settings[
                action.split(":", 1)[1]
            ]

            switch = pygame.Rect(
                draw_rect.right - 79,
                draw_rect.y + 12,
                60,
                26,
            )

            pygame.draw.rect(
                self.game.screen,
                MINT if value else EDGE,
                switch,
            )

            pygame.draw.rect(
                self.game.screen,
                BG,
                (
                    switch.x + (
                        38 if value else 4
                    ),
                    switch.y + 4,
                    18,
                    18,
                ),
            )

            self.text(
                "ON" if value else "OFF",
                switch.x - 35,
                switch.y + 5,
                18,
                MINT if value else MUTED,
            )

        elif action.startswith("level:"):
            level = int(
                action.split(":", 1)[1]
            )

            preview = self.level_preview(level)

            self.game.screen.blit(
                preview,
                (
                    draw_rect.x + 8,
                    draw_rect.y + 5,
                ),
            )

            self.text(
                label,
                draw_rect.x + 13,
                draw_rect.bottom - 29,
                24,
            )

            self.text(
                ">",
                draw_rect.right - 24,
                draw_rect.bottom - 28,
                24,
                ACCENT,
            )

        else:
            if action == "back":
                self.text(
                    "<",
                    draw_rect.x + 18,
                    draw_rect.y + 14,
                    22,
                    MUTED,
                )

                self.text(
                    label,
                    draw_rect.x + 42,
                    draw_rect.y + 12,
                    26,
                    color,
                )

            else:
                size = 26

                reserved = (
                    138
                    if action.startswith("quantum:history:")
                    else 54
                )

                while (
                    size > 16
                    and font(size).size(label)[0]
                    > draw_rect.width - reserved
                ):
                    size -= 1

                self.text(
                    label,
                    draw_rect.x + 20,
                    draw_rect.y + 12,
                    size,
                    color,
                )

                hint_width = font(
                    18 if hint else 22
                ).size(
                    hint or ">"
                )[0]

                if not disabled:
                    self.text(
                        hint or ">",
                        draw_rect.right - hint_width - 16,
                        draw_rect.y + 14,
                        18 if hint else 22,
                        color if primary else MUTED,
                    )

                if action.startswith("quantum:history:"):
                    entry = self.quantum.history_entry(
                        action
                    )

                    self.text(
                        entry.get(
                            "created",
                            "",
                        ),
                        draw_rect.x + 20,
                        draw_rect.y + 35,
                        18,
                        MUTED,
                    )

    def level_preview(self, level):
        """A thumbnail of the level's layout, or a blank card if it is broken.

        Level select previews every file in ./levels, so one malformed file
        must not take the whole menu down with it; the card is simply empty,
        and selecting it reports the same error the loader would.
        """
        if level in self.previews:
            return self.previews[level]

        try:
            data = read_level(
                f"./levels/{level}.json"
            )
        except LevelError:
            self.previews[level] = pygame.Surface(
                (142, 72),
                pygame.SRCALPHA,
            )

            return self.previews[level]

        tiles = {
            parse_pos(pos): kind
            for pos, kind in data["tiles"].items()
        }

        min_x = min(
            x for x, _ in tiles
        )

        min_y = min(
            y for _, y in tiles
        )

        width = (
            max(x for x, _ in tiles)
            - min_x
            + 1
        )

        height = (
            max(y for _, y in tiles)
            - min_y
            + 1
        )

        size = min(
            24,
            140 // width,
            70 // height,
        )

        surface = pygame.Surface(
            (142, 72),
            pygame.SRCALPHA,
        )

        origin = (
            (142 - width * size) // 2,
            (72 - height * size) // 2,
        )

        for (x, y), kind in tiles.items():
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
                (size, size),
            )

            position = (
                origin[0] + (x - min_x) * size,
                origin[1] + (y - min_y) * size,
            )

            surface.blit(
                image,
                position,
            )

            if kind == "START":
                surface.blit(
                    pygame.transform.scale(
                        self.images["character"],
                        (size, size),
                    ),
                    position,
                )

        for positions, name in (
            (data["objects"], "box"),
            (data["quantum_objects"], "pillar"),
        ):
            image = pygame.transform.scale(
                self.images[name],
                (size, size),
            )

            for pos in positions:
                x, y = parse_pos(pos)

                surface.blit(
                    image,
                    (
                        origin[0]
                        + (x - min_x) * size,
                        origin[1]
                        + (y - min_y) * size,
                    ),
                )

        self.previews[level] = surface
        return surface

    def wordmark(self):
        for index, letter in enumerate(
            "QUNGEON"
        ):
            for y, row in enumerate(
                WORDMARK[letter]
            ):
                for x, pixel in enumerate(row):
                    if pixel == "1":
                        rect = pygame.Rect(
                            60 + index * 54 + x * 9,
                            164 + y * 9,
                            9,
                            9,
                        )

                        pygame.draw.rect(
                            self.game.screen,
                            (78, 67, 108),
                            rect.move(0, 5),
                        )

                        pygame.draw.rect(
                            self.game.screen,
                            ACCENT
                            if index == 0
                            else INK,
                            rect,
                        )

    def draw_scene(self):
        screen = self.game.screen
        center = (606, 297)

        pygame.draw.circle(
            screen,
            (29, 33, 47),
            center,
            127,
            1,
        )

        pygame.draw.circle(
            screen,
            (43, 44, 65),
            center,
            96,
            1,
        )

        pygame.draw.line(
            screen,
            EDGE,
            (468, 297),
            (744, 297),
        )

        pygame.draw.line(
            screen,
            EDGE,
            (606, 163),
            (606, 435),
        )

        offset = round(
            math.sin(
                pygame.time.get_ticks() / 900
            ) * 3
        )

        ox, oy, size = (
            510,
            247 + offset,
            48,
        )

        for row in range(2):
            for column in range(4):
                name = (
                    "wall"
                    if row == 0
                    else (
                        "end_tile"
                        if column == 3
                        else "tile"
                    )
                )

                screen.blit(
                    self.scene_images[name],
                    (
                        ox + column * size,
                        oy + row * size,
                    ),
                )

        screen.blit(
            self.scene_images["character"],
            (
                ox,
                oy + 48,
            ),
        )

        screen.blit(
            self.scene_images["pillar"],
            (
                ox + 96,
                oy + 36,
            ),
        )

        for label, point in (
            ("|0>", (490, 197)),
            ("|1>", (693, 384)),
        ):
            pygame.draw.rect(
                screen,
                PANEL,
                (
                    *point,
                    49,
                    29,
                ),
            )

            pygame.draw.rect(
                screen,
                EDGE,
                (
                    *point,
                    49,
                    29,
                ),
                1,
            )

            self.text(
                label,
                point[0] + 10,
                point[1] + 6,
                23,
                MINT,
            )

    def draw_header(self):
        screen = self.game.screen

        pygame.draw.line(
            screen,
            EDGE,
            (40, 76),
            (760, 76),
        )

        pygame.draw.rect(
            screen,
            ACCENT,
            (40, 35, 24, 24),
            2,
        )

        self.text(
            "Q",
            46,
            38,
            23,
            ACCENT,
        )

        self.text(
            "QUNGEON",
            77,
            39,
            22,
        )

    def draw(self):
        screen = self.game.screen

        if self.page in (
            "quantum",
            "quantum_history",
            "quantum_map",
            "quantum_circuit",
        ):
            self.quantum.draw()

            buttons = self.buttons()

            self.focus = min(
                self.focus,
                max(0, len(buttons) - 1),
            )

            self.draw_buttons()

            pygame.display.update()
            return

        if self.page == "editor":
            self.game.editor.draw()
            return

        overlay = self.page in (
            "paused",
            "failed",
            "complete",
        )

        if overlay:
            self.game.display_game(
                update=False,
                interactive=False,
            )

            screen.blit(
                self.veil,
                (0, 0),
            )

            panel = (
                pygame.Rect(
                    140,
                    87,
                    520,
                    427,
                )
                if self.page == "complete"
                else pygame.Rect(
                    204,
                    87,
                    392,
                    427,
                )
            )

            pygame.draw.rect(
                screen,
                (8, 10, 17),
                panel.move(0, 7),
            )

            pygame.draw.rect(
                screen,
                PANEL,
                panel,
            )

            pygame.draw.rect(
                screen,
                EDGE,
                panel,
                2,
            )

            pygame.draw.line(
                screen,
                RED
                if self.page == "failed"
                else ACCENT,
                (229, 88),
                (571, 88),
                3,
            )

            color = (
                RED
                if self.page == "failed"
                else ACCENT
            )

            symbol = (
                "//"
                if self.page == "paused"
                else (
                    "X"
                    if self.page == "failed"
                    else "+"
                )
            )

            pygame.draw.rect(
                screen,
                color,
                (381, 115, 38, 38),
                2,
            )

            self.text(
                symbol,
                400,
                121,
                31,
                color,
                True,
            )

            full_run = (
                self.game.run_mode == "full"
            )

            title = {
                "paused": "Paused",
                "failed": (
                    "Run failed"
                    if full_run
                    else "Level failed"
                ),
                "complete": (
                    "Run complete"
                    if full_run
                    and not self.game.has_next_level()
                    else "Level complete"
                ),
            }[self.page]

            self.text(
                title,
                400,
                170,
                46,
                INK,
                True,
            )

            self.text(
                f"LEVEL {self.game.current_level:02}   /   "
                f"{'FULL RUN' if self.game.run_mode == 'full' else 'SINGLE LEVEL'}",
                400,
                220,
                19,
                MUTED,
                True,
            )

            if self.page != "paused":
                message = (
                    "The level can no longer be completed."
                    if self.page == "failed"
                    else (
                        "All levels completed."
                        if full_run
                        and not self.game.has_next_level()
                        else "Your solved circuit is ready to explore."
                    )
                )

                self.text(
                    message,
                    400,
                    268,
                    23,
                    MUTED,
                    True,
                )

        else:
            screen.blit(
                self.background,
                (0, 0),
            )

            self.draw_header()

            self.text(
                "WASD / arrows to navigate",
                40,
                570,
                18,
                MUTED,
            )

            self.text(
                "ENTER  Select     ESC  Back",
                559,
                570,
                18,
                MUTED,
            )

            if self.page == "main":
                self.wordmark()

                self.text(
                    "A quantum puzzle game.",
                    62,
                    255,
                    26,
                    MUTED,
                )

                self.draw_scene()

            else:
                heading, subheading = {
                    "setup": (
                        "Prepare your run",
                        f"Play all {len(self.game.available_levels)} levels in order.",
                    ),
                    "play": (
                        "Play",
                        "Choose normal levels or enter a custom level seed.",
                    ),
                    "custom_seed": (
                        "Custom level",
                        "Paste a QGL share code copied from the level editor.",
                    ),
                    "settings": (
                        "Settings",
                        "",
                    ),
                    "levels": (
                        "Choose a level",
                        "All levels are available.",
                    ),
                    "help": (
                        "How to play",
                        "",
                    ),
                    "loading": (
                        "Entering the dungeon",
                        "Starting the quantum engine. This takes a moment.",
                    ),
                }.get(
                    self.page,
                    ("", ""),
                )

                self.text(
                    heading,
                    60,
                    112,
                    49,
                )

                self.text(
                    subheading,
                    62,
                    164,
                    24,
                    MUTED,
                )

                if self.page == "custom_seed":
                    field = pygame.Rect(
                        60,
                        255,
                        680,
                        60,
                    )

                    pygame.draw.rect(
                        screen,
                        PANEL,
                        field,
                    )

                    pygame.draw.rect(
                        screen,
                        ACCENT
                        if self.seed_active
                        else EDGE,
                        field,
                        2,
                    )

                    self.text(
                        self.seed_text
                        or "QGL-paste-your-code-here",
                        80,
                        272,
                        24,
                        INK
                        if self.seed_text
                        else MUTED,
                    )

                    # One-click clear control for quickly entering another code.
                    clear_color = ACCENT if self.seed_text else MUTED

                    pygame.draw.line(
                        screen,
                        clear_color,
                        (711, 274),
                        (729, 296),
                        3,
                    )

                    pygame.draw.line(
                        screen,
                        clear_color,
                        (729, 274),
                        (711, 296),
                        3,
                    )

                    self.text(
                        "QGL- = exact level created in the editor · "
                        "Press Enter to play",
                        62,
                        330,
                        17,
                        MUTED,
                    )

                    if self.seed_error:
                        self.text(
                            self.seed_error,
                            62,
                            430,
                            17,
                            RED,
                        )

                if self.page in (
                    "settings",
                    "setup",
                ):
                    self.text(
                        "Preferences saved automatically."
                        if self.settings_saved
                        else (
                            "Preferences apply this session; "
                            "saving is unavailable."
                        ),
                        62,
                        476,
                        17,
                        MUTED,
                    )

        self.draw_buttons()

        pygame.display.update()

        if self.page == "loading":
            self.loading_drawn = True

    def draw_hud(self):
        self.draw_header()

        if pygame.time.get_ticks() < self.game.quantum_notice_until:
            self.text(
                self.game.quantum_notice,
                40,
                89,
                18,
                ACCENT,
            )

        if self.game.current_share_code is not None:
            # Keep the HUD clean: the long share code belongs in the menu,
            # not in the top-right gameplay header.
            self.text(
                "CUSTOM LEVEL",
                362,
                39,
                22,
                INK,
            )
        else:
            self.text(
                f"LEVEL {self.game.current_level:02}",
                362,
                39,
                22,
                INK,
            )

        pygame.draw.rect(
            self.game.screen,
            PANEL,
            (652, 29, 108, 35),
        )

        pygame.draw.rect(
            self.game.screen,
            EDGE,
            (652, 29, 108, 35),
            1,
        )

        self.text(
            "ESC  Pause",
            665,
            39,
            20,
            MUTED,
        )

        self.text(
            "WASD  Move",
            40,
            579,
            18,
            MUTED,
        )

        self.text(
            "Drag gates onto nearby pillars",
            400,
            579,
            18,
            MUTED,
            True,
        )

        self.text(
            "R  Restart",
            692,
            579,
            18,
            MUTED,
        )
