"""Exercise story/editor integration and screen-space input after fitting boards."""
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game, PLAY_AREA
from scripts import story
from scripts.common_functions import set_dragging
from scripts.game_objects import QuantumObject, gates
from scripts.level_share import encode_level
from scripts.opening import ANIMATION_MS

LEVELS = sorted(int(path.stem) for path in Path("levels").glob("*.json"))


@pytest.fixture
def game():
    value = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    pygame.event.clear()
    yield value
    value.editor.cancel_validation()
    pygame.event.clear()


@pytest.mark.parametrize("level", LEVELS)
def test_board_objects_and_player_stay_aligned_after_render_and_color_updates(game, level):
    game.start_level(level)
    for sprite in list(game.tile_sprites) + list(game.object_sprites) + [game.player]:
        assert PLAY_AREA.contains(sprite.rect), (level, sprite.rect)
    assert game.player.rect.topleft == game.tiles[game.player.position].rect.topleft
    for obj in game.objects.values():
        tile = game.tiles[obj.position]
        assert obj.rect.bottomleft == tile.rect.bottomleft
        if isinstance(obj, QuantumObject):
            before = obj.rect.copy()
            obj.apply_effect(game)
            assert obj.image.get_size() == before.size
            assert obj.rect == before
    game.display_game()
    assert game.player.rect.topleft == game.tiles[game.player.position].rect.topleft
    assert set(LEVELS) <= story.ROOMS.keys()


def test_hop_uses_the_same_transform_as_the_tiles(game):
    game.start_level(12)
    start = game.player.position
    end = (start[0] + 1, start[1])
    game.hop_animation(start, end)
    game.update_hop(50)
    assert game.player.rect.x == round((start[0] + .5) * game.board_cell_size) + game.board_offset[0]
    game.update_hop(50)
    assert game.player.rect.topleft == game.tiles[end].rect.topleft


def test_selector_drag_applies_gate_to_visible_pillar_and_consumes_one_item(game):
    game.start_level(1)
    game.update_player_position(4, 4)
    game.display_game()
    obj = game.objects["5,4"]
    slot = game.hotbar.slots["X"]
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                        pos=game.hotbar.selection_rects["X"].center))
    game.run_frame()
    assert slot.dragging
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=obj.rect.center))
    game.run_frame()
    assert "X" not in game.hotbar.slots
    assert obj.function(game, 5, 4)
    assert obj.image.get_size() == obj.rect.size


def test_cancelled_pillar_drag_restores_its_scaled_screen_position(game):
    game.start_level(12)
    obj = game.objects["2,5"]
    before = obj.rect.copy()
    set_dragging(obj, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=obj.rect.center))
    obj.control = "SWAP"
    obj.rect.move_ip(91, 73)
    game.menu.open("paused")
    assert obj.rect == before
    assert obj.control is None and not obj.dragging


def test_entanglement_guides_connect_visible_tiles(game, monkeypatch):
    game.start_level(8)
    obj = next(obj for obj in game.objects.values() if isinstance(obj, QuantumObject) and len(obj.group.objects) > 1)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: obj.rect.center)
    lines = []
    monkeypatch.setattr(pygame.draw, "line", lambda screen, color, start, end, **kw: lines.append((start, end)))
    game.entanglement_visuals()
    expected = {(game.tiles[obj.position].rect.center, game.tiles[other.position].rect.center)
                for other in obj.group.objects if other != obj}
    assert set(lines) == expected


def test_custom_level_restores_explicit_states_inventory_and_hud_on_restart(game, monkeypatch):
    data = {
        "editor_created": True,
        "tiles": {"(1, 1)": "START", "(2, 1)": "EMPTY", "(3, 1)": "END"},
        "objects": {}, "quantum_objects": ["(2, 1)"],
        "pillar_states": {"(2, 1)": {"x": 0, "y": 1}},
        "gates": {"X": 1}, "effects": [],
    }
    code = encode_level(data)
    assert game.start_seed_level(code)
    obj = game.objects["2,1"]
    obj.apply_effect(game, gates["X"])
    game.hotbar.remove_by_key("X")
    game.restart_level()
    assert game.current_share_code == code and game.current_level == 0
    assert game.hotbar.slots["X"].count == 1
    assert not game.objects["2,1"].function(game, 2, 1)
    texts = []
    monkeypatch.setattr(game.menu, "text", lambda text, *args: texts.append(text))
    game.menu.draw_hud()
    assert "CUSTOM LEVEL" in texts
    assert not any(room.learning_line in texts for room in story.ROOMS.values())


def test_normal_play_preserves_run_settings_opening_skip_and_focus_pause(game):
    game.menu.activate("play")
    assert "normal_levels" in [button[0] for button in game.menu.buttons()]
    game.menu.activate("normal_levels")
    assert game.menu.page == "setup" and game.quantum_grid is None
    game.menu.activate("start")
    game.run_frame()  # Draw a loading frame before importing gameplay.
    game.run_frame()
    assert game.menu.page == "intro"
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    game.run_frame()
    opening = game.menu.opening
    elapsed = opening.elapsed
    game.menu.update(500)
    assert opening.suspended and opening.elapsed == elapsed
    game.menu.activate("intro_resume")
    game.menu.update(ANIMATION_MS)
    game.menu.draw()
    assert opening.landed
    game.menu.activate("intro_continue")
    assert game.menu.page == "playing" and game.run_mode == "full"


def test_escape_tracks_the_final_level_even_without_story(game, monkeypatch):
    final = game.available_levels[-1]
    game.start_level(9, "full")
    assert not story.is_escape(game)
    game.start_level(final, "full")
    monkeypatch.delitem(story.ROOMS, final)
    assert story.is_escape(game)
    game.start_level(final, "single")
    assert not story.is_escape(game)


def test_swap_drag_exchanges_states_on_scaled_pillars(game):
    game.start_level(12)
    first, second = game.objects["2,5"], game.objects["5,7"]
    game.update_player_position(2, 5)
    first_rect, second_rect = first.rect.copy(), second.rect.copy()
    assert first.function(game, 2, 5)
    assert not second.function(game, 5, 7)
    game.display_game()
    for kind, pos in ((pygame.MOUSEBUTTONDOWN, game.hotbar.selection_rects["SWAP"].center),
                      (pygame.MOUSEBUTTONUP, first.rect.center)):
        pygame.event.post(pygame.event.Event(kind, button=1, pos=pos))
        game.run_frame()
    assert first.dragging and first.control == "SWAP"
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=second.rect.center))
    game.run_frame()
    assert not first.dragging
    assert not first.function(game, 2, 5)
    assert second.function(game, 5, 7)
    assert game.hotbar.slots["SWAP"].count == 1
    assert first.rect == first_rect and second.rect == second_rect
    assert first.image.get_size() == first_rect.size
    assert second.image.get_size() == second_rect.size


def test_long_share_code_does_not_overdraw_its_clear_control_or_field(game):
    game.menu.open("custom_seed")
    region = pygame.Rect(704, 255, 96, 60)
    game.menu.seed_text = "QGL-short"
    game.menu.draw()
    before = pygame.image.tobytes(game.screen.subsurface(region), "RGB")
    game.menu.seed_text = "QGL-" + "W" * 600
    game.menu.draw()
    assert pygame.image.tobytes(game.screen.subsurface(region), "RGB") == before
