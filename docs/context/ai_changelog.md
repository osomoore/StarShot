# StarShot AI Change Log

Newest entries first. Each AI-agent update should add date/time, a short summary title, build id, agent, and a short summary.

## 2026-07-18 17:18:13 -05:00

- Title: Lobby setup layout polish
- Build ID: `b3934bb`
- AI agent: Codex
- Summary:
  - Split the lobby into desktop setup, raids/history, and existing scoreboard columns; on mobile, Captains on Deck now appears above Set Sail while the scoreboard remains separate.
  - Reordered mobile setup controls to Flesh and Blood Foes, Digital Scallywags, then Advanced Game Features.
  - Reworked Digital Scallywags buttons into compact desktop rows and mobile cards with the AI name full-width on top, then icon, blurb, and count below; increased the mobile AI name size to 15px.
  - Increased Flesh and Blood Foes seat-button numbers and tuned Experience Level button text/wrapping for desktop and mobile.
  - Bumped v2 pirate CSS and lobby JS query strings in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/lobby.js` and markup/CSS diff inspection.

## 2026-07-18 16:18:11 -05:00

- Title: Lobby expansion panels
- Build ID: `c706f57`
- AI agent: Codex
- Summary:
  - Reworked the lobby battle setup order with a "Flesh and Blood Foes" seat panel above Digital Scallywags and kept Advanced Game Features folding out below it.
  - Added a StarDock checkbox beside StarCommand and StarBreach; StarBreach and StarDock now reveal their boss/ship selectors plus compact builder icon buttons only when enabled.
  - Renamed Build New Content hub choices to StarBreach / Build Bosses and StarDock / Build Player Ships.
  - On mobile StarDock, the ship board now moves below the selected-tool reminder and above the secondary damage lane panel.
  - Verified with `node --check frontend/v2/static/lobby.js`, `node --check frontend/v2/static/bossdesigner.js`, and `node --check frontend/v2/static/shipdesigner.js`.

## 2026-07-18 16:03:05 -05:00

- Title: StarDock linear lane numbering
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Added optional `lane_numbers` metadata to StarDock ship designs and taught compiled player damage lanes to honor it, so saved/played ships match their printable lane labels.
  - Added a StarDock "Renumber lanes linearly" control next to auto lane placement; auto-placement runs it automatically. It assigns 1-12 clockwise by lane-entry marker angle, starting from the nose.
  - Updated StarDock board/print lane labels to use assigned lane numbers and bumped the StarDock JS query string in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js` and `PYTHONPATH=backend python -m unittest tests.test_player_ships`.

## 2026-07-18 15:50:58 -05:00

- Title: StarDock scaled arrows
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Replaced fixed-size SVG marker lane arrows on StarDock print sheets with ship-scale triangle arrowheads and scaled shaft widths, keeping tips on the designated entry faces.
  - Bumped the StarDock JS query string in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js`.

## 2026-07-18 15:49:05 -05:00

- Title: StarDock arrow readability
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Enlarged StarDock print-sheet lane arrowheads, thickened their leader lines, and added a little more leader length while keeping arrow tips anchored on entry faces.
  - Bumped the StarDock JS query string in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js`.

## 2026-07-18 15:46:44 -05:00

- Title: StarDock entry-face arrows
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Corrected StarDock print-sheet lane arrows to anchor on the first occupied component in each damage lane, so the arrowhead touches the entry face it designates instead of the outer grid edge.
  - Bumped the StarDock JS query string in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js`.

## 2026-07-18 14:59:21 -05:00

- Title: StarDock print lane markers
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Moved StarDock printable sheet lane bubbles and arrowheads up close to the entry tile faces by deriving a short leader from each hex face instead of using long off-ship callouts.
  - Bumped the StarDock JS query string in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js`.

## 2026-07-18 14:54:26 -05:00

