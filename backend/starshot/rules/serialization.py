from __future__ import annotations

from starshot.rules.models import (
    ActionStack,
    Card,
    CardFamily,
    GamePhase,
    GameResult,
    GameState,
    OrderCardSelection,
    OrdersSubmission,
    PlayerState,
    SealMode,
    ShipState,
)


def state_to_dict(state: GameState, *, reveal_orders: bool = True) -> dict:
    return {
        "round_number": state.round_number,
        "phase": state.phase.value,
        "starting_player_id": state.starting_player_id,
        "players": {
            player_id: player_to_dict(player, reveal_orders=reveal_orders)
            for player_id, player in state.players.items()
        },
        "event_log": state.event_log,
        "result": result_to_dict(state.result) if state.result else None,
    }


def state_from_dict(data: dict) -> GameState:
    return GameState(
        players={player_id: player_from_dict(player) for player_id, player in data["players"].items()},
        round_number=data["round_number"],
        phase=GamePhase(data["phase"]),
        starting_player_id=data["starting_player_id"],
        event_log=list(data.get("event_log", [])),
        result=result_from_dict(data["result"]) if data.get("result") else None,
    )


def player_to_dict(player: PlayerState, *, reveal_orders: bool) -> dict:
    return {
        "id": player.id,
        "deck": [card_to_dict(card) for card in player.deck],
        "overheat": [card_to_dict(card) for card in player.overheat],
        "prepared_orders": (
            orders_to_dict(player.prepared_orders)
            if reveal_orders and player.prepared_orders is not None
            else None
        ),
        "has_submitted_orders": player.prepared_orders is not None,
        "victory_points": player.victory_points,
        "ship": ship_to_dict(player.ship),
        "eliminated": player.eliminated,
    }


def player_from_dict(data: dict) -> PlayerState:
    return PlayerState(
        id=data["id"],
        deck=[card_from_dict(card) for card in data["deck"]],
        overheat=[card_from_dict(card) for card in data.get("overheat", [])],
        prepared_orders=(
            orders_from_dict(data["prepared_orders"]) if data.get("prepared_orders") else None
        ),
        victory_points=data.get("victory_points", 0),
        ship=ship_from_dict(data.get("ship", {})),
        eliminated=data.get("eliminated", False),
    )


def card_to_dict(card: Card) -> dict:
    return {
        "id": card.id,
        "name": card.name,
        "family": card.family.value,
        "value": card.value,
        "is_base": card.is_base,
    }


def card_from_dict(data: dict) -> Card:
    return Card(
        id=data["id"],
        name=data["name"],
        family=CardFamily(data["family"]),
        value=data["value"],
        is_base=data.get("is_base", True),
    )


def ship_to_dict(ship: ShipState) -> dict:
    return {
        "shields": ship.shields,
        "destroyed_components": sorted(ship.destroyed_components),
        "destroyed": ship.destroyed,
        "movement_this_action": ship.movement_this_action,
        "defense_bonus_this_action": ship.defense_bonus_this_action,
    }


def ship_from_dict(data: dict) -> ShipState:
    return ShipState(
        shields=data.get("shields", 2),
        destroyed_components=set(data.get("destroyed_components", [])),
        destroyed=data.get("destroyed", False),
        movement_this_action=data.get("movement_this_action", 0),
        defense_bonus_this_action=data.get("defense_bonus_this_action", 0),
    )


def orders_to_dict(orders: OrdersSubmission) -> dict:
    return {"stacks": [stack_to_dict(stack) for stack in orders.stacks]}


def orders_from_dict(data: dict) -> OrdersSubmission:
    stacks = tuple(stack_from_dict(stack) for stack in data["stacks"])
    if len(stacks) != 3:
        raise ValueError("Orders JSON must contain exactly three stacks.")
    return OrdersSubmission(stacks=stacks)  # type: ignore[arg-type]


def stack_to_dict(stack: ActionStack) -> dict:
    return {
        "action_number": stack.action_number,
        "seal_mode": stack.seal_mode.value,
        "cards": [selection_to_dict(selection) for selection in stack.cards],
    }


def stack_from_dict(data: dict) -> ActionStack:
    return ActionStack(
        action_number=data["action_number"],
        seal_mode=SealMode(data["seal_mode"]),
        cards=tuple(selection_from_dict(selection) for selection in data.get("cards", [])),
    )


def selection_to_dict(selection: OrderCardSelection) -> dict:
    return {
        "card_id": selection.card_id,
        "face": selection.face,
        "orientation": selection.orientation,
        "target_player_id": selection.target_player_id,
    }


def selection_from_dict(data: dict) -> OrderCardSelection:
    return OrderCardSelection(
        card_id=data["card_id"],
        face=data.get("face", "front"),
        orientation=data.get("orientation", "up"),
        target_player_id=data.get("target_player_id"),
    )


def result_to_dict(result: GameResult) -> dict:
    return {
        "winner_ids": list(result.winner_ids),
        "reason": result.reason,
        "is_tie": result.is_tie,
    }


def result_from_dict(data: dict) -> GameResult:
    return GameResult(
        winner_ids=tuple(data.get("winner_ids", [])),
        reason=data["reason"],
        is_tie=data.get("is_tie", False),
    )
