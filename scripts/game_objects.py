import pygame
from collections import OrderedDict
import enum
import cirq
import numpy as np
from scripts.common_functions import add_text
import unitary.alpha as alpha
from scripts.flip_phase import FlipPhase
from math import acos, sqrt, pi


gates = {
    'X': alpha.Flip(),
    'H': alpha.Superposition(),
    'Z': alpha.Phase(),
    'RotY': FlipPhase(-2 * acos(1 / sqrt(3)) / pi),
    'CNOT': None,
    'CHAD': None
}

gate_info_image = {
    'X': pygame.image.load('./assets/x-gate.png'),
    'H': pygame.image.load('./assets/h-gate.png'),
    'Z': pygame.image.load('./assets/z-gate.png'),
    'RotY': pygame.image.load('./assets/roty-gate.png'),
    'CNOT': pygame.image.load('./assets/cnot-gate.png'),
    'CHAD': pygame.image.load('./assets/chad-gate.png')
}

control_gates = ['CNOT', 'CHAD']

# Load game object images
tile_image = pygame.image.load('./assets/tile.png')
end_tile_image = pygame.image.load('./assets/end_tile.png')
pillar_image = pygame.image.load('./assets/pillar.png')
box_image = pygame.image.load('./assets/box.png')
wall_tile_image = pygame.image.load('./assets/wall.png')
x_gate_image = pygame.image.load('./assets/x-gate.png')

SCALE_FACTOR = 3
BLOCK_SIZE = 16 * SCALE_FACTOR
PEEK_COUNT = 1000
# A pillar is walkable only when it is exactly |0>. We read that from the
# world's exact state vector (below) rather than the 1000-shot peek, so the
# decision is deterministic; PURE_ZERO_TOL just absorbs float rounding.
PURE_ZERO_TOL = 1e-6  # cirq simulates in complex64; ~1e-7 rounding is the floor


def exact_probability_zero(world, obj):
    """Exact P(|0>) for a qubit, from the world's state vector.

    get_probabilities() samples the world (1000 shots), so a state merely
    close to |0> can occasionally read as pure and flip a pillar's
    passability with no state change. Simulating the stored circuit gives the
    exact probability instead, which is deterministic.
    """
    result = cirq.Simulator().simulate(world.circuit)
    index = result.qubit_map[obj.qubit]
    num_qubits = len(result.qubit_map)
    probabilities = np.abs(result.final_state_vector) ** 2
    return float(sum(
        amp for state, amp in enumerate(probabilities)
        if (state >> (num_qubits - 1 - index)) & 1 == 0
    ))

class Pillar(enum.Enum):
    """Enumeration for quantum object states."""
    EMPTY = 0
    FULL = 1

class TileType(enum.Enum):
    """Enumeration for different tile types."""
    EMPTY = 0
    START = 1
    END = 2
    WALL = 4

