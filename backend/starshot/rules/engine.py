from __future__ import annotations

from copy import deepcopy
from random import Random

from starshot.rules.decks import base_card_by_id, create_base_deck
from starshot.rules.hex import corner_start, hex_distance, move_forward, turn_left, turn_right, u_turn
from starshot.rules.models import (
    ActionStack,
    Card,
    CardFamily,
    GameConfig,
    GamePhase,
    GameResult,
    GameState,
    OrdersSubmission,
    PlayerState,
    SealMode,
    ShipState,
)
from starshot.rules.ship_layout import first_intact_component_for_lane, is_ship_destroyed


class RulesError(ValueError):
    """Raised when a requested rules operation is illegal."""


ACTION_PHASES = (GamePhase.ACTION_1, GamePhase.ACTION_2, GamePhase.ACTION_3)
NEXT_PHASE = {
    GamePhase.ACTION_1: GamePhase.ACTION_2,
    GamePhase.ACTION_2: GamePhase.ACTION_3,
    GamePhase.ACTION_3: GamePhase.AWARD_BAUBLES,
}


def create_initial_state(config: GameConfig) -> GameState:
    player_ids = tuple(dict.fromkeys(config.player_ids))
    if len(player_ids) < 2 or len(player_ids) > 4:
        raise RulesError("StarShot requires 2 to 4 unique players.")

    setup_rng = Random(config.seed)
    starting_player_id = setup_rng.choice(player_ids)
    rng_seed = config.seed if config.seed is not None else setup_rng.randrange(1, 2**31)
    players = {
        player_id: PlayerState(id=player_id, deck=create_base_deck(), ship=_starting_ship(index))
        for index, player_id in enumerate(player_ids)
    }

    state = GameState(players=players, starting_player_id=starting_player_id, rng_seed=rng_seed)
    state.event_log.append(
        {
            "type": "game_created",
            "round": state.round_number,
            "phase": state.phase,
            "players": list(player_ids),
            "starting_player_id": starting_player_id,
        }
    )
    return state


def legal_actions(state: GameState, player_id: str) -> list[str]:
    _player(state, player_id)
    if state.phase == GamePhase.GIVE_ORDERS:
        return ["submit_orders"]
    if state.phase == GamePhase.COMPLETE:
        return []
    return ["resolve"]


def submit_orders(state: GameState, player_id: str, orders: OrdersSubmission) -> GameState:
    if state.phase != GamePhase.GIVE_ORDERS:
        raise RulesError("Orders may only be submitted during give_orders.")

    next_state = deepcopy(state)
    player = _player(next_state, player_id)
    _validate_orders(next_state, player, orders)
    player.prepared_orders = orders
    _remove_ordered_cards_from_deck(player, orders)
    next_state.event_log.append(
        {
            "type": "orders_submitted",
            "round": next_state.round_number,
            "player_id": player_id,
            "stack_count": len(orders.stacks),
        }
    )

    if all(p.prepared_orders is not None or p.eliminated for p in next_state.players.values()):
        next_state.phase = GamePhase.COOLDOWN
        next_state.event_log.append({"type": "phase_changed", "phase": next_state.phase})

    return next_state


def apply_action(state: GameState, player_id: str, action: dict) -> GameState:
    if action.get("type") != "submit_orders":
        raise RulesError(f"Unsupported action type: {action.get('type')}")
    return submit_orders(state, player_id, action["orders"])


def resolve_next_step(state: GameState) -> GameState:
    if state.phase == GamePhase.GIVE_ORDERS:
        raise RulesError("Cannot resolve until all players submit orders.")
    if state.phase == GamePhase.COMPLETE:
        raise RulesError("Cannot resolve a completed game.")

    next_state = deepcopy(state)
    if next_state.phase == GamePhase.COOLDOWN:
        _resolve_cooldown(next_state)
    elif next_state.phase in ACTION_PHASES:
        _resolve_action_phase(next_state)
    elif next_state.phase == GamePhase.AWARD_BAUBLES:
        _resolve_award_baubles(next_state)
    elif next_state.phase == GamePhase.CLEANUP:
        _resolve_cleanup(next_state)
    else:
        raise RulesError(f"Unsupported phase: {next_state.phase}")
    return next_state


def is_game_over(state: GameState) -> GameResult | None:
    living = [player.id for player in state.players.values() if not player.ship.destroyed and not player.eliminated]
    if len(living) == 1:
        return GameResult(winner_ids=(living[0],), reason="last_ship_standing")
    if len(living) == 0:
        return GameResult(winner_ids=(), reason="all_ships_destroyed", is_tie=True)
    if state.round_number > 6:
        top_vp = max(player.victory_points for player in state.players.values())
        winners = tuple(player.id for player in state.players.values() if player.victory_points == top_vp)
        return GameResult(winner_ids=winners, reason="round_six_victory_points", is_tie=len(winners) > 1)
    return None


