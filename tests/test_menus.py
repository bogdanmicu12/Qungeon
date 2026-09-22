"""Exercise actual menu input and gameplay transitions with an SDL dummy display."""

import asyncio
import json
import os
import pathlib
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game, STUCK_DELAY_MS
from scripts import level_solver, menus


@pytest.fixture
def game():
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    # A game sitting on the main menu with level 1 already loaded. Loading is
    # lazy now (see test_the_menu_runs_before_the_quantum_stack_is_ready), and
    # these tests are about the menu, not about that.
    game.start_level(1, "full")
    game.menu.open("main")
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
    assert (game.current_level, game.menu.page) == (1, "complete")
    assert game.quantum_run.circuit["level"] == 1
    click(game, "next_level")
    assert (game.current_level, game.menu.page) == (2, "playing")
    game.start_level(game.available_levels[-1], "full")
    game.advance_level()
    assert game.menu.page == "complete"
    assert game.running


def test_full_run_settings_reveal_auto_queue_and_save_both_preferences(game):
    saved = []
    game.persist_settings = lambda settings: saved.append(dict(settings))
    click(game, "setup")
    assert "toggle:auto_quantum_runs" not in [b[0] for b in game.menu.buttons()]
    click(game, "toggle:full_run_completion")
    assert game.settings["full_run_completion"] is False
    click(game, "toggle:auto_quantum_runs")
    assert saved[-1]["auto_quantum_runs"] is True
    rects = [rect for _, rect, *_ in game.menu.buttons()]
    assert all(pygame.Rect(0, 0, 800, 552).contains(rect) for rect in rects)
    assert not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i+1:])
    game.menu.draw()
    click(game, "toggle:full_run_completion")
    assert "toggle:auto_quantum_runs" not in [b[0] for b in game.menu.buttons()]
    assert saved[-1]["full_run_completion"] is True


def test_skipping_completion_advances_without_hardware_and_keeps_final_summary(game, monkeypatch):
    from scripts.quantum_run import QuantumRun
    monkeypatch.setattr(QuantumRun, "command", lambda *args: pytest.fail("Automatic hardware runs are off"))
    game.settings["full_run_completion"] = False
    game.start_level(1, "full")
    game.advance_level()
    assert (game.current_level, game.menu.page) == (2, "playing")
    game.start_level(game.available_levels[-1], "full")
    game.advance_level()
    assert game.menu.page == "complete"
    assert not game.background_quantum_runs


@pytest.mark.parametrize("mode,show", [("single", False), ("single", True), ("full", True)])
def test_auto_queue_setting_only_applies_to_full_runs_with_skipped_screens(game, monkeypatch, mode, show):
    from scripts.quantum_run import QuantumRun
    monkeypatch.setattr(QuantumRun, "command", lambda *args: pytest.fail("No automatic request should be sent"))
    game.settings.update(full_run_completion=show, auto_quantum_runs=True)
    game.start_level(1, mode)
    game.advance_level()
    assert (game.current_level, game.menu.page) == (1, "complete")


def test_auto_queue_captures_each_level_before_advancing_and_processes_in_background(game, monkeypatch):
    from scripts.quantum_run import QuantumRun
    requests = []
    def command(run, action):
        requests.append((run, action))
        run.busy = True
    monkeypatch.setattr(QuantumRun, "command", command)
    game.settings.update(full_run_completion=False, auto_quantum_runs=True)
    game.start_level(1, "full")
    game.advance_level()
    first = requests[0][0]
    assert requests[0][1] == "enqueue" and first.circuit["level"] == 1
    assert first.circuit["labels"] == ["5,4"]
    assert game.current_level == 2 and game.quantum_run is None
    game.advance_level()
    assert requests[1][0].circuit["level"] == 2
    assert len(game.background_quantum_runs) == 2
    # A response arriving after the next level loads is still processed.
    first._reply = {"state": "queued"}
    game.menu.open("paused")
    game.run_frame()
    assert first.data["state"] == "queued" and not first.busy
    first._reply = {"state": "done"}
    game.run_frame()
    assert first not in game.background_quantum_runs
    game.start_level(game.available_levels[-1], "full")
    game.advance_level()
    assert requests[-1][0].circuit["level"] == game.available_levels[-1]
    assert game.menu.page == "complete"


