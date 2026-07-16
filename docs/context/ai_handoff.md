# StarShot AI Handoff

Use this file first when starting a new chat about this repo.

## Project Goal

StarShot is a server-authoritative, turn-based browser game. The backend owns all rules and game state; the browser client only displays state and submits player intent.

The user is comfortable with Python and C++, only lightly with web/frontend tech. Keep implementation choices Python-first and keep browser code plain unless there is a clear reason to add tooling.

## Current Architecture

- `backend/starshot/rules/`: pure deterministic rules engine.
- `backend/starshot/api/`: FastAPI app and HTTP routes.
- `backend/starshot/persistence/`: SQLite snapshot/event persistence.
- `frontend/v2/`: active browser interface served by FastAPI at `/v2`; `/` redirects there.
- `tests/`: unittest suite for rules, persistence, serialization, and API.
- `docs/rules/`: canonical rules PDF, extracted text, and implementation checklist.
- `resources/decks/core_0_2/`: default human-editable TOML deck data.

## How To Run

Windows shortcuts:

- `install_dev_deps.bat`
- `start_server.bat`
- `server_status.bat`
- `stop_server.bat`
- `run_cli_demo.bat`

Useful direct test command:

```powershell
set PYTHONPATH=backend
python -m unittest discover -s tests
```

The local server is expected at `http://127.0.0.1:8000`.

To start with a custom deck set:

```powershell
python scripts\server_control.py start --deck-set path\to\deck_set
```

## Current Gameplay Slice

Implemented so far:

- Create 2 to 4 player games.
- Build base player decks (10 cards: 3× Move 1, 4× Move 2, 2× Targeted Attack Aim +1, 1× Targeted Attack Aim +2).
- Submit hidden orders.
- Resolve phases from `give_orders` through cleanup.
- Move ships on an axial hex grid. Move cards turn first, then move forward in the new facing. No U-Turn on base move cards.
- Render a radius-12 hex board in the v2 UI.
- Start ships near board corners, 3 hexes in from the corner.
- Preview all three planned action stacks on the hex board.
- Show movement stops, facing, and attack burst previews.
- Implement the 41-card 0.2 desperation deck, including no-basic-face return behavior, hybrid/modal basic faces, and the non-deferred Desperate faces.
- Show all non-base desperation cards in one debug picker pile named Desperation.
- Choose Basic/Desperate face at pick time before loading a desperation card into a stack.
- Enforce desperation use-choice constraints in the debug builder.
- Preview implemented Desperate movement, Side Slip, U-turn movement, Warp destinations, damage, target roll, Aim, always-hit effects, and Lead the Target metadata.
- Untargeted attack cards can be ordered alone; they shoot straight ahead at the first enemy on the forward line. If paired with a targeted attack, they join that volley and share its target.
- Mini ship cards show pile counts in Hand, Deck, Discard, Overheat order with distinct icons.
- Target picker opens automatically when a Targeted Attack card is placed; skips if the stack already has a target from another card. Auto-fills in 2-player games.
- After choosing card 1 for an order, the debug builder advances to card 2 after any required move/target choice. Move-choice panels only show orientations supported by the selected card.

Current rules target: `docs/rules/rules_0.2.pdf` / `rules_0.2.txt`. All 8 groups of the 0.2 migration are complete.

Deck data notes live in `docs/context/deck_data.md`. New games store `deck_set_id`; order submission and resolution reject games whose deck set does not match the active server catalog.

**Always read `docs/rules/rules_0.2.txt` directly when verifying rules details.** The `rules_implementation.md` file is partially outdated (written against 0.1) and should not be used as the source of truth for card counts, move behavior, or combat math.

Implemented expansions:

- StarCommand (`star_command`): captains + Starfall events.
  Backend behavior module: `backend/starshot/rules/star_command_engine.py`;
  content data: `backend/starshot/rules/star_command.py`.
