"""Headless editor validation, also used by the browser's Python worker."""

import json
from pathlib import Path


def check_level(data, budget=None):
    from scripts.level_validation import validate_level, LevelError

    try:
        validate_level(data, "Editor level")
    except LevelError as error:
        return {"solvable": False, "message": str(error)}

    from scripts.level_solver import solve_level_data, DEFAULT_BUDGET

    solution = solve_level_data(data, DEFAULT_BUDGET if budget is None else budget)
    message = {
        True: "Level is valid",
        False: "Level is not valid yet: no path to the exit. Keep editing.",
        None: "Could not confirm validity within the search limit. Simplify the level and try again.",
    }[solution.solvable]
    return {"solvable": solution.solvable, "message": message}


if __name__ == "__main__":
    import sys

    try:
        result = check_level(json.loads(Path(sys.argv[1]).read_text()))
    except Exception as error:
        result = {"solvable": None, "message": f"Level check failed: {error}"}
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
