# StarShot AI Change Log

Newest entries first. Each AI-agent update should add date/time, a short summary title, build id, agent, and a short summary.

## 2026-07-16 12:48:31 -05:00

- Title: Desktop battle board side stacks
- Build ID: `c145d39cf929`
- AI agent: Claude (Fable 5)
- Summary:
  - `battleBoardCircuitSVG` now takes a layout mode: desktop ("right") hangs the action stacks off the hull's starboard side, vertically centered, with traces routing right through a vertical bus band and dropping down into chips; mobile ("below") keeps the previous under-hull layout unchanged. Mode picked from `data-device`.
  - Desktop bottom row reorganized into Shield Regions | progress track (center, wide) | Legend (`.boss-modal-bottom`); on phones it stacks with the track first, right under the map, preserving the existing mobile order.
  - Fixed a phone flexbox bug where the desktop side-panel `flex-basis: 260px` became *height* in column direction (a big dead gap before the Legend), and switched the phone modal from `100vw` to `100%` so a scrollbar can't force horizontal overflow.
  - Verified via the headless harness on extracted real functions in both device modes: desktop viewBox widens right (731×310) while phone stays tall (386×420), bottom-row ordering asserts per device, progression connectors intact, zero horizontal overflow; screenshots reviewed for both.

## 2026-07-16 12:36:47 -05:00

- Title: Vector-sharp zoom, bigger board fonts
- Build ID: `c145d39cf929`
- AI agent: Claude (Fable 5)
- Summary:
  - Battle-board zoom/pan now works by shrinking/shifting the SVG viewBox instead of a CSS transform — the browser re-renders the vectors at every zoom level, so the board stays sharp at 8x (CSS scale was blowing up a rasterized bitmap, hence the blur). Cursor-anchored wheel zoom uses `getScreenCTM` with a one-pass correction (measured drift 0.01 board units).
  - Hull component labels now scale with hex size (0.72×, so 14.4px on the modal's size-20 hexes vs. the old fixed 8.5px); action chip text bumped 9.5 → 11px and phase labels 12 → 14px.
  - Dragging can no longer start a text selection that eats subsequent drags: `user-select: none` on the modal and map, plus `preventDefault` on pointerdown/dragstart.
  - Verified via the headless harness on extracted real functions: no CSS transform present, viewBox shrinks 1.3225× after two wheel steps, pan shifts the viewBox window, fonts assert at 14.4/11, connectors intact; screenshot reviewed.

## 2026-07-16 12:18:57 -05:00

- Title: Wide battle board, move-first action order
- Build ID: `c145d39cf929`
- AI agent: Claude (Fable 5)
- Summary:
  - Battle-board popup is now double-wide (`min(1440px, 96vw)`, via `.picker.boss-board-modal` to out-rank the later `.picker` max-width cap); the map's default zoom returns to 1x since fit-to-view is now large. Zoom/drag/pinch retained.
  - On phones the battle board fills the whole window (100vw × 100dvh, flat corners) with the map flexing to consume the height the track/legend leave over.
  - Action stacks are two chips wide (left-to-right, top-to-bottom) so they're half as tall; hull traces jog with a per-sub-column stagger so two drops into the same row don't overlap.
  - Rules change: within each boss action stack, move actions now resolve before attacks (stable sort in `active_phase_slots`), and boss fleet craft likewise move before they shoot (`fleet_action_kinds`). Full unittest suite passes (248 tests OK).
  - Chip display order mirrors resolution — active moves, then active attacks — and not-yet-active slots sink to the bottom of the stack until they come online.
  - Verified via the headless-browser harness on the extracted real functions: modal width 1440, stack order (move → attack → offline), fleet move-before-attack, 3 rows for a 7-chip stack, progression connectors intact; screenshot reviewed. Caught and fixed the `.picker` max-width specificity clash this way.

## 2026-07-16 12:04:44 -05:00

- Title: Battle board zoom, hover circuits, track polish
- Build ID: `c145d39cf929`
- AI agent: Claude (Fable 5)
- Summary:
  - Boss battle-board map is now a zoom/pan viewport: opens at 2x scale, mouse wheel zooms toward the cursor, dragging pans, and two-finger pinch zooms/pans on touch devices (`wireBossMapZoom`).
  - Hovering a hull component or an action chip now brightens the full circuit together: the trace, the chip, the hull hex, and (for progression actions) the matching box on the progress track. The whole hull hex is a hover target, not just its center.
  - Fleet action chips no longer carry any hover linkage — they don't power or get powered by anything.
  - Progress-track ability boxes stay gray until their tier comes online, then take the color of the ability kind they grant (matching the chips); the wrapped track rows get extra spacing and a small ↴ loop arrow on the last box of each row.
  - Progression connectors truncate (faded, no arrowhead) at the map edge when their chip is panned/zoomed out of view, and redraw as the map transforms.
  - Verified via a headless-browser harness built from the extracted real functions: hover class propagation, gray/online box colors, single wrap marker, 2x default transform, wheel zoom, and connector counts all asserted; plus a screenshot review.

## 2026-07-16 11:47:29 -05:00

- Title: Boss battle board circuit rework
- Build ID: `c145d39cf929`
- AI agent: Claude (Opus 4.8)
- Summary:
  - Removed the descriptive legend paragraph from the boss battle-board modal and enlarged the hull rendering (bigger hex size, viewBox sized to content, `max-height:70vh`) so the ship reads clearly on mobile.
  - Reworked the action circuit from side rows to vertical columns below the hull: traces route through a per-column gutter (no longer crossing stacked chips) and drop into each chip with a downward arrowhead.
  - Chips and traces are now colored by ability kind (attack/move/breacher/…) instead of by phase; phase column headers dropped the redundant kind glyph since each chip already carries it.
  - Hull tiles in the modal are tinted by component type (cannon/engine/shield-gen/core) with a pinned symbol font to fix stray "?" glyphs; shield arcs still carry region grouping.
  - Progress-track boxes enlarged and made to wrap at panel width; progression (tier) action chips no longer trace to a hull hex — a new DOM overlay draws a circuit line from each track box to its tier chip.
  - Verified by extracting the real hull/circuit SVG builder functions and running them against a mock designed boss in Node, then headless-rendering the output to confirm correct geometry, labels, and trace counts.

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