class BaseObject(pygame.sprite.Sprite):
    """Base class for all game objects that need to be represented as sprites."""
    def __init__(self, x, y):
        """Initializes the base object with position and dragging properties."""
        super().__init__()
        self.position = (x, y)
        self.origin_x = 0
        self.origin_y = 0
        self.offset_x = 0
        self.offset_y = 0
        self.dragging = False
    
    def change_color(self, image, color, alpha=255):
        """Changes the color of the object's image."""
        image_rect = image.get_rect()
        self.image = pygame.transform.scale(image, (int(image_rect.width * SCALE_FACTOR), int(image_rect.height * SCALE_FACTOR)))
        self.colorImage.fill((*color, alpha))
        self.image.blit(self.colorImage, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

class LootableObject(BaseObject):
    """Represents an object that can be looted by the player."""
    def __init__(self, item, x, y):
        """Initializes the lootable object with an item and position."""
        super().__init__(x, y)
        box_rect = box_image.get_rect()
        self.image = pygame.transform.scale(box_image, (int(box_rect.width * SCALE_FACTOR), int(box_rect.height * SCALE_FACTOR)))
        self.rect = self.image.get_rect()
        self.rect.x = x * BLOCK_SIZE
        self.rect.y = y * BLOCK_SIZE
        self.item = item
        add_text(self, item, box_rect.width, box_rect.height)

    def function(self, game, x, y):
        """Adds the item to the player's hotbar and removes the object from the game. Called when player moves to tile object is in."""
        game.hotbar.add_item(self.item, 1)
        self.kill()
        del game.objects[str(x) + "," + str(y)]
        return True

class QuantumObject(BaseObject, alpha.QuantumObject):
    """Represents a quantum object in the game, currently only pillars."""
    def __init__(self, x, y, game):
        """Initializes the quantum object with position and basic state information."""
        BaseObject.__init__(self, x, y)
        alpha.QuantumObject.__init__(self, str(x) + "," + str(y), Pillar.EMPTY)
        wall_rect = pillar_image.get_rect()
        self.image = pygame.transform.scale(pillar_image, (int(wall_rect.width * SCALE_FACTOR), int(wall_rect.height * SCALE_FACTOR)))
        self.rect = self.image.get_rect()
        self.rect.x = x * BLOCK_SIZE 
        self.rect.y = (y + 1) * BLOCK_SIZE - self.image.get_size()[1]

        self.colorImage = pygame.Surface(self.image.get_size()).convert_alpha()
        self.colorImage.fill((255, 255, 255, 255))
        self.image.blit(self.colorImage, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.color = None

        self.phase_Z = False
        self.control = None
        game.quantum_grid.add_object(self)
        self.states = game.quantum_grid.get_probabilities([self], PEEK_COUNT)[0]
        self.group = game.grouping_system.add(self)

    def apply_effect(self, game, effect=None):
        """Applies a quantum effect to the object and updates its color based on the effect."""
        color_alpha = 255

        if effect == alpha.Superposition() and self.states[1] == 1.0:
            self.phase_Z = True
        elif effect == alpha.Phase() and self.states[0] != 1.0:
            self.phase_Z = not self.phase_Z
        elif effect == alpha.Superposition() or self.states[0] == 1.0:
            self.phase_Z = False

        if effect:
            if isinstance(effect, list):
                reference_obj = game.objects[str(effect[1][0]) + ',' + str(effect[1][1])]
                alpha.quantum_if(self).apply(effect[0])(reference_obj)
                game.grouping_system.join(self, reference_obj)
                reference_obj.apply_effect(game)
            else:
                effect(self)

            ordered_dict = OrderedDict(sorted(game.quantum_grid.get_correlated_histogram(self.group.objects, count=PEEK_COUNT).items()))
            self.group.states = ordered_dict

        histogram = game.quantum_grid.get_probabilities([self], PEEK_COUNT)
        self.states = histogram[0]

        self.color = (int(255 * self.states[0]), int(self.phase_Z) * 220, int(255 * self.states[1]))
        if self.states[0] == 1.0:
            color_alpha = 150
            self.color = (255, 255, 255)

        self.change_color(pillar_image, self.color, color_alpha)

    def function(self, game, x, y):
        """Passable only when the pillar is deterministically in a pure |0> state.

        Called when the player tries to move onto the pillar's tile.
        """
        obj = game.objects[str(x) + "," + str(y)]
        return exact_probability_zero(game.quantum_grid, obj) >= 1.0 - PURE_ZERO_TOL

class Tile(BaseObject):
    """Represents a tile on the game board."""
    def __init__(self, x, y, type):
        """Initializes the tile with type and position."""
        super().__init__(x, y)
        self.type = type
        if type == TileType.END:
            image = end_tile_image
        elif type == TileType.WALL:
            image = wall_tile_image
        else:
            image = tile_image

        tile_rect = image.get_rect()
        self.image = pygame.transform.scale(image, (int(tile_rect.width * SCALE_FACTOR), int(tile_rect.height * SCALE_FACTOR)))
        self.rect = self.image.get_rect()
        self.rect.x = x * BLOCK_SIZE
        self.rect.y = y * BLOCK_SIZE

class Player(pygame.sprite.Sprite):
    """Represents the player character in the game."""
    def __init__(self, x, y):
        """Initializes the player with position and image."""
        super().__init__()
        self.position = (x, y)
        self.image = pygame.image.load("./assets/character.png")
        self.rect = self.image.get_rect()
        self.image = pygame.transform.scale(self.image, (int(self.rect.width * SCALE_FACTOR), int(self.rect.height * SCALE_FACTOR)))
        self.rect = self.image.get_rect()
        self.rect.x = x * BLOCK_SIZE
        self.rect.y = y * BLOCK_SIZE

    def update_position(self, x, y):
        """Updates the player's position and rectangle based on new coordinates."""
        self.position = (x, y)
        self.rect.x = x * BLOCK_SIZE
        self.rect.y = y * BLOCK_SIZE
    
    def distance(self, x, y):
        """Checks if the player is within a 1-tile distance from the specified coordinates."""
        return abs(self.position[0] - x) <= 1 and abs(self.position[1] - y) <= 1