def test_skip_screen_survives_a_broken_next_level(game, monkeypatch):
    from scripts.level_validation import LevelError
    game.start_level(1, "full")
    game.settings["full_run_completion"] = False
    def broken(*args):
        raise LevelError("Broken next level")
    monkeypatch.setattr(game, "load_level", broken)
    game.advance_level()
    assert game.current_level == 1 and game.menu.page == "complete"
    assert game.quantum_run.circuit["level"] == 1


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


def test_toggling_a_setting_does_not_leak_into_gameplay_and_guides_can_be_disabled(game, monkeypatch):
    click(game, "settings")
    click(game, "toggle:stuck_warning")
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


def test_a_broken_level_file_never_crashes_the_menu(game):
    """A malformed level must be survivable from every menu route into a level.

    Level select lists (and previews) whatever is in ./levels, so one bad file
    used to take the whole menu down: the preview, selecting it, and the
    restart button each raised out of the frame loop. The game should stay on
    its feet and simply refuse to load it.
    """
    broken = max(game.available_levels) + 1
    pathlib.Path(f"./levels/{broken}.json").write_text('{"tiles": {"(0, 0)": "START"}}')
    try:
        game.available_levels = game.available_levels + [broken]
        game.menu.open("levels")
        game.menu.draw()                       # previews every listed level

        click(game, f"level:{broken}")
        assert game.menu.page == "levels"       # refused, and still on the menu
        assert game.current_level == 1

        game.current_level = broken             # as if the file broke mid-run
        game.menu.open("paused")
        click(game, "retry")
        assert game.menu.page == "paused"
    finally:
        pathlib.Path(f"./levels/{broken}.json").unlink()


def test_direct_level_launch_preserves_shortcut():
    game = Game(SimpleNamespace(level=5, start_direct=True), settings={})
    # The shortcut queues behind the loading screen when the quantum stack has
    # not been imported yet, so drive frames rather than assume either state -
    # test_a_deep_link_waits_for_the_quantum_stack_too covers the wait itself.
    for _ in range(3):
        if game.menu.page == "playing":
            break
        game.run_frame()
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


# --------------------------------------------------------------------------
# Deferred quantum stack (web/main.py installs cirq after the menu is up)
# --------------------------------------------------------------------------

def test_the_menu_runs_before_the_quantum_stack_is_ready():
    """The browser shows the menu while cirq is still downloading.

    Nothing on the menu touches the quantum stack, so a game built while it is
    still installing must draw and take input; only entering a level waits.
    """
    downloaded = False
    game = Game(SimpleNamespace(level=1), settings={},
                persist_settings=lambda _: True, gameplay_downloaded=lambda: downloaded)

    assert (game.menu.page, game.hotbar, game.quantum_grid) == ("main", None, None)
    click(game, "setup")
    assert game.menu.page == "setup"

    click(game, "start")                   # held, not dropped, not crashed
    assert (game.menu.page, game.menu.pending) == ("loading", "start")
    game.run_frame()                       # loading screen stays up meanwhile
    assert game.menu.page == "loading"

    downloaded = True
    game.run_frame()
    assert (game.menu.page, game.menu.pending) == ("playing", None)
    assert (game.current_level, game.run_mode) == (1, "full")
    pygame.event.clear()


def test_the_loading_screen_is_on_screen_before_the_import_blocks(monkeypatch):
    """The import must never run in the frame that took the click.

    It blocks for seconds, so the frame loop has to get a chance to put the
    loading screen on the display - and yield to the browser - in between.
    Downloading is already finished here: being imported is its own condition.
    """
    import Qungeon
    monkeypatch.setattr(Qungeon, "Hotbar", None)     # as if never imported
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)

    click(game, "levels")
    click(game, "level:1")
    assert game.menu.page == "loading"
    assert game.menu.loading_drawn                   # the frame drew it, and
    assert Qungeon.Hotbar is None                    # did not import in it

    game.run_frame()
    assert (game.menu.page, Qungeon.Hotbar is None) == ("playing", False)
    pygame.event.clear()


