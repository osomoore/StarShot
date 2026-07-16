# StarShot AI Change Log

Newest entries first. Each AI-agent update should add date/time, build id, agent, and a short summary.

## 2026-07-16 10:18:27 -05:00

- Build ID: `99c32d8d62ca`
- AI agent: Codex (GPT-5)
- Summary:
  - Changed boss design storage so bundled developer designs remain in `resources/boss_designs/`, while all server/admin/player saves write to `.starshot/content/boss_designs/`.
  - Merged bundled and runtime boss libraries at load/list time; conflicting same-id designs are preserved by exposing the older version with a `_developer` or `_server` suffix.
  - Added tests for runtime saves, bundled reads, and conflicting bundled/runtime boss versions.
  - Verification included `tests.test_boss_designer`, `tests.test_boss_spec`, and `tests.test_v2_api`; full-suite verification followed with `247 tests OK`.

## 2026-07-16 09:31:09 -05:00

- Build ID: `535b6949cea2`
- AI agent: Codex (GPT-5)
- Summary:
  - Added this AI change log and documented the handoff convention.
  - Added an admin-only API/UI surface for viewing the log from the v2 admin console.
  - Current implementation state after this conversation: StarBreach boss design uses Cannon/Engine terminology; designed fleet actions use numeric move/shoot counts; stack viewer labels are compact one-line component/track/fleet rows; Bauble Runner doubles basic movement without Overdrive re-doubling, grants no movement defense, and still gives all players bonus draws when collecting a Bauble; boss progress advances on shield/hull hits once per source per action burst.
  - Verification during the conversation included focused StarBreach/boss designer/v2 API tests, JS syntax checks for `bossdesigner.js`, and the full unittest suite (`245 tests OK`).
