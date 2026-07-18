# StarShot Agent Notes

- Read `docs/context/ai_handoff.md` when starting work in this repo.
- The active browser UI is `frontend/v2/`, served at `/v2`. The root URL redirects there.
- When changing v2 frontend files, bump the matching query string in `frontend/v2/index.html`.
- For current deck/gameplay work and new tests, use the admin-selected active deck set (`/api/v2/admin/deck` shows it). `resources/decks/core_0_2/` is deprecated legacy data; touch it only for explicit legacy compatibility tests.
