"""PyScript entry point for the static browser build."""

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

from pyscript import document, window


def requested_level() -> int:
    query = parse_qs(str(window.location.search).lstrip("?"))
    value = query.get("level", ["1"])[0]
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid level: {value}") from exc


def show_game() -> None:
    document.getElementById("loading").hidden = True
    shell = document.getElementById("game-shell")
    shell.setAttribute("aria-busy", "false")
    document.getElementById("canvas").focus()


def show_error(error: Exception, what: str = "start") -> None:
    document.getElementById("loading").hidden = True
    message = document.getElementById("error")
    message.textContent = f"Qungeon could not {what}: {error}"
    message.hidden = False
    document.getElementById("game-shell").setAttribute("aria-busy", "false")


def browser_settings():
    from scripts.menus import normalize_settings
    try:
        return normalize_settings(json.loads(str(window.localStorage.getItem("qungeon.settings"))))
    except Exception:
        return normalize_settings(None)


def save_browser_settings(settings):
    try:
        window.localStorage.setItem("qungeon.settings", json.dumps(settings))
        return True
    except Exception:
        # Private browsing or storage policies can block localStorage.
        return False


def consume_pause_request():
    requested = bool(window.qungeonPauseRequested)
    window.qungeonPauseRequested = False
    return requested


def update_page(page):
    document.getElementById("game-shell").classList.toggle(
        "dimmed", page in ("paused", "failed", "complete")
    )


async def download_gameplay() -> None:
    """Fetch the quantum stack after the menu is already on screen.

    cirq and its dependencies are ~37 MB - by far the largest part of the
    boot - and nothing before the player picks a level touches them, so this
    runs in the background instead of through pyscript.json's `packages`.

    It deliberately stops at downloading. Importing cirq blocks the main
    thread for several seconds, which would freeze the menu mid-browse; the
    menu does it behind its own loading screen when a level is chosen.
    """
    import micropip

    try:
        await micropip.install("cirq-core==1.7.0")
    except Exception as error:
        # The menu keeps running, so say why levels never become playable.
        show_error(error, "load levels")
        raise


async def main() -> None:
    try:
        from Qungeon import Game

        level = requested_level()
        query = parse_qs(str(window.location.search).lstrip("?"))
        downloaded = asyncio.create_task(download_gameplay())
        game = Game(
            SimpleNamespace(level=level, start_direct="level" in query),
            settings=browser_settings(),
            persist_settings=save_browser_settings,
            gameplay_downloaded=lambda: downloaded.done() and downloaded.exception() is None,
        )
        show_game()
        await game.run_browser(should_pause=consume_pause_request, on_page_change=update_page)
    except Exception as error:
        show_error(error)
        raise


asyncio.create_task(main())
