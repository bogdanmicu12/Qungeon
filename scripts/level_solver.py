"""Exhaustive solvability check for a Qungeon level.

Gates are consumed when used, so a player can spend the level's last `X` on the
wrong pillar and be left with no winning sequence at all. Nothing in the game
detects that today. This module answers, for an *arbitrary* mid-play state:

    is there still some sequence of actions that reaches the END tile?

and, when there is, returns one such sequence.

Why the question is decidable
-----------------------------
The number of state-changing actions in a level is bounded: every gate is
consumed on use, and the only source of new gates is the finite set of loot
boxes. Movement costs nothing and - apart from picking up a loot box - is
reversible, because walking through a pillar leaves that pillar untouched, so
the player can always walk back the way they came. The search space is
therefore finite and, in practice, tiny.

How the state is represented
----------------------------
* **Movement is collapsed away.** Instead of searching over individual steps,
  the solver computes the *region* of tiles the player can currently reach.
  Every tile in a region is equivalent (movement is free and reversible), so
  a region is one search node rather than one node per tile.
* **The quantum state is kept factored.** A joint state vector over every
  pillar would be the wrong size: level 6 has 15 pillars (32768 amplitudes) but
  only single-qubit gates, so its pillars never entangle. The solver keeps one
  small vector per entangled block - the same partition the game itself tracks
  in `GroupingSystem` - and merges two blocks only when a controlled gate
  actually spans them.

Relationship to the game code
-----------------------------
The rules are read from the game rather than restated wherever possible:

* gate unitaries are derived from the live `QuantumEffect` objects in
  `scripts.game_objects.gates`, so a new gate added there needs no change here;
* walkability uses the game's own `PURE_ZERO_TOL` and the same
  "P(|0>) is exactly 1" rule as `QuantumObject.function`;
* the starting state is read out of a real `Game` via :func:`snapshot`, so the
  level file, its initial effects and any gates already spent are all accounted
  for without replaying them.

The one rule that must be mirrored is `CONTROL_EFFECTS` below - see its comment.

Typical use::

    from scripts import level_solver
    level_solver.is_solvable(game)   # True / False / None ("don't know")
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import cirq
import numpy as np
import unitary.alpha as alpha

from scripts.game_objects import (
    PURE_ZERO_TOL,
    LootableObject,
    QuantumObject,
    TileType,
    control_gates,
    gates,
)


# Nodes the search may expand before giving up and reporting "unknown". Reached
# only by levels far larger than any shipped one; see solve() on why exceeding
# it must never be reported as "unsolvable".
DEFAULT_BUDGET = 50_000

# Amplitudes are compared at this many decimals when de-duplicating search
# states. Far tighter than PURE_ZERO_TOL, so two states that hash alike always
# agree on every pillar's walkability.
_HASH_DECIMALS = 9

# Below this magnitude an amplitude is treated as zero when picking the
# reference amplitude for global-phase normalisation.
_PHASE_EPS = 1e-9

# Dropping a controlled gate on a pillar applies this effect to the target,
# conditioned on the control being |1>.
#
# MIRRORS Qungeon.Game.handle_object_dragging, which hardcodes the same two
# cases. If a third controlled gate is ever added there, add it here too -
# test_solver.test_every_gate_is_supported fails loudly until you do.
CONTROL_EFFECTS = {
    "CNOT": alpha.Flip(),
    "CHAD": alpha.Superposition(),
}


class _EffectTarget:
    """Minimal stand-in for a `QuantumObject`, used only to read out a matrix.

    `QuantumEffect.effect()` yields cirq operations on `obj.qubit`, and that is
    the only attribute it touches, so a single dummy qubit is enough to recover
    the effect's unitary without building a `QuantumWorld`.
    """

    qubit = cirq.LineQubit(0)


@lru_cache(maxsize=None)
def gate_unitary(name):
    """The 2x2 matrix a hotbar gate applies, derived from the game's own table.

    For a controlled gate this is the matrix applied *to the target* when the
    control is |1>; the control conditioning is handled by `_apply_controlled`.

    SWAP is intentionally excluded from the solver for now because it is a
    genuine two-qubit operation rather than a single-qubit unitary.

    Raises KeyError for a gate the solver does not know how to simulate.
    """
    if name == "SWAP":
        # SWAP is a genuine two-qubit operation and is handled by
        # _apply_swap(). It is deliberately not converted to a 2x2 matrix.
        raise KeyError("SWAP is a two-qubit gate; use _apply_swap()")

    effect = CONTROL_EFFECTS[name] if name in control_gates else gates[name]
    if effect is None:
        raise KeyError(f"gate {name!r} has no effect the solver can simulate")

    circuit = cirq.Circuit(effect.effect(_EffectTarget()))
    return np.asarray(cirq.unitary(circuit), dtype=np.complex128)


# --------------------------------------------------------------------------
# Quantum state: a partition of the pillars into entangled blocks
# --------------------------------------------------------------------------


class Block:
    """One entangled group of pillars and its joint state vector.

    `qubits` is sorted, and amplitude index `i` encodes qubit `k` in bit
    `len(qubits) - 1 - k` (cirq's big-endian convention).

    Pillars in different blocks are guaranteed to be unentangled, which is what
    makes a block's vector meaningful on its own.

    A block is immutable, and a gate leaves every block it did not touch
    untouched, so the same object is shared by many search states. Walkability
    and the hash key are therefore computed once per block and cached.
    """

    __slots__ = ("qubits", "vector", "_canonical", "_walkable")

    def __init__(self, qubits, vector):
        self.qubits = qubits
        self.vector = vector
        self._canonical = None
        self._walkable = {}

    def index(self, pillar):
        return self.qubits.index(pillar)

    def canonical(self):
        """Hashable, global-phase-normalised identity of this block's state."""
        if self._canonical is None:
            self._canonical = _canonical_vector(self.vector)
        return self._canonical

    def walkable(self, pillar):
        """Cached `is_walkable` for one of this block's pillars."""
        cached = self._walkable.get(pillar)
        if cached is None:
            cached = self._walkable[pillar] = is_walkable(self, pillar)
        return cached


def _sort_block(qubits, vector):
    """Return the block with its qubits in sorted order, permuting the vector."""
    order = sorted(range(len(qubits)), key=lambda i: qubits[i])

    if order != list(range(len(qubits))):
        tensor = vector.reshape((2,) * len(qubits)).transpose(order)
        vector = np.ascontiguousarray(tensor).reshape(-1)

    return Block(tuple(qubits[i] for i in order), vector)


def _apply_single(block, pillar, unitary):
    """Apply a 1-qubit unitary to one pillar of a block."""
    axis = block.index(pillar)

    tensor = block.vector.reshape((2,) * len(block.qubits))
    tensor = np.moveaxis(
        np.tensordot(
            unitary,
            tensor,
            axes=([1], [axis]),
        ),
        0,
        axis,
    )

    return Block(
        block.qubits,
        np.ascontiguousarray(tensor).reshape(-1),
    )


def _apply_controlled(block, control, target, unitary):
    """Apply a 1-qubit unitary to `target` on the |1> branch of `control`.

    Both pillars must already live in the same block; `_merge` puts them there.
    """
    control_axis = block.index(control)
    target_axis = block.index(target)

    tensor = block.vector.reshape((2,) * len(block.qubits)).copy()

    branch = [slice(None)] * len(block.qubits)
    branch[control_axis] = 1
    branch = tuple(branch)

    # Slicing out the control=1 branch drops that axis, so a target axis to its
    # right shifts down by one.
    axis = target_axis - 1 if target_axis > control_axis else target_axis

    sub = tensor[branch]

    tensor[branch] = np.moveaxis(
        np.tensordot(
            unitary,
            sub,
            axes=([1], [axis]),
        ),
        0,
        axis,
    )

    return Block(
        block.qubits,
        tensor.reshape(-1),
    )


def _merge(first, second):
    """Combine two independent blocks into one joint block."""
    return _sort_block(
        first.qubits + second.qubits,
        np.kron(first.vector, second.vector),
    )


def _apply_swap(state, first, second):
    """Return blocks after exchanging the quantum states of two pillars.

    This mirrors Game.handle_object_dragging: SWAP changes the two qubit
    states but does not create an entanglement group by itself.

    If the pillars are in different blocks, they are first combined. A SWAP
    inside a joint block is implemented by exchanging the corresponding tensor
    axes, which is also correct for entangled states.
    """
    first_block = state.block_of(first)
    second_block = state.block_of(second)

    # Different independent blocks.
    if first_block is not second_block:
        merged = _merge(first_block, second_block)

        first_axis = merged.index(first)
        second_axis = merged.index(second)

        tensor = merged.vector.reshape(
            (2,) * len(merged.qubits)
        )

        tensor = np.swapaxes(
            tensor,
            first_axis,
            second_axis
        )

        swapped = Block(
            merged.qubits,
            np.ascontiguousarray(tensor).reshape(-1)
        )

        return _replace_blocks(
            state.blocks,
            [first_block, second_block],
            [swapped],
        )

    # Same entangled block.
    tensor = first_block.vector.reshape(
        (2,) * len(first_block.qubits)
    )

    first_axis = first_block.index(first)
    second_axis = first_block.index(second)

    tensor = np.swapaxes(
        tensor,
        first_axis,
        second_axis
    )

    swapped = Block(
        first_block.qubits,
        np.ascontiguousarray(tensor).reshape(-1)
    )

    return _replace_blocks(
        state.blocks,
        [first_block],
        [swapped],
    )


def _split(block):
    """Peel a block into unentangled sub-blocks, largest factorisation found.

    Applying a controlled gate merges two blocks, but the result is often still
    a product state - a CNOT off a control that is |0> or |1> entangles
    nothing. Splitting again keeps blocks (and therefore search keys) small.

    Returns a list of blocks covering exactly the same pillars.
    """
    if len(block.qubits) < 2:
        return [block]

    for i in range(len(block.qubits)):
        rest = [j for j in range(len(block.qubits)) if j != i]

        single = cirq.sub_state_vector(
            block.vector,
            [i],
            atol=1e-8,
            default=None,
        )

        remainder = cirq.sub_state_vector(
            block.vector,
            rest,
            atol=1e-8,
            default=None,
        )

        if single is None or remainder is None:
            continue

        peeled = Block(
            (block.qubits[i],),
            np.asarray(single, dtype=np.complex128),
        )

        others = Block(
            tuple(block.qubits[j] for j in rest),
            np.asarray(remainder, dtype=np.complex128),
        )

        return [peeled] + _split(others)

    return [block]


def probability_zero(block, pillar):
    """Exact P(|0>) for one pillar, marginalised over the rest of its block."""
    axis = block.index(pillar)

    tensor = block.vector.reshape((2,) * len(block.qubits))

    branch = [slice(None)] * len(block.qubits)
    branch[axis] = 0

    return float(np.sum(np.abs(tensor[tuple(branch)]) ** 2))


def is_walkable(block, pillar):
    """Whether the player may step onto `pillar`.

    Same rule and tolerance as `QuantumObject.function`: passable only when the
    pillar is deterministically |0>.
    """
    return probability_zero(block, pillar) >= 1.0 - PURE_ZERO_TOL


# --------------------------------------------------------------------------
# Level state
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Board:
    """The parts of a level that never change while it is being played."""

    tiles: dict
    pillars: tuple


class SolverState:
    """A complete, self-contained snapshot of everything a player can change.

    Fields:
        board      - the unchanging level geometry
        player     - (x, y) the player stands on
        inventory  - sorted ((gate_name, count), ...)
        loot       - frozenset of ((x, y), gate_name) still on the floor
        blocks     - one Block per entangled group of pillars
    """

    __slots__ = (
        "board",
        "player",
        "inventory",
        "loot",
        "blocks",
        "_by_pillar",
    )

    def __init__(self, board, player, inventory, loot, blocks):
        self.board = board
        self.player = player
        self.inventory = inventory
        self.loot = loot
        self.blocks = blocks
        self._by_pillar = None

    def block_of(self, pillar):
        """The block holding `pillar`, via a lazily built lookup table."""
        if self._by_pillar is None:
            self._by_pillar = {
                qubit: block
                for block in self.blocks
                for qubit in block.qubits
            }

        return self._by_pillar[pillar]


def _inventory_of(counts):
    """Normalise a gate-count mapping into the hashable inventory form."""
    return tuple(
        sorted(
            (name, count)
            for name, count in counts.items()
            if count > 0
        )
    )


def _spend(inventory, name):
    counts = dict(inventory)
    counts[name] -= 1
    return _inventory_of(counts)


def _gain(inventory, name):
    counts = dict(inventory)
    counts[name] = counts.get(name, 0) + 1
    return _inventory_of(counts)


def _replace_blocks(blocks, removed, added):
    """Return `blocks` with the blocks in `removed` swapped for `added`."""
    kept = [
        block
        for block in blocks
        if not any(block is removed_block for removed_block in removed)
    ]

    return tuple(kept + list(added))


def snapshot(game):
    """Build a `SolverState` from a live `Game`.

    Everything is read from the running game rather than re-derived from the
    level file, so a mid-play state - gates already spent, loot already taken,
    pillars already entangled - is captured exactly.
    """
    tiles = {
        position: tile.type
        for position, tile in game.tiles.items()
    }

    pillars = []
    loot = set()

    for obj in game.objects.values():
        if isinstance(obj, QuantumObject):
            pillars.append(obj.position)
        elif isinstance(obj, LootableObject):
            loot.add((obj.position, obj.item))

    return SolverState(
        board=Board(
            tiles=tiles,
            pillars=tuple(sorted(pillars)),
        ),
        player=tuple(game.player.position),
        inventory=_inventory_of(
            {
                name: slot.count
                for name, slot in game.hotbar.slots.items()
            }
        ),
        loot=frozenset(loot),
        blocks=_snapshot_blocks(game),
    )


def _snapshot_blocks(game):
    """Factor the game's quantum world into one `Block` per entangled group.

    The world's circuit is simulated once - the same call
    `game_objects.exact_probability_zero` makes - and the resulting joint
    vector is split along the partition the game already maintains in
    `GroupingSystem`.
    """
    world = game.quantum_grid

    pillars = [
        obj
        for obj in game.objects.values()
        if isinstance(obj, QuantumObject)
    ]

    result = cirq.Simulator().simulate(world.circuit)

    qubit_map = result.qubit_map
    joint = np.asarray(
        result.final_state_vector,
        dtype=np.complex128,
    )

    width = len(qubit_map)

    untouched = [
        pillar
        for pillar in pillars
        if pillar.qubit not in qubit_map
    ]

    simulated = [
        pillar
        for pillar in pillars
        if pillar.qubit in qubit_map
    ]

    blocks = [
        Block(
            (pillar.position,),
            np.array(
                [1.0, 0.0],
                dtype=np.complex128,
            ),
        )
        for pillar in untouched
    ]

    groups, seen = [], set()

    for group in game.grouping_system.groups:
        members = [
            pillar
            for pillar in group.objects
            if pillar in simulated
        ]

        if members:
            groups.append(members)
            seen.update(id(member) for member in members)

    groups.extend(
        [pillar]
        for pillar in simulated
        if id(pillar) not in seen
    )

    for members in groups:
        members = sorted(
            members,
            key=lambda pillar: qubit_map[pillar.qubit],
        )

        keep = [
            qubit_map[pillar.qubit]
            for pillar in members
        ]

        vector = (
            joint
            if keep == list(range(width))
            else cirq.sub_state_vector(
                joint,
                keep,
                atol=1e-6,
                default=None,
            )
        )

        if vector is None:
            # Unexpected entanglement across groups (or ancilla qubits): fall
            # back to one joint block over every simulated pillar.
            if len(simulated) != width:
                raise ValueError(
                    "quantum world contains qubits that are not pillars; "
                    "the solver cannot factor this state"
                )

            ordered = sorted(
                simulated,
                key=lambda pillar: qubit_map[pillar.qubit],
            )

            return tuple(
                blocks
                + [
                    _sort_block(
                        tuple(p.position for p in ordered),
                        joint,
                    )
                ]
            )

        blocks.append(
            _sort_block(
                tuple(p.position for p in members),
                np.asarray(vector, dtype=np.complex128),
            )
        )

    return tuple(blocks)


# --------------------------------------------------------------------------
# Reachability - mirrors Game.update_position
# --------------------------------------------------------------------------


def _can_enter(state, position, loot_positions):
    """Whether the player may step onto `position`.

    Mirrors the branch order of `Qungeon.Game.update_position`: END wins over
    anything standing on it, an object's own rule is consulted next, and only
    then does the tile type decide.
    """
    tile = state.board.tiles.get(position)

    if tile is None:
        return False

    if tile == TileType.END:
        return True

    if position in loot_positions:
        return True

    if position in state.board.pillars:
        return state.block_of(position).walkable(position)

    return tile != TileType.WALL


def reachable(state):
    """Every tile the player can walk to right now, including where they stand."""
    loot_positions = {
        position
        for position, _ in state.loot
    }

    region = {state.player}
    frontier = [state.player]

    while frontier:
        x, y = frontier.pop()

        for neighbour in (
            (x + 1, y),
            (x - 1, y),
            (x, y + 1),
            (x, y - 1),
        ):
            if (
                neighbour not in region
                and _can_enter(
                    state,
                    neighbour,
                    loot_positions,
                )
            ):
                region.add(neighbour)
                frontier.append(neighbour)

    return region


def _is_won(state, region):
    return any(
        state.board.tiles.get(position) == TileType.END
        for position in region
    )


def _reachable_pillars(state, region):
    """Pillars the player can drop a gate on.

    Matches `Player.distance` (Chebyshev distance of 1, diagonals included)
    as enforced by `Hotbar.remove_item`.
    """
    return [
        pillar
        for pillar in state.board.pillars
        if any(
            abs(pillar[0] - x) <= 1
            and abs(pillar[1] - y) <= 1
            for x, y in region
        )
    ]


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def _canonical_vector(vector):
    """Vector bytes with global phase removed, for state de-duplication."""
    significant = np.flatnonzero(
        np.abs(vector) > _PHASE_EPS
    )

    if len(significant):
        reference = vector[significant[0]]
        vector = vector * (
            np.abs(reference) / reference
        )

    return np.round(
        vector,
        _HASH_DECIMALS,
    ).tobytes()


def _key(state, region):
    """Hashable identity of a search node."""
    return (
        min(region),
        state.inventory,
        state.loot,
        tuple(
            sorted(
                (
                    block.qubits,
                    block.canonical(),
                )
                for block in state.blocks
            )
        ),
    )


def _take_loot(state, position, name):
    return SolverState(
        board=state.board,
        player=position,
        inventory=_gain(
            state.inventory,
            name,
        ),
        loot=state.loot - {(position, name)},
        blocks=state.blocks,
    )


def _apply_gate(state, name, pillar, target):
    """State after spending `name` on `pillar`.

    For SWAP, `pillar` is the first qubit and `target` is the second.
    """
    if name == "SWAP":
        if target is None:
            raise ValueError("SWAP requires a target pillar")

        new_blocks = _apply_swap(
            state,
            pillar,
            target,
        )

        return SolverState(
            board=state.board,
            player=state.player,
            inventory=_spend(state.inventory, name),
            loot=state.loot,
            blocks=new_blocks,
        )

    unitary = gate_unitary(name)
    block = state.block_of(pillar)

    if target is None:
        new_blocks = _replace_blocks(
            state.blocks,
            [block],
            [
                _apply_single(
                    block,
                    pillar,
                    unitary,
                )
            ],
        )

    else:
        target_block = state.block_of(target)

        if target_block is block:
            merged, removed = block, [block]
        else:
            merged, removed = (
                _merge(
                    block,
                    target_block,
                ),
                [block, target_block],
            )

        applied = _apply_controlled(
            merged,
            pillar,
            target,
            unitary,
        )

        new_blocks = _replace_blocks(
            state.blocks,
            removed,
            _split(applied),
        )

    return SolverState(
        board=state.board,
        player=state.player,
        inventory=_spend(
            state.inventory,
            name,
        ),
        loot=state.loot,
        blocks=new_blocks,
    )


def _successors(state, region):
    for position, name in sorted(state.loot):
        if position in region:
            yield (
                ("loot", position, name),
                _take_loot(
                    state,
                    position,
                    name,
                ),
            )

    pillars = _reachable_pillars(
        state,
        region,
    )

    for name, _count in state.inventory:
        for pillar in pillars:
            if name == "SWAP":
                # SWAP is dragged from a reachable pillar onto any other pillar.
                for target in state.board.pillars:
                    if target != pillar:
                        yield (
                            ("gate", name, pillar, target),
                            _apply_gate(
                                state,
                                name,
                                pillar,
                                target,
                            ),
                        )
            elif name in control_gates:
                # The control must be within reach; the target may be any pillar.
                for target in state.board.pillars:
                    if target != pillar:
                        yield (
                            ("gate", name, pillar, target),
                            _apply_gate(
                                state,
                                name,
                                pillar,
                                target,
                            ),
                        )
            else:
                yield (
                    ("gate", name, pillar, None),
                    _apply_gate(
                        state,
                        name,
                        pillar,
                        None,
                    ),
                )


@dataclass(frozen=True)
class Solution:
    """Outcome of a search.

    `solvable` is True when `plan` reaches the END tile, False when the level
    is provably dead, and None when the node budget ran out first.
    """

    solvable: Optional[bool]
    plan: tuple
    nodes: int

    @property
    def is_stuck(self):
        """True only when the level is provably unwinnable."""
        return self.solvable is False


def solve(state, budget=DEFAULT_BUDGET):
    """Search for any action sequence that reaches the END tile.

    Depth-first with memoisation on `_key`; the depth is bounded by the number
    of gates the player can still spend plus the loot boxes left, so the search
    terminates without a depth limit.
    """
    visited = set()
    nodes = 0
    exhausted = False

    def descend(current, plan):
        nonlocal nodes, exhausted

        region = reachable(current)

        if _is_won(current, region):
            return plan

        key = _key(
            current,
            region,
        )

        if key in visited:
            return None

        visited.add(key)

        nodes += 1

        if nodes > budget:
            exhausted = True
            return None

        for action, following in _successors(
            current,
            region,
        ):
            found = descend(
                following,
                plan + (action,),
            )

            if found is not None:
                return found

        return None

    plan = descend(
        state,
        (),
    )

    if plan is not None:
        return Solution(
            True,
            plan,
            nodes,
        )

    return Solution(
        None if exhausted else False,
        (),
        nodes,
    )


def state_from_level_data(level_data):
    """Build a solver state directly from a validated level JSON object.

    This lets the level editor check a newly-created level before writing it
    to disk. The initial quantum effects are applied in the same order as the
    game's level loader.
    """
    tiles = {}
    start = None

    for position, kind in level_data["tiles"].items():
        parsed = _parse_level_pos(position)
        tile = TileType[kind]
        tiles[parsed] = tile
        if tile is TileType.START:
            start = parsed

    pillars = tuple(
        sorted(_parse_level_pos(position)
               for position in level_data["quantum_objects"])
    )

    loot = frozenset(
        (
            _parse_level_pos(position),
            name,
        )
        for position, name in level_data["objects"].items()
    )

    blocks = tuple(
        Block(
            (pillar,),
            np.array([1.0, 0.0], dtype=np.complex128),
        )
        for pillar in pillars
    )

    state = SolverState(
        board=Board(tiles=tiles, pillars=pillars),
        player=start,
        inventory=_inventory_of(level_data["gates"]),
        loot=loot,
        blocks=blocks,
    )

    for entry in level_data["effects"]:
        source = _parse_level_pos(entry["position"])
        effect_name = entry["effect"]

        if effect_name == "SWAP":
            target = _parse_level_pos(entry["target"])
            state = SolverState(
                board=state.board,
                player=state.player,
                inventory=state.inventory,
                loot=state.loot,
                blocks=_apply_swap(state, source, target),
            )
            continue

        effect = gate_unitary(effect_name)
        block = state.block_of(source)

        if "target" in entry:
            target = _parse_level_pos(entry["target"])
            target_block = state.block_of(target)

            if target_block is block:
                merged, removed = block, [block]
            else:
                merged = _merge(block, target_block)
                removed = [block, target_block]

            controlled_effect = CONTROL_EFFECTS.get(effect_name)
            if controlled_effect is None:
                raise ValueError(
                    f"effect {effect_name!r} cannot have a target"
                )

            applied = _apply_controlled(
                merged,
                source,
                target,
                gate_unitary(effect_name),
            )

            blocks = _replace_blocks(
                state.blocks,
                removed,
                _split(applied),
            )
        else:
            blocks = _replace_blocks(
                state.blocks,
                [block],
                [_apply_single(block, source, effect)],
            )

        state = SolverState(
            board=state.board,
            player=state.player,
            inventory=state.inventory,
            loot=state.loot,
            blocks=blocks,
        )

    return state


def _parse_level_pos(value):
    """Small local parser used by state_from_level_data."""
    value = value.strip("() ")
    x, y = (int(part.strip()) for part in value.split(","))
    return (x, y)


def solve_level_data(level_data, budget=DEFAULT_BUDGET):
    """Check a validated level JSON object for actual playability."""
    return solve(
        state_from_level_data(level_data),
        budget=budget,
    )


def is_solvable(game, budget=DEFAULT_BUDGET):
    """Can this level still be won from its current state?

    Returns True, False, or None when the search hit its budget. Callers should
    treat None as "assume winnable".
    """
    return solve(
        snapshot(game),
        budget,
    ).solvable