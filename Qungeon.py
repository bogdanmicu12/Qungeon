import os
import asyncio
import pygame
import argparse

from pygame.locals import (
    KEYDOWN,
    MOUSEBUTTONDOWN,
    MOUSEBUTTONUP,
    QUIT,
    K_ESCAPE,
    K_a,
    K_d,
    K_h,
    K_q,
    K_r,
    K_s,
    K_w,
    K_1,
    K_2,
    K_3,
    K_4,
    K_5,
    K_6,
    K_7,
    K_8,
    K_9,
)

from scripts.grouping_system import GroupingSystem
from scripts.common_functions import update_mouse_drag
from scripts.level_validation import (
    read_level,
    validate_level,
    parse_pos,
    LevelError,
)
from scripts.menus import (
    ACCENT,
    MenuUI,
    BG,
    load_settings,
    normalize_settings,
    save_settings,
)

# quantum_run keeps cirq/quantum dependencies behind function-level imports,
# so the menu can appear before the large quantum stack is imported.
from scripts.quantum_run import QuantumRun, capture_circuit
from scripts import story
from scripts.level_editor import LevelEditor
from scripts.level_share import decode_level
# tutorial.py only depends on level_validation, not cirq, so it's safe up here too.
from scripts.tutorial import TutorialController


# ---------------------------------------------------------------------------
# Lazy quantum/gameplay imports
# ---------------------------------------------------------------------------
#
# Everything that depends on the quantum stack stays unloaded until gameplay
# is actually requested. This is important for the browser build because the
# quantum dependencies are large and importing them blocks the main thread.
#
# MenuUI uses gameplay_ready() / gameplay_downloaded() to put up a loading
# screen before this import is allowed to block.
#
alpha = None
level_solver = None
Hotbar = None
BLOCK_SIZE = None
BlochInspector = None
LootableObject = Player = QuantumObject = Tile = TileType = None
pillar_image = None
gates = None


def load_gameplay():
    """Import the quantum/gameplay stack. Idempotent; the first call does work."""
    global BLOCK_SIZE
    global alpha, level_solver, Hotbar, BlochInspector
    global LootableObject, Player, QuantumObject
    global Tile, TileType, pillar_image, gates

    if Hotbar is not None:
        return

    import unitary.alpha as alpha
    from scripts import level_solver

    from scripts.game_objects import (
        BLOCK_SIZE,
        LootableObject,
        Player,
        QuantumObject,
        Tile,
        TileType,
        pillar_image,
        gates,
    )

    from scripts.bloch_inspector import BlochInspector

    # Bound last so the guard above is only satisfied when every dependency
    # needed by gameplay has been loaded.
    from scripts.user_interface import Hotbar


FPS = 60
HOP_FRAMES = 10
HOP_DELAY_MS = 10
SCREEN_BG_COLOR = BG
# Leave room for the story above the board and the gate selector below it.
PLAY_AREA = pygame.Rect(40, 112, 720, 308)
GAME_TITLE = 'Qungeon'
DEFAULT_START_LEVEL = 1
TUTORIAL_LEVELS = ["tutorial_1", "tutorial_2"]

# How long the player keeps playing after the solver proves the level is lost.
STUCK_DELAY_MS = 1800


