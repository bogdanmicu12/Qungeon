"""A saved level's pillar-to-result mapping, independent of the current game."""

import pygame
from scripts.level_validation import LevelError, parse_pos, read_level
from scripts.quantum_run import validate_scene


class PillarMap:
    VIEW = pygame.Rect(78, 241, 392, 197)

    def __init__(self, menu, run):
        self.menu = menu
        self.run = run
        data, circuit = run.data, run.circuit or {}
        self.labels = data.get("labels", circuit.get("labels", []))
        self.selected = 0
        self.caption = "YOUR COMPLETED LEVEL"
        scene = data.get("scene") or circuit.get("scene")
        try:
            validate_scene(scene)
        except ValueError:
            scene = None
        if scene is None:
            # Runs saved before maps were introduced still get a usable view.
            level = data.get("level", circuit.get("level"))
            try:
                source = read_level(f"./levels/{level}.json")
                scene = {"tiles": {f"{x},{y}": kind for pos, kind in source["tiles"].items() for x, y in [parse_pos(pos)]},
                         "loot": [], "player": None}
                self.caption = "LEVEL LAYOUT / OLDER RUN"
            except LevelError:
                scene = {"tiles": {label: "EMPTY" for label in self.labels}, "loot": [], "player": None}
                self.caption = "SAVED PILLAR POSITIONS"
        self.scene = scene
        self.tiles = {parse_pos(pos): kind for pos, kind in scene["tiles"].items()}
        for label in self.labels:
            self.tiles.setdefault(parse_pos(label), "EMPTY")
        positions = list(self.tiles) or [(0, 0)]
        min_x, min_y = min(x for x, y in positions), min(y for x, y in positions)
        width = max(x for x, y in positions) - min_x + 1
        height = max(y for x, y in positions) - min_y + 1
        self.scale = min(56, (self.VIEW.width-10) / width, (self.VIEW.height-10) / (height + .35))
        self.size = max(1, int(self.scale))
        self.origin = (self.VIEW.centerx - width*self.scale/2 - min_x*self.scale,
                       self.VIEW.centery - height*self.scale/2 - min_y*self.scale + self.size*.15)
        self.images = {name: pygame.transform.scale(image, (self.size, round(self.size*1.25) if name == "pillar" else self.size))
                       for name, image in menu.images.items()}
        self.rects = [self.tile_rect(parse_pos(label)) for label in self.labels]
        self.marginals = None
        self._data = None

    def tile_rect(self, pos):
        return pygame.Rect(round(self.origin[0] + pos[0]*self.scale), round(self.origin[1] + pos[1]*self.scale), self.size, self.size)

    def buttons(self):
        return [(f"quantum:pillar:{i}", rect, f"Bit {i+1}", "") for i, rect in enumerate(self.rects)]

    def probabilities(self):
        data = self.run.data
        if data is not self._data:
            self._data = data
            total = data.get("actual_shots", 0)
            self.marginals = []
            for i in range(len(self.labels)):
                ones = sum(count for bits, count in data.get("counts", {}).items() if len(bits) == len(self.labels) and bits[i] == "1")
                ideal = sum(p for bits, p in data.get("ideal", {}).items() if len(bits) == len(self.labels) and bits[i] == "1")
                self.marginals.append((ones/total if total else None, ideal if "ideal" in data else None))
        return self.marginals

    def draw(self):
        from scripts.menus import ACCENT, BG, EDGE, INK, MINT, MUTED, PANEL
        menu, screen = self.menu, self.menu.game.screen
        for panel in (pygame.Rect(60, 196, 428, 279), pygame.Rect(504, 196, 236, 279)):
            pygame.draw.rect(screen, PANEL, panel)
            pygame.draw.rect(screen, EDGE, panel, 1)
        menu.text(self.caption, 80, 211, 18, MUTED)
        # Focus follows the game's existing keyboard and mouse navigation.
        buttons = menu.buttons()
        if menu.focus < len(buttons) and buttons[menu.focus][0].startswith("quantum:pillar:"):
            self.selected = int(buttons[menu.focus][0].split(":")[-1])
        clip = screen.get_clip()
        screen.set_clip(self.VIEW)
        for pos, kind in sorted(self.tiles.items(), key=lambda item: (item[0][1], item[0][0])):
            name = "wall" if kind == "WALL" else "end_tile" if kind == "END" else "tile"
            screen.blit(self.images[name], self.tile_rect(pos))
            if kind == "START":
                pygame.draw.rect(screen, MINT, self.tile_rect(pos).inflate(-4, -4), 1)
        for pos in self.scene["loot"]:
            screen.blit(self.images["box"], self.tile_rect(parse_pos(pos)))
        for i, rect in enumerate(self.rects):
            screen.blit(self.images["pillar"], (rect.x, rect.bottom - self.images["pillar"].get_height()))
            if i == self.selected:
                pygame.draw.rect(screen, INK, rect.inflate(4, 4), 2)
        if self.scene.get("player"):
            screen.blit(self.images["character"], self.tile_rect(parse_pos(self.scene["player"])))
        # Number badges stay in front of sprites, including adjacent pillars.
        for i, rect in enumerate(self.rects):
            badge = pygame.Rect(rect.centerx-10, rect.bottom-17, 20, 16)
            pygame.draw.rect(screen, INK if i == self.selected else BG, badge)
            menu.text(f"{i+1:02}", badge.centerx, badge.y+1, 17, BG if i == self.selected else ACCENT, True)
        screen.set_clip(clip)
        menu.text("Number = outcome bit. Select a pillar.", 80, 448, 18, MUTED)
        if not self.labels:
            menu.text("No pillars in this run.", 524, 220, 22, MUTED)
            return
        i = self.selected
        menu.text(f"BIT {i+1:02}", 524, 214, 29, ACCENT)
        menu.text(f"Tile ({self.labels[i]})", 524, 250, 21, MUTED)
        icon = pygame.transform.scale(menu.images["pillar"], (40, 50))
        screen.blit(icon, (678, 216))
        observed, ideal = self.probabilities()[i]
        for bit, y in ((0, 293), (1, 369)):
            p = None if observed is None else observed if bit else 1-observed
            expected = None if ideal is None else ideal if bit else 1-ideal
            menu.text(f"|{bit}> measured", 524, y, 20, INK)
            menu.text("--" if p is None else f"{p:.1%}", 667, y, 20, ACCENT)
            pygame.draw.rect(screen, EDGE, (524, y+27, 194, 9))
            if p is not None:
                pygame.draw.rect(screen, ACCENT, (524, y+27, round(194*p), 9))
            menu.text("Ideal: --" if expected is None else f"Ideal: {expected:.1%}", 524, y+43, 18, MINT)
        menu.text(f"{self.run.data.get('actual_shots', 0):,} measured shots", 524, 448, 18, MUTED)
        menu.text("Bits read left to right. Tab / arrows select a pillar; Enter inspects it.", 60, 571, 18, MUTED)
