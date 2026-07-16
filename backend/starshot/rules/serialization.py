from __future__ import annotations

import hashlib

from starshot.rules.card_effects import static_card_effect_summary
from starshot.rules.models import (
    ActionStack,
    BaubleState,
    Card,
    CardFamily,
    DesperateFace,
    DesperationDeck,
    FleetCraftState,
    GamePhase,
    GameResult,
    GameState,
    OrderCardSelection,
    OrdersSubmission,
    PlayerState,
    RulesConfig,
    SealMode,
    ShipState,
    StarBreachState,
)
from starshot.rules.star_command import CAPTAINS_BY_ID, STARFALLS_BY_ID, captain_to_dict, starfall_to_dict
from starshot.rules import star_breach as sb_data
from starshot.rules import star_breach_spec as sb_spec
from starshot.rules.deck_data import active_catalog
from starshot.rules.ship_layout import BASE_SHIP_LAYOUT_ID, components_to_dict, damage_lanes_to_dict


def state_to_dict(state: GameState, *, reveal_orders: bool = True) -> dict:
    catalog = active_catalog()
    return {
        "deck_set_id": state.deck_set_id,
        "deck_set": deck_set_to_dict(catalog),
        "rules_config": rules_config_to_dict(catalog.rules_config),
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
        "active_expansions": list(state.active_expansions),
        "starfall_deck": list(state.starfall_deck),
        "active_starfall_id": state.active_starfall_id,
        "active_starfall": (
            starfall_to_dict(STARFALLS_BY_ID[state.active_starfall_id])
            if state.active_starfall_id in STARFALLS_BY_ID
            else None
        ),
        "active_starfall_round": state.active_starfall_round,
        "starfall_bauble_number": state.starfall_bauble_number,
        "star_breach": (
            star_breach_to_dict(state.star_breach, round_number=state.round_number)
            if state.star_breach
            else None
        ),
    }


def state_from_dict(data: dict) -> GameState:
    return GameState(
        players={player_id: player_from_dict(player) for player_id, player in data["players"].items()},
        deck_set_id=data.get("deck_set_id", ""),
        baubles=[bauble_from_dict(bauble) for bauble in data.get("baubles", [])],
        desperation_deck=desperation_deck_from_dict(data.get("desperation_deck", {})),
        round_number=data["round_number"],
        phase=GamePhase(data["phase"]),
        starting_player_id=data["starting_player_id"],
        rng_seed=data.get("rng_seed"),
        rng_step=data.get("rng_step", 0),
        event_log=list(data.get("event_log", [])),
        result=result_from_dict(data["result"]) if data.get("result") else None,
        active_expansions=tuple(data.get("active_expansions", ())),
        starfall_deck=list(data.get("starfall_deck", [])),
        active_starfall_id=data.get("active_starfall_id"),
        active_starfall_round=data.get("active_starfall_round"),
        starfall_bauble_number=data.get("starfall_bauble_number"),
        star_breach=star_breach_from_dict(data["star_breach"]) if data.get("star_breach") else None,
    )


def star_breach_to_dict(sb: StarBreachState, *, round_number: int = 1) -> dict:
    spec = sb_spec.spec_for(sb)
    destroyed = sorted(sb.destroyed_hexes)
    destroyed_components = sb_spec.destroyed_component_ids(spec, sb.destroyed_hexes)
    board_hexes = sb_data.boss_board_hexes(sb.anchor_q, sb.anchor_r, sb.facing)
    return {
        "scenario_id": sb.scenario_id,
        "boss_name": spec["name"],
        "prey_player_id": sb.prey_player_id,
        "anchor_q": sb.anchor_q,
        "anchor_r": sb.anchor_r,
        "facing": sb.facing,
        "board_hexes": [
            {"q": q, "r": r, "area": area}
            for (q, r), area in zip(board_hexes, sb_spec.board_hex_areas(spec))
        ],
        "destroyed_hexes": [[q, r] for q, r in destroyed],
        "destroyed_component_ids": sorted(destroyed_components),
        "shield_hp": dict(sb.shield_hp),
        "shield_max": dict(spec["shield_max"]),
        "progress": sb.progress,
        "tiers_unlocked": list(sb_spec.unlocked_tiers(spec, sb.progress)),
        "active_tiers": list(sb.active_tiers),
        "tier_progress": dict(spec["tier_progress"]),
        "expected_actions": sb_spec.expected_phase_actions(
            spec, sb.destroyed_hexes, sb.active_tiers, round_number
        ),
        "fleet": [fleet_craft_to_dict(craft) for craft in sb.fleet],
        "boss_movement_this_action": sb.boss_movement_this_action,
        "repaired_ship_ids_this_action": list(sb.repaired_ship_ids_this_action),
        "progressed_source_ids_this_action": list(sb.progressed_source_ids_this_action),
        "boss_layout": sb_spec.boss_layout_to_dict(spec),
        "roles": {role.id: sb_data.role_to_dict(role) for role in sb_data.ROLES},
        "boss_spec": sb.boss_spec,
    }


