# Quantum puzzle game (Qungeon)

Simple puzzle game, reach the end to complete a level. This can be done by using gates in your toolbar ("bag") to manipulating the quantum state of pillars.
The player has to be next to an object to interact with it!

![The player next to a loot box and a pillar in state |1>](assets/screenshot.png)

# Unitary Libary

The game was made using the Unitary library, which handles most of the quantum logic. More information can be found at:
https://github.com/quantumlib/unitary

Game examples can be found on this page and explanation on how to make use of the library.

# Running using Docker

Make sure you have Docker desktop installed. If not consult: https://docs.docker.com/desktop/. Run the app using:

```bash
docker compose up
```

# Play in the browser

The browser loads the original Python game code, assets, and levels directly.
Only the small browser adapter and the required Unitary Alpha modules live in
`web/`. Normal play is static; hardware execution uses the optional personal
Quantum Inspire bridge described below.

Serve it locally from the repository root:

```bash
python -m http.server 8000
```

Open <http://localhost:8000> to see the main menu. To jump directly into a
single level, use a URL such as <http://localhost:8000/?level=5>.

For production, serve the repository root from any HTTPS static-file host with
`index.html` as the entry point. No build step or server-side Python process is
required.

# Run a completed circuit on Quantum Inspire

Every completed level has a purple **Run on Quantum Computer** button. It opens
the Quantum Lab, checks available hardware, and shows the selected processor and
shot count before submission. Full runs now pause at each completion screen;
**Continue to next level** resumes the run.

## One-time setup

Use the same Python environment as the game (Python 3.13 recommended):

```bash
python -m pip install -r requirements-quantum.txt
qi login
```

Sign in with your own Quantum Inspire account in the browser opened by the
official CLI. Credentials remain in the SDK's `~/.quantuminspire/config.json`;
Qungeon does not ask for, store, or send credentials to its browser client.
The optional requirements pin a tested, mutually compatible SDK pair. Newer
individual SDK packages currently have conflicting dependency requirements.

