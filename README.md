# Quantum puzzle game (Qungeon)
Simple puzzle game, reach the end to complete a level. This can be done by using gates in your toolbar ("bag") to manipulating the quantum state of pillars.
The player has to be next to an object to interact with it!

![The player next to a loot box and a pillar in state |1>](assets/screenshot.png)

# Unitary Libary
The game was made using the Unitary library, which handles most of the quantum logic. More information can be found at:
https://github.com/quantumlib/unitary

Game examples can be found on this page and explanation on how to make use of the library.

# Play in the browser

The browser loads the original Python game code, assets, and levels directly.
Only the small browser adapter and the required Unitary Alpha modules live in
`web/`. There is no application backend, database, login, or save service.

Serve it locally from the repository root:

```bash
py -3.13 -m http.server 8000
```

Open <http://localhost:8000> to see the main menu. To jump directly into a
single level, use a URL such as <http://localhost:8000/?level=5>.

For production, serve the repository root from any HTTPS static-file host with
`index.html` as the entry point. No build step or server-side Python process is
required.

# Desktop development

## 1. Install

Requires Python 3.10-3.13. On Windows, Python 3.13 is recommended; Python
3.14 is currently too new for some of the game's scientific dependencies.

```bash
py -3.13 -m venv QungeonEnv313           # create the environment
source QungeonEnv313/Scripts/activate    # activate it in Git Bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

## 2. Launch

Run from the repo root - all asset and level paths are relative.

```bash
source QungeonEnv313/Scripts/activate
python Qungeon.py        # open the main menu
python Qungeon.py 5      # jump directly into level 5
```

An invalid or nonexistent level number exits with an error message instead of starting.

# Menus and settings

Both versions use the same Pygame menus and original pixel-art assets. No new
graphics dependency or build step is required.
UI text uses a bundled ASCII subset of DejaVu Sans; its license is in
`assets/DejaVu-LICENSE.txt`.

- **Start run** opens run settings first, then plays every level in order.
- **Level select** opens any of the eight available puzzles as a single level.
- **Settings** saves preferences automatically: in `.qungeon-settings.json` on
  desktop, or browser local storage. Preferences are separate between versions.
- **Decoherence time mode** is a saved preference only, marked coming soon;
  it does not add a timer or change quantum states yet.
- **Entanglement guides** toggles the connections shown on pillar hover.
- **Stuck detection** (on by default) offers a restart once the level can no
  longer be completed. Turning it off stops the prompt and the solver behind
  it; see the level solver section below. It replaces the old Placeholder
  slot, so a saved preference file from before simply falls back to the
  default.
- **How to play** opens an intentionally blank page with a Back button.

Use the mouse, arrow keys / WASD, or Tab / Shift+Tab to navigate menus; Enter
or Space selects. Escape goes back. During play, Escape (or the Pause button)
freezes gameplay, including movement and correlation animations. Resume,
restart the current level, return to the menu, or open How to Play from there.
Changing tabs or losing window focus also pauses the game.

Completing a single level or the final level opens a completion screen instead
of closing the game. The failure screen is driven by the level solver below: it
appears when the level can no longer be completed. Restart level restores the
level and its inventory, Settings opens the settings page and comes back to the
prompt, and Return to menu opens the main menu.

# Level solver

Gates are consumed when used, so spending the wrong one can leave a level with
no way to reach the END tile. `scripts/level_solver.py` answers, for any
mid-play state, whether the level can still be won.

```python
from scripts import level_solver

level_solver.is_solvable(game)          # True / False / None
level_solver.solve(level_solver.snapshot(game)).plan   # a winning action list
```

`None` means the search hit its node budget, not that the level is lost -
callers must treat it as "assume winnable" rather than telling a player to
restart. `Solution.is_stuck` encodes that rule.

The search is exhaustive: gates are consumed on use, so the number of actions
left in a level is finite. Movement is not searched over - it is folded into
the set of tiles the player can reach - and the quantum state is kept as one
small vector per entangled group of pillars rather than one vector over all of
them, which is what keeps level 6 (15 pillars) in the low hundreds of
milliseconds.

Gate matrices are derived from the game's own `gates` table, so a new
single-qubit gate needs no solver change. A new *controlled* gate must also be
added to `level_solver.CONTROL_EFFECTS`; `tests/test_solver.py` fails until it
is.

## When it runs

A level can only become unwinnable when something is consumed - a gate is spent
or a loot box is taken - so `Game.update_stuck` compares
`Game.resource_signature()` once per frame and runs the solver only when it
changes. There is no timer and no polling: an ordinary frame costs nothing, and
new ways to spend a resource are covered without adding another call site. The
check is skipped mid-hop, because the player's position is fractional while
they are jumping and describes no tile; it happens on the frame the hop lands.

All of this is behind the **Stuck detection** setting, on by default. With it
off, `update_stuck` returns before running anything, so a player who would
rather work it out alone pays nothing for the feature. The failure screen's own
Settings button leads straight to the toggle, and re-enabling it re-checks a
level that was played on while it was off.

Once the level is proven lost, the failure screen waits `STUCK_DELAY_MS`
(1.8 s of play) before appearing. Prompting the instant a bad move lands is
intrusive and takes away the chance to work it out; this leaves room to try the
move that no longer works and feel the wall first. The countdown runs only
while playing, so pausing freezes it, and restarting the level clears it.

The solver is not run when a level loads. A level that is unwinnable from its
first frame is a design bug, and catching those belongs to the level designer.

Run the tests with the project environment:

```bash
python -m pytest tests -q
```

# How to Play

## Goal

Reach the **END** tile. Pillars (quantum objects) block your path. Each pillar is a qubit,
and you can only walk through one when it is in a pure |0> state. Apply gates to collapse
the pillars out of your way.

## Controls

| Input | Action |
|---|---|
| `W` `A` `S` `D` | Move |
| `R` | Restart level |
| `Esc` / `Q` | Pause / open the in-game menu |
| Mouse drag | Drag a gate from the hotbar onto a pillar |
| Mouse hover | Hover a pillar to draw entanglement lines to its partners |

## Using gates

Gates live in the hotbar at the bottom of the screen. You start each level with some, and
pick up more by walking into loot boxes.

**You must be standing next to a pillar to drop a gate on it.** For controlled gates this
applies to the control pillar only — the target can be anywhere on the map.

- **Single-qubit gates** (`X`, `H`, `Z`, `RotY`) — drag the gate from the hotbar and drop it
  on the pillar. It applies immediately and the gate is consumed.
- **Controlled gates** (`CNOT`, `CHAD`) — drop the gate on the **control** pillar first, then
  drag from that control pillar to the **target** pillar. This entangles the two.

| Gate | Effect |
|---|---|
| `X` | Flip: \|0> ↔ \|1> |
| `H` | Superposition: puts the pillar in an even mix of \|0> and \|1> |
| `Z` | Phase flip (no change to the measured value, but it matters once entangled) |
| `RotY` | Partial Y rotation — nudges the state part-way between \|0> and \|1> |
| `CNOT` | Controlled flip: flips the target when the control is \|1> |
| `CHAD` | Controlled Hadamard: superposes the target when the control is \|1> |

## Reading a pillar

The pillar's tint tells you its state:

- **Blue** — \|1>, solid, you cannot pass
- **White / transparent** — pure \|0>, walkable
- **Reddish** — very close to \|0> but not exactly there, still blocking
- **Green channel** — the pillar carries a Z phase

Only an *exactly* pure \|0> is walkable — "almost zero" is not good enough. Entangled pillars
pulse through their correlated states, and hovering one draws dark blue lines to its partners.