- StarBreach (`star_breach`): cooperative Bauble Breacher boss scenario.
  Rules source: `docs/rules/StarBreach_Expansion.txt` + `docs/rules/starbreach_boss_scenario_01.jpg`.
  Backend behavior module: `backend/starshot/rules/star_breach_engine.py`;
  content data: `backend/starshot/rules/star_breach.py` (boss layout/lanes/roles data);
  registry: `backend/starshot/rules/expansion_modules.py`; state in
  `GameState.star_breach` (`StarBreachState` in models.py); tests in
  `tests/test_star_breach.py`. Player attack targets in co-op are strings:
  `boss:<area>`, `craft:<id>`, or an ally player id (Engineer repairs only).
  Boss half-phases resolve at the start of player actions 1/2/3 (0.5/1.5/2.5)
  and at the start of award_baubles (3.5 + StarBreach). 1-4 players allowed.
  The boss occupies 3 board hexes (nose + two flanks, facing = last movement
  direction); its detailed hull is an internal damage board (popup in the UI).
  Each active boss slot performs exactly one action; progress tiers reached
  mid-round only power slots from the next round (`active_tiers`). Shields:
  nose 1 charge (intrinsic), other arcs 3, each powered by one nose generator.
  The host may choose the Prey at game creation, including an AI seat. AI
  personalities do not change because they are the Prey; in co-op, Salvage
  runs baubles, Corsair prioritizes hunter-killer craft, and Gunner prioritizes
  the boss. The v2 side panel uses tabs for Fleet and Log.

Admin tools:

- Boss Ship Designer (admin console tab "Boss Designer"): hex editor for custom
  StarBreach-style bosses — hull tiles (generic / shield gen / cannon /
  engine / core), shield regions with a powering generator and a
  configurable number of damage lanes (1-12 per region via a number ticker,
  default 7; the die is lane_count + 1 sides with roll 1 always a glancing
  blow — `region.lane_count` in the design, `lane_die` in the compiled spec;
  each lane has an entry face), and a progression track
  (triggers + filler/action-link/breacher-link/ability-trigger steps).
  Also: per-region shield start/max charges, a Behavior tab (boss AI —
  hunter-killer only for now; fleet craft count/type/HP/AI and a tick-box
  grid of fleet actions per boss stage), JSON download/upload of designs,
  and delete-with-confirmation. Designs are JSON documents in
  `resources/boss_designs/`. Kept insulated: schema/validation/storage in
  `backend/starshot/v2/boss_designs.py` (no FastAPI), routes in
  `backend/starshot/v2/boss_designer_api.py`, UI in
  `frontend/v2/static/bossdesigner.js` + `bossdesigner.css`; tests in
  `tests/test_boss_designer.py`. Lane assignment supports a "Renumber lanes
  left-to-right" button, an "allow a second lane on a laned hex" tick box
  (two lanes may share a hex with different rolls/faces), and partial lane
  sets: regions need at least one lane, and unassigned lane numbers are
  rerolled at runtime (see the reroll loop in `_resolve_volley_vs_boss`).
  An "Action Stacks" mode shows one column per boss stack (0.5-3.5 +
  StarBreach) with draggable, equal-height columns of cards for Firing
  Cannons / Engines / action-link steps (drop on a column to reassign
  the stack); the progression track sits above it as two balanced columns
  joined by a wrap-around arrow, chips drag-reorder, hovering a chip lights
  up its stack card, and hovering a stack header lights up that stack's
  components in the mini ship view (right side panel). Progression rows in
  the Progression tab also drag-reorder via the ⠿ handle. The player-facing
  designer opens from the lobby "🛠 Build New Content" topbar button (also
  the "My Bosses" button in the StarBreach lobby options); the button
  twinkles until first clicked, a one-time lobby popup introduces it, and a
  one-time how-to overlay shows on first entry (localStorage flags
  `ss_build_content_*` / `ss_bossdesigner_howto_seen`). Print Sheets mode
  has tone (color/B&W), a hex-coordinate toggle, a ship-scale slider
  (50-200%), and per-type card markings (C/P/F/B badges; B&W uses hatch/dot/
  crosshatch pattern fills to tell component / progression / fleet /
  breacher abilities apart).
