"""A short sprite-based accident, followed by a landing in the actual first room."""

import math

import pygame


WALK_MS = 3200
CRACK_MS = 800
FALL_MS = 1400
FADE_MS = 400
RUIN_MS = WALK_MS + CRACK_MS + FALL_MS + FADE_MS
DROP_MS = 1100
SETTLE_MS = 600
ANIMATION_MS = RUIN_MS + DROP_MS + SETTLE_MS
OPENING_THOUGHT = "I fell... I can't climb back up. There must be another way out."


class Opening:
    def __init__(self, menu):
        self.menu = menu
        self.elapsed = 0
        self.suspended = False
        self.tiles = {
            name: pygame.transform.scale(menu.images[name], (16, 16))
            for name in ("tile", "wall", "character")
        }

    @property
    def landed(self):
        return self.elapsed >= ANIMATION_MS

    def update(self, elapsed):
        if not self.suspended:
            self.elapsed = min(ANIMATION_MS, self.elapsed + elapsed)

    def skip(self):
        """Skipping the animation still leaves the escape thought available to read."""
        self.elapsed = ANIMATION_MS
        self.suspended = False

    def draw_ruin(self):
        # Draw at the sprites' native resolution and scale once to retain crisp pixels.
        scene = pygame.Surface((224, 128))
        scene.fill((17, 19, 30))
        for row in range(2, 8):
            for column in range(1, 13):
                if row < 4 and (column + row) % 5 == 0:
                    continue
                image = self.tiles["tile" if row == 4 else "wall"]
                scene.blit(image, (column * 16, row * 16))
        # Missing stone and muted mortar marks give the passage a weathered outline.
        for x, y in ((37, 39), (86, 49), (168, 35), (187, 54)):
            pygame.draw.lines(scene, (62, 65, 76), False,
                              [(x, y), (x + 2, y + 3), (x, y + 5)], 1)

        walking = min(1, self.elapsed / WALK_MS)
        x = round(24 + 96 * walking)
        y = 64 - round(abs(math.sin(walking * math.pi * 12)) * 2) if walking < 1 else 64
        crack = max(0, min(1, (self.elapsed - WALK_MS) / CRACK_MS))
        falling = max(0, min(1, (self.elapsed - WALK_MS - CRACK_MS) / FALL_MS))
        if crack:
            points = [(113, 65), (120, 69), (118, 73), (127, 76), (135, 71), (143, 74)]
            pygame.draw.lines(scene, (29, 27, 34), False, points[:2 + round(crack * 4)], 1)
            y += round(math.sin(crack * math.pi * 6))
        if falling:
            # The hole extends into a visible shaft; both stones and the player accelerate down it.
            pygame.draw.rect(scene, (5, 7, 14), (112, 64, 32, 64))
            for side in (109, 144):
                pygame.draw.line(scene, (61, 59, 70), (side, 65), (side, 128), 2)
            for index in range(7):
                px = 114 + index * 4 + round(math.sin(index * 2) * falling * 9)
                py = 69 + round((85 + index * 7) * falling * falling)
                pygame.draw.rect(scene, (102 + index * 5, 98 + index * 4, 105),
                                 (px, py, 3 + index % 2, 3))
            for index in range(5):
                px = 114 + index * 6
                py = 66 - round(math.sin(falling * math.pi) * (5 + index))
                pygame.draw.rect(scene, (142, 132, 127), (px, py, 1, 1))
            x += round(math.sin(falling * math.pi) * 3)
            y += round(116 * falling * falling)
        character = pygame.transform.rotate(self.tiles["character"], -round(falling * 130))
        scene.blit(character, character.get_rect(center=(x + 8, y + 8)))
        screen = self.menu.game.screen
        screen.fill((17, 19, 30))
        screen.blit(pygame.transform.scale(scene, (672, 384)), (64, 104))
        self.menu.text("THE OLD RUINS", 400, 55, 22, (154, 158, 177), True)
        fade_out = max(0, (self.elapsed - RUIN_MS + FADE_MS) / FADE_MS)
        fade_in = max(0, 1 - self.elapsed / 350)
        opacity = round(255 * max(fade_in, fade_out))
        if opacity:
            veil = pygame.Surface((800, 600), pygame.SRCALPHA)
            veil.fill((8, 10, 18, min(255, opacity)))
            screen.blit(veil, (0, 0))

    def draw_arrival(self):
        game = self.menu.game
        progress = max(0, min(1, (self.elapsed - RUIN_MS) / DROP_MS))
        offset = round(-(game.player.rect.y + 64) * (1 - progress * progress))
        settled = max(0, min(1, (self.elapsed - RUIN_MS - DROP_MS) / SETTLE_MS))
        if progress == 1:
            offset = -round(math.sin(settled * math.pi) * 7)
        game.display_game(update=False, interactive=False, player_offset=offset, show_ui=False)
        if progress == 1 and settled < 1:
            for index in range(6):
                x = game.player.rect.centerx + round((index - 2.5) * (5 + settled * 9))
                y = game.player.rect.bottom - 5 - round(math.sin(settled * math.pi) * 12)
                pygame.draw.rect(game.screen, (154, 143, 135), (x, y, 3, 3))
        if progress < 0.3:
            veil = pygame.Surface((800, 600), pygame.SRCALPHA)
            veil.fill((8, 10, 18, round(255 * (1 - progress / 0.3))))
            game.screen.blit(veil, (0, 0))
        if self.landed:
            panel = pygame.Rect(104, 303, 592, 104)
            pygame.draw.rect(game.screen, (8, 10, 17), panel.move(0, 5))
            pygame.draw.rect(game.screen, (26, 29, 43), panel)
            pygame.draw.rect(game.screen, (58, 63, 83), panel, 2)
            self.menu.text("...", 124, 315, 23, (182, 164, 242))
            self.menu.paragraph(OPENING_THOUGHT, 124, 344, 552, size=25,
                                color=(238, 235, 225))

    def draw(self):
        if self.elapsed < RUIN_MS:
            self.draw_ruin()
        else:
            self.draw_arrival()
        if self.suspended:
            self.menu.game.screen.blit(self.menu.veil, (0, 0))
            self.menu.text("Paused", 400, 248, 40, (238, 235, 225), True)
            self.menu.text("Continue when you're ready.", 400, 300, 23, (154, 158, 177), True)
