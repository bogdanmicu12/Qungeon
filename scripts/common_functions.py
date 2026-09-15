import pygame
from functools import lru_cache


@lru_cache(maxsize=32)
def font(size):
    return pygame.font.Font("./assets/DejaVuSans.ttf", round(size * 0.7))

def add_text(sprite, text, x=0, y=0):
    """Adds text to the sprite's image at the specified position."""
    text_surface = font(24).render(text, True, (255, 255, 255))
    sprite.image = sprite.image.convert_alpha()
    sprite.image.blit(text_surface, (x, y))

def update_mouse_drag(elements):
    """Updates the position of elements being dragged by the mouse."""
    for key, element in elements.items():
        if element.dragging:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            element.rect.x = mouse_x - element.offset_x
            element.rect.y = mouse_y - element.offset_y
            break

def set_dragging(element, event):
    """Initializes dragging for an element based on the mouse event."""
    element.dragging = True
    element.origin_x = element.rect.x
    element.origin_y = element.rect.y

    element.offset_x = event.pos[0] - element.rect.x
    element.offset_y = event.pos[1] - element.rect.y

def handle_slot_mouse_down(elements, event):
    """Checks if an element was clicked and sets it to be dragged."""
    for key, element in elements.items():
        if element.rect.collidepoint(event.pos):
            set_dragging(element, event)
            return True
    return False

def hover(elements, screen):
    """Highlights elements under the mouse cursor."""
    mouse_pos = pygame.mouse.get_pos()
    for key, element in elements.items():
        if element.rect.collidepoint(mouse_pos):
            element.hover(screen)
