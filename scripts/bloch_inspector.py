"""Optional live pillar inspector, rendered identically on desktop and web."""

import math

import pygame

from scripts.bloch_state import BlochStateCache
from scripts.common_functions import font
from scripts.game_objects import QuantumObject, PURE_ZERO_TOL
from scripts.menus import ACCENT, BG, EDGE, HEADER_LEFT, HEADER_RIGHT, INK, MINT, MUTED, PANEL, RED


BEFORE = (242, 192, 125)
WIDTH, HEIGHT = 272, 340


def project(vector, center, radius):
    """Orthographic projection with an orthonormal camera basis."""
    x, y, z = vector
    return (round(center[0] + radius * (0.8*x - 0.6*y)),
            round(center[1] + radius * (0.3*x + 0.4*y - math.sqrt(0.75)*z)))


def probability_text(value):
    # Do not round a blocked near-zero state to an apparently certain outcome.
    if 0 < value < 0.0001:
        return "<0.01%"
    if 0.9999 < value < 1:
        return ">99.99%"
    return f"{value:.2%}"


class BlochInspector:
    def __init__(self, game):
        self.game = game
        self.enabled = False
        self.cache = BlochStateCache()
        self.surface = pygame.Surface(game.screen.get_size(), pygame.SRCALPHA)
        self.reset()

    def reset(self):
        """Drop references to the previous level, preserving the session toggle."""
        self.selected = None
        self.help_open = False
        self.previous = {}
        self.last_gate = None
        self.ready = False
        self.rect = pygame.Rect(HEADER_RIGHT-WIDTH, 96, WIDTH, HEIGHT)
        self.mouse_captured = False
        self.drag_offset = None
        self.manually_positioned = False
        self.cache.clear()

    def finish_level(self):
        self.ready = True
        self.previous = {}
        self.last_gate = None
        self.cache.clear()

    def pillars(self):
        return sorted((obj for obj in self.game.objects.values()
                       if isinstance(obj, QuantumObject)),
                      key=lambda obj: (obj.position[1], obj.position[0]))

    def states(self):
        if self.game.quantum_grid.post_selection:
            raise ValueError("Post-selected states are not supported by this inspector.")
        return self.cache.read(self.game.quantum_grid.circuit,
                               (obj.qubit for obj in self.pillars()))

    def before_gate(self):
        if self.enabled and self.ready:
            try:
                return self.states()
            except ValueError:
                pass  # An unavailable inspector must not prevent a legal move.
        return {}

    def after_gate(self, previous, label):
        self.previous = previous
        self.last_gate = label if previous else None

    def dragging(self):
        return (any(slot.dragging for slot in self.game.hotbar.slots.values())
                or any(obj.dragging for obj in self.game.objects.values()))

    def visible(self):
        return (self.enabled and self.ready and self.game.menu.page == "playing"
                and not self.game.gate_help_open)

    def select(self, obj):
        if obj is self.selected:
            return
        self.selected = obj
        # Default placement aligns with the header divider. Once dragged, the
        # player's position wins over automatic placement when selection changes.
        if not self.manually_positioned and self.drag_offset is None:
            self.rect.x = HEADER_LEFT if obj.rect.centerx >= 400 else HEADER_RIGHT-WIDTH

    def cancel_drag(self):
        self.drag_offset = None

    def move_panel(self, position):
        old_position = self.rect.topleft
        self.rect.topleft = (position[0]-self.drag_offset[0], position[1]-self.drag_offset[1])
        self.rect.clamp_ip(self.game.screen.get_rect().inflate(-16, -16))
        if self.rect.topleft != old_position:
            self.manually_positioned = True

    def title_bar(self):
        return pygame.Rect(self.rect.x, self.rect.y, WIDTH, 38)

    def toggle(self):
        self.game.cancel_dragging()
        self.enabled = not self.enabled
        self.help_open = False
        if self.enabled and self.selected is None:
            pillars = self.pillars()
            if pillars:
                hovered = next((p for p in reversed(pillars)
                                if p.rect.collidepoint(pygame.mouse.get_pos())), None)
                px, py = self.game.player.position
                self.select(hovered or min(pillars, key=lambda p:
                            (p.position[0]-px)**2 + (p.position[1]-py)**2))

    def update_hover(self, position):
        if (not self.visible() or self.dragging() or self.drag_offset is not None
                or self.rect.collidepoint(position)):
            return
        for obj in reversed(self.pillars()):
            if obj.rect.collidepoint(position):
                self.select(obj)
                break

    def buttons(self):
        x, y = self.rect.topleft
        return {
            "help": pygame.Rect(x+207, y+10, 22, 25),
            "close": pygame.Rect(x+236, y+10, 24, 25),
        }

    def handle_event(self, event):
        # Consume the matching release even if its press closed the inspector.
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.mouse_captured:
            if self.drag_offset is not None:
                self.move_panel(event.pos)
                self.cancel_drag()
            self.mouse_captured = False
            return True
        if self.game.gate_help_open:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_b:
            if not getattr(event, "repeat", False):
                self.toggle()
            return True
        if not self.enabled:
            return False
        if self.drag_offset is not None:
            if event.type == pygame.MOUSEMOTION:
                if hasattr(event, "buttons") and not event.buttons[0]:
                    # Recover if the pointer was released outside the canvas.
                    self.cancel_drag()
                    self.mouse_captured = False
                else:
                    self.move_panel(event.pos)
                return True
            if event.type == pygame.KEYDOWN and event.key not in (
                    pygame.K_ESCAPE, pygame.K_q, pygame.K_h, pygame.K_r):
                return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                pillars = self.pillars()
                if pillars:
                    index = pillars.index(self.selected) if self.selected in pillars else -1
                    step = -1 if getattr(event, "mod", 0) & pygame.KMOD_SHIFT else 1
                    self.select(pillars[(index + step) % len(pillars)])
                return True
            if event.key == pygame.K_F1:
                if not getattr(event, "repeat", False):
                    self.help_open = not self.help_open
                return True
        # Gate drops and controlled-gate clicks must pass through the faded
        # panel, including when it has been dragged over the target pillar.
        if not self.visible() or self.dragging():
            return False
        if event.type == pygame.MOUSEMOTION:
            self.update_hover(event.pos)
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            if self.rect.collidepoint(event.pos):
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.mouse_captured = True
                    for action, rect in self.buttons().items():
                        if rect.collidepoint(event.pos):
                            if action == "help":
                                self.help_open = not self.help_open
                            else:
                                self.enabled = False
                                self.help_open = False
                            break
                    else:
                        if self.title_bar().collidepoint(event.pos):
                            self.drag_offset = (event.pos[0]-self.rect.x, event.pos[1]-self.rect.y)
                return True
        return False

    def text(self, text, x, y, size=18, color=INK, centered=False):
        image = font(size).render(text, True, color)
        rect = image.get_rect(midtop=(x, y)) if centered else image.get_rect(topleft=(x, y))
        self.surface.blit(image, rect)

    def wrap(self, text, y, color=MUTED, size=18):
        line = ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and font(size).size(candidate)[0] > WIDTH - 28:
                self.text(line, self.rect.x+14, y, size, color)
                y += 19
                line = word
            else:
                line = candidate
        if line:
            self.text(line, self.rect.x+14, y, size, color)
            y += 19
        return y

    def draw_sphere(self, vector, previous):
        screen = self.surface
        center = (self.rect.centerx, self.rect.y+126)
        radius = 70
        pygame.draw.circle(screen, BG, center, radius)
        # Dashed back hemispheres distinguish depth without a graphics library.
        for plane in range(3):
            points = []
            for i in range(97):
                angle = i * math.tau / 96
                a, b = math.cos(angle), math.sin(angle)
                xyz = ((a, b, 0), (a, 0, b), (0, a, b))[plane]
                depth = math.sqrt(0.75)*(0.6*xyz[0]+0.8*xyz[1]) + 0.5*xyz[2]
                points.append((project(xyz, center, radius), depth))
            for i in range(1, len(points)):
                front = points[i][1] >= 0
                if front or i % 4 < 2:
                    pygame.draw.aaline(screen, (91, 97, 122) if front else EDGE,
                                       points[i-1][0], points[i][0])
        pygame.draw.circle(screen, EDGE, center, radius, 1)
        for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            negative = tuple(-v for v in axis)
            pygame.draw.aaline(screen, EDGE, project(negative, center, radius),
                               project(axis, center, radius))
        for label, axis, offset in (
            ("|0>", (0, 0, 1), (0, -18)), ("|1>", (0, 0, -1), (0, 6)),
            ("X", (1, 0, 0), (12, -4)), ("Y", (0, 1, 0), (-12, 0)),
        ):
            x, y = project(axis, center, radius)
            self.text(label, x+offset[0], y+offset[1], 17, MUTED, True)
        if previous is not None:
            end = project(previous, center, radius)
            for i in range(0, 12, 2):
                a = (center[0] + (end[0]-center[0])*i/12,
                     center[1] + (end[1]-center[1])*i/12)
                b = (center[0] + (end[0]-center[0])*(i+1)/12,
                     center[1] + (end[1]-center[1])*(i+1)/12)
                pygame.draw.line(screen, BEFORE, a, b, 2)
            pygame.draw.circle(screen, BEFORE, end, 7, 2)
        end = project(vector, center, radius)
        pygame.draw.line(screen, MINT, center, end, 3)
        dx, dy = end[0]-center[0], end[1]-center[1]
        length = math.hypot(dx, dy)
        if length > 10:
            ux, uy = dx/length, dy/length
            pygame.draw.polygon(screen, MINT, (end,
                (end[0]-9*ux+4*uy, end[1]-9*uy-4*ux),
                (end[0]-9*ux-4*uy, end[1]-9*uy+4*ux)))
        pygame.draw.circle(screen, MINT, end, 4)
        pygame.draw.circle(screen, INK, center, 2)

    def draw(self):
        if not self.visible():
            return
        self.surface.fill((0, 0, 0, 0))
        self.draw_panel()
        self.surface.set_alpha(180 if self.dragging() or self.drag_offset is not None else 255)
        self.game.screen.blit(self.surface, (0, 0))

    def draw_panel(self):
        pillars = self.pillars()
        if self.selected not in pillars:
            self.selected = None
            if pillars:
                self.select(pillars[0])
        screen = self.surface
        x, y = self.rect.topleft
        if self.selected:
            pygame.draw.rect(screen, ACCENT, self.selected.rect.inflate(4, 4), 2)
        pygame.draw.rect(screen, (8, 10, 17), self.rect.move(0, 4))
        pygame.draw.rect(screen, PANEL, self.rect)
        pygame.draw.rect(screen, ACCENT, self.rect, 1)
        title = f"PILLAR {pillars.index(self.selected)+1}" if self.selected else "BLOCH SPHERE"
        grip_color = ACCENT if self.drag_offset is not None else MUTED
        for gx in (x+12, x+17):
            for gy in (y+16, y+21, y+26):
                pygame.draw.circle(screen, grip_color, (gx, gy), 1)
        self.text(title, x+28, y+14, 20, INK)
        self.text("DRAG", x+158, y+17, 14, MUTED)
        for action, rect in self.buttons().items():
            active = action == "help" and self.help_open
            pygame.draw.rect(screen, ACCENT if active else BG, rect)
            pygame.draw.rect(screen, ACCENT if active else EDGE, rect, 1)
            label = {"help": "?", "close": "X"}[action]
            self.text(label, rect.centerx, rect.y+5, 16, BG if active else INK, True)
        pygame.draw.line(screen, EDGE, (x+12, y+312), (x+WIDTH-12, y+312))
        self.text("TAB pillar   B close   F1 help", x+14, y+322, 16, MUTED)
        if self.help_open:
            cursor = y+49
            for paragraph in (
                "Inspecting shows one pillar's local state without measuring or changing it.",
                "The poles are |0> and |1>. Direction shows relative phase: |+> is along X, |+i> along Y.",
                "Pure states lie on the surface. Entangled pillars lie inside. The centre means 50/50, not an empty pillar. One sphere cannot show joint correlations.",
                "Mint is now; the amber ring is before the last gate. Hover to select. Drag the title to move this panel.",
            ):
                cursor = self.wrap(paragraph, cursor, size=16) + 7
            return
        if self.selected is None:
            self.wrap("This level has no quantum pillars to inspect.", y+65)
            return
        self.text(f"Tile {self.selected.position}  /  IDEAL STATE", x+14, y+39, 15, MUTED)
        try:
            state = self.states()[self.selected.qubit]
        except ValueError:
            self.wrap("State unavailable. This inspector supports the game's unitary circuits; measurements and noise need a different simulation.", y+70, RED)
            return
        old = self.previous.get(self.selected.qubit)
        self.draw_sphere(state.vector, old.vector if old else None)
        self.text("NOW", x+26, y+210, 16, MINT)
        self.text(f"BEFORE {self.last_gate}" if old else "Apply a gate to compare", x+85, y+210, 16,
                  BEFORE if old else MUTED)
        self.text(state.description, self.rect.centerx, y+230, 19, INK, True)
        for bit, value in ((0, state.probability_zero), (1, 1-state.probability_zero)):
            row = y+253+bit*21
            self.text(f"P({bit})", x+16, row, 17, MUTED)
            bar = pygame.Rect(x+57, row+2, 102, 9)
            pygame.draw.rect(screen, BG, bar)
            pygame.draw.rect(screen, MINT if bit == 0 else ACCENT,
                             (bar.x, bar.y, round(bar.width*value), bar.height))
            self.text(probability_text(value), x+172, row-1, 17, INK)
        passable = state.probability_zero >= 1-PURE_ZERO_TOL
        self.text("PASSABLE  /  |0>" if passable else "BLOCKED  /  needs |0>",
                  self.rect.centerx, y+295, 16, MINT if passable else RED, True)