- **Desktop:** start `python Qungeon.py` as usual after signing in.
- **Browser:** start `python -m scripts.quantum_server` from the repository root,
  then open [localhost:8000](http://localhost:8000). Use `--port 8001` if needed.
  This replaces `python -m http.server` for hardware-enabled play.
- **Static hosting / default Docker image:** gameplay still works; the Quantum
  Lab shows setup instructions. Hardware execution requires the personal
  launcher or desktop game. The bridge binds to loopback, checks same-origin
  requests, and serves only public game files. It is not a multi-user server.

## Hardware and results

The integration supports the documented **Tuna-5, Tuna-9 and Tuna-17** gate set.
It checks live account access, hardware status, qubit count and connectivity,
then chooses the smallest compatible available processor. Emulators, unknown
device families, offline devices and devices being calibrated are excluded.
There is no automatic simulator fallback.

Runs use **1,024 shots**, capped by the device limit. The captured circuit includes
the level's initial gates and every applied player gate, including controlled H
and fractional Y rotations. Unused pillars are measured too. Qiskit routes gates
onto the actual device topology using a restricted supported basis. The entire
physical register is initialized; only game pillars appear in the outcomes.
Conservative limits are 17 pillars, 512 input operations, compiled depth 200,
and 100 two-qubit gates. Circuits with post-selection, intermediate measurements,
extra ancillas or unsupported operations are refused before submission.

The Quantum Lab shows queue/running status, measured counts and percentages,
the actual number of completed shots, and ideal probabilities from the captured
circuit. Outcome bits read **left to right in pillar order**. **Pillar map**, at
the bottom right, shows the saved completed level with numbered pillar sprites,
walls, exit, player and remaining loot. Select a pillar with the mouse or keyboard
to see its coordinates and measured versus ideal probabilities for 0 and 1.
Saved runs keep their map even after moving to another level or restarting;
older runs fall back to the level layout. Scroll the outcomes table to explore
all results, including small counts; column headings remain visible.
Hardware noise and Tuna's 5-degree rotation quantization can cause differences
from ideal probabilities. Partial runs are explicitly labeled.

**View circuit**, next to **Pillar map** on the results screen, shows the
captured logical circuit, including level setup, controlled gates and fractional
rotations. Wires use the same pillar numbers as the map and result bits. Read left
to right. Scroll vertically through pillars and horizontally through gates with
a trackpad, Shift + mouse wheel, arrow keys, or draggable scrollbars. A regular
mouse wheel scrolls horizontally when all pillars fit. Labels remain pinned.
The circuit screen has only a **Back** button. Select a gate for its name and operands. **M** marks the
final measurement added for hardware runs. The processor's compiled native-gate
sequence may differ. Older saved gates without notation appear as **U**.

You can keep playing while a job runs. **Hardware runs** on the main menu reopens
the latest 50 saved runs and automatic attempts on this computer, including after a browser
refresh or game restart. The launcher must still be running for browser access.
Browse runs with the mouse wheel, trackpad, scrollbar, or keyboard. Refresh keeps
the list and scroll position visible while the button shows **Refreshing...**.
**Run again** from the current level's results prepares a new run; the previous
result stays in history. Local job records and SDK recovery files live in
`.qungeon-quantum/` (ignored by Git). Keep this directory to recover pending jobs;
exclude it when publishing static files. Jobs also remain in
[My QI](https://compute.quantum-inspire.com/).

Submission is guarded against double clicks, repeated requests and restarts.
If a connection drops during submission, Qungeon never silently resubmits:
use **Check status** and inspect My QI if acceptance could not be confirmed.
Expired account access can be renewed with `qi login` while the game is open.

If hardware was unavailable, open that saved attempt in **Hardware runs** and
choose **Retry**. It rechecks current hardware and submits the original completed
circuit, using up to 1,024 shots. This also works for attempts saved before retry
support was added. Repeated clicks and restarts cannot submit the same run twice;
jobs already submitted or awaiting confirmation use **Check status** instead.

Integration tests use the installed SDK for conversion, transpilation, cQASM
serialization and saved-job recovery, with network calls replaced by controlled
test responses. They do not consume hardware shots:

```bash
python -m pytest tests -q
```

Implementation references: [official SDK usage](https://qutech-delft.github.io/qiskit-quantuminspire/getting_started/submitting.html),
[Tuna operational constraints](https://www.quantum-inspire.com/kbase/tuna-operational-specifics/).

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
- **Level completion screens** (on by default) controls pauses between levels
  in a full run. Turn it off to continue directly to the next puzzle. Single
  levels and the final run summary still show their completion screens.
- When completion screens are off, **Queue levels on Quantum Inspire** appears
  (off by default). Enabling it automatically checks and submits each completed
  level, including the final one, using up to 1,024 shots on compatible hardware.
  It requires the same connected account and quantum-enabled browser launcher
  as manual runs. Play continues while submissions are processed. Results and
  failed connection/compatibility checks appear in **Hardware runs**; unavailable
  circuits are skipped, and uncertain submissions are never automatically retried.
  Keep the game and launcher open while submissions finish. Changing settings
  affects future level completions; jobs already sent continue processing.
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

Completing a level opens a completion screen unless intermediate screens are
disabled for a full run. The failure screen is driven by the level solver below: it
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

| Input           | Action                                                    |
| --------------- | --------------------------------------------------------- |
| `W` `A` `S` `D` | Move                                                      |
| `R`             | Restart level                                             |
| `Esc` / `Q`     | Pause / open the in-game menu                             |
| Mouse drag      | Drag a gate from the hotbar onto a pillar                 |
| Mouse hover     | Hover a pillar to draw entanglement lines to its partners |

## Using gates

Gates live in the hotbar at the bottom of the screen. You start each level with some, and
pick up more by walking into loot boxes.

**You must be standing next to a pillar to drop a gate on it.** For controlled gates this
applies to the control pillar only — the target can be anywhere on the map.

- **Single-qubit gates** (`X`, `H`, `Z`, `RotY`) — drag the gate from the hotbar and drop it
  on the pillar. It applies immediately and the gate is consumed.
- **Controlled gates** (`CNOT`, `CHAD`) — drop the gate on the **control** pillar first, then
  drag from that control pillar to the **target** pillar. This entangles the two.

| Gate   | Effect                                                                      |
| ------ | --------------------------------------------------------------------------- |
| `X`    | Flip: \|0> ↔ \|1>                                                           |
| `H`    | Superposition: puts the pillar in an even mix of \|0> and \|1>              |
| `Z`    | Phase flip (no change to the measured value, but it matters once entangled) |
| `RotY` | Partial Y rotation — nudges the state part-way between \|0> and \|1>        |
| `CNOT` | Controlled flip: flips the target when the control is \|1>                  |
| `CHAD` | Controlled Hadamard: superposes the target when the control is \|1>         |

## Reading a pillar

The pillar's tint tells you its state:

- **Blue** — \|1>, solid, you cannot pass
- **White / transparent** — pure \|0>, walkable
- **Reddish** — very close to \|0> but not exactly there, still blocking
- **Green channel** — the pillar carries a Z phase

Only an _exactly_ pure \|0> is walkable — "almost zero" is not good enough. Entangled pillars
pulse through their correlated states, and hovering one draws dark blue lines to its partners.
