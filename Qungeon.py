import os
import asyncio
import pygame
import argparse

from pygame.locals import (
    KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, QUIT,
    K_ESCAPE, K_a, K_d, K_q, K_r, K_s, K_w,
)
from scripts.grouping_system import GroupingSystem
from scripts.common_functions import handle_slot_mouse_down, hover, update_mouse_drag
from scripts.level_validation import read_level, parse_pos, LevelError
from scripts.menus import MenuUI, BG, load_settings, normalize_settings, save_settings


# Bound by load_gameplay(). Everything that reaches cirq - the quantum stack
# itself, the objects built on it, and the solver - stays unimported until a
# level is actually loaded. In the browser build cirq and its dependencies are
# ~37 MB, and the menu needs none of it; see web/main.py, which installs them
# in the background while the menu is already on screen.
alpha = None
level_solver = None
Hotbar = None
BLOCK_SIZE = None
LootableObject = Player = QuantumObject = Tile = TileType = None
pillar_image = None


def load_gameplay():
    """Import the quantum stack. Idempotent; the first call does the work."""
    global alpha, level_solver, Hotbar, BLOCK_SIZE
    global LootableObject, Player, QuantumObject, Tile, TileType, pillar_image
    if Hotbar is not None:
        return
    import unitary.alpha as alpha
    from scripts import level_solver
    from scripts.game_objects import (
        BLOCK_SIZE, LootableObject, Player, QuantumObject, Tile, TileType, pillar_image,
    )
    # Bound last, so the guard above is only satisfied once every name is ready.
    from scripts.user_interface import Hotbar


FPS = 60
HOP_FRAMES = 10
HOP_DELAY_MS = 10
SCREEN_BG_COLOR = BG
GAME_TITLE = 'Qungeon'
DEFAULT_START_LEVEL = 1

# How long the player keeps playing after the solver proves the level is lost,
# before the failure screen appears. Being told a move was wrong the instant it
# lands is intrusive and robs the player of working it out; this leaves room to
# try the move that no longer works and feel the wall first, without a long
# stretch of pointlessly wandering a dead level.
STUCK_DELAY_MS = 1800

