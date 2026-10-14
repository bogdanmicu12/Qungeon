# Qungeon story proposal: The Way Out

Status: implemented on 2026-10-13. The following records the agreed design;
story content lives in `scripts/story.py`. Puzzle layouts and quantum rules are
unchanged.

## Agreed direction

Mysterious and curious, with a hopeful ending. The protagonist is the anonymous
player. The audience is curious beginners. Keep all existing puzzles and their
order. Tell the story mainly through the environment, with very little text.
The story should make the next room more inviting and help explain what players
are doing. People who ignore it should play at their normal pace.

## The story

You wake beneath a sealed hatch in a strange stone dungeon. Beside it is a worn
symbol: a line leading toward an open arch. The same symbol appears beside the
first room's exit. Someone built a way out.

The dungeon's pillars are its locks. They respond to quantum gates, and each
chamber reveals another part of their logic. At first you learn to change a
single pillar. Further in, appearances become unreliable: pillars that look
similar can respond differently. Later, you discover that a lock can control
another, and that some pillars must be understood together.

The repeated arch symbol gradually becomes less damaged. Old maintenance marks
and supplies suggest these chambers were once a working passage. You are
recovering its route to the surface. The mystery is modest: what are the rules
of this place, and where does this route lead? There is no villain, secret
identity, lore twist, or promise of another character to rescue.

Near the end, narrow traces of daylight replace the darkness around the exit.
The final chamber requires you to use what you have learned to reach the outer
lock. You step onto the last exit; the existing completion screen shows the arch
open against a pale sky.

Ending: **"Daylight. You found your way out, one understood rule at a time."**

The player supplies the character arc: an unfamiliar place becomes a place they
can reason about. These locks are a fictional use of qubits; the quantum gate
behavior stays grounded in the existing simulation.

## The nine rooms

The room names are optional flavor in existing UI. The short learning lines are
the only routine in-play text proposed. They describe a principle without naming
the exact sequence or target needed to solve the room.

| Level | Room / narrative purpose | Existing learning opportunity | Short learning line | Environmental cue / completion payoff |
| --- | --- | --- | --- | --- |
| 1 | **The Sealed Room.** Discover that escape is possible. | One pillar starts in 1; the player has X. | "A pillar in 0 lets you through. X flips 0 and 1." | A faded arch mark points toward END. Completion: "The first lock opens. The same mark lies ahead." |
| 2 | **The Uncertain Passage.** The dungeon has more than one kind of lock. | H and X address different starting states. | "H can create a superposition, and undo the one it creates." | An old two-part arch engraving echoes the two barriers. Completion: "Another passage opens. The markings continue." |
| 3 | **The Hidden Difference.** Learn to question similar appearances. | The pillar starts in the minus superposition; H and X are available. | "Similar probabilities can hide different phases. H reveals the difference." | A familiar engraving has one reversed stroke. Completion: "The familiar-looking lock concealed a different state." |
| 4 | **The Phase Lock.** Understand a rule hidden beneath appearances. | The setup reduces to 1; the inventory supports H, Z, H. | "Z changes relative phase; H can turn that into different probabilities." | Paired etched wave shapes introduce phase as an optional visual metaphor. Completion: "An unseen change makes a visible difference." |
| 5 | **The Supply Passage.** Begin navigating independently. | Branching routes, pickups, and limited X/H/Z gates. | "Gates are limited. Consider the next barrier before spending one." | Existing boxes read as abandoned maintenance supplies; repeat the arch motif without marking a correct branch. Completion: "Old supplies carry you further along the escape route." |
| 6 | **The Inner Maze.** Turn separate lessons into confidence. | Fifteen pillars combine familiar states with route and resource planning. | "Use what you have learned: state, phase, and the order of gates." | Weathered marks remain consistent across the larger chamber. Completion: "Beyond the maze, a little daylight reaches the stone." |
| 7 | **The Remote Lock.** Discover that control can reach beyond your path. | CNOT with two pillars initially in 1; the target can be remote. | "CNOT flips its target when the control is 1." | A control/target engraving on a wall, distinct from live entanglement lines. Completion: "One lock can control another." |
| 8 | **The Shared Lock.** Understand why some barriers must be handled together. | A three-pillar entangled state; two CNOTs and H can undo its preparation. | "Entangled pillars share a state. Their individual probabilities aren't the whole picture." | A three-part wall emblem surrounds one arch. Completion: "The shared lock releases. The outer passage is close." |
| 9 | **The Outer Gate.** Apply your understanding to escape. | Controlled H (CHAD), CNOT, and X pickups combine remote control and routing. | "Controlled H applies H to its target when the control is 1." | Warm light frames the final END tile; the completion scene opens onto sky. Final text uses the ending above. |

