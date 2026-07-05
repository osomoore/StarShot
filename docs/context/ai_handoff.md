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
python -m unittest discover -s tests
```

The local server is expected at `http://127.0.0.1:8000`.

## Current Gameplay Slice

Implemented so far:

- Create 2 to 4 player games.
- Build base player decks.
- Submit hidden orders.
- Resolve phases from `give_orders` through cleanup.
- Move ships on an axial hex grid.
- Render a radius-12 hex board in the debug UI.
- Start ships near board corners, 3 hexes in from the corner.
- Preview all three planned action stacks on the hex board.
- Show movement stops, facing, and attack burst previews.
- Implement the basic desperation-deck flow: draw, placement, forward-only desperation moves, and hybrid/modal desperation attacks.
- Implement the normal action-stack Desperate faces for Thrust Ions, Turbo Ions, Homeward Bound, Treasure Hound, Evasive Action, Ace Shot, Deadeye, Nightjammer, Self Destruct, Death Blossom, and Steady Shot.
- Show all non-base desperation cards in one debug picker pile named Desperation.
- Choose Basic/Desperate face at pick time before loading a desperation card into a stack.
- Enforce desperation use-choice constraints in the debug builder: Basic Move in empty/Move stacks, Basic Attack and Desperate Attack Mods only with a targeted attack partner.
- Preview implemented Desperate movement, Warp destinations, damage, target roll, Aim, and always-hit effects.

Not implemented yet:

- Deferred Desperate faces: Hull Repair, Advanced Repair, and All She's Got.
- Full combat damage/shield rules.
- Bauble placement/collection scoring details beyond placeholder phase flow.
- Collision, obstacles, board boundaries, and any rule-specific movement edge cases not yet extracted into code.
- Real player accounts, sessions, or multiplayer lobby UX.
- WebSocket/live updates; current UI is manual/poll-style HTTP.

## Important Conventions

- Hex coordinates are axial `(q, r)`.
- Board radius is `12`.
- Hex direction indexes live in `backend/starshot/rules/hex.py` and are mirrored in `frontend/debug/static/app.js`.
- Ship facing should point toward hex faces, not corners.
- `Turn Left` and `Turn Right` were corrected after visual testing; keep server resolution and JS preview in sync.
- In 2-player games, attack target selection should default to the only opponent where practical.
- Hybrid desperation cards played on their basic face must submit an explicit `mode` of `move` or `attack`; validation uses the selected mode as the card's effective family.
- Desperation cards played on their Desperate face submit `face: "desperate"` and return to the shared Desperation deck after resolution.
- Warp Desperate faces are deterministic until a richer UI exists: Homeward Bound warps to the player's start tile, Treasure Hound warps to the nearest active numbered bauble with a nearest-numbered fallback, and Nightjammer warps to the hex behind the highest-VP active opponent using that ship's facing, then matches that facing. Ties use turn order.

## Collaboration Notes

- Prefer small working increments that can be tried in the browser.
- Keep commits frequent after coherent milestones.
- When changing rules, update or add tests first or alongside the change.
- The debug UI is intentionally a development tool, not final game UX.
