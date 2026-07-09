# StarShot Rules Implementation Notes

Source files:

- Current target rules PDF: `docs/rules/rules_0.2.pdf`
- Current target extracted text: `docs/rules/rules_0.2.txt`
- Historical implemented baseline PDF: `docs/rules/rules_0.1.pdf`
- Historical implemented baseline text: `docs/rules/rules_0.1.txt`
- Migration plan: `docs/context/rules_0.2_migration_plan.md`

This document originally converted the prototype 0.1 rules into an implementation baseline. The repository is now migrating to rules 0.2. Until this file is fully rewritten for 0.2, treat `docs/context/rules_0.2_migration_plan.md` as the working plan for new rules work and this file as historical implementation context.

Status for rules 0.2:

- Groups 1 through 4 of the 0.2 migration are complete: documentation baseline, card-effect interpretation helpers, hand/discard order submission, no-cooldown phase flow, cleanup card destinations, and empty-deck draw behavior.
- The implemented game is still partially 0.1-shaped: base deck composition, combat math, and overdrive behavior still need later migration groups.
- The sections below describe the historical 0.1-derived implementation unless they explicitly mention rules 0.2.
- Do not use the old round flow, base deck, attack math, overdrive, bauble VP, or ship-destruction rules below as 0.2 requirements. Use the migration plan's grouped 0.2 deltas instead.

## Core Game

StarShot is a competitive tactical space combat game for 2 to 4 players. Each player pilots one ship. The default game ends after six rounds, or earlier if only one ship remains undestroyed at the completion of a round.

The server must be authoritative for:

- Game setup.
- Deck, hand, action stack, overheat, and discard/desperation state.
- Hidden order submission.
- Round and phase progression.
- Movement, targeting, attack rolls, shields, damage, VP, and ship destruction.
- Randomness, including starting player, dice rolls, bauble placement, desperation draws, and damage lanes.

The browser client may display state and collect player intent, but it must not decide legality or outcomes.

## Initial Entities

Implement these entities first:

- `GameState`: players, round number, phase, starting player, board, baubles, action index, event log, and winner/result.
- `PlayerState`: player id, color, team id if teams are enabled later, ship, deck, overheat pile, prepared action stacks, VP, eliminated flag.
- `ShipState`: hex position, facing, shield charges, component damage, movement executed during the current action, defense bonus for the current action.
- `Card`: id, source deck, card type, value/effects, whether it is a base card or desperation card.
- `ActionStack`: action number 1 to 3, sealed mode, ordered cards, chosen face/orientation, derived target or movement instruction.
- `BaubleState`: hex position, round number or Fang, VP reward.
- `GameEvent`: append-only accepted event with timestamp/order, actor, event type, payload, and resulting public summary.

Keep the first implementation deterministic except for explicit injected RNG. Rules tests should be able to pass a seeded RNG or fixed dice results.

## Round Flow

Each round follows this sequence:

1. `give_orders`
2. `cooldown`
3. `action_1`
4. `action_2`
5. `action_3`
6. `award_baubles`
7. `cleanup`

At cleanup completion:

- Check end-of-game conditions.
- If the game continues, advance the round tracker.
- Rotate starting player clockwise.
- Clear per-action movement/defense state.
- Begin the next `give_orders` phase.

### Give Orders

Each player secretly prepares three action stacks. For each stack:

- Choose up to two command cards from the player's available deck.
- All cards in a stack must be the same action family: `move` or `attack`.
- Choose each card's face and orientation.
- Seal the stack with the matching sealed card for action 1, 2, or 3.
- Sealed mode is either normal `sealed` or `overdrive`.

Do not reveal a player's prepared stack to other players until that action resolves.

### Cooldown

After all orders are submitted and before action 1 resolves, every card in each player's overheat pile returns to that player's deck.

### Resolve Each Action

For action 1, action 2, and action 3:

- Reveal the matching action stack for every active player.
- Resolve all movement before combat.
- Movement is simultaneous at the action stage, but each player's stacked move cards execute in that player's card order.
- Resolve combat in starting-player order, rotating clockwise.
- Each player can make at most one volley per action.
- After the action resolves, move cards to their destination:
  - Normally sealed base command cards return to the player's deck.
  - Overdriven base command cards move to the player's overheat pile.
  - Desperation cards used on a desperate face return to the desperation deck.
  - Desperation cards are not boosted by overdrive and do not overheat.

### Award Baubles

At the end of each round, award baubles:

- Numbered baubles open on their matching round.
- A ship within 1 tile of the matching bauble gains that round's VP reward and draws one desperation card.
- The Fang is active every round during Award Baubles.
- A ship within 1 tile of The Fang gains 1 VP, or 6 VP at the end of round 6, and takes 1 shieldable damage.
- Fang damage does not draw desperation cards and does not overheat cards.

VP by round:

| Numbered bauble | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| VP | 4 | 3 | 3 | 4 | 4 |

## Cards

### Base Orders Deck

Each player starts with this base deck:

| Quantity | Card |
| --- | --- |
| 2 | Controlled Move 1 |
| 3 | Controlled Move 2 |
| 2 | Targeted Attack 1 |
| 1 | Targeted Attack 2 |

### Move Cards

Controlled moves can be oriented to produce one of:

- Move forward X hexes.
- U-turn.
- Move forward X hexes, then rotate right one hex face.
- Move forward X hexes, then rotate left one hex face.

Multiple move cards in a stack are executed in stack order.

Basic desperation moves move forward only and can be combined with other move cards.

### Attack Cards and Volleys

Targeted attacks identify one enemy target through card face/orientation. Multiple attack cards in the same stack create one volley, not multiple attacks.

Volley calculation:

- Target must be supplied by at least one targeted attack.
- Damage is the sum of attack damage values plus damage modifiers.
- Aim bonus is the sum of aim modifiers.
- Multiple targeted attacks in one stack must target the same enemy.

Attack roll:

- Compute defense threshold as distance from attacker to target, plus target movement during this action, plus any target defense bonus.
- Roll 2d12 and add aim bonuses.
- Hit if roll total is greater than or equal to defense threshold.

### Overdrive

If a stack is sealed with overdrive:

- Base deck move and attack numeric effects increase by 1.
- Turning and U-turn effects are not boosted.
- Boosted base cards move to overheat after the action.
- Desperation cards are not boosted and do not overheat.

## Combat, Shields, and Damage

Ships begin with 2 shield charges.

When a volley would hit a ship with shield charges remaining:

- The shield activates.
- One shield charge is spent.
- The shield blocks all incoming damage for the rest of that action step.
- Each attacker who hits an active shield with a volley gains 1 VP.

When a volley hits an unshielded ship:

- Roll 1d12 for each shot/damage point to choose the incoming lane.
- Each shot destroys the first intact component in that lane.
- If at least one component is destroyed, the attacker gains 1 VP.
- If the volley destroys the ship, the attacker gains 3 VP instead of 1 VP for that volley.

Ship destruction occurs when any of these are true:

- Bridge destroyed.
- Both life support components destroyed.
- All coilguns and all ion engines destroyed.

When the first component is destroyed by a volley, the defender must choose one desperation consequence:

- Move a card from deck to overheat.
- Remove a base card from deck and add a random desperation card to deck.
- Remove a base card from overheat and add a random desperation card to overheat.
- If no valid base card replacement exists, lose 1 VP instead.

## Game End

At completion of a round:

- If only one ship remains undestroyed, that player wins.
- If all ships are destroyed, the game is a tie.
- Otherwise, after round 6, highest VP wins.
- VP tie-breaker: most destroyed enemy ship components.
- If still tied, record an unresolved tie.

The "Void Beckons" destroyed-ship rejoin variant is out of scope for the first implementation.

## First Playable Slice

Implement the first rules engine around these capabilities:

