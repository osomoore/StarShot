# StarShot AI Change Log

Newest entries first. Each AI-agent update should add date/time, a short summary title, build id, agent, and a short summary.

## 2026-07-16 11:01:00 -05:00

- Title: Logged deck rework
- Build ID: `56c5763d5965`
- AI agent: Codex (GPT-5)
- Summary:
  - Added this changelog note for the user's new deck rework.
  - No code changes or verification were performed for this entry.

## 2026-07-16 10:42:44 -05:00

- Title: Standardized changelog titles
- Build ID: `c43deb1bf222`
- AI agent: Codex (GPT-5)
- Summary:
  - Updated the AI handoff directive so each change log entry must include a short summary title of just a few words.
  - Backfilled titles on existing AI change log entries.

## 2026-07-16 10:36:23 -05:00

- Title: Added server/developer deck source resolution
- Build ID: `c43deb1bf222`
- AI agent: Codex (GPT-5)
- Summary:
  - Extended the bundled/runtime content split to deck sets: developer decks stay under `resources/decks/`, while server-created/imported/edited decks default to `.starshot/content/decks/custom/`.
  - Deck scanning now merges bundled and runtime roots, preserves same-id conflicts with `_developer` / `_server` aliases, and materializes aliases into runtime copies before activation/use so game `deck_set_id` bindings stay stable.
  - Added local admin settings for default StarBreach boss ship and allowed global StarBreach boss ships for new games, with lobby defaults and server-side enforcement.
  - Updated admin UI controls and cache-busting query strings for the new settings.
  - Verification included JS syntax checks for `admin.js` and `lobby.js`, `tests.test_v2_api`, and the full unittest suite (`248 tests OK`).

## 2026-07-16 10:18:27 -05:00

- Title: Added server/developer boss storage
- Build ID: `99c32d8d62ca`
- AI agent: Codex (GPT-5)
- Summary:
  - Changed boss design storage so bundled developer designs remain in `resources/boss_designs/`, while all server/admin/player saves write to `.starshot/content/boss_designs/`.
  - Merged bundled and runtime boss libraries at load/list time; conflicting same-id designs are preserved by exposing the older version with a `_developer` or `_server` suffix.
  - Added tests for runtime saves, bundled reads, and conflicting bundled/runtime boss versions.
  - Verification included `tests.test_boss_designer`, `tests.test_boss_spec`, and `tests.test_v2_api`; full-suite verification followed with `247 tests OK`.

## 2026-07-16 09:31:09 -05:00

- Title: Added AI change log viewer
- Build ID: `535b6949cea2`
- AI agent: Codex (GPT-5)
- Summary:
  - Added this AI change log and documented the handoff convention.
  - Added an admin-only API/UI surface for viewing the log from the v2 admin console.
  - Current implementation state after this conversation: StarBreach boss design uses Cannon/Engine terminology; designed fleet actions use numeric move/shoot counts; stack viewer labels are compact one-line component/track/fleet rows; Bauble Runner doubles basic movement without Overdrive re-doubling, grants no movement defense, and still gives all players bonus draws when collecting a Bauble; boss progress advances on shield/hull hits once per source per action burst.
  - Verification during the conversation included focused StarBreach/boss designer/v2 API tests, JS syntax checks for `bossdesigner.js`, and the full unittest suite (`245 tests OK`).