class Game:
    """Level state, input and the game loop."""

    def __init__(self, args, settings=None, persist_settings=None, gameplay_downloaded=None):
        """Initializes the game, sets up the menu, and game display.

        No level is loaded here: the menu is the first thing the player sees
        and needs nothing from the quantum stack, so loading is left to
        start_level. `gameplay_downloaded` lets the browser build report
        whether that stack has arrived yet; by default it always has.
        """
        pygame.init()
        self.screen = pygame.display.set_mode((800, 600))
        self.tiles = {}
        self.objects = {}

        self.grouping_system = GroupingSystem()
        self.quantum_grid = None
        self.gameplay_downloaded = gameplay_downloaded or (lambda: True)
        self.object_sprites = pygame.sprite.Group()
        self.tile_sprites = pygame.sprite.Group()
        self.settings = load_settings() if settings is None else normalize_settings(settings)
        self.persist_settings = persist_settings or save_settings
        self.available_levels = sorted(
            int(filename[:-5]) for filename in os.listdir("./levels")
            if filename.endswith(".json") and filename[:-5].isdigit()
        )
        self.running = True
        self.run_mode = "full"
        self.last_tick = pygame.time.get_ticks()
        self.correlation_elapsed = 0
        self.stuck_elapsed = None
        self.resources = None
        self.hop = None
        self.current_level = args.level
        self.player = None
        self.hotbar = None
        pygame.display.set_caption(GAME_TITLE)
        self.menu = MenuUI(self)
        if getattr(args, "start_direct", False):
            # The same route the level-select buttons take, so a deep link
            # waits for the quantum stack exactly as a click would.
            self.menu.activate(f"level:{self.current_level}")
    
    def gameplay_ready(self):
        """True when a level can start without the player waiting.

        Importing the quantum stack costs several seconds of blocked main
        thread, so "downloaded" is not the same as "ready": until it has also
        been imported the menu owes the player a loading screen first.
        """
        return Hotbar is not None and self.gameplay_downloaded()

    def load_level(self, filename):
        """Loads and parses the game level from a JSON file.

        Validates the file before clean_up() so a malformed level never
        destroys the currently loaded game. Raises LevelError on bad data.
        """
        level_data = read_level(filename)
        load_gameplay()
        if self.hotbar is None:
            self.hotbar = Hotbar()
            self.quantum_grid = alpha.QuantumWorld()
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
            self.objects[str(x) + "," + str(y)] = new_obj
            self.object_sprites.add(new_obj)

        for position in level_data["quantum_objects"]:
            x, y = parse_pos(position)
            new_obj = QuantumObject(x, y, self)
            self.objects[str(x) + "," + str(y)] = new_obj
            self.object_sprites.add(new_obj)

        for gate, count in level_data["gates"].items():
            self.hotbar.add_item(gate, count)

        for effect_entry in level_data["effects"]:
            x, y = parse_pos(effect_entry["position"])
            effect = getattr(alpha, effect_entry["effect"])()

            if "target" in effect_entry:
                target_x, target_y = parse_pos(effect_entry["target"])
                effect = [effect, [target_x, target_y]]

            self.objects[str(x) + "," + str(y)].apply_effect(self, effect)

        self.resources = self.resource_signature()

    def resource_signature(self):
        """Everything the player can still spend, as one comparable value.

        A level can only become unwinnable when something is consumed: a gate
        is spent or a loot box is taken. Comparing this once per frame keeps
        that trigger in one place, instead of scattering a call through every
        code path that spends something - including ones added later.
        """
        return (
            sum(slot.count for slot in self.hotbar.slots.values()),
            len(self.objects),
        )

    def clean_up(self):
        """Resets and clears all game objects, tiles, and hotbar slots when loading a new level."""
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
        """Begin a frame-driven hop, so Escape can pause it mid-movement."""
        self.hop = {"start": start_pos, "end": end_pos, "elapsed": 0}

    def update_hop(self, elapsed):
        if self.hop is None:
            return
        self.hop["elapsed"] += elapsed
        progress = min(1, self.hop["elapsed"] / (HOP_FRAMES * HOP_DELAY_MS))
        start, end = self.hop["start"], self.hop["end"]
        self.player.update_position(
            start[0] + (end[0] - start[0]) * progress,
            start[1] + (end[1] - start[1]) * progress - progress * (1 - progress),
        )
        if progress == 1:
            self.player.update_position(*end)
            self.hop = None
            if self.tiles[end].type == TileType.END:
                self.advance_level()

    def update_position(self, direction):
        """Updates the player's position based on the input direction key and handles level progression."""
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

        # Check tile and object interactions
        tile = self.tiles.get((new_x, new_y))
        object_key = str(new_x) + "," + str(new_y)

        if tile and tile.type == TileType.END:
            self.hop_animation(start_pos, end_pos)
        elif object_key in self.objects:
            if self.objects[object_key].function(self, new_x, new_y):
                self.hop_animation(start_pos, end_pos)
        elif tile and tile.type != TileType.WALL:
            self.hop_animation(start_pos, end_pos)

    def advance_level(self):
        """Finish a single puzzle or advance through the full run without exiting."""
        index = self.available_levels.index(self.current_level)
        if self.run_mode == "full" and index + 1 < len(self.available_levels):
            self.start_level(self.available_levels[index + 1], "full")
        else:
            self.menu.open("complete")

    def start_level(self, level, mode="single"):
        """Load a level and play it.

        Every route into a level - the menu, level select, finishing one level
        of a run, and the restart key - comes through here, so this is the one
        place that has to survive a broken level file. `load_level` validates
        before it touches anything, so a failure here leaves the game exactly
        as it was rather than dropping the player into a half-loaded level.
        """
        try:
            self.load_level(f"./levels/{level}.json")
        except LevelError as err:
            print(f"Could not load level {level}: {err}")
            return
        self.current_level = level
        self.run_mode = mode
        self.menu.open("playing")

    def restart_level(self):
        self.start_level(self.current_level, self.run_mode)

    def return_to_menu(self):
        self.menu.open("main")

    def update_stuck(self, elapsed):
        """Check for an unwinnable level, then let it sink in before saying so.

        The solver runs only when a resource was consumed, so this costs
        nothing on an ordinary frame. It is deliberately skipped mid-hop: the
        player's position is fractional while they are jumping, which describes
        no tile, and the check simply happens on the frame the hop lands.

        A solver result of "unknown" (its budget ran out) is not stuck - see
        `level_solver.Solution.is_stuck`.

        Turning the setting off cancels any pending countdown and stops the
        solver running at all. `resources` is deliberately left stale while it
        is off, so turning it back on looks like a change and re-checks a level
        that was played on in the meantime.
        """
        if not self.settings["stuck_warning"]:
            self.stuck_elapsed = None
            return

        signature = self.resource_signature()
        if self.hop is None and signature != self.resources:
            self.resources = signature
            if level_solver.solve(level_solver.snapshot(self)).is_stuck:
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
        for slot in self.hotbar.slots.values():
            slot.dragging = False
        self.hotbar.update_slots()
        for obj in self.objects.values():
            if obj.dragging:
                obj.rect.topleft = (obj.origin_x, obj.origin_y)
                obj.dragging = False
                if isinstance(obj, QuantumObject):
                    obj.control = None
    
    def display_game(self, update=True, interactive=True):
        """Renders the current game state, including the player, tiles, and hotbar, to the screen."""
        self.screen.fill(SCREEN_BG_COLOR)
        
        self.tile_sprites.draw(self.screen)

        all_sprites = list(self.object_sprites)
        all_sprites.append(self.player)
        all_sprites.sort(key=lambda sprite: (sprite.rect.y, 0 if sprite == self.player else 1))

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
        """Handles the dragging of objects based on mouse events."""
        for name, obj in self.objects.items():
            if obj.dragging:
                obj.dragging = False

                obj.rect.x = obj.origin_x
                obj.rect.y = obj.origin_y

                for name, other_obj in self.objects.items():
                    if other_obj.rect.collidepoint(event.pos):
                        if obj == other_obj:
                            pass
                        elif isinstance(obj, QuantumObject) and isinstance(other_obj, QuantumObject):
                            if obj.control == 'CNOT':
                                obj.apply_effect(self, [alpha.Flip(), other_obj.position])
                            elif obj.control == 'CHAD':
                                obj.apply_effect(self, [alpha.Superposition(), other_obj.position])

                            return obj.control

                return False

    def correlation_update(self):
        """Updates the visual representation of object correlations based on their grouping."""
        groups = self.grouping_system.groups
        for group in groups:
            if len(group.states) > 1:
                state = list(group.states.keys())[self.grouping_system.count % len(group.states)]
                for key, object in enumerate(group.objects):
                    object.change_color(pillar_image, object.color, (state[key] + 1) * 127)

        self.grouping_system.count += 1
    
    def entanglement_visuals(self):
        """Draws visual lines between entangled objects to represent their connections."""
        mouse_pos = pygame.mouse.get_pos()
        for name, object in self.objects.items():
            if isinstance(object, QuantumObject):
                if object.rect.collidepoint(mouse_pos):
                    for entangled_object in object.group.objects:
                        if object != entangled_object:
                            start_pos = ((object.position[0] + 0.5) * BLOCK_SIZE, (object.position[1] + 0.5) * BLOCK_SIZE)
                            end_pos = ((entangled_object.position[0] + 0.5) * BLOCK_SIZE, (entangled_object.position[1] + 0.5) * BLOCK_SIZE)
                            pygame.draw.line(self.screen, (60, 60, 200), start_pos, end_pos, width=2)

    def run_frame(self):
        """Handle and render one frame of the game."""
        now = pygame.time.get_ticks()
        elapsed = min(now - self.last_tick, 100)
        self.last_tick = now
        was_playing = self.menu.page == "playing"
        # Before input, so a level choice held over from an earlier frame is
        # released while its loading screen is the thing on the display.
        self.menu.update()
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
        """Main game loop that handles events, updates, and rendering."""
        clock = pygame.time.Clock()
    
        while self.running:
            self.run_frame()
            clock.tick(FPS)
        pygame.quit()

    async def run_browser(self, should_pause=None, on_page_change=None):
        """Run the same game loop while yielding frames to the browser."""
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
        """Handles all game events such as keyboard input, mouse actions, and custom events."""
        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False
                return
            if event.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
                if self.menu.page == "playing":
                    self.menu.open("paused")
                return
            previous_page = self.menu.page
            if self.menu.page != "playing":
                self.menu.handle_event(event)
            elif event.type == KEYDOWN:
                self.handle_keydown(event)
            elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                if pygame.Rect(652, 29, 108, 35).collidepoint(event.pos):
                    self.menu.open("paused")
                else:
                    obj_effect = self.handle_object_dragging(event)
                    if obj_effect:
                        self.hotbar.remove_by_key(obj_effect)
                    else:
                        handle_slot_mouse_down(self.hotbar.slots, event)
            elif event.type == MOUSEBUTTONUP and event.button == 1:
                self.hotbar.handle_mouse_up(self, event)
            if self.menu.page != previous_page:
                # Discard input queued for the previous screen.
                return

    def handle_keydown(self, event):
        """Handles keydown events for movement and other actions."""
        if event.key in (K_ESCAPE, K_q):
            self.menu.open("paused")
        elif event.key in [K_w, K_s, K_a, K_d]:
            self.update_position(event.key)
        elif event.key == K_r:
            self.restart_level()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optional setting for starting level.")
    parser.add_argument('level', nargs='?', type=int, default=None, help='Jump directly into a single level; omit to open the menu')
    args = parser.parse_args()
    args.start_direct = args.level is not None
    if args.level is None:
        args.level = DEFAULT_START_LEVEL

    if not os.path.isfile(f"./levels/{args.level}.json"):
        parser.error(f"level {args.level} does not exist")

    game_instance = Game(args)
    game_instance.run()