def _resolve_cooldown(state: GameState) -> None:
    for player in state.players.values():
        if not player.overheat:
            continue
        cooled_ids = [card.id for card in player.overheat]
        player.deck.extend(player.overheat)
        player.overheat = []
        state.event_log.append(
            {
                "type": "cards_cooled",
                "round": state.round_number,
                "player_id": player.id,
                "card_ids": cooled_ids,
            }
        )
    _change_phase(state, GamePhase.ACTION_1)


def _resolve_action_phase(state: GameState) -> None:
    action_number = ACTION_PHASES.index(state.phase) + 1
    revealed_stacks: dict[str, ActionStack] = {}
    for player in state.players.values():
        player.ship.movement_this_action = 0
        player.ship.defense_bonus_this_action = 0

    for player in state.players.values():
        if player.eliminated or player.prepared_orders is None:
            continue
        stack = player.prepared_orders.stacks[action_number - 1]
        revealed_stacks[player.id] = stack
        state.event_log.append(
            {
                "type": "action_revealed",
                "round": state.round_number,
                "phase": state.phase,
                "player_id": player.id,
                "action_number": action_number,
                "seal_mode": stack.seal_mode,
                "cards": [
                    {
                        "card_id": selection.card_id,
                        "face": selection.face,
                        "orientation": selection.orientation,
                        "target_player_id": selection.target_player_id,
                    }
                    for selection in stack.cards
                ],
            }
        )
        _resolve_stack_movement(state, player, action_number, stack)

    _resolve_combat(state, action_number, revealed_stacks)

    for player_id in _player_order_from_starting_player(state):
        player = state.players[player_id]
        stack = revealed_stacks.get(player_id)
        if stack is not None:
            _move_resolved_stack_cards(state, player, action_number, stack)

    _change_phase(state, NEXT_PHASE[state.phase])


def _resolve_stack_movement(state: GameState, player: PlayerState, action_number: int, stack: ActionStack) -> None:
    movement_steps: list[dict] = []
    for selection in stack.cards:
        card = base_card_by_id(selection.card_id)
        if card.family.value != "move":
            continue

        distance = card.value + (1 if stack.seal_mode == SealMode.OVERDRIVE and card.is_base else 0)
        before = {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing}
        move_choice = "forward" if selection.orientation == "up" else selection.orientation

        if move_choice == "forward":
            player.ship.q, player.ship.r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
            player.ship.movement_this_action += distance
        elif move_choice == "turn_left":
            player.ship.q, player.ship.r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
            player.ship.facing = turn_left(player.ship.facing)
            player.ship.movement_this_action += distance
        elif move_choice == "turn_right":
            player.ship.q, player.ship.r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
            player.ship.facing = turn_right(player.ship.facing)
            player.ship.movement_this_action += distance
        elif move_choice == "u_turn":
            player.ship.facing = u_turn(player.ship.facing)
        else:
            raise RulesError(f"Unsupported move orientation: {move_choice}")

        movement_steps.append(
            {
                "card_id": card.id,
                "choice": move_choice,
                "distance": 0 if move_choice == "u_turn" else distance,
                "before": before,
                "after": {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing},
            }
        )

    if movement_steps:
        state.event_log.append(
            {
                "type": "movement_resolved",
                "round": state.round_number,
                "player_id": player.id,
                "action_number": action_number,
                "steps": movement_steps,
                "movement_this_action": player.ship.movement_this_action,
            }
        )


def _move_resolved_stack_cards(state: GameState, player: PlayerState, action_number: int, stack: ActionStack) -> None:
    returned: list[str] = []
    overheated: list[str] = []
    for selection in stack.cards:
        card = base_card_by_id(selection.card_id)
        if stack.seal_mode == SealMode.OVERDRIVE and card.is_base:
            player.overheat.append(card)
            overheated.append(card.id)
        else:
            player.deck.append(card)
            returned.append(card.id)

    if returned or overheated:
        state.event_log.append(
            {
                "type": "action_cards_moved",
                "round": state.round_number,
                "player_id": player.id,
                "action_number": action_number,
                "returned_to_deck": returned,
                "moved_to_overheat": overheated,
            }
        )


