import os
import asyncio
import pygame
import argparse
import json

import unitary.alpha as alpha
from pygame.locals import (
    KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, QUIT,
    K_ESCAPE, K_a, K_d, K_q, K_r, K_s, K_w,
)
from scripts.grouping_system import GroupingSystem
from scripts.user_interface import Hotbar
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
from scripts.common_functions import handle_slot_mouse_down, hover, update_mouse_drag
from scripts.level_validation import read_level, validate_level, parse_pos, LevelError
from scripts.menus import MenuUI, BG, load_settings, normalize_settings, save_settings
from scripts import level_solver
from scripts.quantum_run import QuantumRun, capture_circuit
from scripts.level_editor import LevelEditor


FPS = 60
HOP_FRAMES = 10
HOP_DELAY_MS = 10
SCREEN_BG_COLOR = BG
GAME_TITLE = "Qungeon"
DEFAULT_START_LEVEL = 1

STUCK_DELAY_MS = 1800


class Game:
    """Level state, input and the game loop."""

    def __init__(self, args, settings=None, persist_settings=None):
        """Initialize the game, starting level, player, and display."""
        pygame.init()
        self.screen = pygame.display.set_mode((800, 600))

        self.tiles = {}
        self.objects = {}

        self.grouping_system = GroupingSystem()
        self.quantum_grid = alpha.QuantumWorld()

        self.object_sprites = pygame.sprite.Group()
        self.tile_sprites = pygame.sprite.Group()

        self.settings = (
            load_settings()
            if settings is None
            else normalize_settings(settings)
        )
        self.persist_settings = persist_settings or save_settings

        self.available_levels = self.find_levels()

        self.running = True
        self.run_mode = "full"
        self.last_tick = pygame.time.get_ticks()
        self.correlation_elapsed = 0
        self.stuck_elapsed = None
        self.resources = None
        self.hop = None

        self.current_level = args.level
        self.player = None
        self.hotbar = Hotbar()

        self.quantum_run = None
        self.background_quantum_runs = []
        self.quantum_notice = ""
        self.quantum_notice_until = 0

        pygame.display.set_caption(GAME_TITLE)

        self.load_level(f"./levels/{self.current_level}.json")

        self.menu = MenuUI(self)
        self.editor = LevelEditor(self)

        if getattr(args, "start_direct", False):
            self.run_mode = "single"
            self.menu.open("playing")

    def find_levels(self):
        return sorted(
            int(filename[:-5])
            for filename in os.listdir("./levels")
            if filename.endswith(".json") and filename[:-5].isdigit()
        )

    def open_editor(self):
        self.cancel_dragging()
        self.editor = LevelEditor(self)
        self.menu.open("editor")

    def load_level(self, filename):
        """Load and validate a level before replacing the current game state."""
        level_data = read_level(filename)

        with open(filename, "r") as file:
            level_data = json.load(file)

        validate_level(level_data, filename)

        self.clean_up()

        for pos_str, tile_type_str in level_data["tiles"].items():
            x, y = parse_pos(pos_str)
            tile_type = TileType[tile_type_str]

            tile = Tile(x, y, tile_type)
            self.tiles[(x, y)] = tile
            self.tile_sprites.add(tile)

            if tile_type == TileType.START:
                self.player = Player(x, y)

        for position, item in level_data["objects"].items():
            x, y = parse_pos(position)

            new_obj = LootableObject(item, x, y)
            self.objects[f"{x},{y}"] = new_obj
            self.object_sprites.add(new_obj)

        for position in level_data["quantum_objects"]:
            x, y = parse_pos(position)

            new_obj = QuantumObject(x, y, self)
            self.objects[f"{x},{y}"] = new_obj
            self.object_sprites.add(new_obj)

        for gate, count in level_data["gates"].items():
            self.hotbar.add_item(gate, count)

        for effect_entry in level_data["effects"]:
            x, y = parse_pos(effect_entry["position"])
            effect = getattr(alpha, effect_entry["effect"])()

            if "target" in effect_entry:
                target_x, target_y = parse_pos(effect_entry["target"])
                effect = [effect, [target_x, target_y]]

            self.objects[f"{x},{y}"].apply_effect(self, effect)

        self.resources = self.resource_signature()

    def resource_signature(self):
        """Return everything the player can still spend."""
        return (
            sum(slot.count for slot in self.hotbar.slots.values()),
            len(self.objects),
        )

    def clean_up(self):
        """Reset all game objects, tiles, quantum state, and hotbar slots."""
        self.tiles.clear()
        self.tile_sprites.empty()

        self.objects.clear()
        self.object_sprites.empty()

        self.hotbar.slots.clear()
        self.hotbar.sprites.empty()

        self.quantum_grid.clear()

        self.grouping_system.groups.clear()
        self.grouping_system.count = 0

        self.hop = None
        self.correlation_elapsed = 0
        self.stuck_elapsed = None

    def hop_animation(self, start_pos, end_pos):
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
            self.hop["elapsed"] / (HOP_FRAMES * HOP_DELAY_MS),
        )

        start = self.hop["start"]
        end = self.hop["end"]

        self.player.update_position(
            start[0] + (end[0] - start[0]) * progress,
            start[1]
            + (end[1] - start[1]) * progress
            - progress * (1 - progress),
        )

        if progress == 1:
            self.player.update_position(*end)
            self.hop = None

            if self.tiles[end].type == TileType.END:
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

        start_pos = (x, y)
        end_pos = (new_x, new_y)

        tile = self.tiles.get((new_x, new_y))
        object_key = f"{new_x},{new_y}"

        if tile and tile.type == TileType.END:
            self.hop_animation(start_pos, end_pos)

        elif object_key in self.objects:
            if self.objects[object_key].function(
                self,
                new_x,
                new_y,
            ):
                self.hop_animation(start_pos, end_pos)

        elif tile and tile.type != TileType.WALL:
            self.hop_animation(start_pos, end_pos)

    def advance_level(self):
        """Finish the current level and optionally advance to the next."""
        self.stuck_elapsed = None

        try:
            self.quantum_run = QuantumRun(capture_circuit(self))
        except ValueError as exc:
            self.quantum_run = QuantumRun(error=str(exc))

        skip_screen = (
            self.run_mode == "full"
            and not self.settings["full_run_completion"]
        )

        if skip_screen and self.settings["auto_quantum_runs"]:
            if self.quantum_run.circuit is not None:
                self.background_quantum_runs.append(self.quantum_run)
                self.quantum_run.command("enqueue")

                self.show_quantum_notice(
                    f"Level {self.current_level:02}: "
                    "checking hardware and queueing your circuit..."
                )
            else:
                self.show_quantum_notice(
                    f"Level {self.current_level:02}: "
                    "this circuit cannot run on hardware."
                )

        self.menu.open("complete")

        if skip_screen and self.has_next_level():
            self.next_level()

    def show_quantum_notice(self, message):
        self.quantum_notice = message
        self.quantum_notice_until = pygame.time.get_ticks() + 8000

    def update_background_quantum_runs(self):
        for run in self.background_quantum_runs[:]:
            previous = run.data["state"]

            run.update()

            state = run.data["state"]

            if state != previous:
                level = run.circuit["level"]

                if state in ("queued", "running", "done"):
                    self.show_quantum_notice(
                        f"Level {level:02}: hardware run {state}. "
                        "See Hardware runs in the menu."
                    )

                elif state in (
                    "setup",
                    "unavailable",
                    "failed",
                    "uncertain",
                ):
                    self.show_quantum_notice(
                        f"Level {level:02}: hardware run needs attention. "
                        "See Hardware runs in the menu."
                    )

            if not run.busy and state not in (
                "queued",
                "running",
                "submitting",
            ):
                self.background_quantum_runs.remove(run)

    def next_level(self):
        index = self.available_levels.index(self.current_level)

        if (
            self.run_mode == "full"
            and index + 1 < len(self.available_levels)
        ):
            self.start_level(
                self.available_levels[index + 1],
                "full",
            )

    def has_next_level(self):
        return (
            self.run_mode == "full"
            and self.current_level != self.available_levels[-1]
        )

    def start_level(self, level, mode="single"):
        """Load a level and safely handle validation errors."""
        try:
            self.load_level(f"./levels/{level}.json")
        except LevelError as err:
            print(f"Could not load level {level}: {err}")
            return

        self.current_level = level
        self.run_mode = mode
        self.quantum_run = None

        self.menu.open("playing")

    def restart_level(self):
        self.start_level(self.current_level, self.run_mode)

    def return_to_menu(self):
        self.menu.open("main")

    def update_stuck(self, elapsed):
        """Check whether the current level has become unwinnable."""
        if not self.settings["stuck_warning"]:
            self.stuck_elapsed = None
            return

        signature = self.resource_signature()

        if self.hop is None and signature != self.resources:
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
        """Display the failure screen."""
        self.stuck_elapsed = None
        self.menu.open("failed")

    def cancel_dragging(self):
        """Put uncommitted drags back without spending a gate."""
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

                if isinstance(obj, QuantumObject):
                    obj.control = None

    def display_game(self, update=True, interactive=True):
        """Render the current game state."""
        self.screen.fill(SCREEN_BG_COLOR)

        self.tile_sprites.draw(self.screen)

        all_sprites = list(self.object_sprites)
        all_sprites.append(self.player)

        all_sprites.sort(
            key=lambda sprite: (
                sprite.rect.y,
                0 if sprite == self.player else 1,
            )
        )

        for sprite in all_sprites:
            self.screen.blit(sprite.image, sprite.rect)

        self.hotbar.sprites.draw(self.screen)

        if interactive:
            if self.settings["entanglement_guides"]:
                self.entanglement_visuals()

            hover(self.hotbar.slots, self.screen)

        self.menu.draw_hud()

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
                if not other_obj.rect.collidepoint(event.pos):
                    continue

                if obj == other_obj:
                    pass

                elif (
                    isinstance(obj, QuantumObject)
                    and isinstance(other_obj, QuantumObject)
                ):
                    if obj.control == "CNOT":
                        obj.apply_effect(
                            self,
                            [alpha.Flip(), other_obj.position],
                        )

                    elif obj.control == "CHAD":
                        obj.apply_effect(
                            self,
                            [alpha.Superposition(), other_obj.position],
                        )

                    elif obj.control == "SWAP":
                        # SWAP exchanges two qubit states and does not
                        # merge the two groups.
                        gates["SWAP"](obj, other_obj)
                        obj.apply_effect(self)
                        other_obj.apply_effect(self)

                    return obj.control

            return False

    def correlation_update(self):
        """Update visual representation of object correlations."""
        groups = self.grouping_system.groups

        for group in groups:
            if len(group.states) > 1:
                state = list(group.states.keys())[
                    self.grouping_system.count % len(group.states)
                ]

                for key, obj in enumerate(group.objects):
                    obj.change_color(
                        pillar_image,
                        obj.color,
                        (state[key] + 1) * 127,
                    )

        self.grouping_system.count += 1

    def entanglement_visuals(self):
        """Draw visual lines between entangled objects."""
        mouse_pos = pygame.mouse.get_pos()

        for name, obj in self.objects.items():
            if isinstance(obj, QuantumObject):
                if obj.rect.collidepoint(mouse_pos):
                    for entangled_obj in obj.group.objects:
                        if obj != entangled_obj:
                            start_pos = (
                                (obj.position[0] + 0.5) * BLOCK_SIZE,
                                (obj.position[1] + 0.5) * BLOCK_SIZE,
                            )

                            end_pos = (
                                (entangled_obj.position[0] + 0.5)
                                * BLOCK_SIZE,
                                (entangled_obj.position[1] + 0.5)
                                * BLOCK_SIZE,
                            )

                            pygame.draw.line(
                                self.screen,
                                (60, 60, 200),
                                start_pos,
                                end_pos,
                                width=2,
                            )

    def run_frame(self):
        """Handle and render one frame."""
        now = pygame.time.get_ticks()
        elapsed = min(now - self.last_tick, 100)
        self.last_tick = now

        self.update_background_quantum_runs()

        if (
            self.quantum_run is not None
            and self.quantum_run not in self.background_quantum_runs
        ):
            self.quantum_run.update()

        self.menu.quantum.update()

        was_playing = self.menu.page == "playing"

        self.handle_events()

        if not self.running:
            return

        if self.menu.page == "playing":
            if was_playing:
                self.update_hop(elapsed)

                if self.menu.page == "playing":
                    self.correlation_elapsed += elapsed

                    if self.correlation_elapsed >= 1000:
                        self.correlation_update()
                        self.correlation_elapsed %= 1000

                    self.update_stuck(elapsed)

            if self.menu.page == "playing":
                update_mouse_drag(self.hotbar.slots)
                update_mouse_drag(self.objects)

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

    async def run_browser(self, should_pause=None, on_page_change=None):
        """Run the game loop while yielding frames to the browser."""
        previous_page = None

        while self.running:
            if should_pause is not None and should_pause():
                if self.menu.page == "playing":
                    self.menu.open("paused")

            self.run_frame()

            if self.menu.page != previous_page:
                previous_page = self.menu.page

                if on_page_change is not None:
                    on_page_change(previous_page)

            await asyncio.sleep(1 / FPS)

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
                return

            previous_page = self.menu.page

            if self.menu.page == "editor":
                self.editor.handle_event(event)

            elif self.menu.page != "playing":
                self.menu.handle_event(event)

            elif event.type == KEYDOWN:
                self.handle_keydown(event)

            elif (
                event.type == MOUSEBUTTONDOWN
                and event.button == 1
            ):
                if pygame.Rect(
                    652,
                    29,
                    108,
                    35,
                ).collidepoint(event.pos):
                    self.menu.open("paused")
                else:
                    obj_effect = self.handle_object_dragging(event)

                    if obj_effect:
                        self.hotbar.remove_by_key(obj_effect)
                    else:
                        handle_slot_mouse_down(
                            self.hotbar.slots,
                            event,
                        )

            elif (
                event.type == MOUSEBUTTONUP
                and event.button == 1
            ):
                self.hotbar.handle_mouse_up(self, event)

            if self.menu.page != previous_page:
                return

    def handle_keydown(self, event):
        """Handle keyboard input."""
        if event.key in (K_ESCAPE, K_q):
            self.menu.open("paused")

        elif event.key in (K_w, K_s, K_a, K_d):
            self.update_position(event.key)

        elif event.key == K_r:
            self.restart_level()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Optional setting for starting level."
    )

    parser.add_argument(
        "level",
        nargs="?",
        type=int,
        default=None,
        help="Jump directly into a single level; "
        "omit to open the menu",
    )

    args = parser.parse_args()
    args.start_direct = args.level is not None

    if args.level is None:
        args.level = DEFAULT_START_LEVEL

    if not os.path.isfile(f"./levels/{args.level}.json"):
        parser.error(
            f"level {args.level} does not exist"
        )

    game_instance = Game(args)
    game_instance.run()