These concepts are opportunities provided by the puzzles, not assertions about
which solution the player used. Completion text must remain valid for any legal
solution. Level 9 introduces controlled H, so its entry in the gate guide must
be especially clear. RotY is available in the engine but unused by these maps;
it does not need a story chapter.

## Interaction and visual restraint

- **No additional clicks in the main flow.** Start, move, solve, continue.
  No introduction modal, dialogue, typing animation, collectibles, journal,
  quests, new controls, mandatory explanations, or extra ending screen.
- Replace the main menu tagline with a short escape premise. The existing run
  setup supplies one sentence of context: "Follow the old markings to daylight."
- Show a room name and one learning line in the existing upper HUD area. Limit
  the line to about 14 words, wrap within the safe area if needed, and give
  gameplay/hardware notices priority. Restore the learning line after a notice
  expires. No timed reading requirement and no notifications for every gate.
- Reuse the completion screen's existing supporting-text area for the room
  payoff. When intermediate completion screens are disabled, advance immediately;
  the next room's visuals carry the narrative. The existing final summary carries
  the ending. No compensating popups.
- Reuse the existing help surfaces. The H gate guide explains operations in plain
  language; the currently blank How to play page explains the goal, the current
  room's concept, and the difference between the fiction and the simulation.
  Keep room explanations to two short sentences. No automatic opening.
- Keep original pixel art, dark panels, lavender UI accents, and readable type.
  Add a small vocabulary of static pixel-style marks drawn with Pygame primitives:
  arch, route notch, and light wedge. Reuse these across the campaign.
- Place marks on clear wall areas or outside the playable floor. Never cover a
  pillar, tint its state, disguise a pickup, suggest a walkable tile, or create a
  false gate target. Keep decorative marks muted stone colors; reserve warm ivory
  for the final light. State colors and entanglement guides retain their meaning.
- Use shape and placement as well as color. Avoid extra pulsing, particles,
  camera movement, or audio dependencies. The final illustration uses the same
  character and arch motif within the existing completion panel.

At 800 x 600, layout space is constrained: the gate selector begins at y=444,
the header occupies the top 76 pixels, and notices currently appear at y=89.
Do not add a permanent side panel or shrink the board. Pixel fitting and text
wrapping must be checked in the actual game, especially on levels 6 and 9.

The routine reading budget is roughly 250 words across a whole run, spread over
nine rooms and existing screens. All learning and story text can be ignored
without delaying play. A separate story settings page would add more interface
than this proposal warrants.

## Educational wording

Use the story to give the player a purpose and the short learning line to name
what the puzzle demonstrates. Keep gate labels X, H, Z, CNOT, and CHAD visible;
do not replace them with fantasy vocabulary. Explain CHAD as "Controlled H".

Suggested help foundations:

- "Each pillar represents a qubit. In this dungeon, a pillar lets you pass when
  its state is definitely 0."
- "A gate changes a quantum state. The gates you use here do not measure it."
- "Superposition includes amplitudes and relative phase. Two states can have
  the same probabilities for 0 and 1 and still respond differently to H."
- "Entangled pillars have a joint state that cannot be described by a separate
  pure state for each pillar. Controlled gates can create or undo entanglement,
  depending on the starting state."

Avoid the existing README's phrase "apply gates to collapse the pillars":
gate application and measurement are different. Avoid saying that H always
creates superposition or that CNOT always entangles. Do not call the game's
correlation animation a real-time measurement or use its changing appearance as
a story trigger. The decorative phase engraving is an analogy, not a state readout.
Explain the 0/passable convention as a game rule, not a physical law.

The hardware feature remains an optional way to explore a solved circuit. Escape
never depends on an account, a hardware run, or its outcome.

## Codebase findings and implementation plan

