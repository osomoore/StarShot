# StarShot Implementation Status

## Current Status

All 7 groups of the 0.2 migration are complete. The implementation uses the full 0.2 rule set.

Recent corrections made after reviewing `docs/rules/rules_0.2.txt` directly:

- **Base deck corrected to 10 cards**: 3× Controlled Move 1, 4× Controlled Move 2, 2× Targeted Attack Aim +1, 1× Targeted Attack Aim +2. Previous implementation had wrong counts (3+4+2+1 was correct but names and `requires_target` were wrong).
- **Base attack cards are targeted**: All base attack cards (`attack_1_a`, `attack_1_b`, `attack_2_a`) now have `requires_target=True` (default). They are proper Targeted Attack cards that require the player to choose a target.
- **Move cards turn before moving**: `turn_left` and `turn_right` orientations now rotate the ship first, then move forward in the new facing direction. Previously the ship moved first then turned.
- **No U-Turn on base move cards**: `orientation_options` default is now `("forward", "turn_left", "turn_right")`. U-turn has been removed from base move cards and from the frontend move picker.

Use `docs/context/rules_0.2_migration_plan.md` for the next rules-update work. Card interpretation lives in `backend/starshot/rules/card_effects.py`; hand/discard/overheat movement lives in `backend/starshot/rules/card_piles.py`.

The core desperation-card work is in place for the basic-face flow, plus the normal action-stack Desperate-face slices. The backend recognizes desperation moves, hybrid/basic desperation attacks, and implemented Desperate faces for bonus movement, aim, damage, defense-only movement, Warp movement, always-hit/+999 Aim, range-limited damage, attack-all volleys, and single-use return to the shared Desperation deck.

The debug builder has Move, Attack, and Desperation picker piles. All non-base desperation cards live in the Desperation pile. Clicking a desperation card opens a use-choice panel before the card is loaded into the stack.

Current focus is post-0.2 polish and any remaining UI/rules discrepancies.

## Recent Commits Of Interest

- `934388e Add initial ship movement resolution`
- `53fd7ac Rework debug UI around hex board`
- `8f1f5f9 Align ship facing markers to hex faces`
- `f5ddd75 Add action preview overlays to debug board`
- `d785ed2 Preview full order paths on the hex board`

## Rules Engine Notes

Core API:

- `create_initial_state(config) -> GameState`
- `legal_actions(state, player_id) -> list[Action]`
- `apply_action(state, player_id, action) -> GameState`
- `is_game_over(state) -> GameResult | None`

Current phase progression:

1. `give_orders`
2. `action_1`
3. `action_2`
4. `action_3`
5. `award_baubles`
6. `cleanup`

Movement behavior currently implemented:

- Move cards turn first, then move forward in the new facing direction.
- `turn_left` rotates facing +1, then moves forward X.
- `turn_right` rotates facing -1 (mod 6), then moves forward X.
- `forward` moves straight ahead without turning.
- No U-Turn on base move cards.
- `overdrive` duplicates the full stack as an immediate copy. Both movement events include `overdrive_copy`. Overdrive does not boost card values — it duplicates the order.
- Overdriven command cards are routed to overheat during cleanup. One `overdrive_seals_pending` counter per player reduces the next round's draw by 1 per overdriven stack.

Combat behavior currently implemented:

- Base attack cards (`attack_1_a`, `attack_1_b`, `attack_2_a`) are Targeted Attacks and require `target_player_id`.
- Attack rolls use `2d6`.
- A volley deals base 1 damage plus `Damage +X` modifiers; multiple base attack cards add Aim but do not add extra base damage.
- Overdriven attack stacks resolve a normal volley then an immediate duplicate volley before the next attacker.

## Debug UI Notes

The debug UI is in `frontend/debug/`.

Current board behavior:

- SVG axial hex board, radius 12.
- Real ships draw after previews so they remain visible.
- Mini ship cards show pile counts in Hand, Deck, Discard, Overheat order with distinct icons.
- Order previews only show during `give_orders` before the selected player submits orders.
- Preview markers are labeled by action/card slot, e.g. `A1.1`, `A2.1`, `A3.1`.
- Attack preview bursts are drawn at the shooter location, colored by target player.
- Move preview applies turn-before-move to match backend behavior.
- Target picker opens automatically when a Targeted Attack card is placed, unless the stack already has a target set from another card.
- In 2-player games, target auto-fills to the only opponent.

## Good Next Implementation Candidates

1. Verify move card orientation art/labels match the physical card (Face A = straight, Face B = turn options).
2. Post-0.2 feature planning.

## Files To Read Before Rule Work

- `docs/rules/rules_0.2.txt` (canonical — always prefer this over `rules_implementation.md` for 0.2 rules)
- `docs/rules/rules_implementation.md`
- `docs/context/rules_0.2_migration_plan.md`
- `backend/starshot/rules/models.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/hex.py`
- `tests/test_rules_engine.py`
