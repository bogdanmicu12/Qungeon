"""Exercise actual menu input and gameplay transitions with an SDL dummy display."""

import asyncio
import json
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game
from scripts import menus


@pytest.fixture
def game():
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    pygame.event.clear()
    yield game
    pygame.event.clear()


def key(game, value):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value, mod=0))
    game.run_frame()


def click(game, action):
    rect = next(rect for name, rect, _, _ in game.menu.buttons() if name == action)
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        pygame.event.post(pygame.event.Event(kind, button=1, pos=rect.center))
    game.run_frame()


def test_start_requires_setup_and_full_run_advances(game):
    assert game.menu.page == "main"
    click(game, "setup")
    assert game.menu.page == "setup"
    click(game, "start")
    assert (game.menu.page, game.current_level, game.run_mode) == ("playing", 1, "full")
    game.advance_level()
    assert (game.current_level, game.menu.page) == (2, "playing")
    game.start_level(game.available_levels[-1], "full")
    game.advance_level()
    assert game.menu.page == "complete"
    assert game.running


@pytest.mark.parametrize("level", range(1, 9))
def test_level_selection_loads_and_finishes_only_that_level(game, level):
    click(game, "levels")
    click(game, f"level:{level}")
    assert (game.current_level, game.run_mode) == (level, "single")
    rects = [slot.rect for slot in game.hotbar.slots.values()]
    assert rects[0].unionall(rects[1:]).centerx == 400
    game.advance_level()
    assert game.menu.page == "complete"
    click(game, "main")
    assert game.menu.page == "main"


def test_pause_freezes_hop_correlations_and_input(game, monkeypatch):
    game.start_level(1)
    game.hop_animation((3, 4), (4, 4))
    game.update_hop(35)
    key(game, pygame.K_ESCAPE)
    before = (game.player.position, dict(game.hop), game.grouping_system.count, game.correlation_elapsed)
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 100000)
    for value in (pygame.K_d, pygame.K_r, pygame.K_q):
        key(game, value)
    assert game.menu.page == "paused"
    assert (game.player.position, game.hop, game.grouping_system.count, game.correlation_elapsed) == before
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "playing"
    assert game.player.position == before[0]
    game.update_hop(100)
    assert game.player.position == (4, 4)


def test_pause_cancels_gate_drag_without_spending_it(game):
    game.start_level(1)
    slot = game.hotbar.slots["X"]
    slot.dragging = True
    slot.rect.topleft = (311, 220)
    key(game, pygame.K_ESCAPE)
    assert not slot.dragging
    assert slot.count == 1
    assert slot.rect.topleft == (game.hotbar.rect.x, game.hotbar.rect.y)


def test_pause_cancels_control_drag_without_spending_gate(game):
    game.start_level(8)
    pillar = game.objects["4,3"]
    original = pillar.rect.topleft
    pillar.origin_x, pillar.origin_y = original
    pillar.dragging = True
    pillar.control = "CNOT"
    pillar.rect.topleft = (311, 220)
    key(game, pygame.K_ESCAPE)
    assert pillar.rect.topleft == original
    assert not pillar.dragging and pillar.control is None
    assert game.hotbar.slots["CNOT"].count == 2


def test_help_returns_to_pause_and_does_not_resume(game):
    game.start_level(1)
    key(game, pygame.K_ESCAPE)
    click(game, "help")
    assert game.menu.page == "help"
    assert [button[0] for button in game.menu.buttons()] == ["back"]
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "paused"
    click(game, "resume")
    assert game.menu.page == "playing"


def test_restart_restores_level_inventory_position_and_animation(game):
    game.start_level(1, "full")
    game.hotbar.remove_by_key("X")
    game.player.update_position(4, 4)
    key(game, pygame.K_ESCAPE)
    click(game, "retry")
    assert game.menu.page == "playing"
    assert game.run_mode == "full"
    assert game.player.position == (3, 4)
    assert game.hotbar.slots["X"].count == 1
    assert game.hop is None