def star_breach_from_dict(data: dict) -> StarBreachState:
    return StarBreachState(
        scenario_id=data.get("scenario_id", "bauble_breacher"),
        prey_player_id=data.get("prey_player_id", ""),
        anchor_q=data.get("anchor_q", 0),
        anchor_r=data.get("anchor_r", 0),
        facing=data.get("facing", 5),
        destroyed_hexes={(hex_[0], hex_[1]) for hex_ in data.get("destroyed_hexes", [])},
        shield_hp=dict(data.get("shield_hp", {})),
        progress=data.get("progress", 0),
        active_tiers=tuple(data.get("active_tiers", ())),
        fleet=[fleet_craft_from_dict(craft) for craft in data.get("fleet", [])],
        boss_movement_this_action=data.get("boss_movement_this_action", 0),
        repaired_ship_ids_this_action=list(data.get("repaired_ship_ids_this_action", [])),
        progressed_source_ids_this_action=list(data.get("progressed_source_ids_this_action", [])),
        boss_spec=data.get("boss_spec"),
    )


def fleet_craft_to_dict(craft: FleetCraftState) -> dict:
    return {
        "id": craft.id,
        "kind": craft.kind,
        "color": craft.color,
        "q": craft.q,
        "r": craft.r,
        "hp": craft.hp,
        "max_hp": craft.max_hp,
        "destroyed": craft.destroyed,
        "movement_this_action": craft.movement_this_action,
    }


def fleet_craft_from_dict(data: dict) -> FleetCraftState:
    return FleetCraftState(
        id=data["id"],
        kind=data.get("kind", "hunter_killer"),
        color=data.get("color", "blue"),
        q=data.get("q", 0),
        r=data.get("r", 0),
        hp=data.get("hp", 0),
        max_hp=data.get("max_hp", data.get("hp", 0)),
        destroyed=data.get("destroyed", False),
        movement_this_action=data.get("movement_this_action", 0),
    )


def rules_config_to_dict(config: RulesConfig) -> dict:
    return {
        "overheat_pile": config.overheat_pile,
        "allow_mixed_card_type_stacks": config.allow_mixed_card_type_stacks,
        "overdrive_style": getattr(config.overdrive_style, "value", config.overdrive_style),
        "allow_overdrive_desperation": config.allow_overdrive_desperation,
    }


def deck_set_to_dict(catalog) -> dict:
    files = {
        name: deck_file_to_dict(catalog.path / filename)
        for name, filename in (
            ("manifest", "manifest.toml"),
            ("config", "config.toml"),
            ("base_deck", "base_deck.toml"),
            ("desperation_deck", "desperation_deck.toml"),
        )
    }
    return {
        "id": catalog.id,
        "name": catalog.name,
        "rules_version": catalog.rules_version,
        "path": str(catalog.path),
        "rules_config": rules_config_to_dict(catalog.rules_config),
        "files": files,
    }


def deck_file_to_dict(path) -> dict:
    exists = path.exists()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if exists else None,
    }


def player_to_dict(player: PlayerState, *, reveal_orders: bool) -> dict:
    return {
        "id": player.id,
        "deck": [card_to_dict(card) for card in player.deck],
        "hand": [card_to_dict(card) for card in player.hand],
        "discard": [card_to_dict(card) for card in player.discard],
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
        "captain_id": player.captain_id,
        "captain": captain_to_dict(CAPTAINS_BY_ID[player.captain_id]) if player.captain_id in CAPTAINS_BY_ID else None,
        "captain_options": [
            captain_to_dict(CAPTAINS_BY_ID[captain_id])
            for captain_id in player.captain_options
            if captain_id in CAPTAINS_BY_ID
        ],
        "roles": list(player.roles),
        "bonus_draws_pending": player.bonus_draws_pending,
    }


