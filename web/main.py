"""PyScript entry point for the static browser build."""

import asyncio
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


def show_error(error: Exception) -> None:
    document.getElementById("loading").hidden = True
    message = document.getElementById("error")
    message.textContent = f"Qungeon could not start: {error}"
    message.hidden = False


async def main() -> None:
    try:
        from Qungeon import Game

        level = requested_level()
        game = Game(SimpleNamespace(level=level))
        show_game()
        await game.run_browser()
    except Exception as error:
        show_error(error)
        raise


asyncio.create_task(main())
