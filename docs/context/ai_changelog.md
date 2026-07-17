# StarShot AI Change Log

Newest entries first. Each AI-agent update should add date/time, a short summary title, build id, agent, and a short summary.

## 2026-07-16 20:47:35 -05:00

- Title: Full app screenshots
- Build ID: `adc4913`
- AI agent: Codex (GPT-5)
- Summary:
  - Changed bug-report screenshots from board-only captures to a full visible app-window snapshot with the feedback popup hidden.
  - Replaces live canvases in the snapshot with image data first, then scales the final capture to a max 1200px edge for storage.
  - Verified with `node --check frontend/v2/static/lobby.js`, backend `py_compile` sanity checks, and `git diff --check` (CRLF warnings only).

## 2026-07-16 20:41:19 -05:00

- Title: Feedback admin cleanup
- Build ID: `adc4913`
- AI agent: Codex (GPT-5)
- Summary:
  - Made bug-report screenshot capture smaller and more explicit when capture fails; admin now shows a screenshot section for every bug report, including a no-screenshot note.
  - Removed the Render/Reddit warning alert and message from the feedback form while keeping the Reddit clipboard copy action.
  - Added admin controls and endpoints to delete one feedback entry or all feedback entries for a user.
  - Verified with `node --check` on `admin.js` and `lobby.js`, plus `python -m py_compile` on touched v2 backend modules.

## 2026-07-16 20:34:45 -05:00

- Title: Screenshot admin actions
- Build ID: `adc4913`
- AI agent: Codex (GPT-5)
- Summary:
  - Added admin feedback controls to open bug-report board screenshots full-size in a new tab or download them as PNG files.
  - Verified with `node --check frontend/v2/static/admin.js`.

## 2026-07-16 20:26:23 -05:00

- Title: Battle UX fixes
- Build ID: `adc4913`
- AI agent: Codex (GPT-5)
- Summary:
  - Added overdrive-aware Hull Repair/Reconfigure component counts in rules validation/resolution and the v2 order picker.
  - Added player ship damage-lane labels in the expanded ship modal, enemy board-click ship details with hover distance text, lobby expansion chips, and a desktop 2x mini boss attack-stack widget.
  - Added bug-report board screenshots with admin display, and clarified/previewed Drifter's pre-bauble cleanup drift.
  - Verified with `node --check` on `game.js`, `lobby.js`, `board.js`, and `admin.js`; `python -m py_compile` on touched backend modules; `python -m unittest tests.test_desperation_integration`; and `git diff --check` (CRLF warnings only).

## 2026-07-16 19:50:07 -05:00

- Title: Player ship designer
- Build ID: `9f629c1bf382`
- AI agent: Claude Fable 5
- Summary:
  - Added the Player Ship Designer so players can create battle-ready radius-2 ship layouts with budgeted shields, draw, core armor, Signal Jammers, and Targeting Sensors.
  - Added player ship layout compilation/storage, per-player and admin ship design APIs, lobby ship selection, Build New Content hub support, and a bundled `vanguard` example design.
  - Updated engine, StarBreach, serialization, card draw, ship rendering, and match creation/join/launch validation to use per-ship compiled layouts and jammer/sensor bonuses.
  - Verification recorded in the handoff: new coverage in `tests/test_player_ships.py`.

## 2026-07-16 17:10:42 -05:00

- Title: StarBreach docking bays and public bosses
- Build ID: `39022dbc038e`
- AI agent: Codex (GPT-5)
- Summary:
  - Added Docking Bay boss components. Docking Bays launch enemy craft during their linked action stack; progression spawn steps now launch during the linked Docking Bay stack and require both an active tier and at least one intact Docking Bay.
  - Hid the stock StarBreacher from new-game selection. StarBreach match creation now requires a battle-ready boss design or configured default, and admins can mark the current global boss design as public/default from the Boss Designer.
  - Renamed visible Shield Regions language to Ship Regions, added an Unshielded region shortcut, color-coded battle-board shield generators by their powered region, and remembered Fighting Ace lane preferences per boss region.
  - Verified with `python -m unittest discover -s tests` (256 tests) and `node --check` for `bossdesigner.js`, `game.js`, `lobby.js`, and `admin.js`; bumped v2 cache strings for changed frontend scripts.

## 2026-07-16 16:25:51 -05:00

- Title: StarBreach roles, previews, print layout, passive boss components
- Build ID: `6fac5c95bd58`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Bauble Runner's doubled basic movement now shows in the order preview path/ghost; overdrive copies stay undoubled in copy-action mode, matching the engine.
  - StarBreach role selection: the host picks a role at launch ("Your Role" in the lobby expansion box) and joiners pick from unclaimed roles in a popup; match seats store `star_breach_role` (new column), preferences flow through `GameConfig.star_breach_role_preferences`, and unrequested roles still deal round-robin so all four stay in play. Claimed roles show on open-raid rows.
  - Boss print sheet reworked: the ship box now spans the full page width, the progression track prints as a horizontal row of squares (empty = filler; letter/number badges for linked elements: C/E + stack, B core, F spawns, J/T abilities), and the Fleet / Table Aid section prints below everything else with per-stage fleet actions and per-square progression notes.
  - New passive boss components: Signal Jammer (+2 boss defense while intact) and Targeting Sensors (+2 boss Aim while intact). No action-stack elements; also grantable via the new "Ability link" progression step. Designer tools/badges, spec compiler (`tier_abilities`), engine hooks (volley threshold + boss aim), serialization (`boss_defense_bonus`/`boss_aim_bonus`), and the player shot preview all honor them.
  - Verified with `python -m unittest discover -s tests` (256 tests, 8 new) and `node --check` on the four modified JS files; bumped cache strings for api/lobby/game/bossdesigner scripts.

## 2026-07-16 13:35:53 -05:00

- Title: Mobile controls right align
- Build ID: `68122f9a8bd2`
- AI agent: Codex (GPT-5)
- Summary:
  - Right-aligned the phone battle-board top control row while keeping center, replay, and Feedback together.
  - Bumped the v2 pirate stylesheet cache string.
  - Verified with `git diff --check`.

## 2026-07-16 13:28:02 -05:00

- Title: StarBreach mobile print fixes
- Build ID: `68122f9a8bd2`
- AI agent: Codex (GPT-5)
- Summary:
  - StarBreach status rollup no longer opens the boss board; the boss activity tracker remains the damage-board entry point.
  - Mobile battle controls now put center, replay, and Feedback in one top row; the pause-after-actions control uses the same square rollup style as the scenario info chips.
  - Boss print sheets now default to lane arrows, action stacks, progression, and fleet aids only; action stacks print every item, core badges use a compact symbol, and the removed lane-helper text no longer appears.
  - Progression action-link rows now use only action-number/action-type dropdowns with a single column header.
  - Verified with `node --check frontend/v2/static/game.js`, `node --check frontend/v2/static/bossdesigner.js`, and `git diff --check`.

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
