"""Pixel scrolling shared by the desktop and browser menu panels."""

import pygame


class ScrollView:
    def __init__(self, rect, content_size, wheel_rect=None):
        self.rect = pygame.Rect(rect)
        self.wheel_rect = pygame.Rect(wheel_rect or self.rect.inflate(24, 24))
        self.x = self.y = 0.0
        self.drag = None
        self.resize(content_size)

    def resize(self, content_size):
        self.width, self.height = content_size
        self.max_x = max(0, self.width - self.rect.width)
        self.max_y = max(0, self.height - self.rect.height)
        self.move()

    def move(self, dx=0, dy=0):
        self.x = max(0, min(self.max_x, self.x + dx))
        self.y = max(0, min(self.max_y, self.y + dy))

    def bars(self):
        result = []
        for axis, limit in (("x", self.max_x), ("y", self.max_y)):
            if not limit:
                continue
            horizontal = axis == "x"
            track = (pygame.Rect(self.rect.x, self.rect.bottom + 5, self.rect.width, 7) if horizontal
                     else pygame.Rect(self.rect.right + 5, self.rect.y, 7, self.rect.height))
            length = track.width if horizontal else track.height
            visible = self.rect.width if horizontal else self.rect.height
            size = max(24, round(length * visible / (visible + limit)))
            offset = round((length - size) * getattr(self, axis) / limit)
            thumb = (pygame.Rect(track.x + offset, track.y, size, track.height) if horizontal
                     else pygame.Rect(track.x, track.y + offset, track.width, size))
            result.append((axis, track, thumb))
        return result

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if not self.wheel_rect.collidepoint(getattr(event, "pos", pygame.mouse.get_pos())):
                return False
            dx = float(getattr(event, "precise_x", event.x)) * 36
            dy = -float(getattr(event, "precise_y", event.y)) * 36
            mod = getattr(event, "mod", pygame.key.get_mods())
            if mod & pygame.KMOD_SHIFT or (not self.max_y and self.max_x):
                dx, dy = dx + dy, 0
            self.move(dx, dy)
            return True
        if event.type == pygame.KEYDOWN:
            movement = {pygame.K_LEFT: (-36, 0), pygame.K_RIGHT: (36, 0),
                        pygame.K_UP: (0, -32), pygame.K_DOWN: (0, 32),
                        pygame.K_PAGEUP: (0, -self.rect.height), pygame.K_PAGEDOWN: (0, self.rect.height)}
            if event.key in movement:
                self.move(*movement[event.key])
                return True
            if event.key in (pygame.K_HOME, pygame.K_END):
                self.x, self.y = (0, 0) if event.key == pygame.K_HOME else (self.max_x, self.max_y)
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for axis, track, thumb in self.bars():
                if track.inflate(8, 8).collidepoint(event.pos):
                    component = 0 if axis == "x" else 1
                    start = thumb.x if axis == "x" else thumb.y
                    size = thumb.width if axis == "x" else thumb.height
                    grab = event.pos[component] - start if thumb.collidepoint(event.pos) else size / 2
                    self.drag = (axis, grab)
                    self._drag_to(event.pos)
                    return True
        if event.type == pygame.MOUSEMOTION and self.drag:
            self._drag_to(event.pos)
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drag:
            self._drag_to(event.pos)
            self.drag = None
            return True
        return False

    def _drag_to(self, pos):
        axis, grab = self.drag
        for candidate, track, thumb in self.bars():
            if candidate != axis:
                continue
            horizontal = axis == "x"
            start = track.x if horizontal else track.y
            travel = (track.width - thumb.width) if horizontal else (track.height - thumb.height)
            fraction = (pos[0 if horizontal else 1] - start - grab) / travel
            setattr(self, axis, max(0, min(1, fraction)) * getattr(self, "max_" + axis))

    def draw(self, screen):
        from scripts.menus import ACCENT, EDGE
        for axis, track, thumb in self.bars():
            pygame.draw.rect(screen, EDGE, track)
            pygame.draw.rect(screen, ACCENT, thumb)
