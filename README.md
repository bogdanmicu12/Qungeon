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

Open <http://localhost:8000>. A different starting level can be selected with a
URL such as <http://localhost:8000/?level=5>.

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
python Qungeon.py        # start at level 1
python Qungeon.py 5      # start at level 5
```

An invalid or nonexistent level number exits with an error message instead of starting.

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
| `Q` | Quit |
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
