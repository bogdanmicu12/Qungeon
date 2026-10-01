"""A continuous, two-dimensional view of the captured logical circuit."""

import pygame
from scripts.quantum_run import circuit_diagram
from scripts.scroll_view import ScrollView


class CircuitView:
    VIEW = pygame.Rect(200, 252, 516, 161)
    COLUMN_WIDTH = 102
    ROW_HEIGHT = 32

    def __init__(self, menu, run):
        self.menu = menu
        diagram = circuit_diagram(run.circuit) or run.data.get("diagram")
        self.labels = diagram["labels"]
        self.gates = diagram["gates"]
        self.scroll = ScrollView(self.VIEW, (self.total * self.COLUMN_WIDTH, len(self.labels) * self.ROW_HEIGHT),
                                 wheel_rect=(60, 196, 680, 279))
        self.selected = None
        self.pressed_gate = None

    @property
    def total(self):
        return len(self.gates) + 1  # Final readout added for hardware runs.

    def gate_rect(self, index):
        return pygame.Rect(round(self.VIEW.x + index * self.COLUMN_WIDTH + 8 - self.scroll.x),
                           self.VIEW.y, 86, self.VIEW.height)

    def gate_at(self, pos):
        if self.VIEW.collidepoint(pos):
            index = int((pos[0] - self.VIEW.x + self.scroll.x) // self.COLUMN_WIDTH)
            if index < self.total:
                return index
        return None

    def handle_event(self, event):
        if self.scroll.handle_event(event):
            self.pressed_gate = None
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.pressed_gate = self.gate_at(event.pos)
            return self.pressed_gate is not None
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            gate = self.gate_at(event.pos)
            pressed = self.pressed_gate
            self.pressed_gate = None
            if gate is not None and gate == pressed:
                self.selected = gate
                return True
        return False

    def draw(self):
        from scripts.common_functions import font
        from scripts.menus import ACCENT, BG, EDGE, INK, MINT, MUTED, PANEL

        menu, screen = self.menu, self.menu.game.screen
        pygame.draw.rect(screen, PANEL, (60, 196, 680, 279))
        pygame.draw.rect(screen, EDGE, (60, 196, 680, 279), 1)
        menu.text("PILLAR / TILE", 78, 210, 17, MUTED)
        menu.text(f"READ LEFT TO RIGHT   /   {self.total} STEPS", 208, 210, 17, MUTED)
        first_row = max(0, int(self.scroll.y // self.ROW_HEIGHT))
        last_row = min(len(self.labels), int((self.scroll.y + self.VIEW.height) // self.ROW_HEIGHT) + 1)
        positions = {row: round(self.VIEW.y + 16 + row * self.ROW_HEIGHT - self.scroll.y)
                     for row in range(first_row, last_row)}
        first = max(0, int(self.scroll.x // self.COLUMN_WIDTH))
        last = min(self.total, int((self.scroll.x + self.VIEW.width) // self.COLUMN_WIDTH) + 1)
        clip = screen.get_clip()
        # Labels and step numbers remain pinned to their respective axes.
        screen.set_clip(pygame.Rect(76, self.VIEW.y, self.VIEW.right - 76, self.VIEW.height))
        for row, y in positions.items():
            menu.text(f"P{row+1}", 78, y-8, 22, ACCENT)
            menu.text(self.labels[row], 118, y-7, 18, MUTED)
            menu.text("|0>" if self.scroll.x == 0 else "...", 172, y-7, 18, MINT)
            pygame.draw.line(screen, EDGE, (self.VIEW.x, y), (self.VIEW.right, y), 2)
        screen.set_clip(pygame.Rect(self.VIEW.x, 234, self.VIEW.width, 16))
        for index in range(first, last):
            menu.text(str(index+1), self.gate_rect(index).centerx, 235, 16, MUTED, True)
        screen.set_clip(self.VIEW)
        for index in range(first, last):
            rect = self.gate_rect(index)
            x = rect.centerx
            if index == self.selected:
                pygame.draw.rect(screen, ACCENT, rect, 1)
            if index == len(self.gates):
                qubits, symbols = list(positions), ["M"] * len(positions)
            else:
                gate = self.gates[index]
                qubits, symbols = gate["qubits"], gate["symbols"]
                if len(qubits) > 1:
                    ys = [round(self.VIEW.y + 16 + q * self.ROW_HEIGHT - self.scroll.y) for q in qubits]
                    pygame.draw.line(screen, ACCENT, (x, min(ys)), (x, max(ys)), 2)
            for q, symbol in zip(qubits, symbols):
                if q not in positions:
                    continue
                y = positions[q]
                if symbol in ("@", "(0)"):
                    pygame.draw.circle(screen, ACCENT if symbol == "@" else PANEL, (x, y), 5)
                    pygame.draw.circle(screen, ACCENT, (x, y), 5, 2)
                elif symbol == "X" and "@" in symbols:
                    pygame.draw.circle(screen, ACCENT, (x, y), 9, 2)
                    pygame.draw.line(screen, ACCENT, (x-6, y), (x+6, y), 2)
                    pygame.draw.line(screen, ACCENT, (x, y-6), (x, y+6), 2)
                else:
                    box = pygame.Rect(x-35, y-11, 70, 22)
                    pygame.draw.rect(screen, BG, box)
                    pygame.draw.rect(screen, MINT if symbol == "M" else ACCENT, box, 1)
                    label = symbol
                    if "^" in label:
                        base, exponent = label.rsplit("^", 1)
                        try:
                            label = base + "^" + format(float(exponent), ".3g")
                        except ValueError:
                            pass
                    while len(label) > 1 and font(18).size(label)[0] > 64:
                        label = label[:-2] + "…"
                    menu.text(label, x, y-7, 18, MINT if symbol == "M" else INK, True)
        screen.set_clip(clip)
        self.scroll.draw(screen)
        menu.text("Dot: control   +: controlled X   Y^t: fractional rotation   M: readout", 80, 428, 16, MUTED)
        if self.selected is None:
            detail = "Select a gate for details. M reads each pillar as 0 or 1."
        elif self.selected == len(self.gates):
            detail = "M / Final hardware readout. Outcome bits follow pillar order."
        else:
            gate = self.gates[self.selected]
            operands = ", ".join(f"P{q+1}" for q in gate["qubits"])
            detail = f"Step {self.selected+1} / {gate['name']} / {operands}"
        size = 20
        while size > 14 and font(size).size(detail)[0] > 638:
            size -= 1
        while font(size).size(detail)[0] > 638:
            detail = detail[:-2] + "…"
        menu.text(detail, 80, 447, size, MUTED)
        menu.text("Scroll pillars / Shift + scroll gates / Drag scrollbars / Arrow keys", 60, 571, 18, MUTED)