def _resolve_combat(state: GameState, action_number: int, revealed_stacks: dict[str, ActionStack]) -> None:
    shielded_target_ids: set[str] = set()
    resolved_any = False
    for attacker_id in _player_order_from_starting_player(state):
        attacker = state.players[attacker_id]
        if attacker.eliminated:
            continue
        stack = revealed_stacks.get(attacker_id)
        if stack is None:
            continue

        attack_cards = _attack_cards_for_stack(stack)
        if not attack_cards:
            continue

        target_id = _target_player_id_for_attack(stack)
        if target_id is None:
            continue
        target = _player(state, target_id)
        if target.eliminated or target.ship.destroyed:
            state.event_log.append(
                {
                    "type": "volley_skipped",
                    "round": state.round_number,
                    "action_number": action_number,
                    "attacker_id": attacker_id,
                    "target_id": target_id,
                    "reason": "target_not_active",
                }
            )
            resolved_any = True
            continue

        damage = sum(
            card.value + (1 if stack.seal_mode == SealMode.OVERDRIVE and card.is_base else 0)
            for card in attack_cards
        )
        distance = hex_distance(attacker.ship.q, attacker.ship.r, target.ship.q, target.ship.r)
        defense_threshold = distance + target.ship.movement_this_action + target.ship.defense_bonus_this_action
        roll = _roll_2d12(state)
        hit = roll >= defense_threshold
        event = {
            "type": "volley_resolved",
            "round": state.round_number,
            "action_number": action_number,
            "attacker_id": attacker_id,
            "target_id": target_id,
            "card_ids": [card.id for card in attack_cards],
            "damage": damage,
            "distance": distance,
            "target_movement": target.ship.movement_this_action,
            "target_defense_bonus": target.ship.defense_bonus_this_action,
            "defense_threshold": defense_threshold,
            "roll": roll,
            "hit": hit,
            "shielded": False,
            "damage_applied": 0,
            "vp_awarded": 0,
        }

        if hit and (target.ship.shields > 0 or target_id in shielded_target_ids):
            if target_id not in shielded_target_ids:
                target.ship.shields -= 1
                shielded_target_ids.add(target_id)
            attacker.victory_points += 1
            event["shielded"] = True
            event["vp_awarded"] = 1
        elif hit:
            damage_result = _apply_unshielded_damage(state, target, damage)
            destroyed_by_volley = not damage_result["was_destroyed"] and target.ship.destroyed
            vp_awarded = 3 if destroyed_by_volley else 1 if damage_result["damage_applied"] > 0 else 0
            attacker.victory_points += vp_awarded
            event.update(damage_result)
            event["vp_awarded"] = vp_awarded

        state.event_log.append(event)
        resolved_any = True

    if not resolved_any:
        state.event_log.append(
            {
                "type": "combat_resolved",
                "round": state.round_number,
                "action_number": action_number,
                "message": "No attacks were resolved.",
            }
        )


def _target_player_id_for_attack(stack: ActionStack) -> str | None:
    for selection in stack.cards:
        card = base_card_by_id(selection.card_id)
        if card.family == CardFamily.ATTACK:
            return selection.target_player_id
    return None


def _attack_cards_for_stack(stack: ActionStack) -> list[Card]:
    attack_cards: list[Card] = []
    for selection in stack.cards:
        card = base_card_by_id(selection.card_id)
        if card.family == CardFamily.ATTACK:
            attack_cards.append(card)
    return attack_cards


def _apply_unshielded_damage(state: GameState, target: PlayerState, damage: int) -> dict:
    shots: list[dict] = []
    was_destroyed = target.ship.destroyed

    for shot_number in range(1, damage + 1):
        lane_roll = _roll_d12(state)
        component = first_intact_component_for_lane(lane_roll, target.ship.destroyed_components)
        shot = {
            "shot_number": shot_number,
            "roll": lane_roll,
            "lane": lane_roll,
            "component_id": None,
            "component_type": None,
            "destroyed": False,
        }
        if component is not None:
            target.ship.destroyed_components.add(component.id)
            target.ship.damage_taken += 1
            shot.update(
                {
                    "component_id": component.id,
                    "component_type": component.component_type,
                    "destroyed": True,
                }
            )
            target.ship.destroyed = is_ship_destroyed(target.ship.destroyed_components)
        shots.append(shot)

    return {
        "damage_applied": sum(1 for shot in shots if shot["destroyed"]),
        "damage_rolls": [shot["roll"] for shot in shots],
        "damage_shots": shots,
        "target_damage_taken": target.ship.damage_taken,
        "target_destroyed_components": sorted(target.ship.destroyed_components),
        "target_destroyed": target.ship.destroyed,
        "was_destroyed": was_destroyed,
    }


def _roll_2d12(state: GameState) -> int:
    if state.rng_seed is None:
        state.rng_seed = 0
    rng = Random(state.rng_seed)
    for _ in range(state.rng_step):
        rng.randint(1, 12)
    first = rng.randint(1, 12)
    second = rng.randint(1, 12)
    state.rng_step += 2
    return first + second


def _roll_d12(state: GameState) -> int:
    if state.rng_seed is None:
        state.rng_seed = 0
    rng = Random(state.rng_seed)
    for _ in range(state.rng_step):
        rng.randint(1, 12)
    value = rng.randint(1, 12)
    state.rng_step += 1
    return value


