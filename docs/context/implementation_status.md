# StarShot Implementation Status

## Current Status

The core desperation-card work is now in place for the basic-face flow. The backend recognizes desperation moves and hybrid desperation attacks, the debug builder shows a dedicated Hybrid column, and hybrid cards preserve their chosen mode through serialization and UI state.

Current focus is the next slice: resolving desperate faces and especially desperate abilities, rather than the basic card draw and placement flow.

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