def test_escape_leaves_the_loading_screen_when_the_stack_never_arrives():
    """A failed micropip install must not trap the player.

    gameplay_downloaded() then stays False forever, so the held choice is
    never released; the loading page has no buttons, which leaves Escape as
    the only way back to the menu.
    """
    game = Game(SimpleNamespace(level=1), settings={},
                persist_settings=lambda _: True, gameplay_downloaded=lambda: False)

    click(game, "levels")
    click(game, "level:1")
    assert game.menu.page == "loading"

    key(game, pygame.K_ESCAPE)
    assert (game.menu.page, game.menu.pending) == ("levels", None)
    game.run_frame()                       # and it does not resume by itself
    assert game.menu.page == "levels"
    pygame.event.clear()


def test_a_deep_link_waits_for_the_quantum_stack_too(monkeypatch):
    """?level=N must queue like a click instead of importing cirq at boot.

    It reaches activate() directly rather than through a frame of input, so
    it is the case where the import could most easily run before anything has
    been drawn - leaving the player on a blank canvas through the freeze.
    """
    import Qungeon
    monkeypatch.setattr(Qungeon, "Hotbar", None)     # as if never imported
    game = Game(SimpleNamespace(level=2, start_direct=True), settings={},
                persist_settings=lambda _: True)
    drawn = []
    monkeypatch.setattr(game.menu, "draw", lambda: drawn.append(game.menu.page))

    assert (game.menu.page, game.menu.pending) == ("loading", "level:2")

    game.run_frame()                                 # draws, does not import
    assert (drawn, Qungeon.Hotbar) == (["loading"], None)

    game.menu.loading_drawn = True                   # the stubbed draw cannot
    game.run_frame()
    assert (game.menu.page, game.current_level, game.run_mode) == ("playing", 2, "single")
    pygame.event.clear()


# --------------------------------------------------------------------------
# Unwinnable-level detection (scripts/level_solver.py wired into the loop)
# --------------------------------------------------------------------------

class Clock:
    """Deterministic stand-in for pygame.time.get_ticks."""

    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    ticks = Clock()
    monkeypatch.setattr(pygame.time, "get_ticks", ticks)
    return ticks


def play(game, clock, milliseconds, step=100):
    """Run the real game loop for `milliseconds` of in-game time."""
    for _ in range(milliseconds // step):
        clock.now += step
        game.run_frame()


def spend_gate(game, name, pillar):
    """Drop a hotbar gate onto a pillar the way a player does, via the loop."""
    game.hotbar.slots[name].dragging = True
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONUP, button=1, pos=game.objects[pillar].rect.center))
    game.run_frame()


def test_wasted_gate_prompts_but_not_immediately(game, clock):
    """Level 3's pillar is |->, where X is a no-op that burns the only X.

    The prompt has to wait: being told instantly is intrusive, and the player
    should get the chance to try the move that no longer works.
    """
    game.start_level(3)
    game.player.update_position(4, 4)          # step next to the pillar
    spend_gate(game, "X", "5,4")

    assert game.menu.page == "playing"
    assert "X" not in game.hotbar.slots        # the gate really was spent

    play(game, clock, STUCK_DELAY_MS - 100)
    assert game.menu.page == "playing", "prompted too early"

    play(game, clock, 200)
    assert game.menu.page == "failed"


def test_a_good_move_never_prompts(game, clock):
    """H is the right first move on level 3, so nothing should interrupt."""
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "H", "5,4")

    play(game, clock, 5000)
    assert game.menu.page == "playing"


def test_countdown_freezes_while_paused(game, clock):
    """Pausing must not run the clock out on a player who stepped away."""
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "X", "5,4")

    key(game, pygame.K_ESCAPE)
    play(game, clock, 5000)
    assert game.menu.page == "paused"

    click(game, "resume")
    play(game, clock, STUCK_DELAY_MS + 200)
    assert game.menu.page == "failed"


