"""Guided play must coexist with the story, menus, inspector, and gate toolbar."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game
from scripts import story
from scripts.common_functions import font
from scripts.level_validation import LevelError, validate_level


@pytest.fixture
def game():
    value = Game(SimpleNamespace(level=1), settings={"stuck_warning": False},
                 persist_settings=lambda _: True)
    pygame.event.clear()
    yield value
    pygame.event.clear()


def key(game, value):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value, mod=0))
    game.handle_events()


def move(game, direction):
    key(game, direction)
    assert game.hop is not None
    game.update_hop(100)


def dismiss(game):
    assert game.tutorial.active
    key(game, pygame.K_RETURN)


def test_both_tutorials_play_to_completion_through_actual_input(game):
    game.start_tutorial()
    assert game.current_level == -1 and game.run_mode == "tutorial"
    assert all(number > 0 for number in game.available_levels)
    initial = game.player.position
    key(game, pygame.K_d)
    assert game.player.position == initial and game.hop is None
    dismiss(game)
    move(game, pygame.K_RIGHT)  # Also exercise the movement promised by the tutorial.
    assert game.player.position == (4, 4) and game.hotbar.slots["X"].count == 1
    dismiss(game)
    key(game, pygame.K_1)
    move(game, pygame.K_d)
    assert "X" not in game.hotbar.slots
    dismiss(game)
    move(game, pygame.K_d)
    assert game.pending_advance and game.current_level == -1
    dismiss(game)
    assert game.current_level == -2 and game.tutorial.active
    assert not game.pending_advance
    dismiss(game)
    move(game, pygame.K_s)
    assert game.hotbar.slots["H"].count == 1
    dismiss(game)
    move(game, pygame.K_w)
    move(game, pygame.K_d)
    assert game.hotbar.slots["X"].count == 1
    key(game, pygame.K_2)
    move(game, pygame.K_d)
    dismiss(game)
    key(game, pygame.K_1)
    move(game, pygame.K_d)
    move(game, pygame.K_d)
    assert game.pending_advance
    dismiss(game)
    assert game.menu.page == "complete" and game.quantum_run is None
    assert not story.is_escape(game)
    assert "quantum_run" not in [button[0] for button in game.menu.buttons()]
    game.menu.draw()
    game.menu.activate("retry_run")
    assert game.current_level == -1 and game.tutorial.active


def test_tutorial_popup_pauses_solver_and_correlations_without_freezing_landing(game, monkeypatch):
    game.start_tutorial()
    dismiss(game)
    move(game, pygame.K_d)
    assert game.tutorial.active
    game.settings["stuck_warning"] = True
    monkeypatch.setattr(game, "update_stuck", lambda _: pytest.fail("Solver ran behind a tutorial popup"))
    before = game.correlation_elapsed
    game.run_frame()
    assert game.correlation_elapsed == before


def test_restarting_or_leaving_tutorial_clears_pending_exit_and_restores_normal_play(game):
    game.start_tutorial()
    game.pending_advance = True
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "paused" and game.tutorial.active
    game.restart_level()
    assert game.current_level == -1 and not game.pending_advance and game.tutorial.active
    game.start_level(1, "full")
    assert not game.tutorial.active and not game.pending_advance
    assert game.run_mode == "full"
    game.menu.activate("help")
    game.menu.draw()
    game.start_seed_level(_custom_code())
    assert not game.tutorial.active and game.current_level == 0


def _custom_code():
    from scripts.level_share import encode_level
    return encode_level({
        "editor_created": True, "tiles": {"(1,1)": "START", "(2,1)": "END"},
        "objects": {}, "quantum_objects": [], "pillar_states": {}, "gates": {}, "effects": [],
    })


@pytest.mark.parametrize("step", [0, 1])
def test_tutorial_popup_keeps_all_text_board_and_gate_controls_separate(game, monkeypatch, step):
    game.start_tutorial(step)
    game.bloch.enabled = True
    assert not game.bloch.visible()
    game.display_game()
    box = pygame.Rect(60, 336, 680, 108)
    for sprite in list(game.tile_sprites) + list(game.object_sprites) + [game.player]:
        assert not sprite.rect.colliderect(box)
    assert all(not rect.colliderect(box) for rect in game.hotbar.selection_rects.values())
    for entry in game.tutorial.steps:
        rendered = []
        def text(value, x, y, size=24, color=None, center=False):
            rect = font(size).render(value, True, (255, 255, 255)).get_rect(topleft=(x, y))
            assert box.contains(rect), (value, rect)
            rendered.append(rect)
        monkeypatch.setattr(game.menu, "text", text)
        game.menu.draw_tutorial_popup(entry["text"])
        assert not any(first.colliderect(second) for i, first in enumerate(rendered)
                       for second in rendered[i+1:])
    dismiss(game)
    assert game.bloch.visible()


def test_help_and_tutorial_are_both_accessible_and_play_buttons_do_not_overlap(game):
    assert "help" in [button[0] for button in game.menu.buttons()]
    game.menu.activate("play")
    buttons = game.menu.buttons()
    assert {"normal_levels", "custom_seed", "tutorial", "back"} <= {b[0] for b in buttons}
    assert all(rect.bottom + 4 < 552 for _, rect, *_ in buttons)
    assert not any(a[1].colliderect(b[1]) for i, a in enumerate(buttons) for b in buttons[i+1:])


@pytest.mark.parametrize("entry", [None, 4, [], {}, {"trigger": [], "text": "text"},
    {"trigger": "on_start", "text": 3}, {"trigger": "on_start", "text": ""},
    {"trigger": "on_pickup", "item": [], "text": "text"},
    {"trigger": "on_enter", "position": "bad", "text": "text"}])
def test_bad_tutorial_data_raises_level_error_before_changing_existing_level(game, entry):
    game.start_level(1)
    circuit = game.quantum_grid.circuit.copy()
    data = json.loads(Path("levels/1.json").read_text())
    data["tutorial"] = [entry]
    with pytest.raises(LevelError):
        game.load_level_data(data)
    assert game.current_level == 1 and game.quantum_grid.circuit == circuit
