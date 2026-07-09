from __future__ import annotations

from starshot.rules.card_effects import static_card_effect_summary
from starshot.rules.models import (
    ActionStack,
    BaubleState,
    Card,
    CardFamily,
    DesperateFace,
    DesperationDeck,
    GamePhase,
    GameResult,
    GameState,
    OrderCardSelection,
    OrdersSubmission,
    PlayerState,
    SealMode,
    ShipState,
)
from starshot.rules.ship_layout import BASE_SHIP_LAYOUT_ID, components_to_dict, damage_lanes_to_dict


def state_to_dict(state: GameState, *, reveal_orders: bool = True) -> dict:
    return {
        "round_number": state.round_number,
        "phase": state.phase.value,
        "starting_player_id": state.starting_player_id,
        "rng_seed": state.rng_seed,
        "rng_step": state.rng_step,
        "baubles": [bauble_to_dict(bauble) for bauble in state.baubles],
        "desperation_deck": desperation_deck_to_dict(state.desperation_deck),
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
        baubles=[bauble_from_dict(bauble) for bauble in data.get("baubles", [])],
        desperation_deck=desperation_deck_from_dict(data.get("desperation_deck", {})),
        round_number=data["round_number"],
        phase=GamePhase(data["phase"]),
        starting_player_id=data["starting_player_id"],
        rng_seed=data.get("rng_seed"),
        rng_step=data.get("rng_step", 0),
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
        "orientation_options": list(card.orientation_options),
        "requires_target": card.requires_target,
        "is_hybrid": card.is_hybrid,
        "desperate_face": desperate_face_to_dict(card.desperate_face) if card.desperate_face else None,
        "effect": static_card_effect_summary(card),
    }


def card_from_dict(data: dict) -> Card:
    return Card(
        id=data["id"],
        name=data["name"],
        family=CardFamily(data["family"]),
        value=data["value"],
        is_base=data.get("is_base", True),
        orientation_options=tuple(data.get("orientation_options", ("forward", "turn_left", "turn_right", "u_turn"))),
        requires_target=data.get("requires_target", True),
        is_hybrid=data.get("is_hybrid", False),
        desperate_face=desperate_face_from_dict(data["desperate_face"]) if data.get("desperate_face") else None,
    )


def desperate_face_to_dict(face: DesperateFace) -> dict:
    return {
        "family": face.family.value,
        "value": face.value,
        "orientation_options": list(face.orientation_options),
        "requires_target": face.requires_target,
        "aim_bonus": face.aim_bonus,
        "damage_bonus": face.damage_bonus,
        "defense_bonus": face.defense_bonus,
        "always_hits": face.always_hits,
        "movement_disabled": face.movement_disabled,
        "warp_destination": face.warp_destination,
        "max_range": face.max_range,
        "fixed_defense_threshold": face.fixed_defense_threshold,
        "attacks_all": face.attacks_all,
    }


def desperate_face_from_dict(data: dict) -> DesperateFace:
    return DesperateFace(
        family=CardFamily(data["family"]),
        value=data.get("value", 0),
        orientation_options=tuple(data.get("orientation_options", ("forward",))),
        requires_target=data.get("requires_target", False),
        aim_bonus=data.get("aim_bonus", 0),
        damage_bonus=data.get("damage_bonus", 0),
        defense_bonus=data.get("defense_bonus", 0),
        always_hits=data.get("always_hits", False),
        movement_disabled=data.get("movement_disabled", False),
        warp_destination=data.get("warp_destination"),
        max_range=data.get("max_range"),
        fixed_defense_threshold=data.get("fixed_defense_threshold"),
        attacks_all=data.get("attacks_all", False),
    )


def ship_to_dict(ship: ShipState) -> dict:
    return {
        "q": ship.q,
        "r": ship.r,
        "facing": ship.facing,
        "shields": ship.shields,
        "damage_taken": ship.damage_taken,
        "destroyed_components": sorted(ship.destroyed_components),
        "layout_id": BASE_SHIP_LAYOUT_ID,
        "component_layout": components_to_dict(),
        "damage_lanes": damage_lanes_to_dict(),
        "destroyed": ship.destroyed,
        "movement_this_action": ship.movement_this_action,
        "defense_bonus_this_action": ship.defense_bonus_this_action,
    }


def ship_from_dict(data: dict) -> ShipState:
    return ShipState(
        q=data.get("q", 0),
        r=data.get("r", 0),
        facing=data.get("facing", 0),
        shields=data.get("shields", 2),
        damage_taken=data.get("damage_taken", 0),
        destroyed_components=set(data.get("destroyed_components", [])),
        destroyed=data.get("destroyed", False),
        movement_this_action=data.get("movement_this_action", 0),
        defense_bonus_this_action=data.get("defense_bonus_this_action", 0),
    )


def bauble_to_dict(bauble: BaubleState) -> dict:
    return {
        "id": bauble.id,
        "number": bauble.number,
        "q": bauble.q,
        "r": bauble.r,
        "victory_points": bauble.victory_points,
        "is_fang": bauble.is_fang,
        "claimed_by": list(bauble.claimed_by),
    }


def bauble_from_dict(data: dict) -> BaubleState:
    return BaubleState(
        id=data["id"],
        number=data["number"],
        q=data["q"],
        r=data["r"],
        victory_points=data["victory_points"],
        is_fang=data.get("is_fang", False),
        claimed_by=list(data.get("claimed_by", [])),
    )


def desperation_deck_to_dict(deck: DesperationDeck) -> dict:
    return {
        "cards": [card_to_dict(card) for card in deck.cards],
        "shuffle_marker_on_top": deck.shuffle_marker_on_top,
    }


def desperation_deck_from_dict(data: dict) -> DesperationDeck:
    return DesperationDeck(
        cards=[card_from_dict(card) for card in data.get("cards", [])],
        shuffle_marker_on_top=data.get("shuffle_marker_on_top", True),
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
        "mode": selection.mode,
    }


def selection_from_dict(data: dict) -> OrderCardSelection:
    return OrderCardSelection(
        card_id=data["card_id"],
        face=data.get("face", "front"),
        orientation=data.get("orientation", "up"),
        target_player_id=data.get("target_player_id"),
        mode=data.get("mode"),
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
