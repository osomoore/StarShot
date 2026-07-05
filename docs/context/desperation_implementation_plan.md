Desperation Deck - Basic Faces + First Desperate-Face Slice

## Current Status

The basic-face desperation deck flow is implemented and covered by tests. The rules engine can define, draw, serialize, and place desperation cards; basic desperation moves are forward-only; targeted desperation attacks can stand alone; untargeted/hybrid desperation attacks can be played as either basic Move or basic Attack depending on the selected mode.

The first normal action-stack Desperate faces are implemented for bonus movement, aim, damage, defense-only movement, always-hit, and single-use routing back to the shared Desperation deck. Implemented Desperate faces:

- Thrust Ions: Move 5.
- Turbo Ions: Move 10.
- Evasive Action: +10 Defense, cannot move.
- Ace Shot: +5 Aim.
- Deadeye: always hits.
- Steady Shot: +2 Aim, +1 Damage.

The debug UI picker has three piles: Move, Attack, and Desperation. All non-base desperation cards are in the Desperation pile. Choosing a desperation card opens a use-choice panel before loading the card into the stack:

- Hybrid/basic-back cards can offer Basic Move, Basic Attack, and the Desperate face, with unavailable choices disabled.
- Basic Move choices for desperation cards are forward-only and do not open a direction modal.
- Desperate Move selections render bright green; Desperate Attack selections render bright orange.
- Attack previews show target roll after Aim, with the Aim bonus in parentheses, e.g. `ROLL 3+ (+5 Aim)`.

The remaining work is to resolve the especially desperate abilities.

## Completed Scope

- Desperation deck definition: all in-scope basic-face cards from Table 12.2 + 13.1.
- Shared DesperationDeck state living on GameState.
- Desperation draws: draw from the bottom and handle the "Shuffle Desperately" reshuffle sentinel.
- Bauble draws: non-Fang baubles add the drawn desperation card to the player's deck.
- Damage consequence: when the first component is destroyed by a volley, apply the deterministic auto-choice priority described below.
- Card routing: desperation cards played on their basic face return to the player deck normally; is_base=False gates overdrive correctly.
- Validation: desperation cards follow effective family constraints and cannot mix Move/Attack modes in a stack.
- Serialization: DesperationDeck and DesperateFace metadata round-trip through state serialization.
- Tests: draw, reshuffle, bauble draw, consequence choice, VP penalty, hybrid mode legality, non-overdrive behavior, desperate-face movement/combat/routing, and debug split setup.

## Open Questions
IMPORTANT

Consequence choice is a player decision. In the current single-server-call model there is no interactive mid-resolution prompt. For this increment, the server will auto-choose the consequence with the following deterministic priority (per user preference: always prefer drawing a desperation card):

Swap the first base card in deck for a drawn desperation card (removes that base card from play).
Swap the first base card in overheat for a drawn desperation card (if deck has no base card).
Lose 1 VP (if no valid base card exists in deck or overheat).
"First card" means the first is_base=True card found in the list order — no interactive pick. A UI for player choice is a follow-up task. This makes the feature fully testable without adding an async choice API.

NOTE

Some Desperate faces are still deferred: Hull Repair, Advanced Repair, and All She's Got. Cards played on a Desperate face return to the shared Desperation deck; cards played on their basic face return to the player deck normally.

NOTE

"All She's Got" and "Hull Repair / Advanced Repair" are Especially Desperate / special-seal cards that don't fit the normal action-stack model. They are deferred per the rules doc.

## Implementation Notes

The following notes describe the implementation that is now in place.

1. Models: `backend/starshot/rules/models.py`

- DesperationDeck dataclass with cards: list[Card] and a shuffle_marker_on_top: bool flag.
- desperation_deck: DesperationDeck field on GameState.
- No separate desperation_hand is currently used; drawn cards are placed directly into player.deck.

2. Desperation cards: `backend/starshot/rules/desperation.py`

create_desperation_deck() -> DesperationDeck includes all basic-face cards from the rules (Table 12.2 + 13.1), excluding "Hull Repair", "Advanced Repair" (deferred), and "All She's Got" (deferred).

Included cards:

qty	id prefix	name	family	basic_value	desperate_face
2	desp_thrust_ions_*	Thrust Ions	move	1	Move 5
1	desp_turbo_ions	Turbo Ions	move	1	Move 10
1	desp_homeward_bound	Homeward Bound	move	1	Warp Home, +5 Defense
1	desp_treasure_hound	Treasure Hound	move	1	Warp Bauble, +5 Defense
1	desp_evasive_action	Evasive Action	move	1	+10 Defense, cannot move
2	desp_ace_shot_*	Ace Shot	attack	1	+5 Aim
1	desp_deadeye	Deadeye	attack	1	+999 Aim / Always hits
1	desp_nightjammer	Nightjammer	attack	1	Warp Leader, +5 Defense
1	desp_self_destruct	Self Destruct	attack	1	Range 2, Damage 4, Keep VP
1	desp_death_blossom	Death Blossom	attack	1	Attack all with Defense 10
2	desp_steady_shot_*	Steady Shot	attack	1	+2 Aim, +1 Damage
4	desp_targeted_attack_1_*	Desperation Attack 1	attack	1	N/A (targeted)
Cards have is_base=False. The targeted attack cards are proper targeted attacks (can designate a target); the others need a paired targeted attack card.

draw_desperation_card(deck: DesperationDeck, rng: Random) draws from the conceptual "bottom" (implemented as pop(0) from the list), reshuffles after the shuffle marker/sentinel is reached, and returns a valid desperation card.

Desperation card definitions, draw/return mechanics, and effective-face semantics live in `backend/starshot/rules/desperation.py`. `backend/starshot/rules/decks.py` owns the base deck and keeps compatibility exports plus the combined card_by_id lookup.

Warp is deterministic until there is a richer choice UI: Homeward Bound warps to the player's start tile; Treasure Hound warps to the nearest active numbered Bauble with a nearest-numbered fallback; Nightjammer warps to the hex behind the current VP leader, using that ship's facing, and then matches the leader's facing.

3. Engine: `backend/starshot/rules/engine.py`

- create_initial_state shuffles and attaches desperation_deck to the new state.
- _resolve_award_baubles draws and places a real desperation card into player.deck for non-Fang baubles.
- _apply_unshielded_damage calls _apply_desperation_consequence(state, target) exactly once per volley after the first shot that destroys a component.
- _apply_desperation_consequence(state, player) implements the auto-choice priority described above and emits a desperation_consequence event.
- _resolve_stack_movement / _resolve_combat use effective face helpers to read DesperateFace metadata.
- _move_resolved_stack_cards routes cards played on a Desperate face back to the shared Desperation deck.
- _validate_stack uses effective hybrid family/mode and the combined card lookup so desperation card IDs are legal inputs.

4. Card lookup: `backend/starshot/rules/decks.py`, `backend/starshot/rules/desperation.py`, and `backend/starshot/rules/engine.py`

- desperation_card_by_id(card_id: str) -> Card.
- card_by_id(card_id: str) -> Card tries base first, then desperation.
- Engine card lookup uses card_by_id(...) where desperation cards can appear, while Desperation-specific setup and card semantics import from `starshot.rules.desperation`.

5. Serialization: `backend/starshot/rules/serialization.py`

desperation_deck_to_dict / desperation_deck_from_dict are wired into state_to_dict / state_from_dict.

6. Tests

test_initial_state_has_desperation_deck – deck has correct card count (17 non-deferred cards + sentinel behavior).
test_bauble_award_draws_desperation_card_into_deck – player in bauble range gains a desperation card in their deck.
test_unshielded_damage_triggers_desperation_consequence_move_to_overheat – when first component destroyed, a base card moves to overheat.
test_desperation_consequence_swaps_base_for_desperation_card_when_deck_has_no_base – when deck has no base cards, swap a deck desperation/overheat card? (Check rules: if no valid base card to replace, lose 1 VP.)
test_desperation_consequence_vp_penalty_when_no_base_cards_anywhere – lose 1 VP when fully depleted.
test_desperation_card_not_overdriven – desperation card used with overdrive seal still has base value and goes to deck not overheat.
test_desperation_card_in_attack_stack_requires_targeted_attack_partner – (validation test, deferred per rules; desperation attack 1 targeted cards are full targeted attacks and can stand alone).
test_desperation_deck.py contains deck/draw mechanics plus integration coverage.

Verification Plan
Automated Tests
powershell

python -m unittest discover -s tests
Expected: 55 tests pass as of the latest verified run. This doc update was not test-run per user request.

Manual Verification
Start a game in the debug UI, advance to Award Baubles while a ship is in a bauble hex, verify the player's deck grows by 1 card in the state panel.
Trigger unshielded damage and confirm the event log contains a desperation_consequence entry.