class Game:
    """Level state, input and the game loop."""

    def __init__(
        self,
        args,
        settings=None,
        persist_settings=None,
        gameplay_downloaded=None,
    ):
        """Initialize the game and show the menu before loading gameplay.

        The quantum stack is intentionally not imported here. In browser
        builds, the menu can therefore appear immediately while the browser
        downloads the gameplay dependencies in the background.
        """
        pygame.init()
        self.screen = pygame.display.set_mode((800, 600))

        self.tiles = {}
        self.objects = {}
        self.board_offset = (0, 0)
        self.board_cell_size = 64

        self.grouping_system = GroupingSystem()
        self.quantum_grid = None

        self.gameplay_downloaded = (
            gameplay_downloaded
            or (lambda: True)
        )

        self.object_sprites = pygame.sprite.Group()
        self.tile_sprites = pygame.sprite.Group()

        self.settings = (
            load_settings()
            if settings is None
            else normalize_settings(settings)
        )

        self.persist_settings = (
            persist_settings
            or save_settings
        )

        self.available_levels = self.find_levels()

        self.running = True
        self.run_mode = "full"
        self.last_tick = pygame.time.get_ticks()

        self.correlation_elapsed = 0
        self.stuck_elapsed = None
        self.resources = None
        self.hop = None

        self.current_level = args.level
        self.current_seed = None
        self.current_share_code = None

        self.player = None
        self.hotbar = None
        self.bloch = None

        self.quantum_run = None
        self.background_quantum_runs = []

        self.quantum_notice = ""
        self.quantum_notice_color = ACCENT
        self.quantum_notice_until = 0

        # Guided tutorial state. No quantum dependency, so it is safe to build
        # before the menu (a deep link may load a level during construction).
        self.tutorial = TutorialController()
        self.tutorial_step = 0
        self.pending_advance = False

        # Main branch functionality: gate help window.
        self.gate_help_open = False

        pygame.display.set_caption(GAME_TITLE)

        # The menu is shown first. No quantum stack is needed for this.
        self.menu = MenuUI(self)

        # Level editor is also created before gameplay is imported.
        self.editor = LevelEditor(self)

        if getattr(args, "start_direct", False):
            # Use the same route as the level-select buttons so direct level
            # launches also receive the loading screen in browser builds.
            self.run_mode = "single"
            self.menu.activate(
                f"level:{self.current_level}"
            )

    def gameplay_ready(self):
        """Return True when gameplay can start immediately."""
        return (
            Hotbar is not None
            and self.gameplay_downloaded()
        )

    def find_levels(self):
        """Find all numeric JSON level files."""
        return sorted(
            int(filename[:-5])
            for filename in os.listdir("./levels")
            if (
                filename.endswith(".json")
                and filename[:-5].isdigit()
            )
        )

    def open_editor(self):
        """Open the level editor."""
        self.cancel_dragging()

        self.editor = LevelEditor(self)
        self.menu.open("editor")

    def load_level(self, filename):
        """Read, validate, and load a normal JSON level."""
        # Validate the external file before importing the expensive gameplay
        # stack. A malformed file therefore fails fast without touching state.
        level_data = read_level(filename)

        self.load_level_data(
            level_data,
            filename,
        )

    def load_level_data(
        self,
        level_data,
        source="level",
    ):
        """Load an already-parsed level dictionary."""
        validate_level(
            level_data,
            source,
        )

        # This is normally reached only after MenuUI has shown the loading
        # screen in browser mode. Direct callers still work correctly.
        load_gameplay()

        if self.hotbar is None:
            self.hotbar = Hotbar()

        if self.quantum_grid is None:
            self.quantum_grid = alpha.QuantumWorld()

        if self.bloch is None:
            self.bloch = BlochInspector(self)

        self.clean_up()

        self.current_seed = level_data.get("seed")

        # Normal levels clear custom-level state. start_seed_level() restores
        # the share code after this method returns.
        self.current_share_code = None

        for pos_str, tile_type_str in level_data["tiles"].items():
            x, y = parse_pos(pos_str)
            tile_type = TileType[tile_type_str]

            tile = Tile(
                x,
                y,
                tile_type,
            )

            self.tiles[(x, y)] = tile
            self.tile_sprites.add(tile)

            if tile_type == TileType.START:
                self.player = Player(
                    x,
                    y,
                )

        for position, item in level_data["objects"].items():
            x, y = parse_pos(position)

            new_obj = LootableObject(
                item,
                x,
                y,
            )

            self.objects[f"{x},{y}"] = new_obj
            self.object_sprites.add(new_obj)

        # Editor-created levels may contain explicit pillar amplitudes.
        pillar_states = level_data.get(
            "pillar_states",
            {},
        )

        for position in level_data["quantum_objects"]:
            x, y = parse_pos(position)

            state = pillar_states.get(position)

            new_obj = QuantumObject(
                x,
                y,
                self,
                state=state,
            )

            self.objects[f"{x},{y}"] = new_obj
            self.object_sprites.add(new_obj)

        for gate, count in level_data["gates"].items():
            self.hotbar.add_item(
                gate,
                count,
            )

        for effect_entry in level_data["effects"]:
            x, y = parse_pos(
                effect_entry["position"]
            )

            effect = getattr(
                alpha,
                effect_entry["effect"],
            )()

            if "target" in effect_entry:
                target_x, target_y = parse_pos(
                    effect_entry["target"]
                )

                effect = [
                    effect,
                    [target_x, target_y],
                ]

            self.objects[f"{x},{y}"].apply_effect(
                self,
                effect,
            )

        self.tutorial.load(level_data)
        self.center_level()
        self.resources = self.resource_signature()
        self.bloch.finish_level()

    def center_level(self):
        """Fit the board in the play area without changing logical coordinates."""
        sprites = list(self.tile_sprites) + list(self.object_sprites) + [self.player]
        bounds = sprites[0].rect.unionall([sprite.rect for sprite in sprites[1:]])
        area = pygame.Rect(40, 112, 720, 208) if self.tutorial.steps else PLAY_AREA
        scale = min(1, area.width / bounds.width, area.height / bounds.height)
        self.board_cell_size = max(1, int(BLOCK_SIZE * scale))
        scale = self.board_cell_size / BLOCK_SIZE
        for sprite in sprites:
            sprite.render_scale = scale
            size = tuple(max(1, round(value * scale)) for value in sprite.image.get_size())
            sprite.image = pygame.transform.scale(sprite.image, size)
            sprite.rect = pygame.Rect(round(sprite.rect.x * scale), round(sprite.rect.y * scale), *size)
            if isinstance(sprite, QuantumObject):
                sprite.colorImage = pygame.Surface(size, pygame.SRCALPHA)
        bounds = sprites[0].rect.unionall([sprite.rect for sprite in sprites[1:]])
        offset = (area.centerx - bounds.centerx, area.centery - bounds.centery)
        for sprite in sprites:
            sprite.rect.move_ip(offset)
        self.board_offset = offset
        self.update_player_position(*self.player.position)

    def update_player_position(self, x, y):
        """Apply the board transform to every player pose, including mid-hop."""
        self.player.position = (x, y)
        self.player.rect.topleft = (round(x * self.board_cell_size) + self.board_offset[0],
                                    round(y * self.board_cell_size) + self.board_offset[1])

    def resource_signature(self):
        """Return everything the player can still spend."""
        return (
            sum(
                slot.count
                for slot in self.hotbar.slots.values()
            ),
            len(self.objects),
        )

    def clean_up(self):
        """Reset all game objects, tiles, quantum state, and hotbar slots."""
        self.clear_quantum_notice()
        self.gate_help_open = False

        if self.bloch is not None:
            self.bloch.reset()

        self.tiles.clear()
        self.board_offset = (0, 0)
        self.board_cell_size = 64
        self.tile_sprites.empty()

        self.objects.clear()
        self.object_sprites.empty()

        if self.hotbar is not None:
            self.hotbar.slots.clear()
            self.hotbar.sprites.empty()

            # Main branch functionality.
            if hasattr(
                self.hotbar,
                "selected_key",
            ):
                self.hotbar.selected_key = None

        if self.quantum_grid is not None:
            self.quantum_grid.clear()

        self.grouping_system.groups.clear()
        self.grouping_system.count = 0

        self.hop = None
        self.correlation_elapsed = 0
        self.stuck_elapsed = None

        # A level advance held back by a tutorial popup must never leak into
        # whatever level is loaded next (restart, menu, another level).
        self.pending_advance = False

    def hop_animation(
        self,
        start_pos,
        end_pos,
    ):
        """Begin a frame-driven hop."""
        self.hop = {
            "start": start_pos,
            "end": end_pos,
            "elapsed": 0,
        }

    def update_hop(self, elapsed):
        if self.hop is None:
            return

        self.hop["elapsed"] += elapsed

        progress = min(
            1,
            self.hop["elapsed"]
            / (HOP_FRAMES * HOP_DELAY_MS),
        )

        start = self.hop["start"]
        end = self.hop["end"]

        self.update_player_position(
            start[0]
            + (end[0] - start[0]) * progress,
            start[1]
            + (end[1] - start[1]) * progress
            - progress * (1 - progress),
        )

        if progress == 1:
            self.update_player_position(*end)
            self.hop = None
            self.tutorial.on_enter(end)

            if self.tiles[end].type == TileType.END:
                self.tutorial.on_win()
                if self.tutorial.active:
                    self.pending_advance = True   # advance after the popup is dismissed
                else:
                    self.advance_level()

    def update_position(self, direction):
        """Update the player's position based on movement input."""
        if self.hop is not None:
            return

        x, y = self.player.position

        new_x, new_y = x, y

        if direction == K_w:
            new_y -= 1

        elif direction == K_s:
            new_y += 1

        elif direction == K_a:
            new_x -= 1

        elif direction == K_d:
            new_x += 1

        start_pos = (
            x,
            y,
        )

        end_pos = (
            new_x,
            new_y,
        )

        tile = self.tiles.get(
            (new_x, new_y)
        )

        object_key = f"{new_x},{new_y}"

        if tile and tile.type == TileType.END:
            self.hop_animation(
                start_pos,
                end_pos,
            )

        elif object_key in self.objects:
            obj = self.objects[object_key]

            # Selected quantum gates can be applied to QuantumObjects before
            # their normal movement function runs.
            if (
                isinstance(obj, QuantumObject)
                and self.hotbar.apply_selected(
                    self,
                    obj,
                )
            ):
                if obj.function(
                    self,
                    new_x,
                    new_y,
                ):
                    self.hop_animation(
                        start_pos,
                        end_pos,
                    )

            elif obj.function(
                self,
                new_x,
                new_y,
            ):
                self.hop_animation(
                    start_pos,
                    end_pos,
                )

        elif tile and tile.type != TileType.WALL:
            self.hop_animation(
                start_pos,
                end_pos,
            )

    def advance_level(self):
        """Finish the current level and optionally advance to the next.

        Tutorial levels chain straight to the next step without capturing a
        hardware circuit; other levels keep the solved circuit and open the
        completion screen.
        """
        if self.run_mode == "tutorial":
            next_step = self.tutorial_step + 1
            if next_step < len(TUTORIAL_LEVELS):
                self.start_tutorial(next_step)
            else:
                self.menu.open("complete")
            return

        self.stuck_elapsed = None

        try:
            self.quantum_run = QuantumRun(
                capture_circuit(self)
            )
        except ValueError as exc:
            self.quantum_run = QuantumRun(
                error=str(exc)
            )

        skip_screen = (
            self.run_mode == "full"
            and not self.settings["full_run_completion"]
        )

        if (
            skip_screen
            and self.settings["auto_quantum_runs"]
        ):
            if self.quantum_run.circuit is not None:
                self.background_quantum_runs.append(
                    self.quantum_run
                )

                self.quantum_run.command(
                    "enqueue"
                )

                self.show_quantum_notice(
                    f"Level {self.current_level:02}: "
                    "checking hardware and queueing your circuit..."
                )
            else:
                self.show_quantum_notice(
                    f"Level {self.current_level:02}: "
                    "this circuit cannot run on hardware."
                )

        # Keep completion screen as a recovery route.
        self.menu.open("complete")

        if (
            skip_screen
            and self.has_next_level()
        ):
            self.next_level()

    def show_quantum_notice(
        self,
        message,
        color=ACCENT,
        duration=8000,
    ):
        """Display a temporary quantum hardware notification."""
        self.quantum_notice = message
        self.quantum_notice_color = color
        self.quantum_notice_until = (
            pygame.time.get_ticks()
            + duration
        )

    def clear_quantum_notice(self):
        """Clear the current quantum hardware notification."""
        self.quantum_notice = ""
        self.quantum_notice_until = 0

    def update_background_quantum_runs(self):
        """Update quantum runs executing in the background."""
        for run in self.background_quantum_runs[:]:
            previous = run.data["state"]

            run.update()

            state = run.data["state"]

            if state != previous:
                level = run.circuit["level"]

                if state in (
                    "queued",
                    "running",
                    "done",
                ):
                    self.show_quantum_notice(
                        f"Level {level:02}: "
                        f"hardware run {state}. "
                        "See Hardware runs in the menu."
                    )

                elif state in (
                    "setup",
                    "unavailable",
                    "failed",
                    "uncertain",
                ):
                    self.show_quantum_notice(
                        f"Level {level:02}: "
                        "hardware run needs attention. "
                        "See Hardware runs in the menu."
                    )

            if (
                not run.busy
                and state not in (
                    "queued",
                    "running",
                    "submitting",
                )
            ):
                self.background_quantum_runs.remove(run)

    def next_level(self):
        """Advance to the next level in a full run."""
        index = self.available_levels.index(
            self.current_level
        )

        if (
            self.run_mode == "full"
            and index + 1 < len(self.available_levels)
        ):
            self.start_level(
                self.available_levels[index + 1],
                "full",
            )

    def has_next_level(self):
        """Return whether another level exists in the current full run."""
        return (
            self.run_mode == "full"
            and self.current_level != self.available_levels[-1]
        )

    def start_level(
        self,
        level,
        mode="single",
    ):
        """Load a normal JSON level and handle validation errors."""
        try:
            self.load_level(
                f"./levels/{level}.json"
            )
        except LevelError as err:
            print(
                f"Could not load level {level}: {err}"
            )
            return False

        self.current_level = level
        self.current_seed = None
        self.current_share_code = None
        self.run_mode = mode
        self.quantum_run = None

        self.menu.open("playing")
        return True

    def start_seed_level(self, seed_text):
        """Start an exact level created by the level editor."""
        try:
            text = seed_text.strip()

            if not text.upper().startswith("QGL-"):
                raise ValueError(
                    "Only QGL- editor share codes are accepted."
                )

            level_data = decode_level(text)

            if not level_data.get("editor_created"):
                raise ValueError(
                    "This code was not created by the level editor."
                )

            self.load_level_data(
                level_data,
                "editor share code",
            )

            share_code = text

        except (
            ValueError,
            LevelError,
        ) as err:
            self.menu.seed_error = str(err)
            return False

        self.current_level = 0
        self.current_seed = None
        self.current_share_code = share_code
        self.run_mode = "single"
        self.quantum_run = None

        self.menu.open("playing")
        return True

    def start_tutorial(self, step=0):
        """Start (or advance to) one guided tutorial step.

        Tutorial levels are addressed by name (tutorial_1.json, ...) rather
        than the numbered ids in available_levels, so current_level is set to
        a negative sentinel (-1, -2, ...) purely for display - see
        MenuUI.level_label(). Loads before committing any state, same as
        start_level, so a broken tutorial file can't strand the player.
        """
        try:
            self.load_level(f"./levels/{TUTORIAL_LEVELS[step]}.json")
        except LevelError as err:
            print(f"Could not load tutorial step {step}: {err}")
            return
        self.tutorial_step = step
        self.run_mode = "tutorial"
        self.current_level = -(step + 1)
        self.quantum_run = None
        self.menu.open("playing")

    def restart_level(self):
        """Restart the current level, including tutorial and custom levels."""
        if self.run_mode == "tutorial":
            self.start_tutorial(self.tutorial_step)
        elif self.current_share_code is not None:
            self.start_seed_level(
                self.current_share_code
            )
        else:
            self.start_level(
                self.current_level,
                self.run_mode,
            )

    def return_to_menu(self):
        """Return to the main menu."""
        self.menu.open("main")

    def update_stuck(self, elapsed):
        """Check whether the current level has become unwinnable.

        The solver runs only when a resource was consumed. A solver result of
        "unknown" is not considered stuck.
        """
        if not self.settings["stuck_warning"]:
            self.stuck_elapsed = None
            return

        signature = self.resource_signature()

        if (
            self.hop is None
            and signature != self.resources
        ):
            self.resources = signature

            if level_solver.solve(
                level_solver.snapshot(self)
            ).is_stuck:
                self.stuck_elapsed = 0

        if self.stuck_elapsed is not None:
            self.stuck_elapsed += elapsed

            if self.stuck_elapsed >= STUCK_DELAY_MS:
                self.show_failed()

    def show_failed(self):
        """Open the failure screen and stop any pending countdown."""
        self.stuck_elapsed = None
        self.menu.open("failed")

    def cancel_dragging(self):
        """Put uncommitted drags back without spending a gate."""
        if self.bloch is not None:
            self.bloch.cancel_drag()

        if self.hotbar is not None:
            for slot in self.hotbar.slots.values():
                slot.dragging = False

            self.hotbar.update_slots()

        for obj in self.objects.values():
            if obj.dragging:
                obj.rect.topleft = (
                    obj.origin_x,
                    obj.origin_y,
                )

                obj.dragging = False

                if isinstance(
                    obj,
                    QuantumObject,
                ):
                    obj.control = None

    def display_game(
        self,
        update=True,
        interactive=True,
        player_offset=0,
        show_ui=True,
    ):
        """Render the board, optional story pose, and gameplay controls."""
        self.screen.fill(
            SCREEN_BG_COLOR
        )

        if self.player is not None:
            self.update_player_position(*self.player.position)
        self.tile_sprites.draw(self.screen)
        story.draw_marks(self)

        all_sprites = list(
            self.object_sprites
        )

        if self.player is not None:
            all_sprites.append(
                self.player
            )

        all_sprites.sort(
            key=lambda sprite: (
                sprite.rect.y,
                0
                if sprite == self.player
                else 1,
            )
        )

        for sprite in all_sprites:
            if not getattr(sprite, "dragging", False):
                rect = sprite.rect.move(0, player_offset) if sprite == self.player else sprite.rect
                self.screen.blit(sprite.image, rect)

        if show_ui and self.hotbar is not None:
            if hasattr(
                self.hotbar,
                "draw_selection_panel",
            ):
                self.hotbar.draw_selection_panel(
                    self.screen
                )

        # Main branch help/selection UI where supported.
        if interactive and self.hotbar is not None:
            if self.settings["entanglement_guides"]:
                self.entanglement_visuals()

        if show_ui:
            self.menu.draw_hud()

        if show_ui and interactive and self.bloch is not None:
            self.bloch.draw()

        # Draw each dragged object once, above the translucent inspector.
        if show_ui and self.hotbar is not None:
            for sprite in (*self.objects.values(), *self.hotbar.slots.values()):
                if sprite.dragging:
                    self.screen.blit(sprite.image, sprite.rect)

        # Main branch functionality.
        if show_ui and self.gate_help_open and self.hotbar is not None:
            if hasattr(
                self.hotbar,
                "draw_help_window",
            ):
                self.hotbar.draw_help_window(
                    self.screen
                )

        if update:
            pygame.display.update()

    def handle_object_dragging(self, event):
        """Handle dragging and applying quantum gates."""
        for name, obj in self.objects.items():
            if not obj.dragging:
                continue

            obj.dragging = False
            obj.rect.x = obj.origin_x
            obj.rect.y = obj.origin_y

            for other_name, other_obj in self.objects.items():
                if not other_obj.rect.collidepoint(
                    event.pos
                ):
                    continue

                if obj == other_obj:
                    pass

                elif (
                    isinstance(
                        obj,
                        QuantumObject,
                    )
                    and isinstance(
                        other_obj,
                        QuantumObject,
                    )
                ):
                    if obj.control == "CNOT":
                        obj.apply_effect(
                            self,
                            [
                                alpha.Flip(),
                                other_obj.position,
                            ],
                        )

                    elif obj.control == "CHAD":
                        obj.apply_effect(
                            self,
                            [
                                alpha.Superposition(),
                                other_obj.position,
                            ],
                        )

                    elif obj.control == "SWAP":
                        self.swap_pillars(
                            obj,
                            other_obj,
                        )

                    if obj.control in ("CNOT", "CHAD", "SWAP"):
                        self.tutorial.on_apply(obj.position)

                    return obj.control

            return False

    def swap_pillars(
        self,
        obj,
        other_obj,
    ):
        """Exchange the quantum states of two pillars.

        SWAP creates no new entanglement, so the grouping structure must be
        preserved accurately. Cached state and phase information move with
        the swapped state as well.
        """
        previous = self.bloch.before_gate() if self.bloch is not None else {}
        gates["SWAP"](
            obj,
            other_obj,
        )
        if self.bloch is not None:
            self.bloch.after_gate(previous, "SWAP")

        self.grouping_system.swap(
            obj,
            other_obj,
        )

        obj.states, other_obj.states = (
            other_obj.states,
            obj.states,
        )

        obj.phase_Z, other_obj.phase_Z = (
            other_obj.phase_Z,
            obj.phase_Z,
        )

        obj.apply_effect(self)
        other_obj.apply_effect(self)

    def correlation_update(self):
        """Update visual representation of object correlations."""
        groups = self.grouping_system.groups

        for group in groups:
            if len(group.states) > 1:
                state = list(
                    group.states.keys()
                )[
                    self.grouping_system.count
                    % len(group.states)
                ]

                for key, obj in enumerate(
                    group.objects
                ):
                    obj.change_color(
                        pillar_image,
                        obj.color,
                        (state[key] + 1) * 127,
                    )

        self.grouping_system.count += 1

    def entanglement_visuals(self):
        """Draw visual lines between entangled objects."""
        mouse_pos = pygame.mouse.get_pos()
        for name, object in self.objects.items():
            if isinstance(object, QuantumObject):
                if object.rect.collidepoint(mouse_pos):
                    for entangled_object in object.group.objects:
                        if object != entangled_object:
                            start_pos = self.tiles[object.position].rect.center
                            end_pos = self.tiles[entangled_object.position].rect.center
                            pygame.draw.line(self.screen, (60, 60, 200), start_pos, end_pos, width=2)

    def run_frame(self):
        """Handle and render one frame."""
        now = pygame.time.get_ticks()

        elapsed = min(
            now - self.last_tick,
            100,
        )

        self.last_tick = now

        self.update_background_quantum_runs()

        if (
            self.quantum_run is not None
            and self.quantum_run
            not in self.background_quantum_runs
        ):
            self.quantum_run.update()

        self.menu.quantum.update()

        was_playing = (
            self.menu.page == "playing"
        )

        # A pending level choice may be waiting for the loading screen to
        # appear before the quantum stack is imported.
        self.menu.update(elapsed)
        self.editor.update_validation()

        self.handle_events()

        if not self.running:
            self.editor.cancel_validation()
            return

        if self.menu.page == "playing":
            if was_playing:
                self.update_hop(
                    elapsed
                )

                if self.menu.page == "playing" and not self.tutorial.active:
                    self.correlation_elapsed += elapsed

                    if self.correlation_elapsed >= 1000:
                        self.correlation_update()
                        self.correlation_elapsed %= 1000

                    self.update_stuck(
                        elapsed
                    )

            if self.menu.page == "playing":
                update_mouse_drag(
                    self.hotbar.slots
                )

                update_mouse_drag(
                    self.objects
                )

                self.display_game()
                return

        self.menu.draw()

    def run(self):
        """Run the main game loop."""
        clock = pygame.time.Clock()

        while self.running:
            self.run_frame()
            clock.tick(FPS)

        pygame.quit()

    async def run_browser(
        self,
        should_pause=None,
        on_page_change=None,
    ):
        """Run the game loop while yielding frames to the browser."""
        previous_page = None

        while self.running:
            if (
                should_pause is not None
                and should_pause()
            ):
                if self.menu.page == "playing":
                    self.menu.open("paused")
                elif self.menu.page == "intro":
                    self.menu.opening.suspended = True
            self.run_frame()

            if self.menu.page != previous_page:
                previous_page = self.menu.page

                if on_page_change is not None:
                    on_page_change(
                        previous_page
                    )

            await asyncio.sleep(
                1 / FPS
            )

    def handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False
                return

            if event.type == getattr(
                pygame,
                "WINDOWFOCUSLOST",
                -1,
            ):
                if self.menu.page == "playing":
                    self.menu.open("paused")
                elif self.menu.page == "intro":
                    self.menu.opening.suspended = True
                return

            previous_page = self.menu.page

            # While a tutorial popup is up it owns all input.
            if (
                self.menu.page == "playing"
                and self.tutorial.active
            ):
                self.handle_tutorial_event(event)

            # Preserve level editor functionality.
            elif self.menu.page == "editor":
                self.editor.handle_event(event)

            elif self.menu.page != "playing":
                self.menu.handle_event(event)

            elif self.bloch is not None and self.bloch.handle_event(event):
                pass

            elif event.type == KEYDOWN:
                self.handle_keydown(event)

            elif (
                event.type == MOUSEBUTTONDOWN
                and event.button == 1
            ):
                # Main branch gate help functionality.
                if self.gate_help_open:
                    close_rect = getattr(
                        self.hotbar,
                        "help_close_rect",
                        None,
                    )

                    if (
                        close_rect is not None
                        and close_rect.collidepoint(
                            event.pos
                        )
                    ):
                        self.gate_help_open = False

                elif pygame.Rect(
                    652,
                    29,
                    108,
                    35,
                ).collidepoint(
                    event.pos
                ):
                    self.menu.open("paused")

                else:
                    obj_effect = self.handle_object_dragging(
                        event
                    )

                    if obj_effect:
                        self.hotbar.remove_by_key(
                            obj_effect
                        )

                    else:
                        self.hotbar.handle_selection_mouse_down(event)

            elif (
                event.type == MOUSEBUTTONUP
                and event.button == 1
            ):
                self.hotbar.handle_mouse_up(
                    self,
                    event,
                )

            if self.menu.page != previous_page:
                return

    def handle_keydown(self, event):
        """Handle keyboard input."""

        # Main branch: gate help.
        if event.key == K_h:
            self.cancel_dragging()
            self.gate_help_open = not self.gate_help_open
            return

        if self.gate_help_open:
            if event.key == K_ESCAPE:
                self.gate_help_open = False
            return

        # Main branch: numbered hotbar selection.
        number_keys = (
            K_1,
            K_2,
            K_3,
            K_4,
            K_5,
            K_6,
            K_7,
            K_8,
            K_9,
        )

        if event.key in number_keys:
            if hasattr(
                self.hotbar,
                "select_by_number",
            ):
                self.hotbar.select_by_number(
                    self,
                    number_keys.index(
                        event.key
                    ) + 1,
                )

        elif event.key in (
            K_ESCAPE,
            K_q,
        ):
            self.menu.open("paused")

        elif event.key in (
            K_w,
            K_s,
            K_a,
            K_d,
            pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
        ):
            direction = {pygame.K_UP: K_w, pygame.K_DOWN: K_s,
                         pygame.K_LEFT: K_a, pygame.K_RIGHT: K_d}.get(event.key, event.key)
            self.update_position(direction)

        elif event.key == K_r:
            self.restart_level()

    def handle_tutorial_event(self, event):
        if event.type == KEYDOWN and event.key == K_ESCAPE:
            self.menu.open("paused")
        elif event.type == KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self.advance_tutorial_popup()
        elif event.type == MOUSEBUTTONDOWN and event.button == 1:
            self.advance_tutorial_popup()

    def advance_tutorial_popup(self):
        self.tutorial.dismiss()
        if not self.tutorial.active and self.pending_advance:
            self.pending_advance = False
            self.advance_level()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Optional setting for starting level."
    )

    parser.add_argument(
        "level",
        nargs="?",
        type=int,
        default=None,
        help=(
            "Jump directly into a single level; "
            "omit to open the menu"
        ),
    )

    args = parser.parse_args()

    args.start_direct = (
        args.level is not None
    )

    if args.level is None:
        args.level = DEFAULT_START_LEVEL

    if not os.path.isfile(
        f"./levels/{args.level}.json"
    ):
        parser.error(
            f"level {args.level} does not exist"
        )

    game_instance = Game(args)
    game_instance.run()
