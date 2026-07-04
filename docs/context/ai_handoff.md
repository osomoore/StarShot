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
- Show hybrid desperation cards in their own debug picker column with light-blue styling and a mode chooser.

Not implemented yet:

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

## Collaboration Notes

- Prefer small working increments that can be tried in the browser.
- Keep commits frequent after coherent milestones.
- When changing rules, update or add tests first or alongside the change.
- The debug UI is intentionally a development tool, not final game UX.
