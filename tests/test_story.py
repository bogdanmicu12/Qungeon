"""Story remains presentation-only and fits the game's existing screens."""

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game
from scripts import story
from scripts.common_functions import font
from scripts.quantum_run import capture_circuit


@pytest.fixture
def game():
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    pygame.event.clear()
    yield game
    pygame.event.clear()


def record_text(monkeypatch, menu):
    rendered = []
    original = menu.text

    def text(value, *args, **kwargs):
        rendered.append(str(value))
        return original(value, *args, **kwargs)

    monkeypatch.setattr(menu, "text", text)
    return rendered


def test_help_works_before_gameplay_loads_and_uses_context_only_from_pause(game, monkeypatch):
    rendered = record_text(monkeypatch, game.menu)
    game.menu.activate("help")
    game.menu.draw()
    assert game.hotbar is None and game.quantum_grid is None
    assert "The way out" in rendered
    game.menu.back()
    assert game.menu.page == "main"

    game.start_level(8)
    game.menu.open("paused")
    game.menu.activate("help")
    rendered.clear()
    game.menu.draw()
    assert story.ROOMS[8].title in rendered
    assert any("entangled" in text for text in rendered)
    game.menu.back()
    assert game.menu.page == "paused"
    game.return_to_menu()
    game.menu.activate("help")
    rendered.clear()
    game.menu.draw()
    assert "The way out" in rendered
    assert story.ROOMS[8].title not in rendered


def test_notice_temporarily_replaces_learning_line(game, monkeypatch):
    game.start_level(1)
    rendered = record_text(monkeypatch, game.menu)
    game.show_quantum_notice("Hardware run queued.")
    game.menu.draw_hud()
    assert "Hardware run queued." in rendered
    assert story.ROOMS[1].learning_line not in rendered
    game.quantum_notice_until = 0
    rendered.clear()
    game.menu.draw_hud()
    assert story.ROOMS[1].learning_line in rendered
    assert "Hardware run queued." not in rendered


@pytest.mark.parametrize("level", sorted(story.ROOMS))
def test_story_rendering_preserves_puzzle_and_fits_existing_panels(game, level):
    game.start_level(level, "full")
    circuit = capture_circuit(game)
    resources = game.resource_signature()
    inventory = {key: slot.count for key, slot in game.hotbar.slots.items()}
    room = story.ROOMS[level]
    game.display_game()
    assert capture_circuit(game) == circuit
    assert game.resource_signature() == resources
    assert {key: slot.count for key, slot in game.hotbar.slots.items()} == inventory
    assert font(19).size(room.learning_line)[0] <= 720
    assert 79 + font(19).get_height() <= 96  # earliest wall row
    assert font(22).size(f"{level:02}  /  {room.title}")[0] <= 400
    assert game.menu.paragraph(room.help_note, 62, 427, 676, size=20) <= 491
    assert game.menu.paragraph(room.completion_line, 170, 263, 460, size=23) <= 320
    assert game.menu.paragraph(story.ENDING, 170, 263, 460, size=23) <= 320
    game.menu.open("complete")
    game.menu.draw()
    assert capture_circuit(game) == circuit


@pytest.mark.parametrize("show_completion", [False, True])
def test_escape_uses_existing_final_summary_and_does_not_appear_in_practice(game, monkeypatch, show_completion):
    game.settings["full_run_completion"] = show_completion
    game.start_level(9, "full")
    game.advance_level()
    rendered = record_text(monkeypatch, game.menu)
    game.menu.draw()
    assert game.menu.page == "complete"
    assert "You escaped" in rendered
    assert len(game.menu.buttons()) == 3
    game.start_level(9, "single")
    game.advance_level()
    rendered.clear()
    game.menu.draw()
    assert "Level complete" in rendered and "You escaped" not in rendered


def test_missing_story_is_playable_and_edited_walls_are_not_required(game, monkeypatch):
    game.start_level(1)
    # Decorations must also tolerate a map edited independently of the story.
    game.tiles.pop((6, 3))
    game.display_game()
    monkeypatch.delitem(story.ROOMS, 1)
    rendered = record_text(monkeypatch, game.menu)
    game.display_game()
    assert "LEVEL 01" in rendered
    game.restart_level()
    assert game.menu.page == "playing"
    game.advance_level()
    game.menu.draw()
    assert "Level complete" in rendered
