# StarShot Rules 0.2 Migration Plan

Use this file when starting work on the `rules_0.2.pdf` update. The goal is to move from the current playable 0.1-derived implementation to 0.2 core rules while keeping the game playable after every group.

Expansion material is out of scope for this migration: StarCommand, StarTech, StarBreach, StarTrader, Starfall events, captains, NPC ships, bosses, and mission systems.

## Source References

- Canonical 0.2 PDF: `docs/rules/rules_0.2.pdf`
- Extracted 0.2 text: `docs/rules/rules_0.2.txt`
- Current 0.1 baseline text: `docs/rules/rules_0.1.txt`
- Current implementation notes: `docs/rules/rules_implementation.md`
- Current handoff: `docs/context/ai_handoff.md`

## Current Implementation Snapshot

The current rules engine is still largely 0.1-shaped:

- Phase flow includes `cooldown`.
- `PlayerState.deck` doubles as the player's available order cards.
- There is no explicit `hand` or `discard`.
- Overdrive adds `+1` to base card numeric effects.
- Attacks roll `2d12`.
- Attack damage is the sum of attack card values plus damage modifiers.
- Base deck has 8 cards: 2 Move 1, 3 Move 2, 2 Attack 1, 1 Attack 2.
- Numbered baubles use VP values 4/3/3/4/4.
- Ship destruction includes Bridge, both Life Supports, or all weapons plus all engines.
- Desperation consequence still uses the older replacement-choice model.

Key files:

- `backend/starshot/rules/models.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/decks.py`
- `backend/starshot/rules/desperation.py`
- `backend/starshot/rules/serialization.py`
- `backend/starshot/rules/baubles.py`
- `backend/starshot/rules/ship_layout.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`
- `tests/test_serialization.py`
- `tests/test_api.py`

## Important 0.2 Core Deltas

- Round flow removes `cooldown`: `give_orders`, `action_1`, `action_2`, `action_3`, `award_baubles`, `cleanup`.
- Give Orders draws a hand: 5 cards normally, 6 cards once the player's shields are exhausted.
- Unused hand cards go to discard after orders are sealed.
- Empty deck while drawing: shuffle discard into deck, move overheat pile into discard, then continue drawing.
- Resolved sealed/basic cards go to discard during cleanup.
- Overdriven command cards go to overheat during cleanup.
- Desperate-face desperation cards return to the bottom of the shared Desperation deck.
- Overdrive duplicates the whole order as a second immediate order; it no longer adds `+1` to base card values.
- Base deck becomes 10 cards: 2 Targeted Attack Aim +1, 1 Targeted Attack Aim +2, 3 Move 1, 4 Move 2.
- Attack rolls use `2d6`; damage lanes still use `1d12`.
- Volley damage is base 1 plus `Damage +X` modifiers. Multiple attack cards do not add multiple base damage.
- Untargeted attacks trace directly forward and target the first enemy ship on that line.
- Numbered baubles are worth 2 VP each. Fang is still 1 VP, or 6 VP in round 6.
- Ship destruction is Bridge destroyed or both Life Supports destroyed.
- First component destroyed by a volley: move the defender's top deck card to overheat, then draw the top Desperation card onto the top of the defender's deck. If deck is empty, shuffle discard first.

## Suggested Module Split

Split before expanding `engine.py` further.

### `backend/starshot/rules/card_effects.py`

Own card interpretation:

- Determine selected/effective card family.
- Interpret selected face, orientation, and mode.
- Return move directives.
- Return attack contribution: targeted status, aim bonus, damage bonus, base damage.
- Hide desperate/basic face details from `engine.py`.
- Provide compatibility wrappers during early groups so behavior can stay playable.

### `backend/starshot/rules/card_piles.py`

Own card-zone movement:

- Draw hands.
- Shuffle discard into deck.
- Move overheat into discard on deck exhaustion.
- Discard unused hand.
- Move resolved sealed/basic cards to discard.
- Move overdriven cards to overheat.
- Return desperate-face cards to the shared Desperation deck.

Keep `engine.py` focused on phase orchestration, validation calls, movement/combat sequencing, and event emission.

## Migration Groups

Each group should end with `python -m unittest discover -s tests` passing and the debug UI able to create, submit, and resolve a small game.

### Group 1: Documentation Baseline

Status: complete. Playable after: yes. No behavior change.

- Add or refresh `docs/rules/rules_0.2.txt`.
- Update `docs/rules/rules_implementation.md` to identify 0.2 as the target and 0.1 as historical.
- Keep this migration plan current as implementation decisions change.
- Do not change rules code in this group.

Completed notes:

- `docs/rules/rules_0.2.pdf` and `docs/rules/rules_0.2.txt` are present.
- `docs/rules/rules_implementation.md` now labels 0.2 as the target and the old 0.1-derived sections as historical context.
- Next implementation work should start with Group 3.

Verification:

- `git status --short` shows only doc/source additions or edits.
- `python -m unittest discover -s tests` still passes.

### Group 2: Card Schema and Effect Helpers, Preserve Current Behavior

