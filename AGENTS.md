# StarShot Agent Notes

- Read `docs/context/ai_handoff.md` when starting work in this repo.
- When changing frontend files under `frontend/debug/`, bump the cache-buster query string in `frontend/debug/index.html` for any changed static assets, especially `/static/app.js?v=...`. The browser can keep serving old JavaScript even after the tab is closed.
