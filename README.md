# StarShot

StarShot is a server-authoritative, turn-based tactical space combat game.

## Current Status

The project has a rules extraction workflow, a first implementation spec, and an initial Python rules-engine scaffold. The current code supports:

- Creating a 2 to 4 player game state.
- Building each player's base orders deck.
- Validating hidden order submissions.
- Advancing from `give_orders` to `cooldown` once all players submit orders.
- Running a small CLI smoke path.

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

When ready to run the FastAPI app, install the project dependencies:

```powershell
python -m pip install -e .[dev]
uvicorn starshot.api.app:app --app-dir backend --reload
```
