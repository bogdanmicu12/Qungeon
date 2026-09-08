import os
import sys
import asyncio
import pygame
import argparse
import json

from pygame.locals import *
from scripts.grouping_system import *
from scripts.user_interface import *
from scripts.game_objects import *
from scripts.common_functions import *
from scripts.level_validation import validate_level, parse_pos, LevelError


# Constants
FPS = 60
HOP_FRAMES = 10
HOP_DELAY_MS = 10
SCREEN_BG_COLOR = (255, 255, 255)
GAME_TITLE = 'Qungeon'
DEFAULT_START_LEVEL = 1

class GameHotbar(Hotbar):
    """Handles the game's hotbar interactions, primarily drag-and-drop functionality for items."""

    def __init__(self):
        super().__init__()

    def handle_mouse_up(self, game, event):
        """Handles mouse release events to stop dragging an item from the hotbar."""
        for i, (key, slot) in enumerate(self.slots.items()):
            if slot.dragging:
                slot.dragging = False
                self.remove_item(game, event, key)

                slot.rect.x = self.rect.x + i * 55
                slot.rect.y = self.rect.y
                break

class Game:
    """Main game class for Qungeon, managing levels, player movement, and the game loop.
    Lower level working of class can be found in Engine class."""

    def __init__(self, args):
        """Initializes the game, sets up the starting level, player, and game display."""
        pygame.init()
        self.screen = pygame.display.set_mode((800, 600))
        self.tiles = {}
        self.objects = {}

        self.grouping_system = GroupingSystem()
        self.quantum_grid = alpha.QuantumWorld()
        self.object_sprites = pygame.sprite.Group()
        self.tile_sprites = pygame.sprite.Group()
        self.correlation_timer_supported = True
        try:
            pygame.time.set_timer(pygame.USEREVENT, 1000)
        except NotImplementedError:
            self.correlation_timer_supported = False
            self.next_correlation_update = pygame.time.get_ticks() + 1000

        self.current_level = args.level
        self.player = None
        self.hotbar = GameHotbar()
        pygame.display.set_caption(GAME_TITLE)
        self.load_level(f"./levels/{self.current_level}.json")
    
    def load_level(self, filename):
        """Loads and parses the game level from a JSON file.

        Validates the file before clean_up() so a malformed level never
        destroys the currently loaded game. Raises LevelError on bad data.
        """
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

    def hop_animation(self, start_pos, end_pos):
        """Animates the player's movement with a hopping effect."""
        for i in range(HOP_FRAMES):
            progress = (i + 1) / HOP_FRAMES
            hop_height = -(progress * (1 - progress))
            new_x = start_pos[0] + (end_pos[0] - start_pos[0]) * progress
            new_y = start_pos[1] + (end_pos[1] - start_pos[1]) * progress + hop_height

            self.player.update_position(new_x, new_y)
            self.display_game()
            pygame.time.delay(HOP_DELAY_MS)

    def update_position(self, direction):
        """Updates the player's position based on the input direction key and handles level progression."""
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
            self.advance_level()
        elif object_key in self.objects:
            if self.objects[object_key].function(self, new_x, new_y):
                self.hop_animation(start_pos, end_pos)
                self.player.update_position(new_x, new_y)
        elif tile and tile.type != TileType.WALL:
            self.hop_animation(start_pos, end_pos)
            self.player.update_position(new_x, new_y)

    def advance_level(self):
        """Advances to the next level, or ends the game if no further levels exist."""
        self.current_level += 1
        next_level_filename = f"./levels/{self.current_level}.json"
        if os.path.isfile(next_level_filename):
            self.load_level(next_level_filename)
        else:
            print("Game completed!")
            pygame.quit()
            sys.exit()
    
    #Below functions rea for rendering of the game.
    def display_game(self):
        """Renders the current game state, including the player, tiles, and hotbar, to the screen."""
        self.screen.fill(SCREEN_BG_COLOR)
        
        self.tile_sprites.draw(self.screen)

        all_sprites = list(self.object_sprites)
        all_sprites.append(self.player)
        all_sprites.sort(key=lambda sprite: (sprite.rect.y, 0 if sprite == self.player else 1))

        for sprite in all_sprites:
            self.screen.blit(sprite.image, sprite.rect)

        self.hotbar.sprites.draw(self.screen)
        self.entanglement_visuals()
        hover(self.hotbar.slots, self.screen)

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

    # Below functions are for the main game loop.
    def run_frame(self):
        """Handle and render one frame of the game."""
        if (
            not self.correlation_timer_supported
            and pygame.time.get_ticks() >= self.next_correlation_update
        ):
            self.correlation_update()
            self.next_correlation_update = pygame.time.get_ticks() + 1000

        self.handle_events()
        update_mouse_drag(self.hotbar.slots)
        update_mouse_drag(self.objects)
        self.display_game()

    def run(self):
        """Main game loop that handles events, updates, and rendering."""
        clock = pygame.time.Clock()
    
        while True:
            self.run_frame()
            clock.tick(FPS)

    async def run_browser(self):
        """Run the same game loop while yielding frames to the browser."""
        while True:
            self.run_frame()
            await asyncio.sleep(1 / FPS)

    def handle_events(self):
        """Handles all game events such as keyboard input, mouse actions, and custom events."""
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == KEYDOWN:
                self.handle_keydown(event)
            elif event.type == pygame.USEREVENT:
                self.correlation_update()
            elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                obj_effect = self.handle_object_dragging(event)
                if obj_effect:
                    self.hotbar.remove_by_key(obj_effect)
                else:
                    handle_slot_mouse_down(self.hotbar.slots, event)
            elif event.type == MOUSEBUTTONUP and event.button == 1:
                self.hotbar.handle_mouse_up(self, event)

    def handle_keydown(self, event):
        """Handles keydown events for movement and other actions."""
        if event.key == K_q:
            pygame.quit()
            sys.exit()
        elif event.key in [K_w, K_s, K_a, K_d]:
            self.update_position(event.key)
        elif event.key == K_r:
            try:
                self.load_level(f"./levels/{self.current_level}.json")
            except LevelError as err:
                print(f"Could not restart level: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optional setting for starting level.")
    parser.add_argument('level', nargs='?', type=int, default=DEFAULT_START_LEVEL, help='The starting level of the game (default is 1)')
    args = parser.parse_args()

    if not os.path.isfile(f"./levels/{args.level}.json"):
        parser.error(f"level {args.level} does not exist")

    game_instance = Game(args)
    game_instance.run()
