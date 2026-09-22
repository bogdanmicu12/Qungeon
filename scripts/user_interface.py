import pygame
from scripts.game_objects import QuantumObject, gates, gate_info_image, control_gates
from scripts.common_functions import add_text, set_dragging


GATE_DESCRIPTIONS = {
    "X": "Flip the pillar between 0 and 1.",
    "H": "Create a superposition of 0 and 1.",
    "Z": "Change the phase of the 1 state.",
    "RotY": "Rotate the state around the Y axis.",
    "CNOT": "Flip a target pillar when the control is 1.",
    "CHAD": "Apply a Hadamard to a target when the control is 1.",
}

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
            background_width = hover_width + 20
            background_height = hover_height + 20

            self.hover_image = pygame.Surface((background_width, background_height), pygame.SRCALPHA)
            pygame.draw.rect(self.hover_image, (150, 150, 150), pygame.Rect(1, 1, background_width - 2, background_height - 2))
            pygame.draw.rect(self.hover_image, (100, 100, 100), pygame.Rect(0, 0, background_width, background_height), 2, 3)

            scaled_image = pygame.transform.scale(info_image, (hover_width, hover_height))
            hover_image_pos = ((background_width - hover_width) // 2, (background_height - hover_height) // 2)
            self.hover_image.blit(scaled_image, hover_image_pos)

            self.hover_image_rect = self.hover_image.get_rect()

    def hover(self, screen):
        """Draws the hover image at the mouse position if the slot is not being dragged."""
        if not self.dragging:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            self.hover_image_rect.topleft = (mouse_x, mouse_y - 45)
            screen.blit(self.hover_image, self.hover_image_rect)

class Hotbar:
    """Gate inventory and drag handling."""
    def __init__(self):
        self.rect = pygame.Rect(400, 525, 0, 50)
        self.slots = {}
        self.sprites = pygame.sprite.Group()
        self.selected_key = None
    
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

    def select_by_number(self, game, number):
        """Selects the gate in the numbered hotbar slot."""
        keys = list(gates)
        if number < 1 or number > len(keys):
            return False
        key = keys[number - 1]
        slot = self.slots.get(key)
        if not slot or slot.count <= 0:
            from scripts.menus import RED
            game.show_quantum_notice(f"{key} is not available", RED, duration=2000)
            return False
        if self.selected_key == key:
            self.selected_key = None
            game.clear_quantum_notice()
        else:
            self.selected_key = key
            game.show_quantum_notice(f"{key} was selected")
        return True

    def apply_selected(self, game, obj):
        """Applies the selected single-pillar gate and consumes one item."""
        key = self.selected_key
        slot = self.slots.get(key)
        if not slot or key in control_gates:
            return False
        obj.apply_effect(game, slot.effect)
        self.remove_by_key(key)
        if key not in self.slots:
            self.selected_key = None
            game.clear_quantum_notice()
        return True

    def draw_selection_panel(self, screen):
        """Draws the keyboard gate selector above the draggable hotbar."""
        from scripts.common_functions import font
        from scripts.menus import ACCENT, BG, EDGE, INK, MUTED, PANEL, RED

        entry_width = 88
        panel = pygame.Rect(0, 444, len(gates) * entry_width + 20, 70)
        panel.centerx = 400
        pygame.draw.rect(screen, PANEL, panel)
        pygame.draw.rect(screen, EDGE, panel, 1)
        self.selection_rects = {}

        for index, key in enumerate(gates, start=1):
            slot = self.slots.get(key)
            count = slot.count if slot else 0
            card = pygame.Rect(panel.x + 8 + (index - 1) * entry_width, panel.y + 9, 82, 52)
            self.selection_rects[key] = card.copy()
            selected = key == self.selected_key
            unavailable = count == 0
            card_color = RED if unavailable else ACCENT if selected else EDGE
            pygame.draw.rect(screen, BG if selected else PANEL, card)
            pygame.draw.rect(screen, card_color, card, 2 if selected else 1)
            key_badge = pygame.Rect(card.x + 6, card.y + 15, 24, 24)
            pygame.draw.rect(screen, card_color, key_badge)
            key_text = font(17).render(str(index), True, BG if selected else INK)
            screen.blit(key_text, key_text.get_rect(center=key_badge.center))
            gate_text = font(15).render(key, True, RED if unavailable else INK)
            screen.blit(gate_text, gate_text.get_rect(midleft=(card.x + 36, card.y + 20)))
            count_text = font(13).render(f"x{count}", True, RED if unavailable else MUTED)
            screen.blit(count_text, count_text.get_rect(midleft=(card.x + 36, card.y + 37)))

        instruction = font(15).render(
            "Select with keys and move over a pillar, or drag when next to a pillar",
            True, MUTED,
        )
        screen.blit(instruction, instruction.get_rect(midtop=(400, panel.bottom + 7)))
        help_instruction = font(15).render("Press H for help on gates", True, MUTED)
        screen.blit(help_instruction, help_instruction.get_rect(midtop=(400, panel.bottom + 23)))

    def handle_selection_mouse_down(self, event):
        """Starts dragging an available gate from the keyboard selector."""
        for key, rect in getattr(self, "selection_rects", {}).items():
            if rect.collidepoint(event.pos):
                slot = self.slots.get(key)
                if slot and slot.count > 0:
                    slot.rect.topleft = rect.topleft
                    set_dragging(slot, event)
                    return True
        return False

    def draw_help_window(self, screen):
        """Draws the gate guide over the game board."""
        from scripts.common_functions import font
        from scripts.menus import ACCENT, BG, EDGE, INK, MUTED, PANEL

        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((8, 10, 17, 205))
        screen.blit(veil, (0, 0))

        window = pygame.Rect(54, 34, 692, 528)
        pygame.draw.rect(screen, PANEL, window)
        pygame.draw.rect(screen, ACCENT, window, 2)
        screen.blit(font(28).render("Gate guide", True, INK), (80, 54))
        screen.blit(font(15).render("H or ESC to close", True, MUTED), (80, 84))

        close = pygame.Rect(676, 52, 48, 30)
        close_hovered = close.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, ACCENT if close_hovered else BG, close)
        pygame.draw.rect(screen, ACCENT if close_hovered else EDGE, close, 2 if close_hovered else 1)
        close_text = font(14).render("CLOSE", True, BG if close_hovered else INK)
        screen.blit(close_text, close_text.get_rect(center=close.center))
        self.help_close_rect = close

        for index, key in enumerate(gates):
            column, row = index % 3, index // 3
            card = pygame.Rect(78 + column * 216, 116 + row * 198, 196, 174)
            pygame.draw.rect(screen, BG, card)
            pygame.draw.rect(screen, EDGE, card, 1)

            image = gate_info_image[key]
            scale = min(58 / image.get_width(), 58 / image.get_height())
            size = (round(image.get_width() * scale), round(image.get_height() * scale))
            gate_image = pygame.transform.smoothscale(image, size)
            screen.blit(gate_image, gate_image.get_rect(center=(card.centerx, card.y + 42)))

            name = font(18).render(f"{index + 1}. {key}", True, ACCENT)
            screen.blit(name, name.get_rect(center=(card.centerx, card.y + 86)))
            description_font = font(14)
            words = GATE_DESCRIPTIONS[key].split()
            lines, current = [], ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and description_font.size(candidate)[0] > card.width - 18:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            for line_index, line in enumerate(lines):
                description = description_font.render(line, True, MUTED)
                description_rect = description.get_rect(center=(card.centerx, card.y + 119 + line_index * 17))
                screen.blit(description, description_rect)

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
