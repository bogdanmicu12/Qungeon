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
            label_font = pygame.font.Font('./assets/DejaVuSans.ttf', 18)
            description_font = pygame.font.Font('./assets/DejaVuSans.ttf', 11)
            padding_x = 18
            padding_y = 16
            preview_max_width = 154
            preview_max_height = 76
            source_width, source_height = info_image.get_size()
            preview_scale = min(
                preview_max_width / source_width,
                preview_max_height / source_height,
            )
            preview_width = max(1, int(source_width * preview_scale))
            preview_height = max(1, int(source_height * preview_scale))

            content_width = max(300, preview_width + padding_x * 2)
            words = self.info["description"].split()
            lines = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if description_font.size(candidate)[0] <= content_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)

            label = label_font.render(self.info["label"], True, (255, 255, 255))
            text_height = label.get_height() + 7 + len(lines) * 14
            background_height = padding_y + preview_height + 10 + text_height + padding_y
            self.hover_image = pygame.Surface((content_width, background_height), pygame.SRCALPHA)
            self.hover_image.fill((30, 30, 32, 255))
            pygame.draw.rect(self.hover_image, (30, 30, 32, 255), self.hover_image.get_rect())
            pygame.draw.rect(self.hover_image, (170, 170, 190, 255), self.hover_image.get_rect(), 2, 4)
            pygame.draw.rect(self.hover_image, (83, 190, 121, 255), (2, 2, content_width - 4, 4))

            preview = pygame.Surface((preview_width + 10, preview_height + 10), pygame.SRCALPHA)
            preview.fill((48, 48, 54, 255))
            pygame.draw.rect(preview, (100, 100, 112, 255), preview.get_rect(), 1, 3)
            scaled_image = pygame.transform.smoothscale(info_image, (preview_width, preview_height))
            preview.blit(scaled_image, (5, 5))
            self.hover_image.blit(preview, ((content_width - preview.get_width()) // 2, padding_y + 5))

            text_y = padding_y + preview.get_height() + 10
            self.hover_image.blit(label, (padding_x, text_y))
            for index, line in enumerate(lines):
                text = description_font.render(line, True, (220, 220, 220))
                self.hover_image.blit(text, (padding_x, text_y + label.get_height() + 7 + index * 14))

            self.hover_image_rect = self.hover_image.get_rect()

    def hover(self, screen):
        """Draws the hover image at the mouse position if the slot is not being dragged."""
        if not self.dragging:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            hover_x = max(
                4,
                min(mouse_x - 18, screen.get_width() - self.hover_image.get_width() - 4),
            )
            hover_y = max(4, mouse_y - self.hover_image.get_height() - 12)
            self.hover_image_rect.topleft = (hover_x, hover_y)
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