- Title: StarDock print sheets
- Build ID: `76007b5`
- AI agent: Codex
- Summary:
  - Added a StarDock Print Sheets view to the player ship designer, following the StarBreach boss-sheet approach: generated SVG preview, Download SVG, Print, color/B&W tone selection, ship scale, and toggles for lanes, lane list, coordinates, components, starting deck, and table checklist.
  - The printed sheet shows the ship hull, numbered damage-lane arrows, component labels, starting deck cards from Engine/Cannon components, shield/draw/core-point summary, and the selected special advantage.
  - Bumped the v2 StarDock JS/CSS query strings in `frontend/v2/index.html`.
  - Verified with `node --check frontend/v2/static/shipdesigner.js` and `PYTHONPATH=backend python -m unittest tests.test_player_ships`.

## 2026-07-18 13:00:00 -05:00

- Title: StarDock overhaul — lanes, core points, upgrades
- Build ID: `738b04afdada`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Rewrote the StarDock player-ship rules: radius-5 hex grid; 15 contiguous tiles (1 Core, 2 Life Supports, 1 Bone Room, 1 Docking Bay, 10 Engine/Cannon components); the 10 components buy the ship's 10-card starting deck with 15 Core Component points (Engine=Move 1/1pt, Double Engine=Move 2/2pt, Cannon=Aim +1/1pt, Double Cannon=Aim +2/2pt).
  - Damage lanes split into 6 auto primary lanes through the Core (max 10 armoring components, admin configurable) and 6 player-placed secondary lanes (rolls 3/5/6/8/9/11) that each must sever ≥2 surviving components from the Core when shot fully through (admin configurable), may not pass through the Core, and may not duplicate a line+direction.
  - One special upgrade per ship: +1 shield (3), +1 draw (6), flat Defense, flat Aim (both admin configurable, default 1), or +2 Core points. Flat bonuses apply in PvP volleys and StarBreach both ways.
  - Admin settings (Account & Project) for tile total (extras become Structure tiles), primary-lane limit, min severed, and upgrade bonus sizes; config is baked into the compiled layout spec at match start so games in flight never change.
  - Designed decks are built from the placed components at game creation; extra card copies get `__sN` ids that still resolve through `card_by_id`.
  - Designer UI: radius-5 board, new tile tools, live deck preview, upgrade picker, and secondary-lane placement — default flow is a "🎲 Auto-place lanes" button cycling deterministic valid arrangements (mirrored pairs on symmetric hulls), with an Advanced toggle for manual chip + direction placement. Legacy pre-overhaul designs still open but are flagged not battle-ready.
  - Replaced `resources/ship_designs/vanguard.json` with a battle-ready new-format ship (classic base deck + shield upgrade).
  - Verified: rewrote `tests/test_player_ships.py` (42 tests) and ran the full suite — only the 4 pre-existing deck-set failures remain (also fail on a clean tree); JS files pass `node --check`; smoke script exercised design→validate→compile→game→serialize round trip.

## 2026-07-18 08:30:00 -05:00

- Title: Active deck guidance
- Build ID: `96f90363e8d1`
- AI agent: Codex
- Summary:
  - Updated repo and deck-folder agent guidance so future code assistants use the admin-selected active deck set for current gameplay, AI battle analysis, and new tests.
  - Added a local warning README inside deprecated `core_0_2` and corrected stale docs that still described it as the default deck.
  - Adjusted the AI battle API test to use the active deck from `/api/v2/admin/deck` instead of choosing by scan order.

## 2026-07-18 08:20:00 -05:00

- Title: Deprecated deck set handling
- Build ID: `96f90363e8d1`
- AI agent: Codex
- Summary:
  - Added deck-set deprecation metadata to v2 scanning, sorted deprecated decks after live decks, and marked the old bundled `core_0_2` deck deprecated.
  - Added an admin Deprecate/Restore action; active decks cannot be deprecated, deprecated decks cannot be activated, and AI battle runs reject explicit deprecated deck ids.
  - Updated the admin AI battle deck selector to omit deprecated decks and added API coverage so tests choose non-deprecated decks.

## 2026-07-18 08:05:00 -05:00

- Title: Admin deck set deletion
- Build ID: `96f90363e8d1`
- AI agent: Codex
- Summary:
  - Added an admin-only delete route for custom deck sets with server-side guards against deleting stock decks, the active deck, or paths outside the custom deck roots.
  - Added a Deck Editor delete button that is disabled for stock/active sets and refreshes the deck list after deletion.
  - Added API coverage for active/stock rejection and inactive custom deck deletion.

