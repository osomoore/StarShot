# StarShot

StarShot is a server-authoritative, turn-based tactical space combat game.

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

The server runs at `http://127.0.0.1:8000` and writes logs to `.starshot\server.log`.

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
      "cards": [{ "card_id": "move_1_a" }]
    },
    {
      "action_number": 2,
      "seal_mode": "sealed",
      "cards": []
    },
    {
      "action_number": 3,
      "seal_mode": "overdrive",
      "cards": [{ "card_id": "move_2_a" }]
    }
  ]
}
```

When ready to run the FastAPI app, install the project dependencies:

```powershell
python -m pip install -e .[dev]
uvicorn starshot.api.app:app --app-dir backend --reload
```