Status: complete. Playable after: yes. Existing gameplay should behave the same.

- Add `card_effects.py`.
- Add richer card fields or helper return objects for move value, aim bonus, damage bonus, base attack damage, targeting, and orientation options.
- Route existing engine card interpretation through helper functions.
- Keep current 0.1-style outcomes for now: `2d12`, summed attack values, `+1` overdrive.
- Update serialization and frontend tolerance for new card fields without requiring them.

Completed notes:

- Added `backend/starshot/rules/card_effects.py` with structured `MoveDirective`, `AttackContribution`, and `CardEffect` helpers.
- Routed engine movement and combat interpretation through card-effect helpers while preserving current 0.1-style behavior.
- Kept `desperation.py` helper exports as compatibility wrappers for existing callers/tests.
- Added additive serialized card `effect` metadata and debug UI fallbacks for that metadata.
- Added focused card-effect tests.

Likely files:

- `backend/starshot/rules/models.py`
- `backend/starshot/rules/card_effects.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/desperation.py`
- `backend/starshot/rules/serialization.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`
- `tests/test_serialization.py`

Verification:

- Existing movement, attack, desperation, API, and serialization tests pass.
- Start a debug game and submit orders from the browser.

### Group 3: Hand and Discard Economy Behind Legacy Phase Flow

Status: complete. Playable after: yes. Card economy starts feeling like 0.2, while cooldown/overdrive can remain legacy for one group.

- Add `hand` and `discard` to `PlayerState`.
- Add `card_piles.py`.
- Draw a hand at game start or on entering `give_orders`.
- Use hand, not deck, as the legal order source.
- Submitting orders removes selected cards from hand.
- Unused hand cards go to discard.
- Debug builder reads from `player.hand`.
- Show deck, hand, discard, and overheat counts in the debug UI.
- Keep cooldown and current post-action card movement temporarily if needed to avoid combining too many changes.

Completed notes:

- Added `hand` and `discard` to `PlayerState`.
- Added `backend/starshot/rules/card_piles.py` for drawing hands, discarding unused hand cards, and removing submitted cards from hand.
- New games draw a 5-card hand from the player deck; submitted cards leave hand and unsubmitted hand cards move to discard.
- Order validation now uses hand cards, not deck cards.
- Debug UI builder/demo orders use `player.hand` and show deck, hand, discard, and overheat counts.
- Mini ship cards display pile counts in Hand, Deck, Discard, Overheat order with distinct icons.
- Removed the split-debug startup option that seeded many desperation cards for immediate testing. Desperation cards gained/debug-seeded into a player pile remain in the deck until drawn.
- Legacy cooldown and per-action resolved-card destinations remain in place for Group 4.

Likely files:

- `backend/starshot/rules/models.py`
- `backend/starshot/rules/card_piles.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/serialization.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`
- `tests/test_serialization.py`
- `tests/test_api.py`

Verification:

- New games expose a hand.
- Builder can submit only hand cards.
- Submitted cards leave hand; unused hand cards go to discard.
- A full round still resolves.

### Group 4: 0.2 Phase Flow and Cleanup Card Destinations

Status: complete. Playable after: yes. This group fully replaces the old cooldown/card-return loop.

Implemented:

- Removed `GamePhase.COOLDOWN` from normal flow.
- All players submitted -> `action_1`.
- Retired `_resolve_cooldown`.
- Moved resolved command-card destinations to cleanup. `prepared_orders` acts as the round's play area until cleanup.
- Cleanup destinations:
  - sealed/basic command cards -> discard
  - overdriven command cards -> overheat
  - desperate-face cards -> bottom of shared Desperation deck
  - modeled overdrive seal card effect -> skipped for now because seal cards are not represented as player cards
- Starts the next round by drawing the next hand.
- Implements empty-deck draw behavior: shuffle discard into deck, then move overheat to discard, then continue drawing.

Likely files:

- `backend/starshot/rules/models.py`
- `backend/starshot/rules/card_piles.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/serialization.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`

Verification:

- Phase sequence contains no cooldown.
- Overheated cards are not available next round unless the deck exhausts.
- Cleanup leaves players ready for a new `give_orders` hand.
- `python -m unittest discover -s tests` passes.

### Group 5: Base Deck and Combat Math

Status: complete. Playable after: yes.
Combat should now match the central 0.2 attack model.

- Change base deck to 10 cards:
  - 2 Targeted Attack Aim +1
  - 1 Targeted Attack Aim +2
  - 3 Move 1
  - 4 Move 2
- Attack roll becomes `2d6`.
- Damage lanes remain `1d12`.
- Volley damage becomes base 1 plus total `Damage +X`.
- Multiple attack cards combine aim/damage, but do not add extra base damage.
- Update event payload fields so logs/previews show aim and damage clearly.
- Update debug previews from old damage/card-value assumptions.

Completed notes:

