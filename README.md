# StarShot

StarShot is a server-authoritative, turn-based tactical space combat game.

## v2 — Void Corsairs (online multiplayer)

`/v2` is the revamped space-pirate client + multiplayer stack, built on the same
rules engine but using the **core 0.3** decks (v1 stays on core 0.2 via the
process default; v2 selects its deck set per request with
`starshot.rules.deck_data.deck_set_override`).

- **Play:** `https://david.cybrwzrds.com/v2` (site gate: HTTP Basic auth, see below)
- **Frontend:** `frontend/v2/` — vanilla JS SPA. Starfield + canvas battle
  effects (lasers, shields, explosions, warp), physical card deck/hand-fan
  order builder, hex board with replay animation, 2.5s auto-refresh polling.
- **Backend:** `backend/starshot/v2/` — accounts (pbkdf2 + cookie sessions),
  quick-match queue, open lobbies, vs-AI matches, per-viewer redacted game
  views (opponents' hands/decks/orders and the RNG cursor are never sent),
  and server-side AI pilots.
- **AI pilots** (`backend/starshot/v2/ai.py`): Salvage Captain Morrigan
  (bauble runner), Corsair Blackvane (hunter-killer), Gunner Redbeard
  (blaster). They use the engine's own `interpret_card` for planning, predict
  target movement from actual history, and price overdrive for the 0.3
  no-overheat rules.
- **API:** everything under `/api/v2/...` (auth, lobby, matches, games).
  Order submission is bound to the signed-in session — clients cannot act for
  other players.
- **Site password gate:** the Apache vhost proxies the whole site to this app,
  so the Basic-auth gate lives in FastAPI (`STARSHOT_SITE_AUTH=on`, users in
  `.htpasswd` at the repo root, `{SHA}` format). `docs`-root
  `.htaccess`/`.htpasswd` files also exist for any future disk-served content.
- **Tests:** `tests/test_v2_api.py` covers auth, redaction, matchmaking,
  security, and full games vs AI.

After changing backend code, the container picks it up automatically
(`uvicorn --reload`); the first deploy of this setup needs one
`docker compose up -d --force-recreate` (or `docker restart starshot` if only
code changed).

## Current Status

The project has a rules extraction workflow, a first implementation spec, and an initial Python rules-engine scaffold. The current code supports:

- Creating a 2 to 4 player game state.
- Building each player's base orders deck.
- Validating hidden order submissions.
- Advancing from `give_orders` to `cooldown` once all players submit orders.
- Persisting local games in SQLite.
- Running CLI smoke paths for game creation, listing, showing, and order submission.

## Rules Sources

- Canonical PDF: `docs/rules/rules_0.1.pdf`
- Extracted text: `docs/rules/rules_0.1.txt`
- Implementation notes: `docs/rules/rules_implementation.md`
- Future-chat handoff notes: `docs/context/ai_handoff.md`
- Current implementation status: `docs/context/implementation_status.md`

Regenerate extracted text after PDF changes:

```powershell
python tools\extract_rules_pdf.py
```

If `pdfplumber` is missing:

```powershell
python -m pip install --target .tmp_pdf_extract pdfplumber
```

## Local Development

### Easy Windows Shortcuts

Run a complete CLI demo:

```powershell
.\run_cli_demo.bat
```

Install server/test dependencies:

```powershell
.\install_dev_deps.bat
```

Start, check, or stop the local server:

```powershell
.\start_server.bat
.\server_status.bat
.\stop_server.bat
```

The server runs at `http://127.0.0.1:8000` and writes logs to `.starshot\server.log`. Open that URL in a browser; it redirects to the active `/v2` game UI.

The v2 UI can:

- Sign in or register a local test captain.
- Create and join battles with human or AI seats.
- Build and seal action stacks.
- Replay battles and export debug logs.

### Manual Commands

Run rules tests without installing dependencies:

```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s tests
```

Run a CLI smoke test:

```powershell
$env:PYTHONPATH='backend'
python -m starshot.cli new-game --players red blue --seed 3
```

Use an explicit local database path:

```powershell
$env:PYTHONPATH='backend'
python -m starshot.cli --db .starshot\games.sqlite3 new-game --players red blue --seed 3
python -m starshot.cli --db .starshot\games.sqlite3 list-games
python -m starshot.cli --db .starshot\games.sqlite3 show GAME_ID
python -m starshot.cli --db .starshot\games.sqlite3 orders GAME_ID red .\orders-red.json
```

Example orders JSON:

```json
{
  "stacks": [
    {
      "action_number": 1,
      "seal_mode": "sealed",
      "cards": [{ "card_id": "controlled_move_1_a" }]
    },
    {
      "action_number": 2,
      "seal_mode": "sealed",
      "cards": []
    },
    {
      "action_number": 3,
      "seal_mode": "overdrive",
      "cards": [{ "card_id": "controlled_move_2_a" }]
    }
  ]
}
```

When ready to run the FastAPI app, install the project dependencies:

```powershell
python -m pip install -e .[dev]
uvicorn starshot.api.app:app --app-dir backend --reload
```

Useful local endpoints:

- `GET /`
- `GET /api/health`

Deck definitions live in `resources/decks/core_0_2/`. See `docs/context/deck_data.md` for the side-based card format and custom deck-set startup options.
- `GET /api/games`
- `POST /api/games`
- `GET /api/games/{game_id}`
- `POST /api/games/{game_id}/orders`