def test_loot_pickup_is_checked_only_once_the_hop_lands(game, clock):
    """Mid-hop the player's position is fractional and describes no tile.

    Level 5 stays winnable after taking this box, so a check taken mid-jump -
    which would find no reachable END at all - must not happen.
    """
    game.start_level(5)
    game.player.update_position(7, 3)
    game.update_position(pygame.K_d)           # walk into the loot box at (8,3)
    assert game.hop is not None

    play(game, clock, 3000, step=50)           # small steps: frames land mid-hop
    assert game.menu.page == "playing"
    assert game.hotbar.slots["H"].count == 3


def test_solver_runs_only_when_something_was_spent(game, clock, monkeypatch):
    """No polling: the check is driven by consumption, not by a timer."""
    calls = []
    real_solve = level_solver.solve
    monkeypatch.setattr(
        level_solver, "solve", lambda *args, **kw: calls.append(1) or real_solve(*args, **kw))

    game.start_level(3)
    play(game, clock, 3000)
    assert calls == [], "solver ran while nothing was spent"

    game.player.update_position(4, 4)
    spend_gate(game, "H", "5,4")
    assert len(calls) == 1

    play(game, clock, 3000)
    assert len(calls) == 1


def test_failed_screen_offers_restart_settings_and_menu(game):
    """The prompt's three ways out, and Settings returning to the prompt."""
    game.start_level(3)
    game.show_failed()
    assert [button[0] for button in game.menu.buttons()] == ["retry", "settings", "main"]

    click(game, "settings")
    assert game.menu.page == "settings"
    click(game, "toggle:entanglement_guides")
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "failed", "Settings should come back to the prompt"

    click(game, "main")
    assert game.menu.page == "main"


def test_restarting_from_the_prompt_clears_the_countdown(game, clock):
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "X", "5,4")
    play(game, clock, STUCK_DELAY_MS + 200)
    assert game.menu.page == "failed"

    click(game, "retry")
    assert game.menu.page == "playing"
    assert game.hotbar.slots["X"].count == 1
    assert game.stuck_elapsed is None
    play(game, clock, 5000)
    assert game.menu.page == "playing"


def test_stuck_detection_is_on_by_default(game):
    assert game.settings["stuck_warning"] is True
    assert menus.DEFAULT_SETTINGS["stuck_warning"] is True


def test_stuck_detection_can_be_turned_off(game, clock, monkeypatch):
    """With the setting off, a lost level never prompts - and never searches."""
    calls = []
    real_solve = level_solver.solve
    monkeypatch.setattr(
        level_solver, "solve", lambda *args, **kw: calls.append(1) or real_solve(*args, **kw))

    game.settings["stuck_warning"] = False
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "X", "5,4")               # the move that loses the level

    play(game, clock, STUCK_DELAY_MS + 2000)
    assert game.menu.page == "playing"
    assert calls == [], "solver ran while stuck detection was off"


def test_turning_stuck_detection_back_on_rechecks(game, clock):
    """Re-enabling mid-level must notice a level that was lost while it was off."""
    game.settings["stuck_warning"] = False
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "X", "5,4")
    play(game, clock, STUCK_DELAY_MS + 200)
    assert game.menu.page == "playing"

    game.settings["stuck_warning"] = True
    play(game, clock, STUCK_DELAY_MS + 200)
    assert game.menu.page == "failed"


def test_turning_stuck_detection_off_cancels_a_pending_prompt(game, clock):
    game.start_level(3)
    game.player.update_position(4, 4)
    spend_gate(game, "X", "5,4")
    play(game, clock, 500)
    assert game.stuck_elapsed is not None       # counting down

    game.settings["stuck_warning"] = False
    play(game, clock, STUCK_DELAY_MS + 500)
    assert game.menu.page == "playing"
    assert game.stuck_elapsed is None


def test_setting_is_reachable_from_the_prompt_itself(game):
    """The Settings button on the prompt is how a player turns this off."""
    game.start_level(3)
    game.show_failed()
    click(game, "settings")
    assert any(action == "toggle:stuck_warning" for action, _, _, _ in game.menu.buttons())
    click(game, "toggle:stuck_warning")
    assert game.settings["stuck_warning"] is False
    key(game, pygame.K_ESCAPE)
    assert game.menu.page == "failed"