def player_from_dict(data: dict) -> PlayerState:
    return PlayerState(
        id=data["id"],
        deck=[card_from_dict(card) for card in data["deck"]],
        hand=[card_from_dict(card) for card in data.get("hand", [])],
        discard=[card_from_dict(card) for card in data.get("discard", [])],
        overheat=[card_from_dict(card) for card in data.get("overheat", [])],
        prepared_orders=(
            orders_from_dict(data["prepared_orders"]) if data.get("prepared_orders") else None
        ),
        victory_points=data.get("victory_points", 0),
        ship=ship_from_dict(data.get("ship", {})),
        eliminated=data.get("eliminated", False),
        captain_id=data.get("captain_id"),
        captain_options=tuple(
            option["id"] if isinstance(option, dict) else option
            for option in data.get("captain_options", ())
        ),
        roles=tuple(data.get("roles", ())),
        bonus_draws_pending=data.get("bonus_draws_pending", 0),
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
        "no_basic_face": card.no_basic_face,
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
        no_basic_face=data.get("no_basic_face", False),
        desperate_face=desperate_face_from_dict(data["desperate_face"]) if data.get("desperate_face") else None,
    )


def desperate_face_to_dict(face: DesperateFace) -> dict:
    return {
        "family": face.family.value,
        "value": face.value,
        "base_damage": face.base_damage,
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
        "side_slip_direction": face.side_slip_direction,
        "double_turn_right": face.double_turn_right,
        "double_turn_after_move": face.double_turn_after_move,
        "u_turn_move": face.u_turn_move,
        "u_turn_attack": face.u_turn_attack,
        "active_cooling": face.active_cooling,
        "lead_the_target": face.lead_the_target,
        "ramming_distance": face.ramming_distance,
        "ramming_damage": face.ramming_damage,
        "attacks_cone_120": face.attacks_cone_120,
        "repair_components": face.repair_components,
        "reconfigure_components": face.reconfigure_components,
    }


def desperate_face_from_dict(data: dict) -> DesperateFace:
    return DesperateFace(
        family=CardFamily(data["family"]),
        value=data.get("value", 0),
        base_damage=data.get("base_damage", 1),
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
        side_slip_direction=data.get("side_slip_direction"),
        double_turn_right=data.get("double_turn_right", False),
        double_turn_after_move=data.get("double_turn_after_move", False),
        u_turn_move=data.get("u_turn_move", False),
        u_turn_attack=data.get("u_turn_attack", False),
        active_cooling=data.get("active_cooling", False),
        lead_the_target=data.get("lead_the_target", False),
        ramming_distance=data.get("ramming_distance", 0),
        ramming_damage=data.get("ramming_damage", 0),
        attacks_cone_120=data.get("attacks_cone_120", False),
        repair_components=data.get("repair_components", 0),
        reconfigure_components=data.get("reconfigure_components", 0),
    )


def ship_to_dict(ship: ShipState) -> dict:
    return {
        "q": ship.q,
        "r": ship.r,
        "facing": ship.facing,
        "shields": ship.shields,
        "damage_taken": ship.damage_taken,
        "destroyed_components": sorted(ship.destroyed_components),
        "component_hit_counts": dict(ship.component_hit_counts),
        "layout_id": BASE_SHIP_LAYOUT_ID,
        "component_layout": components_to_dict(),
        "damage_lanes": damage_lanes_to_dict(),
        "destroyed": ship.destroyed,
        "knocked_out_round": ship.knocked_out_round,
        "knocked_out_action_number": ship.knocked_out_action_number,
        "knocked_out_phase": ship.knocked_out_phase.value if ship.knocked_out_phase else None,
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
        component_hit_counts=dict(data.get("component_hit_counts", {})),
        destroyed=data.get("destroyed", False),
        knocked_out_round=data.get("knocked_out_round"),
        knocked_out_action_number=data.get("knocked_out_action_number"),
        knocked_out_phase=GamePhase(data["knocked_out_phase"]) if data.get("knocked_out_phase") else None,
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
        "repair_component_ids": list(selection.repair_component_ids),
        "reconfigure_from_component_ids": list(selection.reconfigure_from_component_ids),
        "reconfigure_to_component_ids": list(selection.reconfigure_to_component_ids),
        "ace_lane_preference": selection.ace_lane_preference,
    }


def _lane_preference(value) -> int | None:
    try:
        lane = int(value)
    except (TypeError, ValueError):
        return None
    # Designed bosses may have up to 12 lanes (rolls 2-13); a preference past
    # the target area's die is harmless — the engine ignores unusable lanes.
    return lane if 2 <= lane <= 13 else None


def selection_from_dict(data: dict) -> OrderCardSelection:
    return OrderCardSelection(
        card_id=data["card_id"],
        face=data.get("face", "front"),
        orientation=data.get("orientation", "up"),
        target_player_id=data.get("target_player_id"),
        mode=data.get("mode"),
        repair_component_ids=tuple(data.get("repair_component_ids", ())),
        reconfigure_from_component_ids=tuple(data.get("reconfigure_from_component_ids", ())),
        reconfigure_to_component_ids=tuple(data.get("reconfigure_to_component_ids", ())),
        ace_lane_preference=_lane_preference(data.get("ace_lane_preference")),
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