The shared Pygame game is in `Qungeon.py`; the browser runs that same code through
`web/main.py`. `scripts/menus.py` owns menus, HUD, completion, settings, and the
blank help page. `scripts/user_interface.py` owns the gate selector and H guide.
`scripts/game_objects.py` applies quantum operations and checks passability from
the simulated state, with a floating-point tolerance. Level JSON describes only
the map, objects, inventory, and initial gates. `scripts/level_solver.py` reasons
about remaining resources. `scripts/quantum_run.py` captures completed circuits
before level changes.

Implement this as content and presentation, using the existing lifecycle:

1. **One small story module: `scripts/story.py`.** A dictionary keyed by level
   ID holds `title`, `learning_line`, `completion_line`, `help_note`, and a short
   list of decorative marks/positions. Include a small drawing helper. No event
   engine, dialogue framework, quantum imports, new dependency, or asset pipeline.
   Use ordinary static content, not generated runtime text. Missing level entries
   fall back to the current numbered UI and plain completion text.
2. **Integrate rendering.** `Game.display_game()` draws wall/floor decorations
   before objects and the player. `MenuUI.draw_hud()` draws the short room text,
   sharing the notice area with priority for existing notices. `MenuUI.draw()`
   uses room payoff text on completion and draws the final arch only for the
   last level of a full run. Reflow that panel's existing text rather than adding
   another overlay. Keep numeric level identity wherever used by hardware views.
3. **Explain in the existing help UI.** Revise gate descriptions in
   `scripts/user_interface.py`; populate `MenuUI`'s help page with concise controls,
   the 0/passable rule, and a contextual room note when opened from play. It must
   still work from the main menu before quantum dependencies load. Help content
   should fit its panel and use existing back/close behavior.
4. **Derive story position from the current level.** A restart redraws the same
   room. It does not replay an introduction. Level selection and `?level=` links
   show the selected room's self-contained context. A single-level completion
   reports that room's success, not that the entire escape was completed. A new
   full run starts the visual journey again. No persistent story progress is
   required; no changes to settings storage or circuit capture are needed.
5. **Align desktop and browser content.** There are nine level files, but
   `web/pyscript.json` only includes 1–8. Bundle level 9 and the story module so
   both versions finish at the same place. The personal quantum server derives
   its public-file list from this manifest. Bump the manifest cache version in
   `index.html` when implementing. Update README's eight-level wording and
   inaccurate quantum descriptions.

The current full-run order comes from sorted numeric level filenames. Preserve
it. Preserve gate counts, maps, physics, solver behavior, and circuit history.
Do not add story hooks to gate application, movement, loot, or resource tracking.
Decorative assets do not enter the quantum world or the solver. Existing saved
hardware maps remain functional without story decoration.

## Delivery and acceptance

First implement the shared text placement and one reusable decoration style on
levels 1, 6, and 9. Inspect the smallest room, the largest maze, and the ending
before filling the remaining content. Then integrate all nine rooms and the help
copy. This is one modest presentation feature, not a new game subsystem.

When implementation is requested, verification should cover:

- Existing puzzles and inventories stay identical; solver/gameplay regressions
  pass. Current shipped-level solver tests only enumerate 1–8: extend coverage to
  9 and replay its solution before relying on it as the shared finale.
- Full run, skipped completion screens, restart, single-level play, direct links,
  pause, loading failure, and hardware notices all keep their existing behavior.
- Missing story data leaves a playable level; main-menu help works before quantum
  imports; no story code alters quantum state or recorded circuits.
- Every shipped level and the story module are present in browser packaging.
- Visual checks at 800 x 600 and a smaller browser display: no clipped copy,
  covered objects, ambiguous decorations, or inaccessible controls.

Success means a beginner can say "I'm finding a way out, and this room teaches
me something about how these pillars work," while a returning player can finish
the same puzzles with no extra button presses or enforced pauses.

Implementation verification: all 216 tests pass, including solution replay for
all nine levels, story rendering without circuit changes, notice priority,
contextual help, completion behavior, browser file coverage, and the local
browser bridge. The shared Pygame screens were rendered and visually inspected
at their native 800 x 600 size. An interactive browser session and smaller
browser viewport were not exercised in this implementation pass.