def test_failed_screen_is_explicit_and_retry_works(game):
    game.start_level(1)
    game.hotbar.remove_by_key("X")
    game.run_frame()
    assert game.menu.page == "playing"
    game.show_failed()
    game.run_frame()
    assert game.menu.page == "failed"
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "failed"
    click(game, "retry")
    assert game.menu.page == "playing"
    assert game.hotbar.slots["X"].count == 1
    game.show_failed()
    click(game, "main")
    assert game.menu.page == "main"


def test_decoherence_is_saved_without_changing_quantum_state(game):
    saved = []
    game.persist_settings = lambda settings: saved.append(dict(settings))
    before = game.quantum_grid.circuit.copy()
    click(game, "settings")
    click(game, "toggle:decoherence")
    assert saved[-1]["decoherence"] is True
    assert game.quantum_grid.circuit == before
    key(game, pygame.K_ESCAPE)
    click(game, "setup")
    assert game.settings["decoherence"] is True


def test_settings_round_trip_and_corrupt_file_fallback(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(menus, "SETTINGS_PATH", path)
    settings = {**menus.DEFAULT_SETTINGS, "decoherence": True}
    assert menus.save_settings(settings)
    assert menus.load_settings() == settings
    path.write_text("broken", encoding="utf-8")
    assert menus.load_settings() == menus.DEFAULT_SETTINGS
    path.write_text(json.dumps({"decoherence": "false", "entanglement_guides": False, "reduced_motion": True}), encoding="utf-8")
    assert menus.load_settings() == {**menus.DEFAULT_SETTINGS, "entanglement_guides": False}


def test_keyboard_navigation_and_click_release_do_not_leak_into_game(game):
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN)
    assert game.menu.page == "levels"
    key(game, pygame.K_RETURN)
    assert game.menu.page == "playing"
    assert game.player.position == (3, 4)
    assert game.hotbar.slots["X"].count == 1


def test_focus_loss_pauses_game(game):
    game.start_level(1)
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    game.run_frame()
    assert game.menu.page == "paused"


def test_placeholder_has_no_effect_and_guides_can_be_disabled(game, monkeypatch):
    click(game, "settings")
    click(game, "toggle:placeholder")
    game.start_level(1)
    game.update_position(pygame.K_d)
    assert game.player.position == (3, 4)
    assert game.hop is not None
    game.settings["entanglement_guides"] = False
    monkeypatch.setattr(game, "entanglement_visuals", lambda: pytest.fail("Guides are disabled"))
    game.display_game()


def test_hotbar_recenters_after_pickup_use_and_cancelled_drop(game):
    game.start_level(1)
    bar = game.hotbar
    bar.add_item("H", 2)
    bar.add_item("Z", 1)
    bar.remove_by_key("X")
    rects = [slot.rect for slot in bar.slots.values()]
    assert rects[0].unionall(rects[1:]).centerx == 400
    slot = bar.slots["H"]
    slot.dragging = True
    slot.rect.topleft = (10, 10)
    bar.handle_mouse_up(game, pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(10, 10), button=1))
    assert slot.count == 2
    assert slot.rect.topleft == bar.rect.topleft
    bar.remove_by_key("Z")
    assert slot.rect.centerx == 400


def test_direct_level_launch_preserves_shortcut():
    game = Game(SimpleNamespace(level=5, start_direct=True), settings={})
    assert (game.menu.page, game.run_mode, game.current_level) == ("playing", "single", 5)


def test_browser_reports_page_changes_without_repeating_each_frame(game, monkeypatch):
    pages = iter(("playing", "paused", "paused", "help", "paused", "playing"))
    reported = []

    def frame():
        page = next(pages, None)
        if page is None:
            game.running = False
        else:
            game.menu.open(page)

    monkeypatch.setattr(game, "run_frame", frame)
    asyncio.run(game.run_browser(on_page_change=reported.append))
    assert reported == ["playing", "paused", "help", "paused", "playing"]