def _resolve_award_baubles(state: GameState) -> None:
    state.event_log.append(
        {
            "type": "award_baubles_placeholder",
            "round": state.round_number,
            "message": "Bauble rewards are not implemented yet.",
        }
    )
    _change_phase(state, GamePhase.CLEANUP)


def _resolve_cleanup(state: GameState) -> None:
    result = _round_completion_result(state)
    if result is not None:
        state.result = result
        _change_phase(state, GamePhase.COMPLETE)
        return

    for player in state.players.values():
        player.prepared_orders = None
        player.ship.movement_this_action = 0
        player.ship.defense_bonus_this_action = 0

    state.round_number += 1
    state.starting_player_id = _next_starting_player_id(state)
    state.event_log.append(
        {
            "type": "round_advanced",
            "round": state.round_number,
            "starting_player_id": state.starting_player_id,
        }
    )
    _change_phase(state, GamePhase.GIVE_ORDERS)


def _round_completion_result(state: GameState) -> GameResult | None:
    living = [player.id for player in state.players.values() if not player.ship.destroyed and not player.eliminated]
    if len(living) == 1:
        return GameResult(winner_ids=(living[0],), reason="last_ship_standing")
    if len(living) == 0:
        return GameResult(winner_ids=(), reason="all_ships_destroyed", is_tie=True)
    if state.round_number >= 6:
        top_vp = max(player.victory_points for player in state.players.values())
        winners = tuple(player.id for player in state.players.values() if player.victory_points == top_vp)
        return GameResult(winner_ids=winners, reason="round_six_victory_points", is_tie=len(winners) > 1)
    return None


def _next_starting_player_id(state: GameState) -> str:
    player_ids = tuple(state.players)
    current_index = player_ids.index(state.starting_player_id)
    return player_ids[(current_index + 1) % len(player_ids)]


def _player_order_from_starting_player(state: GameState) -> tuple[str, ...]:
    player_ids = tuple(state.players)
    current_index = player_ids.index(state.starting_player_id)
    return player_ids[current_index:] + player_ids[:current_index]


def _change_phase(state: GameState, phase: GamePhase) -> None:
    state.phase = phase
    state.event_log.append({"type": "phase_changed", "phase": phase})


def _starting_ship(index: int) -> ShipState:
    q, r, facing = corner_start(index)
    return ShipState(q=q, r=r, facing=facing)


def _player(state: GameState, player_id: str) -> PlayerState:
    try:
        return state.players[player_id]
    except KeyError as exc:
        raise RulesError(f"Unknown player: {player_id}") from exc


def _validate_orders(state: GameState, player: PlayerState, orders: OrdersSubmission) -> None:
    if len(orders.stacks) != 3:
        raise RulesError("Exactly three action stacks are required.")

    expected_numbers = (1, 2, 3)
    actual_numbers = tuple(stack.action_number for stack in orders.stacks)
    if actual_numbers != expected_numbers:
        raise RulesError("Action stacks must be ordered 1, 2, 3.")

    available = {card.id: card for card in player.deck}
    used_card_ids: set[str] = set()
    for stack in orders.stacks:
        _validate_stack(state, player, stack, available, used_card_ids)


def _validate_stack(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    available: dict[str, Card],
    used_card_ids: set[str],
) -> None:
    if len(stack.cards) > 2:
        raise RulesError("An action stack may contain at most two command cards.")

    families = set()
    target_player_ids = set()
    for selection in stack.cards:
        if selection.card_id in used_card_ids:
            raise RulesError(f"Card is already used in this order set: {selection.card_id}")
        card = available.get(selection.card_id)
        if card is None:
            raise RulesError(f"Card is not available in deck: {selection.card_id}")
        used_card_ids.add(selection.card_id)
        families.add(card.family)
        if card.family.value == "attack":
            if not selection.target_player_id:
                raise RulesError("Attack cards require a target player.")
            if selection.target_player_id == "":
                raise RulesError("Attack cards require a target player.")
            if selection.target_player_id == player.id:
                raise RulesError("Attack cards must target an enemy player.")
            if selection.target_player_id not in state.players:
                raise RulesError(f"Unknown attack target: {selection.target_player_id}")
            target_player_ids.add(selection.target_player_id)

    if len(families) > 1:
        raise RulesError("A stack cannot mix move and attack cards.")
    if len(target_player_ids) > 1:
        raise RulesError("All targeted attacks in a stack must target the same player.")


def _remove_ordered_cards_from_deck(player: PlayerState, orders: OrdersSubmission) -> None:
    ordered_ids = {selection.card_id for stack in orders.stacks for selection in stack.cards}
    player.deck = [card for card in player.deck if card.id not in ordered_ids]
