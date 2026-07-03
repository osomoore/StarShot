from __future__ import annotations

from copy import deepcopy
from random import Random

from starshot.rules.decks import base_card_by_id, create_base_deck
from starshot.rules.hex import move_forward, turn_left, turn_right, u_turn
from starshot.rules.models import (
    ActionStack,
    Card,
    GameConfig,
    GamePhase,
    GameResult,
    GameState,
    OrdersSubmission,
    PlayerState,
    SealMode,
    ShipState,
)


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

    rng = Random(config.seed)
    starting_player_id = rng.choice(player_ids)
    players = {
        player_id: PlayerState(id=player_id, deck=create_base_deck(), ship=_starting_ship(index))
        for index, player_id in enumerate(player_ids)
    }

    state = GameState(players=players, starting_player_id=starting_player_id)
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
    _validate_orders(player, orders)
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
    for player in state.players.values():
        player.ship.movement_this_action = 0
        player.ship.defense_bonus_this_action = 0

    for player in state.players.values():
        if player.eliminated or player.prepared_orders is None:
            continue
        stack = player.prepared_orders.stacks[action_number - 1]
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
        _move_resolved_stack_cards(state, player, action_number, stack)

    state.event_log.append(
        {
            "type": "combat_resolution_placeholder",
            "round": state.round_number,
            "action_number": action_number,
            "message": "Combat resolution is not implemented yet.",
        }
    )
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


def _change_phase(state: GameState, phase: GamePhase) -> None:
    state.phase = phase
    state.event_log.append({"type": "phase_changed", "phase": phase})


def _starting_ship(index: int) -> ShipState:
    starts = (
        ShipState(q=-6, r=0, facing=0),
        ShipState(q=6, r=0, facing=3),
        ShipState(q=0, r=-6, facing=5),
        ShipState(q=0, r=6, facing=2),
    )
    return starts[index]


def _player(state: GameState, player_id: str) -> PlayerState:
    try:
        return state.players[player_id]
    except KeyError as exc:
        raise RulesError(f"Unknown player: {player_id}") from exc


def _validate_orders(player: PlayerState, orders: OrdersSubmission) -> None:
    if len(orders.stacks) != 3:
        raise RulesError("Exactly three action stacks are required.")

    expected_numbers = (1, 2, 3)
    actual_numbers = tuple(stack.action_number for stack in orders.stacks)
    if actual_numbers != expected_numbers:
        raise RulesError("Action stacks must be ordered 1, 2, 3.")

    available = {card.id: card for card in player.deck}
    used_card_ids: set[str] = set()
    for stack in orders.stacks:
        _validate_stack(stack, available, used_card_ids)


def _validate_stack(stack: ActionStack, available: dict[str, Card], used_card_ids: set[str]) -> None:
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
            target_player_ids.add(selection.target_player_id)

    if len(families) > 1:
        raise RulesError("A stack cannot mix move and attack cards.")
    if len(target_player_ids) > 1:
        raise RulesError("All targeted attacks in a stack must target the same player.")


def _remove_ordered_cards_from_deck(player: PlayerState, orders: OrdersSubmission) -> None:
    ordered_ids = {selection.card_id for stack in orders.stacks for selection in stack.cards}
    player.deck = [card for card in player.deck if card.id not in ordered_ids]
