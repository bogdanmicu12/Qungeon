"""Tutorial system: contextual text popups fired during tutorial levels.

A tutorial level is an ordinary level JSON file with one extra key,
"tutorial": a list of steps. Each step fires once, the first time its
trigger condition is met, and its text is queued for display. Rendering the
popup box itself lives in menus.py (draw_tutorial_popup) so it can share the
existing panel/text styling; this module only tracks *when* a step should
fire.

Step shape:
    {"trigger": "on_start", "text": "..."}
    {"trigger": "on_enter", "position": "(5,4)", "text": "..."}
    {"trigger": "on_pickup", "item": "X", "text": "..."}
    {"trigger": "on_apply", "position": "(5,4)", "text": "..."}
    {"trigger": "on_win", "text": "..."}
"""

from scripts.level_validation import parse_pos, LevelError

VALID_TRIGGERS = {"on_start", "on_enter", "on_pickup", "on_apply", "on_win"}


def validate_tutorial(tutorial_data, filename):
    """Validate the optional "tutorial" list of a level file.

    Call this from level_validation.validate_level() alongside its other
    checks, e.g.:
        validate_tutorial(level_data.get("tutorial"), filename)
    """
    if tutorial_data is None:
        return
    if not isinstance(tutorial_data, list):
        raise LevelError(f"{filename}: 'tutorial' must be a list")
    for entry in tutorial_data:
        if "trigger" not in entry or "text" not in entry:
            raise LevelError(f"{filename}: tutorial entry missing 'trigger'/'text': {entry}")
        trigger = entry["trigger"]
        if trigger not in VALID_TRIGGERS:
            raise LevelError(f"{filename}: unknown tutorial trigger {trigger!r}")
        if trigger in ("on_enter", "on_apply") and "position" not in entry:
            raise LevelError(f"{filename}: {trigger} tutorial step needs 'position'")
        if trigger == "on_pickup" and "item" not in entry:
            raise LevelError(f"{filename}: on_pickup tutorial step needs 'item'")
        if "position" in entry:
            parse_pos(entry["position"])


class TutorialController:
    """Tracks a level's tutorial popups and which have already fired.

    Keep one instance on Game for the whole session and call load() every
    time a level (tutorial or not) is started or restarted. On a level with
    no "tutorial" key this is simply always inactive, so it's safe to call
    the on_*() hooks unconditionally from normal gameplay code.
    """

    def __init__(self):
        self.steps = []
        self.fired = set()
        self.queue = []
        self.current = None

    @property
    def active(self):
        """True while a popup is on screen and should be blocking input."""
        return self.current is not None

    def load(self, level_data):
        """Reset state for a newly (re)started level and fire any on_start step."""
        self.steps = level_data.get("tutorial", [])
        self.fired = set()
        self.queue = []
        self.current = None
        self._check("on_start")

    def _check(self, trigger, **kwargs):
        for index, step in enumerate(self.steps):
            if index in self.fired or step["trigger"] != trigger:
                continue
            if trigger == "on_enter" and parse_pos(step["position"]) != kwargs.get("pos"):
                continue
            if trigger == "on_apply" and parse_pos(step["position"]) != kwargs.get("pos"):
                continue
            if trigger == "on_pickup" and step["item"] != kwargs.get("item"):
                continue
            self.fired.add(index)
            self.queue.append(step["text"])
        if self.current is None and self.queue:
            self.current = self.queue.pop(0)

    # --- call these from gameplay code, see integration notes ---

    def on_enter(self, pos):
        """Call right after the player's grid position updates."""
        self._check("on_enter", pos=pos)

    def on_pickup(self, item):
        """Call when a gate is looted into the hotbar (LootableObject.function)."""
        self._check("on_pickup", item=item)

    def on_apply(self, pos):
        """Call after a quantum effect is applied to the pillar at pos
        (end of QuantumObject.apply_effect)."""
        self._check("on_apply", pos=pos)

    def on_win(self):
        """Call when the player reaches the END tile."""
        self._check("on_win")

    def dismiss(self):
        """Advance to the next queued popup, if any. Bind this to the
        dismiss key/click while self.active is True."""
        self.current = self.queue.pop(0) if self.queue else None