- 2 to 4 players.
- Base game only; no StarCommand or StarTech expansion.
- Hex board coordinates, ship position, and facing.
- Random bauble placement for numbered baubles and fixed Fang.
- Base deck cards only.
- Three hidden action stacks per round.
- Cooldown and overheat for base cards.
- Movement cards with forward, left-turn, right-turn, and U-turn outcomes.
- Targeted attack volleys.
- 2d12 attack rolls.
- Shields, VP for shield hits, unshielded damage, and ship destruction.
- Bauble VP and desperation-card draw events.
- Six-round ending and last-ship-standing ending.

Defer these until the base loop is working:

- Desperation card desperate faces.
- Especially Desperate abilities.
- Team play.
- Void Beckons variant.
- StarCommand captains.
- Starfall events.
- StarTech engineering cards.
- Browser visualization of hidden card orientation art.

## Open Implementation Questions

These need confirmation or a PDF/table reference pass before coding the full rules:

- Exact hex coordinates for starting tiles, baubles, and The Fang.
- Exact ship component layout and which d12 lane maps to which component path.
- Exact color/target mapping on each targeted attack card face/orientation.
- Exact movement face/orientation mapping on each controlled move card.
- Whether ships can collide, overlap, pass through each other, or leave the board.
- Whether distance uses axial/cube hex distance and whether blocked/occupied hexes matter.
- How simultaneous movement conflicts are resolved.
- Whether all attackers hitting an already-activated shield gain VP, or only attackers whose roll hits the shielded defender.
- Whether bauble Fang damage rolls once globally or once per affected ship when multiple ships are in range.
- How hidden information is represented in API responses for each player versus spectators.

## Ship Board and Damage Lanes

The debug UI has a ship-board panel that renders `resources/base_ship_0.png` for each player. It shows shield count, total component damage, destruction state, and destroyed-component markers from `ShipState.destroyed_components`.

Damage lane implementation contract:

- `backend/starshot/rules/ship_layout.py` is the canonical `base_ship_0` layout. It models component ids, component types, logical ship hex coordinates, normalized image anchors, and twelve ordered d12 damage lanes based on the lane markings in the image.
- Each unshielded damage point rolls 1d12 and destroys the first intact component in that lane. If every component in the lane is already destroyed, that shot records no destroyed component.
- Store destroyed component ids in `ShipState.destroyed_components`; keep `damage_taken` as a summary counter only.
- Emit per-shot damage events in `volley_resolved.damage_shots` with `roll`, `lane`, `component_id`, `component_type`, and `destroyed` fields. Shielded hits keep the shield event details and skip lane rolls.
- A ship is destroyed when the command bridge is destroyed, both life support components are destroyed, or every weapon and every engine is destroyed.
- Render persistent destroyed-component markers from normalized coordinates on top of `base_ship_0.png`. Use `base_ship_0_mini.png` later for compact player summaries.

## Initial Public API Contract

CLI:

- `starshot new-game --players PLAYER_ID ...`
- `starshot show GAME_ID`
- `starshot orders GAME_ID PLAYER_ID ORDERS_JSON`
- `starshot resolve GAME_ID`

HTTP:

- `POST /api/games`
- `GET /api/games/{game_id}`
- `POST /api/games/{game_id}/join`
- `POST /api/games/{game_id}/orders`
- `POST /api/games/{game_id}/resolve`

The `actions` endpoint from the original plan should be named `orders` for this game because players submit hidden action stacks, not individual immediate actions.

## Testing Baseline

Rules tests should cover:

- Setup creates correct player count, decks, shields, round, and phase.
- Players cannot submit orders with unavailable cards.
- Players cannot mix move and attack cards in one stack.
- Cooldown returns overheated cards to deck.
- Overdrive boosts base card values and overheats base cards.
- Desperation cards are not overdriven.
- Movement changes position/facing as expected.
- Attack rolls compare against distance plus target movement and defense bonus.
- Shield hit spends one charge, prevents damage for the action, and grants VP.
- Unshielded hit destroys components and grants VP.
- Ship destruction conditions end the game at round completion.
- Round 6 VP comparison determines the winner.
- Hidden orders are not exposed in public game state before reveal.
