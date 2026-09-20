import pygame
from scripts.game_objects import (
    GATE_INFO,
    QuantumObject,
    gates,
    gate_info_image,
    control_gates,
)
from scripts.common_functions import add_text, set_dragging

class ItemSlot(pygame.sprite.Sprite):
    """Represents a slot for an item in the hotbar."""
    def __init__(self, x, y, count, item_name):
        super().__init__()
        self.image = pygame.Surface([50, 50], pygame.SRCALPHA)
        pygame.draw.rect(self.image, (150, 150, 150), pygame.Rect(1, 1, 47, 47))
        pygame.draw.rect(self.image, (100, 100, 100), self.image.get_rect(), 2, 3)
        self.rect = self.image.get_rect()
        self.rect.x = x
        self.rect.y = y
        self.original_image = self.image
        self.name = item_name
        self.info = GATE_INFO.get(item_name, {"label": item_name, "description": "Quantum gate."})

        self.count = count
        self.effect = gates.get(item_name)
        self.origin_x = 0
        self.origin_y = 0
        self.offset_x = 0
        self.offset_y = 0
        self.dragging = False

        info_image = gate_info_image.get(item_name)
        if info_image:
            rect = info_image.get_rect()
            hover_width = int(rect.width * 0.5)
            hover_height = int(rect.height * 0.5)
            padding_x = 16
            padding_y = 14
            background_width = max(180, hover_width + (padding_x * 2))
            background_height = hover_height + 82

            self.hover_image = pygame.Surface((background_width, background_height), pygame.SRCALPHA)
            self.hover_image.fill((30, 30, 32, 255))
            pygame.draw.rect(self.hover_image, (30, 30, 32, 255), pygame.Rect(1, 1, background_width - 2, background_height - 2))
            pygame.draw.rect(self.hover_image, (170, 170, 190, 255), pygame.Rect(0, 0, background_width, background_height), 2, 3)

            scaled_image = pygame.transform.scale(info_image, (hover_width, hover_height))
            hover_image_pos = ((background_width - hover_width) // 2, padding_y)
            self.hover_image.blit(scaled_image, hover_image_pos)

            label = pygame.font.Font('./assets/DejaVuSans.ttf', 18).render(self.info["label"], True, (255, 255, 255))
            self.hover_image.blit(label, (padding_x, hover_height + padding_y + 8))

            description = self.info["description"]
            words = description.split()
            lines = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if len(candidate) <= 24:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            for index, line in enumerate(lines[:2]):
                text = pygame.font.Font('./assets/DejaVuSans.ttf', 11).render(line, True, (220, 220, 220))
                self.hover_image.blit(text, (padding_x, hover_height + padding_y + 30 + index * 14))

            self.hover_image_rect = self.hover_image.get_rect()

    def hover(self, screen):
        """Draws the hover image at the mouse position if the slot is not being dragged."""
        if not self.dragging:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            self.hover_image_rect.topleft = (mouse_x - 18, mouse_y - self.hover_image.get_height() - 12)
            screen.blit(self.hover_image, self.hover_image_rect)

class Hotbar:
    """Gate inventory and drag handling."""
    def __init__(self):
        self.rect = pygame.Rect(400, 525, 0, 50)
        self.slots = {}
        self.sprites = pygame.sprite.Group()
    
    def change_item_text(self, slot, item, count=0):
        add_text(slot, item)
        if count:
            add_text(slot, f'x{count}', 0, 30)

    def add_item(self, item, count):
        if item in self.slots:
            slot = self.slots[item]
            slot.count += count
            slot.image = slot.original_image
            self.change_item_text(slot, item, str(slot.count))
            return slot
        else:
            new_slot = ItemSlot(0, self.rect.y, count, item)
            self.change_item_text(new_slot, item, str(count))
            self.slots[item] = new_slot
            self.sprites.add(new_slot)
            self.update_slots()
            return new_slot

    def remove_by_key(self, key):
        slot = self.slots[key]
        slot.count -= 1
        if slot.count <= 0:
            slot.kill()
            self.slots.pop(key)
            self.update_slots()
        else:
            slot.image = slot.original_image
            self.change_item_text(slot, key, str(slot.count))

    def remove_item(self, game, event, key):
        slot = self.slots.get(key)
        if not slot:
            return

        for _, obj in game.objects.items():
            if isinstance(obj, QuantumObject):
                if obj.rect.collidepoint(event.pos) and game.player.distance(obj.position[0], obj.position[1]):
                    if key in control_gates:
                        set_dragging(obj, event)
                        obj.control = key
                        return
                    else:
                        obj.apply_effect(game, slot.effect)
                    self.remove_by_key(key)
                    break

    def update_slots(self):
        self.rect.width = max(0, len(self.slots) * 55 - 5)
        self.rect.centerx = 400
        for i, slot in enumerate(self.slots.values()):
            if not slot.dragging:
                slot.rect.topleft = (self.rect.x + i * 55, self.rect.y)

    def handle_mouse_up(self, game, event):
        for key, slot in self.slots.items():
            if slot.dragging:
                slot.dragging = False
                self.remove_item(game, event, key)
                self.update_slots()
                break
