# StarShot Implementation Status

## Current Status

The core desperation-card work is in place for the basic-face flow, plus the normal action-stack Desperate-face slices. The backend recognizes desperation moves, hybrid/basic desperation attacks, and implemented Desperate faces for bonus movement, aim, damage, defense-only movement, Warp movement, always-hit/+999 Aim, range-limited damage, attack-all volleys, and single-use return to the shared Desperation deck.

The debug builder now has Move, Attack, and Desperation picker piles. All non-base desperation cards live in the Desperation pile. Clicking a desperation card opens a use-choice panel before the card is loaded into the stack:

- Empty stack or Move stack: hybrid cards can choose Basic Move; Basic Attack and Desperate Attack Mod choices are disabled until a targeted attack partner exists.
- Targeted Attack stack: hybrid cards can choose Basic Attack or their Desperate Attack Mod; Basic Move is disabled.
- Basic Move desperation choices are forward-only and do not show a direction modal.
- Desperate Move selections use bright green styling; Desperate Attack selections use bright orange styling.
- Attack previews show target roll after Aim, with Aim shown in parentheses, e.g. `ROLL 3+ (+5 Aim)`.
- Warp previews jump to the deterministic server destination: Home, nearest active numbered Bauble, or current VP Leader.

Current focus is the next slice: especially desperate abilities.

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
2. `cooldown`
3. `action_1`
4. `action_2`
5. `action_3`
6. `award_baubles`
7. `cleanup`

Movement behavior currently implemented:

- Move cards advance along current facing unless orientation is `u_turn`.
- `turn_left` and `turn_right` move first, then rotate.
- `u_turn` rotates in place.
- `overdrive` adds 1 to move distance and sends the card to overheat.

## Debug UI Notes

The debug UI is in `frontend/debug/`.

Current board behavior:

- SVG axial hex board, radius 12.
- Real ships draw after previews so they remain visible.
- Order previews only show during `give_orders` before the selected player submits orders.
- Preview markers are labeled by action/card slot, e.g. `A1.1`, `A2.1`, `A3.1`.
- Attack preview bursts are drawn at the shooter location, colored by target player.
- Order previews use selected face/mode as the effective card family, so Basic Move/Attack and implemented Desperate faces preview movement, damage, target roll, Aim, and always-hit effects.

## Good Next Implementation Candidates

1. Implement the next concrete combat slice: attack range/arc, shield interaction, or damage markers, depending on the rules doc.
2. Add board-boundary validation and tests for illegal movement if the rules define it.
3. Add collision/overlap handling if ships cannot share hexes.
4. Improve the debug UI with a compact combat log that explains each resolved action.
5. Add API/UI support to reload and continue an existing game cleanly after server restart.

## Files To Read Before Rule Work

- `docs/rules/rules_implementation.md`
- `backend/starshot/rules/models.py`
- `backend/starshot/rules/engine.py`
- `backend/starshot/rules/hex.py`
- `tests/test_rules_engine.py`