## 2026-07-18 07:05:00 -05:00

- Title: Fake-player AI movement/overdrive overhaul for modern duels
- Build ID: `6a15b6b2e7d8`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Measured the three duel AIs (Freebooter/vault_runner, Bloodthirsty/hunter_killer, Cannoneer/blaster) headlessly on the core_0_3 deck: they passed 12-46% of their action stacks and the blaster starved itself by overdriving all three stacks in round 1 (each overdriven stack is one fewer card next round).
  - Overdrive economy: new `Situation.overdrive_budget` — one overdriven stack per round, unlimited in round 6 (no next draw, so seals are free). Threaded through route search, chase moves, and attack stacks; mixed move+attack stacks never overdrive (the copy replays the move past the priced firing position).
  - Movement mirror fixes: added the missing `double_turn_right` (Drift King) branch to `_apply_move`, and planners now track Crazy Ivan's u-turn-attack facing flip. Verified planner-predicted end-of-round positions match the engine exactly across 24 full AI duels.
  - Vault chasing: `_plan_route` returns a best-progress route instead of giving up when no card combination lands in claim radius; the runner camps next round's vaults at a value discount, re-milks the Fang every round (it re-awards), and never moves off a vault it is holding before cleanup scores it.
  - Combat model: `volley_hit_chance` now honors max range, fixed defense thresholds, and the natural-12 auto hit; enemy movement prediction is capped at 3 so early overdrive sprints don't scare the AI off shooting forever. Hands discard at cleanup, so the AIs now always take a shot or a positioning move instead of passing with usable cards.
  - Captain exemption: AI seats never pick movement-altering captains (Drifter's cleanup drift, Turbo's +1 move) — `AI_EXCLUDED_CAPTAIN_IDS` in `starshot.v2.service` — so the planners need no model of those powers.
  - Results on the same 24-duel probe: empty stacks 132→30 / 112→2 / 35→0; total VP 148→180 (vault_runner), 60→141 (blaster), 110→151 (hunter_killer).
  - Verified with `python -m unittest discover -s tests` (325 tests passing, incl. 8 new in `tests/test_v2_ai.py` covering vault chasing/parking, prey chasing, low-odds shots over passing, overdrive rationing, round-6 free overdrive, and the captain exclusion).

## 2026-07-17 21:35:00 -05:00

- Title: Boss Supers reworked as core-synced recurring stack slots
- Build ID: `6bad57b4d569`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Per design direction: each Super is now synced to a Core and occupies an action-stack slot like any other boss action. It fires every round in its assigned stack once its round or progression-step requirement is met, and falls silent while (or after) its Core is destroyed. Triggers are now `round`/`progress` only (`core_destroyed` removed); progression gates follow the powers-up-next-round tier rule.
  - Spec: Supers materialize as `slot: "super"` entries via `phase_slots`, gated in `slot_is_active` (core hex intact + round/tier); they count in `expected_phase_actions`. Engine fires them in the slot loop (`_fire_super_slot`); dropped the one-shot `fired_super_ids` state.
  - Designer: Super rows gained Core and Stack pickers (with a "missing!" marker for unsynced cores); Supers appear as ✹ cards in the Action Stacks organizer and on printed sheets (starburst icon, core-tinted stripe, table-aid lines).
  - Serialized supers now carry an `active` flag instead of `fired`.
  - Verified with `python -m unittest discover -s tests` (317 tests passing) and `node --check frontend/v2/static/bossdesigner.js`; bumped bossdesigner asset versions.

## 2026-07-17 21:05:00 -05:00

