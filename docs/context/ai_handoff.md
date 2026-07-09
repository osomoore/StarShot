# StarShot AI Handoff

Use this file first when starting a new chat about this repo.

## Project Goal

StarShot is a server-authoritative, turn-based browser game. The backend owns all rules and game state; the browser client only displays state and submits player intent.

The user is comfortable with Python and C++, only lightly with web/frontend tech. Keep implementation choices Python-first and keep browser code plain unless there is a clear reason to add tooling.

## Current Architecture

- `backend/starshot/rules/`: pure deterministic rules engine.
- `backend/starshot/api/`: FastAPI app and HTTP routes.
- `backend/starshot/persistence/`: SQLite snapshot/event persistence.
- `frontend/debug/`: plain HTML/CSS/JavaScript debug UI served by FastAPI at `/`.
- `tests/`: unittest suite for rules, persistence, serialization, and API.
- `docs/rules/`: canonical rules PDF, extracted text, and implementation checklist.

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

## Current Gameplay Slice

Implemented so far:

- Create 2 to 4 player games.
- Build base player decks (10 cards: 3× Move 1, 4× Move 2, 2× Targeted Attack Aim +1, 1× Targeted Attack Aim +2).
- Submit hidden orders.
- Resolve phases from `give_orders` through cleanup.
- Move ships on an axial hex grid. Move cards turn first, then move forward in the new facing. No U-Turn on base move cards.
- Render a radius-12 hex board in the debug UI.
- Start ships near board corners, 3 hexes in from the corner.
- Preview all three planned action stacks on the hex board.
- Show movement stops, facing, and attack burst previews.
- Implement the 41-card 0.2 desperation deck, including no-basic-face return behavior, hybrid/modal basic faces, and the non-deferred Desperate faces.
- Show all non-base desperation cards in one debug picker pile named Desperation.
- Choose Basic/Desperate face at pick time before loading a desperation card into a stack.
- Enforce desperation use-choice constraints in the debug builder.
- Preview implemented Desperate movement, Side Slip, U-turn movement, Warp destinations, damage, target roll, Aim, always-hit effects, and Lead the Target metadata.
- Mini ship cards show pile counts in Hand, Deck, Discard, Overheat order with distinct icons.
- Target picker opens automatically when a Targeted Attack card is placed; skips if the stack already has a target from another card. Auto-fills in 2-player games.

Current rules target: `docs/rules/rules_0.2.pdf` / `rules_0.2.txt`. All 8 groups of the 0.2 migration are complete.

**Always read `docs/rules/rules_0.2.txt` directly when verifying rules details.** The `rules_implementation.md` file is partially outdated (written against 0.1) and should not be used as the source of truth for card counts, move behavior, or combat math.

Not implemented yet:

- Deferred desperate faces: Reconfigure, Hull Repair, Holdo Maneuver, ScatterShot, Overdrive 2x.
- Real player accounts, sessions, or multiplayer lobby UX.
- WebSocket/live updates; current UI is manual/poll-style HTTP.
- Expansion content: StarCommand, StarTech, StarBreach, StarTrader, Starfall events, captains, NPC ships, bosses, mission systems.

## Important Conventions

- Hex coordinates are axial `(q, r)`.
- Board radius is `14` (code constant `BOARD_RADIUS`).
- Hex direction indexes live in `backend/starshot/rules/hex.py` and are mirrored in `frontend/debug/static/app.js`.
- Ship facing points toward hex faces, not corners.
- Move cards: `turn_left` rotates facing +1 then moves forward; `turn_right` rotates facing -1 (mod 6) then moves forward; `forward` moves straight. No U-Turn.
- Overdrive duplicates the full order as an immediate copy. It does **not** boost card values.
- One `overdrive_seals_pending` counter on `PlayerState` reduces the next round's draw by 1 per overdriven stack.
- Base attack cards require `target_player_id`. Hybrid desperation attack cards on their basic face do not (they pair with a targeted card in the same stack).
- Hybrid desperation cards played on their basic face must submit an explicit `mode` of `move` or `attack`.
- Desperation cards played on their Desperate face submit `face: "desperate"` and return to the shared Desperation deck during cleanup.
- Warp Desperate faces are deterministic: NightJammer warps to the hex behind the highest-VP active opponent using that ship's facing.

## Collaboration Notes

- Prefer small working increments that can be tried in the browser.
- When changing rules, update or add tests first or alongside the change.
- Always verify card counts, names, and behavior against `docs/rules/rules_0.2.txt` before implementing.
- The debug UI is intentionally a development tool, not final game UX.
- 84 tests passing as of last session.