- Base deck is the 10-card 0.2 deck: 3 Move 1, 4 Move 2, 2 Targeted Attack Aim +1, and 1 Targeted Attack Aim +2.
- Base attack cards contribute Aim, not damage value. A combined volley has base 1 damage plus `Damage +X` modifiers.
- Multiple base attack cards combine into one volley with summed Aim and no extra base damage.
- Attack rolls now use `2d6`; damage lanes remain `1d12`.
- Debug previews use the same base-damage-plus-modifiers model.

Likely files:

- `backend/starshot/rules/decks.py`
- `backend/starshot/rules/card_effects.py`
- `backend/starshot/rules/engine.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`
- `tests/test_desperation_deck.py`

Verification:

- Attack event rolls are in the `2..12` range.
- A two-card attack without `Damage +X` deals 1 damage on an unshielded hit.
- Aim changes hit chance but not damage.

### Group 6: 0.2 Overdrive

Status: complete. Playable after: yes.
Isolate this because it affects sequencing and event logs.

- Replace numeric `+1` overdrive with duplicate-order execution.
- Movement: execute normal moves, then execute overdrive duplicate moves immediately after normal moves.
- Combat: execute normal volley, then overdrive duplicate volley immediately before the next player attacks.
- Ensure duplicate volleys can trigger shields, VP, damage, and per-volley effects separately.
- Mark events with enough detail for the debug log, e.g. `overdrive_copy: true`.
- Remove remaining old overdrive boost assumptions from frontend previews and tests.

Completed notes:

- Removed the legacy overdrive `+1` card-value boost from backend card interpretation and debug previews.
- Movement stacks sealed with Overdrive execute once normally, then immediately execute a duplicate copy. Movement events include `overdrive_copy`.
- Attack stacks sealed with Overdrive resolve a normal volley, then immediately resolve a duplicate volley before the next attacker. Volley events include `overdrive_copy`.
- Duplicate volleys resolve shields, VP, component damage, and desperation consequences as separate volleys.
- Cleanup still sends overdriven command cards to overheat.

Likely files:

- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/card_effects.py`
- `backend/starshot/rules/card_piles.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`

Verification:

- Overdrive Move 2 moves twice for two separate Move 2 executions, not once for Move 3.
- Overdrive attack creates two volley events.
- Overdriven command cards end in overheat at cleanup.

### Group 7: Remaining 0.2 Core Rules

Status: complete. Playable after: yes. This group catches the smaller but visible core-rule deltas.

Completed notes:

- Numbered baubles 1-5 are 2 VP each (BAUBLE_VP_BY_NUMBER already set; test updated).
- Removed the all-weapons-and-engines ship destruction condition from `is_ship_destroyed`; only Bridge or both Life Supports destroy a ship.
- Desperation consequence is automatic: top deck card moves to overheat, Desperation card drawn onto top of defender deck (shuffles discard first if deck is empty). Old choice-model tests updated.
- Added untargeted forward-line attacks: base attack cards now have `requires_target=False`; `_first_enemy_forward_target_id` already existed and is used when no `target_player_id` is set. Desperation untargeted cards still require a partner with an explicit `target_player_id`.
- Fang damage remains shieldable with no desperation/overheat consequence.

Likely files:

- `backend/starshot/rules/baubles.py`
- `backend/starshot/rules/ship_layout.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/hex.py`
- `frontend/debug/static/app.js`
- `tests/test_rules_engine.py`
- `tests/test_ship_layout.py`

Verification:

- Round 1-5 numbered baubles award 2 VP.
- Destroying all engines/weapons alone does not destroy a ship.
- Bridge or both Life Supports still destroy a ship.
- Untargeted attack misses if no enemy is directly ahead and hits the first enemy on the forward line.

## Open Design Questions To Resolve While Implementing

- Whether the one-minute hourglass/unsealed-actions timing should exist in the digital debug UI or remain a physical-table-only rule for now.
- Whether the Desperate Inspiration 7-card draw variant should remain out of scope. Default assumption: out of scope.
- How to model Sealed/Overdrive cards as physical cards. Default assumption: keep `SealMode` as metadata unless the top-of-deck sealed-card rule needs visible gameplay.
- Whether overdrive should be allowed on orders containing Desperate faces. The PDF has a dev note suggesting a possible simplifier/nerf; default assumption: allow until clarified.
- Whether Fang should draw a Desperation card in 0.2. The Award Baubles summary says "and a Desperation card," but the Baubles section specifically only says numbered baubles draw. Default assumption: numbered baubles draw; Fang does not.
- Whether targeted color/orientation should be physically modeled, or whether `target_player_id` remains the digital substitute. Default assumption: keep `target_player_id`.
- How to represent untargeted attacks against multiple ships in the same first occupied hex. Current player ships probably cannot overlap; implement tie behavior only if overlap becomes possible.

## Fresh-Context Startup Checklist

1. Read `docs/context/ai_handoff.md`.
2. Read this file.
3. Read `docs/context/implementation_status.md`.
4. Read the source/test files listed in the chosen group.
5. Run `git status --short`.
6. Run `python -m unittest discover -s tests` before editing if the group is behavioral.
7. Make the smallest complete group or subgroup that leaves the game playable.
8. Update this file and `implementation_status.md` if the group status changes.