- Title: StarBreach AI programs, boss Supers, goals, editor zoom + autonumber
- Build ID: `6bad57b4d569`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Enemy AI programs for the boss and fleet (independently selectable in the Behavior tab): Hunter-Killer (classic), Vault Runner (harvests the current vault, reroutes to next round's when out of reach; claims vaults on contact), Blaster (moves to/fires at the nearest player), and Dynamic (switches its hunt directive up to once per round when a player hits it, heals, grabs a bauble, or opens a damage lane to a Core — `boss_directive_changed` events with callouts).
  - Boss Super effects: nine one-shot showpiece abilities (Immobilizer Shot, Tractor Beam, Knockback, Inferno Zone, Infuser, Chain Shot, ScatterShot, Mark the Prey, Mine Dropper) triggered by round, progress, or a Core's destruction. Designed in the Behavior tab, resolved at the start of boss half-phases, with `boss_super_activated`/`boss_super_resolved` events, a shockwave FX + callout in the v2 client, mine tokens rendered on the board, and mine detonations (3 dmg within 2 hexes) hooked into player movement.
  - New player goals per boss design: capture at least N vaults (default 8) or eliminate the entire fleet (boss optional), both immediate wins; classic Fang escape remains the default. Goal shown in the StarBreach status widget and goal-aware endgame text.
  - Boss editor: mouse-wheel zoom (cursor-centered) + drag pan with a "⤢ Fit" reset button on the hex board; pan suppresses tile-painting clicks.
  - Damage lanes: "✨ Autonumber lanes" lays out a region's full lane set — evenly spaced along the region's hull perimeter for coverage/symmetry, preferring deeper rays and varied entry faces for a straight/angled mix, then renumbered in perimeter order.
  - Schema/spec/state: `supers`, `goal`, expanded `boss_ai`/`fleet_ai` enums in boss designs (+ validation warnings and designer meta); compiled into boss specs with accessors; new StarBreachState fields (directives, fired supers, mines, immobilized/marked players) serialized and round-tripped.
  - Verified with `python -m unittest discover -s tests` (316 tests passing, incl. 19 new in `tests/test_star_breach_features.py`) and `node --check` on `bossdesigner.js`, `game.js`, `board.js`, `effects.js`. Bumped v2 asset query strings.

## 2026-07-17 20:28:51 -05:00

- Title: Boss designer zoom revert
- Build ID: `36b18ffa09a3`
- AI agent: Codex (GPT-5)
- Summary:
  - Removed the just-added StarBreach Boss Ship Designer zoom/pan layer, including its board state, SVG event handlers, controls markup, and CSS.
  - Confirmed no boss-designer zoom/pan symbols remain.
  - Verified with `node --check frontend/v2/static/bossdesigner.js` and `git diff --check` (CRLF warnings only).

## 2026-07-17 20:23:29 -05:00

- Title: Boss designer zoom correction
- Build ID: `36b18ffa09a3`
- AI agent: Codex (GPT-5)
- Summary:
  - Reverted the mobile lobby Captains on Deck/scoreboard layout change.
  - Removed the misplaced StarDock zoom/pan controls and restored its v2 asset query strings.
  - Added zoom in/out/fit controls plus wheel zoom and drag pan to the StarBreach Boss Ship Designer board used by both admin and player-facing designer screens.
  - Verified with `node --check frontend/v2/static/bossdesigner.js`, `node --check frontend/v2/static/shipdesigner.js`, and `git diff --check` (CRLF warnings only).

## 2026-07-17 20:10:52 -05:00

- Title: Endgame and StarBreach fixes
- Build ID: `36b18ffa09a3`
- AI agent: Codex (GPT-5)
- Summary:
  - Final-round replays now treat phase/action reveals as visual events so the battle can play out before the battle report, and the v2 service no longer uses early give-orders completion for round-six scoring/objective results.
  - StarBreach player movement now stops one tile short when an action would end on an enemy ship, with replay/log support and coverage; boss movement also stops before ending on a player.
  - Boss Designer stack view now links spawn-fleet progression steps to the Docking Bay stack, and B&W boss print sheets give Docking Bays a grayscale fill.
  - Mobile lobby moves the Captains on Deck panel above Set Sail, and StarDock gained zoom/pan controls.
  - Bumped affected v2 asset query strings.
  - Verified with `python -m unittest discover -s tests` (297 tests passing), `node --check` on `game.js`, `bossdesigner.js`, `shipdesigner.js`, and `tutorial.js`, plus `git diff --check` (CRLF warnings only).

## 2026-07-17 06:44:58 -05:00

- Title: Compact mobile action cards
- Build ID: `e66364211f35`
- AI agent: Codex (GPT-5)
- Summary:
  - Added a mobile-only compact rendering mode for action-slot cards that hides card names and target/orientation tags.
  - Basic attack cards now show shortened action-slot text such as `Aim +2` instead of target/volley wording; target and zone details remain in Shot Info.
  - Bumped the v2 `cards.js` asset query string.
  - Verified with `node --check frontend/v2/static/cards.js` and `node --check frontend/v2/static/game.js`.

## 2026-07-17 06:35:15 -05:00

- Title: Mobile order controls
- Build ID: `e66364211f35`
- AI agent: Codex (GPT-5)
- Summary:
  - Mobile now returns to the map immediately after a successful Seal Orders submit.
  - Enlarged the mobile Shot Info and Sealed/Overdrive controls while reserving a stable control row so card text does not crowd them.
  - Bumped the v2 `pirate.css` and `game.js` asset query strings.
  - Verified with `node --check frontend/v2/static/game.js` and `git diff --check` (CRLF warnings only).

## 2026-07-17 · Player display names & account moderation

- Title: Player display names & account moderation
- Build ID: `7c50b74afa16`
- AI agent: Claude Fable 5 (Claude Code)
- Summary:
  - Players can now set a display name (defaults to their username) from the lobby user menu, with a 🎲 Random button that generates piratey names and bad puns (`backend/starshot/v2/names.py`).
  - Proposed names run through a profanity/reprehensible screen (leetspeak-normalized substring + whole-word tiers with a Scunthorpe allowlist). Objectionable names are allowed but flagged: the player is told their name is hidden from leaderboards and they won't be matched against other players (quick match, challenges, and open-seat raids blocked; AI-only raids still allowed) until renamed.
  - New admin "Accounts" tab lists every account (record, status, last seen) with per-player matchmaking and leaderboard toggles, plus "Ban name": adds the display name to an illegal-names list, immediately flags anyone wearing it, and forces a rename next time they reach the lobby. Banned names cannot be re-taken; the illegal list is editable.
  - Match seats, match titles, leaderboards, titles, infamy, and Captains on Deck all show display names now (`users.display_name` + moderation columns, `illegal_names` table, idempotent migrations).
  - Bumped `pirate.css`, `admin.css`, `api.js`, `lobby.js`, `admin.js` query strings.
  - Verified with `python -m unittest discover -s tests` (296 tests passing, includes new `tests/test_v2_names.py` and `DisplayNameTests` in `tests/test_v2_api.py`) and `node --check` on the modified JS.

## 2026-07-16 22:58:41 -05:00

- Title: Effect-based card labels
- Build ID: `586d8737b815`
- AI agent: Codex (GPT-5)
- Summary:
  - Changed v2 card rendering so basic attack card labels use parsed effect fields instead of reading bonuses from the display name.
  - Bumped the v2 `cards.js` asset query string.
  - Verified with `node --check frontend/v2/static/cards.js` and `python -m unittest tests.test_card_effects tests.test_deck_data tests.test_serialization`.

## 2026-07-16 21:46:34 -05:00

- Title: Fixed deck attack bonuses
- Build ID: `586d8737b815`
- AI agent: Codex (GPT-5)
- Summary:
  - Confirmed new games were using the admin-selected Deck Rework 7/16/26 deck set, but the active deck data still encoded base damage cards as targeted Aim cards.
  - Corrected the Deck Rework base deck entries and taught front-face cards to preserve parsed attack aim/damage bonuses through loading and serialization.
  - Verified with `python -m unittest tests.test_card_effects tests.test_deck_data tests.test_serialization` and a direct load of the active custom deck catalog.

## 2026-07-16 20:59:08 -05:00

- Title: Shield source assignment
- Build ID: `26e75b0`
- AI agent: Codex (GPT-5)
- Summary:
  - Split StarBreach boss designer shield-region editing into Protected Hexes, Power Source, and Damage Lanes modes.
  - Protected Hexes now lets Shield Gen tiles be protected like any other hull tile; Power Source mode intentionally selects or clears the matching Shield Gen that powers the active region.
  - Added coverage for one region shielding another region's source generator.
  - Verified with `node --check frontend/v2/static/bossdesigner.js`, `python -m unittest tests.test_boss_designer tests.test_boss_spec`, and `git diff --check` (CRLF warnings only).

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
