Desperation Deck – Initial Implementation Plan
Background
StarShot already has base deck cards, movement, combat, shields, and bauble VP. When a ship takes unshielded component damage for the first time in a volley, the defender must choose a desperation consequence. One option is to swap a base card for a random Desperation card drawn from a shared Desperation deck. Baubles (non-Fang) also trigger a desperation card draw.

Currently the code logs desperation_card_drawn: true for baubles and has placeholder desperation consequence comments, but no actual Desperation deck object exists in the state and no cards are drawn or added to player decks.

Scope for This Increment
The rules doc marks "desperation card desperate faces" as deferred but says the basic face and draw mechanics are in-scope for the first playable slice. We will implement:

Desperation deck definition – all cards from Table 12.2 + 13.1, basic face only.
Shared DesperationDeck state living on GameState.
Drawing a desperation card – draws from the bottom, handles the "Shuffle Desperately" reshuffle sentinel.
Bauble desperation draw – actually adds the drawn card to the player's deck when in bauble range.
Damage consequence choice – when first component is destroyed by a volley, defender picks one of:
Move a base card from deck to overheat.
Swap a base card in deck for a desperation card.
Swap a base card in overheat for a desperation card.
If no valid choice exists, lose 1 VP.
Card routing after use – desperation cards played on their basic face return to player deck normally; is_base=False already gates overdrive correctly.
Validation – desperation cards cannot be placed in the same stack as base attack/move cards that mix types; they follow the same family constraint.
Serialization – round-trip DesperationDeck.
Tests – cover draw, reshuffle, bauble draw, consequence choice, VP penalty.
Open Questions
IMPORTANT

Consequence choice is a player decision. In the current single-server-call model there is no interactive mid-resolution prompt. For this increment, the server will auto-choose the consequence with the following deterministic priority (per user preference: always prefer drawing a desperation card):

Swap the first base card in deck for a drawn desperation card (removes that base card from play).
Swap the first base card in overheat for a drawn desperation card (if deck has no base card).
Lose 1 VP (if no valid base card exists in deck or overheat).
"First card" means the first is_base=True card found in the list order — no interactive pick. A UI for player choice is a follow-up task. This makes the feature fully testable without adding an async choice API.

NOTE

Desperate faces are deferred. The Desperate back of each card (e.g. "Thrust Ions: Move 5", "Ace Shot: +5 to Hit") is noted in the model but not resolved in this increment. Cards with a desperate face that are played on their basic face return to the player deck normally, just like any other desperation card. Resolving desperate faces is a follow-up task.

NOTE

"All She's Got" and "Hull Repair / Advanced Repair" are Especially Desperate / special-seal cards that don't fit the normal action-stack model. They are deferred per the rules doc.

Proposed Changes
1. Models (models.py)
[MODIFY] 
models.py
Add DesperationDeck dataclass with cards: list[Card] and a shuffle_marker_on_top: bool flag.
Add desperation_deck: DesperationDeck field to GameState.
Add desperation_hand: list[Card] to PlayerState (cards drawn but not yet placed in deck – simplifies draw-then-place).
2. Desperation Cards (decks.py)
[MODIFY] 
decks.py
Add create_desperation_deck() -> DesperationDeck with all cards from the rules (Table 12.2 + 13.1), excluding "Hull Repair", "Advanced Repair" (deferred), and "All She's Got" (deferred). Included cards:

qty	id prefix	name	family	basic_value	desperate_face
2	desp_thrust_ions_*	Thrust Ions	move	1	deferred
1	desp_turbo_ions	Turbo Ions	move	1	deferred
1	desp_homeward_bound	Homeward Bound	move	1	deferred
1	desp_treasure_hound	Treasure Hound	move	1	deferred
1	desp_evasive_action	Evasive Action	move	1	deferred
2	desp_ace_shot_*	Ace Shot	attack	1	deferred
1	desp_deadeye	Deadeye	attack	1	deferred
1	desp_nightjammer	Nightjammer	attack	1	deferred
1	desp_self_destruct	Self Destruct	attack	1	deferred
1	desp_death_blossom	Death Blossom	attack	1	deferred
2	desp_steady_shot_*	Steady Shot	attack	1	deferred
4	desp_targeted_attack_1_*	Desperation Attack 1	attack	1	N/A (targeted)
Cards have is_base=False. The targeted attack cards are proper targeted attacks (can designate a target); the others need a paired targeted attack card.

Add draw_from_desperation_deck(deck: DesperationDeck, rng: Random) -> Card that draws from the conceptual "bottom" (implemented as pop(0) from the list), reshuffles and re-tops sentinel when the sentinel is drawn.

3. Engine (engine.py)
[MODIFY] 
engine.py
create_initial_state: shuffle and attach desperation_deck to the new state.

_resolve_award_baubles: replace the placeholder desperation_card_drawn: True log with an actual draw-and-place call that appends the card to player.deck.

_apply_unshielded_damage: after the first shot that destroys a component, call _apply_desperation_consequence(state, target) exactly once per volley.

_apply_desperation_consequence(state, player): implements the auto-choice priority described above; emits a desperation_consequence event.

_resolve_stack_movement / _move_resolved_stack_cards: already correctly routes non-base cards back to deck (because is_base=False skips overheat). No change needed for basic-face use; desperate-face routing is deferred.

Validation in _validate_stack: update base_card_by_id calls to handle desperation cards. The validator currently calls base_card_by_id(selection.card_id) which will KeyError on desperation IDs. Fix by providing a combined lookup.

4. Card Lookup (decks.py and engine.py)
[MODIFY] 
decks.py
Add desperation_card_by_id(card_id: str) -> Card and card_by_id(card_id: str) -> Card (tries base first, then desperation).

[MODIFY] 
engine.py
Replace all base_card_by_id(...) calls with card_by_id(...).

5. Serialization (serialization.py)
[MODIFY] 
serialization.py
Add desperation_deck_to_dict / desperation_deck_from_dict. Wire into state_to_dict / state_from_dict.

6. Tests (tests/test_rules_engine.py)
[MODIFY] 
test_rules_engine.py
New test cases:

test_initial_state_has_desperation_deck – deck has correct card count (17 non-deferred cards + sentinel behavior).
test_bauble_award_draws_desperation_card_into_deck – player in bauble range gains a desperation card in their deck.
test_unshielded_damage_triggers_desperation_consequence_move_to_overheat – when first component destroyed, a base card moves to overheat.
test_desperation_consequence_swaps_base_for_desperation_card_when_deck_has_no_base – when deck has no base cards, swap a deck desperation/overheat card? (Check rules: if no valid base card to replace, lose 1 VP.)
test_desperation_consequence_vp_penalty_when_no_base_cards_anywhere – lose 1 VP when fully depleted.
test_desperation_card_not_overdriven – desperation card used with overdrive seal still has base value and goes to deck not overheat.
test_desperation_card_in_attack_stack_requires_targeted_attack_partner – (validation test, deferred per rules; desperation attack 1 targeted cards are full targeted attacks and can stand alone).
[NEW] 
test_desperation_deck.py
Unit tests specifically for the deck/draw mechanics (draw order, reshuffle sentinel).

Verification Plan
Automated Tests
powershell

python -m unittest discover -s tests
Expected: all existing 12 tests pass, plus ~7 new tests pass.

Manual Verification
Start a game in the debug UI, advance to Award Baubles while a ship is in a bauble hex, verify the player's deck grows by 1 card in the state panel.
Trigger unshielded damage and confirm the event log contains a desperation_consequence entry.