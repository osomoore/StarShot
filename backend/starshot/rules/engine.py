from __future__ import annotations

from copy import deepcopy
from random import Random

from starshot.rules.decks import create_base_deck
from starshot.rules.models import (
    ActionStack,
    Card,
    GameConfig,
    GamePhase,
    GameResult,
    GameState,
    OrdersSubmission,
    PlayerState,
)


class RulesError(ValueError):
    """Raised when a requested rules operation is illegal."""


def create_initial_state(config: GameConfig) -> GameState:
    player_ids = tuple(dict.fromkeys(config.player_ids))
    if len(player_ids) < 2 or len(player_ids) > 4:
        raise RulesError("StarShot requires 2 to 4 unique players.")

    rng = Random(config.seed)
    starting_player_id = rng.choice(player_ids)
    players = {player_id: PlayerState(id=player_id, deck=create_base_deck()) for player_id in player_ids}

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
    if state.phase in {GamePhase.COOLDOWN, GamePhase.ACTION_1, GamePhase.ACTION_2, GamePhase.ACTION_3}:
        return ["wait"]
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