- Designed bosses are playable: `backend/starshot/rules/star_breach_spec.py`
  compiles a design into a JSON "boss spec" (hull, areas = shield regions,
  damage-lane rays, phases from cannons / engines / progression
  steps, fleet, triggers); `star_breach_engine.py` and serialization read all
  boss data through its accessors. `spec_for(sb)` returns the stock scenario
  when `StarBreachState.boss_spec` is None, so base games are untouched. The
  spec is stored in game state, so design edits never affect games in flight.
  Match creation accepts `star_breach_boss_design_id` (matches table column,
  lobby "StarBreach Boss" dropdown via public `GET /api/v2/boss-designs`);
  only problem-free designs are offered/accepted — incomplete designs can be
  saved but not played. Tests in `tests/test_boss_spec.py`.

Not implemented yet:

- Deferred desperate faces: Reconfigure, Hull Repair, Holdo Maneuver, ScatterShot, Overdrive 2x.
- Real player accounts, sessions, or multiplayer lobby UX.
- WebSocket/live updates; current UI is manual/poll-style HTTP.
- Expansion content: StarTech, StarTrader, additional StarBreach scenarios (Boss Deck, Boss Tier abilities, Breacher Core objectives, Bauble Runner/Blaster fleet behaviors), NPC missions.

## Important Conventions

- Hex coordinates are axial `(q, r)`.
- Board radius is `14` (code constant `BOARD_RADIUS`).
- Hex direction indexes live in `backend/starshot/rules/hex.py` and are mirrored in `frontend/v2/static/board.js`.
- Ship facing points toward hex faces, not corners.
- Move cards: `turn_left` rotates facing +1 then moves forward; `turn_right` rotates facing -1 (mod 6) then moves forward; `forward` moves straight. No U-Turn.
- Overdrive duplicates the full order as an immediate copy. It does **not** boost card values.
- One `overdrive_seals_pending` counter on `PlayerState` reduces the next round's draw by 1 per overdriven stack.
- Base attack cards require `target_player_id`. Untargeted desperation attacks do not; alone they shoot forward, and with a targeted partner they share the partner's target.
- After each component damage instance, intact ship components that are no longer connected to the Command Bridge through intact adjacent components are knocked off: they are added to `destroyed_components`, no longer block future damage lanes, and award 1 VP total for that knock-off event.
- Hybrid desperation cards played on their basic face must submit an explicit `mode` of `move` or `attack`.
- Desperation cards played on their Desperate face submit `face: "desperate"` and return to the shared Desperation deck during cleanup.
- Warp Desperate faces are deterministic: NightJammer warps to the hex behind the highest-VP active opponent using that ship's facing.

## Collaboration Notes

- Prefer small working increments that can be tried in the browser.
- When changing rules, update or add tests first or alongside the change.
- Keep expansion-specific rules in expansion modules and register them through
  `backend/starshot/rules/expansion_modules.py`. The base `engine.py` should
  call installed active expansion hooks rather than embedding expansion logic.
  This is intentional so partial work on an inactive expansion does not break
  base games or other expansions.
- Always verify card counts, names, and behavior against `docs/rules/rules_0.2.txt` before implementing.
- `/v2` is the active browser interface. The legacy non-v2 frontend has been removed; do not recreate it.
- 227 tests passing as of last session (2 API test modules require `fastapi` installed).
- Replays rewind and animate StarBreach fleet craft (`replayFleetPose` in
  `game.js`, `options.fleetPose` in `board.js`), so lasers and impacts land
  where units actually stood at that moment.
- The boss token does not push other ships out of its way when it moves; it
  can share a hex with player ships and fleet craft.
