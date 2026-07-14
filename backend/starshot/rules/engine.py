from __future__ import annotations

from copy import deepcopy
from random import Random

from starshot.rules.baubles import (
    BaublePlacementError,
    bauble_event_payload,
    create_baubles,
    fang_vp_for_round,
    ship_inside_bauble,
)
from starshot.rules.card_piles import (
    available_order_cards,
    discard_hand,
    draw_hand,
    remove_ordered_cards_from_hand,
)
from starshot.rules.deck_data import active_catalog
from starshot.rules.card_effects import (
    card_aim_bonus as _effect_card_aim_bonus,
    card_always_hits as _effect_card_always_hits,
    card_attacks_all as _effect_card_attacks_all,
    card_damage_bonus as _effect_card_damage_bonus,
    card_defense_bonus as _effect_card_defense_bonus,
    card_fixed_defense_threshold as _effect_card_fixed_defense_threshold,
    card_max_range as _effect_card_max_range,
    card_movement_disabled as _effect_card_movement_disabled,
    card_orientation_options as _effect_card_orientation_options,
    card_requires_target as _effect_card_requires_target,
    card_value as _effect_card_value,
    card_warp_destination as _effect_card_warp_destination,
    interpret_card,
    is_desperate_face,
    selected_card_family as _effect_selected_card_family,
)
from starshot.rules.decks import (
    card_by_id,
    create_base_deck,
)
from starshot.rules.desperation import (
    create_desperation_deck,
    draw_desperation_card,
    return_desperation_card,
)
from starshot.rules.hex import (
    clamp_to_board,
    corner_start,
    hex_distance,
    is_within_board,
    move_forward,
    turn_left,
    turn_right,
    u_turn,
)
from starshot.rules.models import (
    ActionStack,
    Card,
    CardFamily,
    FleetCraftState,
    GameConfig,
    GamePhase,
    GameResult,
    GameState,
    OrderCardSelection,
    OrdersSubmission,
    OverdriveStyle,
    PlayerState,
    SealMode,
    ShipState,
    StarBreachState,
)
from starshot.rules.ship_layout import (
    BASE_SHIP_COMPONENTS,
    BASE_SHIP_COMPONENT_BY_ID,
    detached_component_ids,
    first_intact_component_for_lane,
    is_ship_destroyed,
)
from starshot.rules.star_command import CAPTAINS, CAPTAINS_BY_ID, EXPANSION_ID as STAR_COMMAND_ID, STARFALLS, STARFALLS_BY_ID
from starshot.rules import star_breach as sb_data
from starshot.rules.star_breach import EXPANSION_ID as STAR_BREACH_ID

# Lateral direction offsets for Side Slip (perpendicular to facing).
# slip_right = facing - 1 (mod 6); slip_left = facing + 1 (mod 6).
_SLIP_RIGHT_OFFSET = -1
_SLIP_LEFT_OFFSET = 1


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
    star_breach_active = STAR_BREACH_ID in config.active_expansions
    minimum_players = 1 if star_breach_active else 2
    if len(player_ids) < minimum_players or len(player_ids) > 4:
        if star_breach_active:
            raise RulesError("StarBreach requires 1 to 4 unique players.")
        raise RulesError("StarShot requires 2 to 4 unique players.")

    catalog = active_catalog()
    if config.deck_set_id is not None and config.deck_set_id != catalog.id:
        raise RulesError(
            f"Requested deck set {config.deck_set_id!r}, but active deck set is {catalog.id!r}."
        )

    setup_rng = Random(config.seed)
    starting_player_id = setup_rng.choice(player_ids)
    rng_seed = config.seed if config.seed is not None else setup_rng.randrange(1, 2**31)
    players = {
        player_id: PlayerState(
            id=player_id,
            deck=create_base_deck(),
            ship=_starting_ship_star_breach(index) if star_breach_active else _starting_ship(index),
        )
        for index, player_id in enumerate(player_ids)
    }
    if config.seed is None:
        for player in players.values():
            setup_rng.shuffle(player.deck)
    if config.debug_start_with_attack_desperation_card:
        from starshot.rules.desperation import desperation_card_by_id

        for player in players.values():
            player.deck.append(desperation_card_by_id("desp_steady_shot_a"))
    if star_breach_active:
        _assign_star_breach_roles(players)
    for player in players.values():
        draw_hand(player)

    try:
        baubles = create_baubles(setup_rng, players)
    except BaublePlacementError as exc:
        raise RulesError(str(exc)) from exc

    desperation_deck = create_desperation_deck(setup_rng)
    state = GameState(
        players=players,
        deck_set_id=catalog.id,
        baubles=baubles,
        desperation_deck=desperation_deck,
        starting_player_id=starting_player_id,
        rng_seed=rng_seed,
        active_expansions=tuple(config.active_expansions),
    )
    state.event_log.append(
        {
            "type": "game_created",
            "round": state.round_number,
            "phase": state.phase,
            "players": list(player_ids),
            "starting_player_id": starting_player_id,
            "deck_set_id": catalog.id,
            "baubles": [bauble_event_payload(bauble) for bauble in baubles],
        }
    )
    for player in state.players.values():
        if player.hand:
            state.event_log.append(
                {
                    "type": "hand_drawn",
                    "round": state.round_number,
                    "player_id": player.id,
                    "card_ids": [card.id for card in player.hand],
                    "deck_count": len(player.deck),
                    "hand_count": len(player.hand),
                    "discard_count": len(player.discard),
                }
            )
    if _star_command_enabled(state):
        _initialize_star_command(state)
    if star_breach_active:
        _initialize_star_breach(state)
    return state


def legal_actions(state: GameState, player_id: str) -> list[str]:
    _player(state, player_id)
    if _captain_choice_pending(state, player_id):
        return ["choose_captain"]
    if state.phase == GamePhase.GIVE_ORDERS:
        return ["submit_orders"]
    if state.phase == GamePhase.COMPLETE:
        return []
    return ["resolve"]


def submit_orders(state: GameState, player_id: str, orders: OrdersSubmission) -> GameState:
    _validate_active_deck_set(state)
    if state.phase != GamePhase.GIVE_ORDERS:
        raise RulesError("Orders may only be submitted during give_orders.")
    if _captain_choice_pending(state, player_id):
        raise RulesError("Choose a StarCommand captain before giving orders.")

    next_state = deepcopy(state)
    player = _player(next_state, player_id)
    _validate_orders(next_state, player, orders)
    player.prepared_orders = orders
    _remove_ordered_cards_from_hand(player, orders)
    _discard_unused_hand(next_state, player)
    next_state.event_log.append(
        {
            "type": "orders_submitted",
            "round": next_state.round_number,
            "player_id": player_id,
            "stack_count": len(orders.stacks),
            "stacks": [
                {
                    "action_number": stack.action_number,
                    "seal_mode": stack.seal_mode,
                    "cards": [
                        {
                            "card_id": selection.card_id,
                            "face": selection.face,
                            "orientation": selection.orientation,
                            "target_player_id": selection.target_player_id,
                            "mode": selection.mode,
                            "repair_component_ids": list(selection.repair_component_ids),
                            "reconfigure_from_component_ids": list(selection.reconfigure_from_component_ids),
                            "reconfigure_to_component_ids": list(selection.reconfigure_to_component_ids),
                        }
                        for selection in stack.cards
                    ],
                }
                for stack in orders.stacks
            ],
        }
    )

    if all(p.prepared_orders is not None or p.eliminated for p in next_state.players.values()):
        next_state.phase = GamePhase.ACTION_1
        next_state.event_log.append({"type": "phase_changed", "phase": next_state.phase})

    return next_state


def apply_action(state: GameState, player_id: str, action: dict) -> GameState:
    if action.get("type") == "choose_captain":
        return choose_captain(state, player_id, action["captain_id"])
    if action.get("type") != "submit_orders":
        raise RulesError(f"Unsupported action type: {action.get('type')}")
    return submit_orders(state, player_id, action["orders"])


def choose_captain(state: GameState, player_id: str, captain_id: str) -> GameState:
    _validate_active_deck_set(state)
    if not _star_command_enabled(state):
        raise RulesError("StarCommand is not active for this game.")
    next_state = deepcopy(state)
    player = _player(next_state, player_id)
    if player.captain_id:
        raise RulesError("Captain already chosen.")
    if captain_id not in player.captain_options:
        raise RulesError("That captain is not one of this player's options.")
    player.captain_id = captain_id
    _apply_captain_setup(player)
    captain = CAPTAINS_BY_ID[captain_id]
    next_state.event_log.append(
        {
            "type": "captain_chosen",
            "round": next_state.round_number,
            "player_id": player_id,
            "captain_id": captain_id,
            "captain_name": captain.name,
            "captain_callsign": captain.callsign,
        }
    )
    return next_state


def resolve_next_step(state: GameState) -> GameState:
    _validate_active_deck_set(state)
    if state.phase == GamePhase.GIVE_ORDERS:
        raise RulesError("Cannot resolve until all players submit orders.")
    if _any_captain_choice_pending(state):
        raise RulesError("Cannot resolve until all StarCommand captains are chosen.")
    if state.phase == GamePhase.COMPLETE:
        raise RulesError("Cannot resolve a completed game.")

    next_state = deepcopy(state)
    if next_state.phase in ACTION_PHASES:
        _resolve_action_phase(next_state)
    elif next_state.phase == GamePhase.AWARD_BAUBLES:
        _resolve_award_baubles(next_state)
    elif next_state.phase == GamePhase.CLEANUP:
        _resolve_cleanup(next_state)
    else:
        raise RulesError(f"Unsupported phase: {next_state.phase}")
    return next_state


def is_game_over(state: GameState) -> GameResult | None:
    if state.star_breach is not None:
        return _star_breach_result(state, final_round_complete=state.round_number > 6)
    living = [player.id for player in state.players.values() if not player.ship.destroyed and not player.eliminated]
    if len(living) == 1:
        return GameResult(winner_ids=(living[0],), reason="last_ship_standing")
    if len(living) == 0:
        return GameResult(winner_ids=(), reason="all_ships_destroyed", is_tie=True)
    if state.round_number > 6:
        contenders = [state.players[player_id] for player_id in living]
        top_vp = max(player.victory_points for player in contenders)
        winners = tuple(player.id for player in contenders if player.victory_points == top_vp)
        return GameResult(winner_ids=winners, reason="round_six_victory_points", is_tie=len(winners) > 1)
    return None


def _resolve_action_phase(state: GameState) -> None:
    action_number = ACTION_PHASES.index(state.phase) + 1
    if state.star_breach is not None:
        _resolve_boss_phase(state, sb_data.BOSS_PHASES_BY_PLAYER_ACTION[action_number])
        if state.phase == GamePhase.COMPLETE:
            return
        state.star_breach.repaired_ship_ids_this_action = []
    revealed_stacks: dict[str, ActionStack] = {}
    for player in state.players.values():
        player.ship.movement_this_action = 0
        player.ship.defense_bonus_this_action = 0

    for player in state.players.values():
        if player.eliminated or player.ship.destroyed or player.prepared_orders is None:
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
                        "mode": selection.mode,
                        "repair_component_ids": list(selection.repair_component_ids),
                        "reconfigure_from_component_ids": list(selection.reconfigure_from_component_ids),
                        "reconfigure_to_component_ids": list(selection.reconfigure_to_component_ids),
                    }
                    for selection in stack.cards
                ],
            }
        )
        _resolve_stack_movement(state, player, action_number, stack)
        if _overdrive_copies_action(stack):
            _resolve_stack_movement(state, player, action_number, stack, overdrive_copy=True)
        _resolve_stack_engineering(state, player, action_number, stack)

    _resolve_combat(state, action_number, revealed_stacks)

    if state.phase == GamePhase.COMPLETE:
        return
    _change_phase(state, NEXT_PHASE[state.phase])


def _normalize_move_choice(orientation: str) -> str:
    return "forward" if orientation in {"up", "forward"} else orientation


def _translate_card_error(callback, *args):
    try:
        return callback(*args)
    except ValueError as exc:
        raise RulesError(str(exc)) from exc


def _is_desperate_face(selection: OrderCardSelection) -> bool:
    return is_desperate_face(selection)


def _selected_card_family(card: Card, selection: OrderCardSelection) -> CardFamily:
    return _translate_card_error(_effect_selected_card_family, card, selection)


def _card_requires_target(card: Card, selection: OrderCardSelection) -> bool:
    return _translate_card_error(_effect_card_requires_target, card, selection)


def _card_orientation_options(card: Card, selection: OrderCardSelection) -> tuple[str, ...]:
    return _translate_card_error(_effect_card_orientation_options, card, selection)


def _card_value(card: Card, selection: OrderCardSelection, seal_mode: SealMode) -> int:
    return _translate_card_error(_effect_card_value, card, selection, seal_mode)


def _card_aim_bonus(card: Card, selection: OrderCardSelection) -> int:
    return _translate_card_error(_effect_card_aim_bonus, card, selection)


def _card_damage_bonus(card: Card, selection: OrderCardSelection) -> int:
    return _translate_card_error(_effect_card_damage_bonus, card, selection)


def _card_defense_bonus(card: Card, selection: OrderCardSelection) -> int:
    return _translate_card_error(_effect_card_defense_bonus, card, selection)


def _card_always_hits(card: Card, selection: OrderCardSelection) -> bool:
    return _translate_card_error(_effect_card_always_hits, card, selection)


def _card_movement_disabled(card: Card, selection: OrderCardSelection) -> bool:
    return _translate_card_error(_effect_card_movement_disabled, card, selection)


def _card_warp_destination(card: Card, selection: OrderCardSelection) -> str | None:
    return _translate_card_error(_effect_card_warp_destination, card, selection)


def _card_max_range(card: Card, selection: OrderCardSelection) -> int | None:
    return _translate_card_error(_effect_card_max_range, card, selection)


def _card_fixed_defense_threshold(card: Card, selection: OrderCardSelection) -> int | None:
    return _translate_card_error(_effect_card_fixed_defense_threshold, card, selection)


def _card_attacks_all(card: Card, selection: OrderCardSelection) -> bool:
    return _translate_card_error(_effect_card_attacks_all, card, selection)


def _card_effect(card: Card, selection: OrderCardSelection, seal_mode: SealMode):
    return _translate_card_error(interpret_card, card, selection, seal_mode)


def _resolve_warp_destination(state: GameState, player: PlayerState, destination: str) -> tuple[int, int, int | None]:
    if destination == "home":
        player_index = tuple(state.players).index(player.id)
        q, r, _facing = corner_start(player_index)
        return q, r, None

    if destination == "bauble":
        active_numbered = [
            bauble
            for bauble in state.baubles
            if not bauble.is_fang and bauble.number == state.round_number
        ]
        numbered = [bauble for bauble in state.baubles if not bauble.is_fang]
        candidates = active_numbered or numbered
        if not candidates:
            return player.ship.q, player.ship.r, None
        bauble = min(
            candidates,
            key=lambda candidate: (
                hex_distance(player.ship.q, player.ship.r, candidate.q, candidate.r),
                candidate.number,
                candidate.id,
            ),
        )
        return bauble.q, bauble.r, None

    if destination == "leader":
        candidates = [candidate for candidate in state.players.values() if candidate.id != player.id and not candidate.eliminated]
        if not candidates:
            candidates = [candidate for candidate in state.players.values() if not candidate.eliminated]
        if not candidates:
            return player.ship.q, player.ship.r, None

        order = _player_order_from_starting_player(state)
        order_index = {player_id: index for index, player_id in enumerate(order)}
        leader = min(
            candidates,
            key=lambda candidate: (-candidate.victory_points, order_index.get(candidate.id, len(order))),
        )
        q, r = move_forward(leader.ship.q, leader.ship.r, u_turn(leader.ship.facing), 1)
        q, r = clamp_to_board(q, r)
        return q, r, leader.ship.facing

    raise RulesError(f"Unsupported warp destination: {destination}")


def _resolve_stack_movement(
    state: GameState,
    player: PlayerState,
    action_number: int,
    stack: ActionStack,
    overdrive_copy: bool = False,
) -> None:
    movement_steps: list[dict] = []
    passes = 2 if _overdrive_copies_cards(stack) and not overdrive_copy else 1
    for _ in range(passes):
        for selection in stack.cards:
            card = card_by_id(selection.card_id)
            effect = _card_effect(card, selection, stack.seal_mode)
            if overdrive_copy and effect.is_desperate_face and not _overdrive_desperation_enabled():
                continue
            if effect.family != CardFamily.MOVE or effect.move is None:
                continue

            move_effect = effect.move
            defense_bonus = 0 if player.captain_id == "riley_rounder" else move_effect.defense_bonus
            if defense_bonus:
                player.ship.defense_bonus_this_action += defense_bonus

            move_choice = _normalize_move_choice(selection.orientation)
            orientation_options = move_effect.orientation_options
            if move_choice not in orientation_options:
                raise RulesError(f"Move choice {move_choice} is not valid for card {card.id}.")

            distance = move_effect.distance
            if not move_effect.warp_destination and not move_effect.movement_disabled:
                if player.captain_id == "riley_rounder":
                    distance += 1
                if _active_starfall(state, "gusty_winds"):
                    distance += 1
            before = {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing}
            attempted_q = player.ship.q
            attempted_r = player.ship.r
            warp_destination = move_effect.warp_destination

            if warp_destination:
                attempted_q, attempted_r, attempted_facing = _resolve_warp_destination(state, player, warp_destination)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                if attempted_facing is not None:
                    player.ship.facing = attempted_facing
            elif move_effect.movement_disabled:
                pass
            elif move_effect.double_turn_right:
                player.ship.facing = turn_right(turn_right(player.ship.facing))
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            elif move_effect.double_turn_after_move:
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                if move_choice == "turn_left":
                    player.ship.facing = turn_left(turn_left(player.ship.facing))
                else:
                    player.ship.facing = turn_right(turn_right(player.ship.facing))
                player.ship.movement_this_action += distance
            elif move_effect.u_turn_move:
                player.ship.facing = u_turn(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            elif move_effect.side_slip_direction:
                slip_facing = (player.ship.facing + (_SLIP_RIGHT_OFFSET if move_choice == "slip_right" else _SLIP_LEFT_OFFSET)) % 6
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, slip_facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            elif move_choice == "forward":
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            elif move_choice == "turn_left":
                player.ship.facing = turn_left(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            elif move_choice == "turn_right":
                player.ship.facing = turn_right(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += distance
            else:
                raise RulesError(f"Unsupported move orientation: {move_choice}")

            player.ship.q, player.ship.r = clamp_to_board(player.ship.q, player.ship.r)

            if move_effect.active_cooling:
                player.discard.extend(player.overheat)
                player.overheat = []

            movement_steps.append(
                {
                    "card_id": card.id,
                    "face": selection.face,
                    "choice": move_choice,
                    "distance": 0 if move_effect.movement_disabled or warp_destination else distance,
                    "warp_destination": warp_destination,
                    "defense_bonus": defense_bonus,
                    "active_cooling": move_effect.active_cooling,
                    "before": before,
                    "attempted": {"q": attempted_q, "r": attempted_r, "facing": player.ship.facing},
                    "after": {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing},
                    "clamped": (attempted_q, attempted_r) != (player.ship.q, player.ship.r),
                }
            )

    if movement_steps:
        state.event_log.append(
            {
                "type": "movement_resolved",
                "round": state.round_number,
                "player_id": player.id,
                "action_number": action_number,
                "overdrive_copy": overdrive_copy,
                "steps": movement_steps,
                "movement_this_action": player.ship.movement_this_action,
            }
        )


def _resolve_stack_engineering(
    state: GameState,
    player: PlayerState,
    action_number: int,
    stack: ActionStack,
) -> None:
    repairs: list[dict] = []
    reconfigures: list[dict] = []
    for selection in stack.cards:
        card = card_by_id(selection.card_id)
        effect = _card_effect(card, selection, stack.seal_mode)
        if effect.repair_components:
            before = sorted(player.ship.destroyed_components)
            restored = _repair_components(player, selection.repair_component_ids, effect.repair_components)
            if restored:
                repairs.append(
                    {
                        "card_id": card.id,
                        "restored_component_ids": restored,
                        "before_destroyed_components": before,
                        "after_destroyed_components": sorted(player.ship.destroyed_components),
                    }
                )
        if effect.reconfigure_components:
            before = sorted(player.ship.destroyed_components)
            moved = _reconfigure_components(
                player,
                selection.reconfigure_from_component_ids,
                selection.reconfigure_to_component_ids,
                effect.reconfigure_components,
            )
            if moved:
                reconfigures.append(
                    {
                        "card_id": card.id,
                        "from_component_ids": moved["from"],
                        "to_component_ids": moved["to"],
                        "before_destroyed_components": before,
                        "after_destroyed_components": sorted(player.ship.destroyed_components),
                    }
                )
    if repairs or reconfigures:
        state.event_log.append(
            {
                "type": "engineering_resolved",
                "round": state.round_number,
                "player_id": player.id,
                "action_number": action_number,
                "repairs": repairs,
                "reconfigures": reconfigures,
            }
        )


def _repair_components(player: PlayerState, component_ids: tuple[str, ...], count: int) -> list[str]:
    if not component_ids:
        return []
    _ensure_unique_component_ids(component_ids)
    if len(component_ids) > count:
        raise RulesError(f"Hull Repair can restore at most {count} component(s).")
    current = set(player.ship.destroyed_components)
    for component_id in component_ids:
        if component_id not in current:
            continue
        current.remove(component_id)
    _ensure_intact_components_connected(current)
    for component_id in component_ids:
        player.ship.destroyed_components.discard(component_id)
        player.ship.component_hit_counts.pop(component_id, None)
    player.ship.damage_taken = max(0, player.ship.damage_taken - len(component_ids))
    player.ship.destroyed = is_ship_destroyed(player.ship.destroyed_components)
    return list(component_ids)


def _reconfigure_components(
    player: PlayerState,
    from_component_ids: tuple[str, ...],
    to_component_ids: tuple[str, ...],
    count: int,
) -> dict[str, list[str]] | None:
    if not from_component_ids and not to_component_ids:
        return None
    if len(from_component_ids) != count or len(to_component_ids) != count:
        raise RulesError(f"Reconfigure must move exactly {count} damage marker(s).")
    _ensure_unique_component_ids(from_component_ids)
    _ensure_unique_component_ids(to_component_ids)
    if set(from_component_ids).intersection(to_component_ids):
        raise RulesError("Reconfigure cannot move damage from and to the same component.")
    current = set(player.ship.destroyed_components)
    for component_id in from_component_ids:
        if component_id not in current:
            raise RulesError(f"Reconfigure source is not damaged: {component_id}")
    interim = current - set(from_component_ids)
    for component_id in to_component_ids:
        if component_id in interim:
            raise RulesError(f"Reconfigure destination is already damaged: {component_id}")
        if not _component_adjacent_to_intact(component_id, interim):
            raise RulesError(f"Reconfigure destination is not adjacent to an undamaged component: {component_id}")
    final_destroyed = set(interim).union(to_component_ids)
    _ensure_intact_components_connected(final_destroyed)
    player.ship.destroyed_components = final_destroyed
    for component_id in from_component_ids:
        player.ship.component_hit_counts.pop(component_id, None)
    for component_id in to_component_ids:
        player.ship.component_hit_counts[component_id] = max(1, player.ship.component_hit_counts.get(component_id, 0))
    player.ship.destroyed = is_ship_destroyed(player.ship.destroyed_components)
    return {"from": list(from_component_ids), "to": list(to_component_ids)}


def _ensure_unique_component_ids(component_ids: tuple[str, ...]) -> None:
    if len(set(component_ids)) != len(component_ids):
        raise RulesError("Component selections must not contain duplicates.")
    unknown = [component_id for component_id in component_ids if component_id not in BASE_SHIP_COMPONENT_BY_ID]
    if unknown:
        raise RulesError(f"Unknown ship component: {unknown[0]}")


def _component_adjacent_to_intact(component_id: str, destroyed_components: set[str]) -> bool:
    component = BASE_SHIP_COMPONENT_BY_ID[component_id]
    for other in BASE_SHIP_COMPONENTS:
        if other.id in destroyed_components:
            continue
        if hex_distance(component.q, component.r, other.q, other.r) == 1:
            return True
    return False


def _ensure_intact_components_connected(destroyed_components: set[str]) -> None:
    if detached_component_ids(destroyed_components):
        raise RulesError("Undamaged ship components must remain connected to the Command Bridge.")


def _move_resolved_stack_cards(state: GameState, player: PlayerState, action_number: int, stack: ActionStack) -> None:
    discarded: list[str] = []
    overheated: list[str] = []
    returned_to_desperation_deck: list[str] = []
    for selection in stack.cards:
        card = card_by_id(selection.card_id)
        if _is_desperate_face(selection) or card.no_basic_face:
            return_desperation_card(state.desperation_deck, card)
            returned_to_desperation_deck.append(card.id)
        elif stack.seal_mode == SealMode.OVERDRIVE:
            if _overheat_pile_enabled():
                player.overheat.append(card)
                overheated.append(card.id)
            else:
                player.discard.append(card)
                discarded.append(card.id)
        else:
            player.discard.append(card)
            discarded.append(card.id)

    if stack.seal_mode == SealMode.OVERDRIVE and not _star_breach_overdrive_exempt(state, player, stack):
        player.overdrive_seals_pending += 1

    if discarded or overheated or returned_to_desperation_deck:
        state.event_log.append(
            {
                "type": "action_cards_moved",
                "round": state.round_number,
                "player_id": player.id,
                "action_number": action_number,
                "moved_to_discard": discarded,
                "moved_to_overheat": overheated,
                "returned_to_desperation_deck": returned_to_desperation_deck,
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

        if state.star_breach is not None:
            if _resolve_star_breach_attacker(state, action_number, stack, attacker, attack_cards):
                resolved_any = True
            if state.phase == GamePhase.COMPLETE:
                return
            continue

        attack_effects = [_card_effect(card, sel, stack.seal_mode) for card, sel in attack_cards]
        ramming_effects = [effect.attack for effect in attack_effects if effect.attack is not None and effect.attack.ramming_damage]
        if ramming_effects:
            _resolve_ramming_attack(state, action_number, stack, attacker, attack_cards)
            resolved_any = True
            continue
        # Crazy Ivan u_turn_attack: each copied card flips facing once.
        u_turn_attack_count = sum(1 for e in attack_effects if e.attack is not None and e.attack.u_turn_attack)
        if u_turn_attack_count % 2:
            attacker.ship.facing = u_turn(attacker.ship.facing)

        target_ids = _target_player_ids_for_attack(state, attacker, stack, attack_cards)
        if not target_ids:
            continue
        for target_id in target_ids:
            _resolve_attack_volley(state, action_number, stack, attacker, target_id, attack_cards, shielded_target_ids)
            resolved_any = True
        if _overdrive_copies_action(stack):
            overdrive_attack_cards = _attack_cards_for_stack(
                stack,
                include_desperate=_overdrive_desperation_enabled(),
            )
            if not overdrive_attack_cards:
                continue
            overdrive_target_ids = _target_player_ids_for_attack(state, attacker, stack, overdrive_attack_cards)
            for target_id in overdrive_target_ids:
                _resolve_attack_volley(
                    state,
                    action_number,
                    stack,
                    attacker,
                    target_id,
                    overdrive_attack_cards,
                    shielded_target_ids,
                    overdrive_copy=True,
                )
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
        card = card_by_id(selection.card_id)
        effect = _card_effect(card, selection, stack.seal_mode)
        if effect.family == CardFamily.ATTACK and effect.requires_target:
            return selection.target_player_id
    return None


def _target_player_ids_for_attack(
    state: GameState,
    attacker: PlayerState,
    stack: ActionStack,
    attack_cards: list[tuple[Card, OrderCardSelection]],
) -> list[str]:
    attack_effects = [_card_effect(card, selection, stack.seal_mode) for card, selection in attack_cards]
    if any(effect.attack is not None and effect.attack.attacks_all for effect in attack_effects):
        return [
            player.id
            for player in state.players.values()
            if player.id != attacker.id and not player.eliminated and not player.ship.destroyed
        ]
    if any(effect.attack is not None and effect.attack.attacks_cone_120 for effect in attack_effects):
        return [
            player.id
            for player in state.players.values()
            if (
                player.id != attacker.id
                and not player.eliminated
                and not player.ship.destroyed
                and _ship_in_facing_cone_120(attacker.ship, player.ship)
            )
        ]
    target_id = _target_player_id_for_attack(stack)
    if target_id:
        return [target_id]
    forward_target_id = _first_enemy_forward_target_id(state, attacker)
    return [forward_target_id] if forward_target_id else []


def _first_enemy_forward_target_id(state: GameState, attacker: PlayerState) -> str | None:
    distance = 1
    while True:
        q, r = move_forward(attacker.ship.q, attacker.ship.r, attacker.ship.facing, distance)
        if not is_within_board(q, r):
            return None
        for player_id in _player_order_from_starting_player(state):
            candidate = state.players[player_id]
            if candidate.id == attacker.id or candidate.eliminated or candidate.ship.destroyed:
                continue
            if (candidate.ship.q, candidate.ship.r) == (q, r):
                return candidate.id
        distance += 1


def _resolve_attack_volley(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    target_id: str,
    attack_cards: list[tuple[Card, OrderCardSelection]],
    shielded_target_ids: set[str],
    overdrive_copy: bool = False,
) -> None:
    target = _player(state, target_id)
    if target.eliminated or target.ship.destroyed:
        state.event_log.append(
            {
                "type": "volley_skipped",
                "round": state.round_number,
                "action_number": action_number,
                "attacker_id": attacker.id,
                "target_id": target_id,
                "reason": "target_not_active",
            }
        )
        return

    attack_effects = [
        effect.attack
        for card, selection in attack_cards
        if (effect := _card_effect(card, selection, stack.seal_mode)).attack is not None
    ]
    base_damage = max((effect.base_damage for effect in attack_effects), default=1)
    if base_damage <= 1:
        base_damage = 1
    damage = base_damage + sum(effect.damage_bonus for effect in attack_effects)
    aim_bonus = sum(effect.aim_bonus for effect in attack_effects)
    if attacker.captain_id == "malcolm_manderly":
        aim_bonus += 2
    always_hits = any(effect.always_hits for effect in attack_effects)
    lead_the_target = any(effect.lead_the_target for effect in attack_effects)
    u_turn_atk = any(effect.u_turn_attack for effect in attack_effects)
    distance = hex_distance(attacker.ship.q, attacker.ship.r, target.ship.q, target.ship.r)
    fixed_defense_threshold = next(
        (effect.fixed_defense_threshold for effect in attack_effects if effect.fixed_defense_threshold is not None),
        None,
    )
    max_range = next(
        (effect.max_range for effect in attack_effects if effect.max_range is not None),
        None,
    )
    target_movement = 0 if lead_the_target else target.ship.movement_this_action
    defense_threshold = (
        fixed_defense_threshold
        if fixed_defense_threshold is not None
        else distance + target_movement + target.ship.defense_bonus_this_action
    )
    roll = _roll_attack(state)
    roll_total = roll + aim_bonus
    in_range = max_range is None or distance <= max_range
    natural_auto_hit = roll >= (18 if _active_starfall(state, "clear_skies") else 12)
    hit = in_range and (always_hits or natural_auto_hit or roll_total >= defense_threshold)
    event = {
        "type": "volley_resolved",
        "round": state.round_number,
        "action_number": action_number,
        "attacker_id": attacker.id,
        "target_id": target_id,
        "attacker_position": {"q": attacker.ship.q, "r": attacker.ship.r, "facing": attacker.ship.facing},
        "target_position": {"q": target.ship.q, "r": target.ship.r, "facing": target.ship.facing},
        "overdrive_copy": overdrive_copy,
        "card_ids": [card.id for card, selection in attack_cards],
        "damage": damage,
        "aim_bonus": aim_bonus,
        "distance": distance,
        "target_movement": target_movement,
        "target_defense_bonus": target.ship.defense_bonus_this_action,
        "defense_threshold": defense_threshold,
        "fixed_defense_threshold": fixed_defense_threshold,
        "max_range": max_range,
        "in_range": in_range,
        "roll": roll,
        "roll_total": roll_total,
        "natural_auto_hit": natural_auto_hit,
        "always_hits": always_hits,
        "lead_the_target": lead_the_target,
        "u_turn_attack": u_turn_atk,
        "hit": hit,
        "shielded": False,
        "damage_applied": 0,
        "vp_awarded": 0,
    }

    if hit and target.ship.shields > 0:
        target.ship.shields -= 1
        shielded_target_ids.add(target_id)
        bonus_vp = _starfall_hit_bonus_vp(state, attacker.id, action_number)
        attacker.victory_points += 1 + bonus_vp
        event["shielded"] = True
        event["vp_awarded"] = 1 + bonus_vp
        event["starfall_bonus_vp"] = bonus_vp
        _apply_starfall_hit_desperation(state, attacker)
    elif hit:
        damage_result = _apply_unshielded_damage(state, target, damage, action_number=action_number)
        destroyed_by_volley = not damage_result["was_destroyed"] and target.ship.destroyed
        vp_awarded = 3 if destroyed_by_volley else 1 if damage_result["damage_applied"] > 0 else 0
        vp_awarded += damage_result["knockoff_vp_awarded"]
        bonus_vp = _starfall_hit_bonus_vp(state, attacker.id, action_number) if damage_result["damage_applied"] > 0 else 0
        vp_awarded += bonus_vp
        attacker.victory_points += vp_awarded
        event.update(damage_result)
        event["vp_awarded"] = vp_awarded
        event["starfall_bonus_vp"] = bonus_vp
        _apply_starfall_hit_desperation(state, attacker)

    state.event_log.append(event)


def _attack_cards_for_stack(stack: ActionStack, *, include_desperate: bool = True) -> list[tuple[Card, OrderCardSelection]]:
    attack_cards: list[tuple[Card, OrderCardSelection]] = []
    passes = 2 if _overdrive_copies_cards(stack) else 1
    for _ in range(passes):
        for selection in stack.cards:
            card = card_by_id(selection.card_id)
            effect = _card_effect(card, selection, stack.seal_mode)
            if not include_desperate and effect.is_desperate_face:
                continue
            if effect.family == CardFamily.ATTACK and effect.attack is not None:
                attack_cards.append((card, selection))
    return attack_cards


def _ship_in_facing_cone_120(origin: ShipState, target: ShipState) -> bool:
    dq = target.q - origin.q
    dr = target.r - origin.r
    if dq == 0 and dr == 0:
        return True
    left_dq, left_dr = move_forward(0, 0, turn_left(origin.facing), 1)
    right_dq, right_dr = move_forward(0, 0, turn_right(origin.facing), 1)
    max_distance = hex_distance(origin.q, origin.r, target.q, target.r)
    for left_steps in range(max_distance + 1):
        for right_steps in range(max_distance + 1):
            if left_steps == 0 and right_steps == 0:
                continue
            if (
                left_steps * left_dq + right_steps * right_dq == dq
                and left_steps * left_dr + right_steps * right_dr == dr
            ):
                return True
    return False


def _resolve_ramming_attack(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    attack_cards: list[tuple[Card, OrderCardSelection]],
) -> None:
    attack_effects = [
        effect.attack
        for card, selection in attack_cards
        if (effect := _card_effect(card, selection, stack.seal_mode)).attack is not None
    ]
    ram = next(effect for effect in attack_effects if effect.ramming_damage)
    before = {"q": attacker.ship.q, "r": attacker.ship.r, "facing": attacker.ship.facing}
    collision_target: PlayerState | None = None
    path: list[dict] = []
    for step in range(1, ram.ramming_distance + 1):
        q, r = move_forward(before["q"], before["r"], attacker.ship.facing, step)
        q, r = clamp_to_board(q, r)
        path.append({"q": q, "r": r})
        for player_id in _player_order_from_starting_player(state):
            candidate = state.players[player_id]
            if candidate.id == attacker.id or candidate.eliminated or candidate.ship.destroyed:
                continue
            if (candidate.ship.q, candidate.ship.r) == (q, r):
                collision_target = candidate
                break
        if collision_target is not None:
            break
    if path:
        attacker.ship.q = path[-1]["q"]
        attacker.ship.r = path[-1]["r"]
        attacker.ship.movement_this_action += len(path)

    event = {
        "type": "ramming_resolved",
        "round": state.round_number,
        "action_number": action_number,
        "attacker_id": attacker.id,
        "target_id": collision_target.id if collision_target else None,
        "card_ids": [card.id for card, selection in attack_cards],
        "damage": ram.ramming_damage,
        "path": path,
        "before": before,
        "after": {"q": attacker.ship.q, "r": attacker.ship.r, "facing": attacker.ship.facing},
        "hit": collision_target is not None,
        "attacker_damage": None,
        "target_damage": None,
        "vp_awarded": 0,
    }
    if collision_target is not None:
        target_damage = _apply_unshielded_damage(state, collision_target, ram.ramming_damage, action_number=action_number)
        attacker_damage = _apply_unshielded_damage(state, attacker, ram.ramming_damage, action_number=action_number)
        destroyed_by_ram = not target_damage["was_destroyed"] and collision_target.ship.destroyed
        vp_awarded = 3 if destroyed_by_ram else 1 if target_damage["damage_applied"] > 0 else 0
        vp_awarded += target_damage["knockoff_vp_awarded"]
        attacker.victory_points += vp_awarded
        event["target_damage"] = target_damage
        event["attacker_damage"] = attacker_damage
        event["vp_awarded"] = vp_awarded
    state.event_log.append(event)


def _apply_unshielded_damage(
    state: GameState,
    target: PlayerState,
    damage: int,
    *,
    action_number: int | None = None,
    apply_desperation: bool = True,
    fixed_lane_roll: int | None = None,
) -> dict:
    shots: list[dict] = []
    was_destroyed = target.ship.destroyed
    desperation_consequence_applied = False
    knockoff_vp_awarded = 0

    for shot_number in range(1, damage + 1):
        lane_roll = fixed_lane_roll if fixed_lane_roll is not None else _roll_d12(state)
        component = first_intact_component_for_lane(lane_roll, target.ship.destroyed_components)
        shot = {
            "shot_number": shot_number,
            "roll": lane_roll,
            "lane": lane_roll,
            "component_id": None,
            "component_type": None,
            "destroyed": False,
            "detached_component_ids": [],
        }
        if component is not None:
            if (
                target.captain_id == "knute_knuckles"
                and component.component_type in {"bridge", "life_support"}
                and target.ship.component_hit_counts.get(component.id, 0) == 0
            ):
                target.ship.component_hit_counts[component.id] = 1
                shot.update(
                    {
                        "component_id": component.id,
                        "component_type": component.component_type,
                        "reinforced": True,
                        "destroyed": False,
                    }
                )
                shots.append(shot)
                continue
            target.ship.destroyed_components.add(component.id)
            target.ship.component_hit_counts[component.id] = target.ship.component_hit_counts.get(component.id, 0) + 1
            target.ship.damage_taken += 1
            detached_ids = sorted(detached_component_ids(target.ship.destroyed_components))
            if detached_ids:
                target.ship.destroyed_components.update(detached_ids)
                target.ship.damage_taken += len(detached_ids)
                knockoff_vp_awarded += 1
            shot.update(
                {
                    "component_id": component.id,
                    "component_type": component.component_type,
                    "destroyed": True,
                    "detached_component_ids": detached_ids,
                }
            )
            target.ship.destroyed = is_ship_destroyed(target.ship.destroyed_components)
            if target.ship.destroyed and not was_destroyed and target.ship.knocked_out_round is None:
                target.ship.knocked_out_round = state.round_number
                target.ship.knocked_out_action_number = action_number
                target.ship.knocked_out_phase = state.phase
            # The first component destroyed by this volley triggers a desperation consequence.
            if apply_desperation and not desperation_consequence_applied:
                _apply_desperation_consequence(state, target)
                desperation_consequence_applied = True
            _apply_component_destroyed_captain_effects(state, target, component.component_type)
        shots.append(shot)

    return {
        "damage_applied": sum(1 for shot in shots if shot["destroyed"]),
        "knockoff_vp_awarded": knockoff_vp_awarded,
        "damage_rolls": [shot["roll"] for shot in shots],
        "damage_shots": shots,
        "target_damage_taken": target.ship.damage_taken,
        "target_destroyed_components": sorted(target.ship.destroyed_components),
        "target_destroyed": target.ship.destroyed,
        "was_destroyed": was_destroyed,
    }


def _apply_desperation_consequence(state: GameState, player: PlayerState) -> None:
    rng = _make_rng(state)

    reshuffled_discard: list[str] = []
    if not player.deck and player.discard:
        reshuffled = list(player.discard)
        _shuffle_cards(state, player.discard)
        player.deck = list(player.discard)
        player.discard = []
        reshuffled_discard = [card.id for card in reshuffled]

    moved_to_overheat = player.deck.pop(0) if player.deck else None
    if moved_to_overheat is not None and _overheat_pile_enabled():
        player.overheat.append(moved_to_overheat)
    elif moved_to_overheat is not None:
        player.discard.append(moved_to_overheat)

    drawn = draw_desperation_card(state.desperation_deck, rng)
    player.deck.insert(0, drawn)
    state.event_log.append(
        {
            "type": "desperation_consequence",
            "player_id": player.id,
            "choice": "automatic",
            "moved_to_overheat_card_id": moved_to_overheat.id if moved_to_overheat is not None else None,
            "desperation_card_id": drawn.id,
            "reshuffled_discard": reshuffled_discard,
            "deck_count": len(player.deck),
            "discard_count": len(player.discard),
            "overheat_count": len(player.overheat),
        }
    )


def _make_rng(state: GameState) -> Random:
    """Return a seeded RNG at the current rng_step position (without consuming a step)."""
    if state.rng_seed is None:
        state.rng_seed = 0
    rng = Random(state.rng_seed)
    for _ in range(state.rng_step):
        rng.randint(1, 12)
    return rng


def _shuffle_cards(state: GameState, cards: list[Card]) -> None:
    rng = _make_rng(state)
    rng.shuffle(cards)
    state.rng_step += len(cards)


def _roll_2d6(state: GameState) -> int:
    rng = _make_rng(state)
    first = rng.randint(1, 6)
    second = rng.randint(1, 6)
    state.rng_step += 2
    return first + second


def _roll_attack(state: GameState) -> int:
    if not _active_starfall(state, "clear_skies"):
        return _roll_2d6(state)
    rng = _make_rng(state)
    values = [rng.randint(1, 6) for _ in range(3)]
    state.rng_step += 3
    return sum(values)


def _roll_d12(state: GameState) -> int:
    rng = _make_rng(state)
    value = rng.randint(1, 12)
    state.rng_step += 1
    return value


def _resolve_award_baubles(state: GameState) -> None:
    if state.star_breach is not None:
        _resolve_boss_phase(state, "3.5")
        if state.phase == GamePhase.COMPLETE:
            return
        _resolve_boss_phase(state, "starbreach")
        if state.phase == GamePhase.COMPLETE:
            return
    awarded_any = False
    rng = _make_rng(state)
    for bauble in state.baubles:
        if not _bauble_open_this_round(state, bauble):
            continue
        awards: list[dict] = []
        for player in state.players.values():
            if player.eliminated or player.ship.destroyed:
                continue
            distance = hex_distance(player.ship.q, player.ship.r, bauble.q, bauble.r)
            if not ship_inside_bauble(player.ship, bauble):
                continue

            vp_awarded = fang_vp_for_round(state.round_number) if bauble.is_fang else bauble.victory_points
            player.victory_points += vp_awarded
            if player.id not in bauble.claimed_by:
                bauble.claimed_by.append(player.id)

            drawn_card_id: str | None = None
            if not bauble.is_fang:
                drawn = draw_desperation_card(state.desperation_deck, rng)
                player.deck.insert(0, drawn)
                drawn_card_id = drawn.id
                if player.captain_id == "beto_briego":
                    extra = draw_desperation_card(state.desperation_deck, rng)
                    player.deck.insert(0, extra)
                    vp_awarded += 1
                    player.victory_points += 1

            award = {
                "player_id": player.id,
                "distance": distance,
                "vp_awarded": vp_awarded,
                "desperation_card_drawn": not bauble.is_fang,
                "desperation_card_id": drawn_card_id,
                "captain_bonus": player.captain_id == "beto_briego" and not bauble.is_fang,
            }
            if bauble.is_fang:
                award.update(_apply_fang_damage(state, player))
            elif state.star_breach is not None and "treasure_hunter" in player.roles:
                for crew_member in state.players.values():
                    if not crew_member.eliminated:
                        crew_member.bonus_draws_pending += 1
                award["treasure_hunter_bonus_draw"] = True
            awards.append(award)

        if awards:
            awarded_any = True
            state.event_log.append(
                {
                    "type": "bauble_awarded",
                    "round": state.round_number,
                    "bauble": bauble_event_payload(bauble),
                    "awards": awards,
                }
            )

    if not awarded_any:
        state.event_log.append(
            {
                "type": "baubles_awarded",
                "round": state.round_number,
                "message": "No ships were in range of an active bauble.",
            }
        )
    if state.star_breach is not None:
        _check_star_breach_defeat(state)
        if state.phase == GamePhase.COMPLETE:
            return
    _change_phase(state, GamePhase.CLEANUP)


def _apply_fang_damage(state: GameState, player: PlayerState) -> dict:
    if player.ship.shields > 0:
        player.ship.shields -= 1
        return {
            "fang_damage": 1,
            "shielded": True,
            "damage_applied": 0,
            "damage_shots": [],
            "target_destroyed": player.ship.destroyed,
        }

    damage_result = _apply_unshielded_damage(state, player, 1)
    return {
        "fang_damage": 1,
        "shielded": False,
        "damage_applied": damage_result["damage_applied"],
        "damage_shots": damage_result["damage_shots"],
        "target_destroyed": damage_result["target_destroyed"],
    }


def _resolve_cleanup(state: GameState) -> None:
    _resolve_cleanup_start_star_command(state)
    result = _round_completion_result(state)
    if result is not None:
        state.result = result
        _change_phase(state, GamePhase.COMPLETE)
        return

    for player in state.players.values():
        if player.prepared_orders is not None:
            _move_resolved_order_cards(state, player)
        player.prepared_orders = None
        player.ship.movement_this_action = 0
        player.ship.defense_bonus_this_action = 0

    state.round_number += 1
    state.starting_player_id = _next_starting_player_id(state)
    for player in state.players.values():
        if player.eliminated:
            continue
        draw_result = draw_hand(player, shuffle_cards=lambda cards: _shuffle_cards(state, cards))
        if draw_result.reshuffled_discard or draw_result.moved_overheat_to_discard:
            state.event_log.append(
                {
                    "type": "deck_refreshed",
                    "round": state.round_number,
                    "player_id": player.id,
                    "reshuffled_discard": [card.id for card in draw_result.reshuffled_discard],
                    "moved_overheat_to_discard": [
                        card.id for card in draw_result.moved_overheat_to_discard
                    ],
                    "deck_count": len(player.deck),
                    "discard_count": len(player.discard),
                    "overheat_count": len(player.overheat),
                }
            )
        if draw_result.drawn:
            state.event_log.append(
                {
                    "type": "hand_drawn",
                    "round": state.round_number,
                    "player_id": player.id,
                    "card_ids": [card.id for card in draw_result.drawn],
                    "deck_count": len(player.deck),
                    "hand_count": len(player.hand),
                    "discard_count": len(player.discard),
                }
            )
    state.event_log.append(
        {
            "type": "round_advanced",
            "round": state.round_number,
            "starting_player_id": state.starting_player_id,
        }
    )
    _activate_star_breach_tiers(state)
    _reveal_starfall_for_round(state)
    _change_phase(state, GamePhase.GIVE_ORDERS)


def _move_resolved_order_cards(state: GameState, player: PlayerState) -> None:
    assert player.prepared_orders is not None
    for stack in player.prepared_orders.stacks:
        _move_resolved_stack_cards(state, player, stack.action_number, stack)


def _round_completion_result(state: GameState) -> GameResult | None:
    if state.star_breach is not None:
        return _star_breach_result(state, final_round_complete=state.round_number >= 6)
    living = [player.id for player in state.players.values() if not player.ship.destroyed and not player.eliminated]
    if len(living) == 1:
        return GameResult(winner_ids=(living[0],), reason="last_ship_standing")
    if len(living) == 0:
        return GameResult(winner_ids=(), reason="all_ships_destroyed", is_tie=True)
    if state.round_number >= 6:
        contenders = [state.players[player_id] for player_id in living]
        top_vp = max(player.victory_points for player in contenders)
        winners = tuple(player.id for player in contenders if player.victory_points == top_vp)
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


def _validate_active_deck_set(state: GameState) -> None:
    active_id = active_catalog().id
    state_id = state.deck_set_id or active_id
    if state_id != active_id:
        raise RulesError(f"Game uses deck set {state_id!r}, but active deck set is {active_id!r}.")


def _overheat_pile_enabled() -> bool:
    return active_catalog().rules_config.overheat_pile


def _mixed_card_type_stacks_enabled() -> bool:
    return active_catalog().rules_config.allow_mixed_card_type_stacks


def _overdrive_copies_action(stack: ActionStack) -> bool:
    return (
        stack.seal_mode == SealMode.OVERDRIVE
        and str(active_catalog().rules_config.overdrive_style) == OverdriveStyle.COPY_ACTION.value
    )


def _overdrive_copies_cards(stack: ActionStack) -> bool:
    return (
        stack.seal_mode == SealMode.OVERDRIVE
        and str(active_catalog().rules_config.overdrive_style) == OverdriveStyle.COMBINE_CARDS.value
    )


def _overdrive_desperation_enabled() -> bool:
    return active_catalog().rules_config.allow_overdrive_desperation


def _starting_ship(index: int) -> ShipState:
    q, r, facing = corner_start(index)
    return ShipState(q=q, r=r, facing=facing)


# StarBreach spawns keep the crew away from the boss along the top of the
# board: south, west, east, then south-west corners, facing the center.
_STAR_BREACH_START_DIRECTIONS = (5, 3, 0, 4)


def _starting_ship_star_breach(index: int) -> ShipState:
    from starshot.rules.hex import BOARD_RADIUS, DIRECTIONS, START_INSET_FROM_CORNER

    direction = _STAR_BREACH_START_DIRECTIONS[index]
    distance = BOARD_RADIUS - START_INSET_FROM_CORNER
    dq, dr = DIRECTIONS[direction]
    return ShipState(q=dq * distance, r=dr * distance, facing=(direction + 3) % 6)


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

    available = available_order_cards(player)
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
            raise RulesError(f"Card is not available in hand: {selection.card_id}")
        if selection.face not in {"front", "desperate"}:
            raise RulesError(f"Unsupported card face: {selection.face}")
        if selection.face == "desperate" and card.desperate_face is None:
            raise RulesError(f"Card {card.id} does not have an implemented desperate face.")
        if stack.seal_mode == SealMode.OVERDRIVE and not _overdrive_desperation_enabled():
            if selection.face == "desperate" or card.no_basic_face:
                raise RulesError("Desperation cards cannot be overdriven unless the rules config allows it.")
        used_card_ids.add(selection.card_id)
        effective_family = _selected_card_family(card, selection)
        families.add(effective_family)
        effect = _card_effect(card, selection, stack.seal_mode)
        _validate_engineering_selection(player, selection, effect)
        if effective_family == CardFamily.MOVE:
            move_choice = _normalize_move_choice(selection.orientation)
            if move_choice not in _card_orientation_options(card, selection):
                raise RulesError(f"Move choice {move_choice} is not valid for card {card.id}.")
        if effective_family == CardFamily.ATTACK and selection.target_player_id:
            if state.star_breach is not None:
                _validate_star_breach_target(state, player, selection.target_player_id)
            else:
                if selection.target_player_id == player.id:
                    raise RulesError("Attack cards must target an enemy player.")
                if selection.target_player_id not in state.players:
                    raise RulesError(f"Unknown attack target: {selection.target_player_id}")
            target_player_ids.add(selection.target_player_id)

    if len(families) > 1 and not _mixed_card_type_stacks_enabled():
        raise RulesError("A stack cannot mix move and attack cards.")
    if len(target_player_ids) > 1:
        raise RulesError("All targeted attacks in a stack must target the same player.")


def _validate_engineering_selection(player: PlayerState, selection: OrderCardSelection, effect) -> None:
    if effect.repair_components:
        ids = selection.repair_component_ids
        if len(ids) != effect.repair_components:
            raise RulesError(f"Hull Repair must select {effect.repair_components} damaged component(s).")
        _ensure_unique_component_ids(ids)
        destroyed = set(player.ship.destroyed_components)
        for component_id in ids:
            if component_id not in destroyed:
                raise RulesError(f"Hull Repair component is not damaged: {component_id}")
        final_destroyed = destroyed - set(ids)
        _ensure_intact_components_connected(final_destroyed)
    if effect.reconfigure_components:
        _reconfigure_components_preview(
            player,
            selection.reconfigure_from_component_ids,
            selection.reconfigure_to_component_ids,
            effect.reconfigure_components,
        )


def _reconfigure_components_preview(
    player: PlayerState,
    from_component_ids: tuple[str, ...],
    to_component_ids: tuple[str, ...],
    count: int,
) -> None:
    if len(from_component_ids) != count or len(to_component_ids) != count:
        raise RulesError(f"Reconfigure must move exactly {count} damage marker(s).")
    _ensure_unique_component_ids(from_component_ids)
    _ensure_unique_component_ids(to_component_ids)
    if set(from_component_ids).intersection(to_component_ids):
        raise RulesError("Reconfigure cannot move damage from and to the same component.")
    current = set(player.ship.destroyed_components)
    for component_id in from_component_ids:
        if component_id not in current:
            raise RulesError(f"Reconfigure source is not damaged: {component_id}")
    interim = current - set(from_component_ids)
    for component_id in to_component_ids:
        if component_id in interim:
            raise RulesError(f"Reconfigure destination is already damaged: {component_id}")
        if not _component_adjacent_to_intact(component_id, interim):
            raise RulesError(f"Reconfigure destination is not adjacent to an undamaged component: {component_id}")
    _ensure_intact_components_connected(set(interim).union(to_component_ids))


def _star_command_enabled(state: GameState) -> bool:
    return STAR_COMMAND_ID in state.active_expansions


def _initialize_star_command(state: GameState) -> None:
    captain_ids = [captain.id for captain in CAPTAINS]
    starfall_ids = [starfall.id for starfall in STARFALLS]
    _shuffle_values(state, captain_ids)
    _shuffle_values(state, starfall_ids)
    state.starfall_deck = starfall_ids
    for index, player in enumerate(state.players.values()):
        start = (index * 3) % len(captain_ids)
        options = [captain_ids[(start + offset) % len(captain_ids)] for offset in range(3)]
        player.captain_options = tuple(options)
    state.event_log.append(
        {
            "type": "expansion_enabled",
            "round": state.round_number,
            "expansion_id": STAR_COMMAND_ID,
        }
    )
    _reveal_starfall_for_round(state)


def _shuffle_values(state: GameState, values: list[str]) -> None:
    rng = _make_rng(state)
    rng.shuffle(values)
    state.rng_step += len(values)


def _captain_choice_pending(state: GameState, player_id: str) -> bool:
    if not _star_command_enabled(state):
        return False
    player = _player(state, player_id)
    return bool(player.captain_options) and not player.captain_id


def _any_captain_choice_pending(state: GameState) -> bool:
    return _star_command_enabled(state) and any(
        bool(player.captain_options) and not player.captain_id
        for player in state.players.values()
        if not player.eliminated
    )


def _apply_captain_setup(player: PlayerState) -> None:
    if player.captain_id == "anya_andrews":
        player.ship.shields = 0


def _reveal_starfall_for_round(state: GameState) -> None:
    if not _star_command_enabled(state) or state.active_starfall_round == state.round_number:
        return
    if not state.starfall_deck:
        state.starfall_deck = [starfall.id for starfall in STARFALLS]
        _shuffle_values(state, state.starfall_deck)
    starfall_id = state.starfall_deck.pop(0)
    state.active_starfall_id = starfall_id
    state.active_starfall_round = state.round_number
    state.starfall_bauble_number = None
    event = {
        "type": "starfall_revealed",
        "round": state.round_number,
        "starfall_id": starfall_id,
        "starfall": STARFALLS_BY_ID[starfall_id].name,
        "text": STARFALLS_BY_ID[starfall_id].text,
        "animation": STARFALLS_BY_ID[starfall_id].animation,
    }
    if starfall_id == "solar_storm":
        lane_roll = _roll_d12(state)
        event["damage_roll"] = lane_roll
        event["targets"] = _deal_environmental_damage(state, 1, penetrates_shields=True, fixed_lane_roll=lane_roll)
    elif starfall_id == "gravity_burst":
        event["movement"] = _pull_all_ships_toward_fang(state, 2)
    elif starfall_id == "stars_align":
        state.starfall_bauble_number = _roll_d6_no_six(state)
        event["bauble_number"] = state.starfall_bauble_number
    elif starfall_id == "safe_harbor":
        restored = []
        for player in state.players.values():
            if player.eliminated or player.ship.destroyed:
                continue
            before = player.ship.shields
            player.ship.shields = min(2, player.ship.shields + 1)
            restored.append({"player_id": player.id, "before": before, "after": player.ship.shields})
        event["shields"] = restored
    state.event_log.append(event)


def _active_starfall(state: GameState, starfall_id: str) -> bool:
    return state.active_starfall_id == starfall_id and state.active_starfall_round == state.round_number


def _roll_d6_no_six(state: GameState) -> int:
    value = 6
    while value == 6:
        rng = _make_rng(state)
        value = rng.randint(1, 6)
        state.rng_step += 1
    return value


def _fang(state: GameState):
    return next((bauble for bauble in state.baubles if bauble.is_fang), None)


def _pull_all_ships_toward_fang(state: GameState, distance: int) -> list[dict]:
    fang = _fang(state)
    if fang is None:
        return []
    movements = []
    for player in state.players.values():
        if player.eliminated or player.ship.destroyed:
            continue
        before = {"q": player.ship.q, "r": player.ship.r}
        for _ in range(distance):
            candidates = []
            for direction in range(6):
                q, r = move_forward(player.ship.q, player.ship.r, direction, 1)
                if is_within_board(q, r):
                    candidates.append((hex_distance(q, r, fang.q, fang.r), q, r))
            if not candidates:
                break
            _dist, q, r = min(candidates)
            player.ship.q, player.ship.r = q, r
        movements.append({"player_id": player.id, "before": before, "after": {"q": player.ship.q, "r": player.ship.r}})
    return movements


def _deal_environmental_damage(
    state: GameState,
    damage: int,
    *,
    penetrates_shields: bool = False,
    fixed_lane_roll: int | None = None,
) -> list[dict]:
    results = []
    for player in state.players.values():
        if player.eliminated or player.ship.destroyed:
            continue
        results.append(
            _apply_environmental_damage_to_player(
                state,
                player,
                damage,
                penetrates_shields=penetrates_shields,
                fixed_lane_roll=fixed_lane_roll,
            )
        )
    return results


def _apply_environmental_damage_to_player(
    state: GameState,
    player: PlayerState,
    damage: int,
    *,
    penetrates_shields: bool = False,
    fixed_lane_roll: int | None = None,
) -> dict:
    shields_before = player.ship.shields
    shield_hits = 0
    remaining_damage = damage
    if not penetrates_shields and remaining_damage > 0 and player.ship.shields > 0:
        shield_hits = min(player.ship.shields, remaining_damage)
        player.ship.shields -= shield_hits
        remaining_damage -= shield_hits

    result = {
        "player_id": player.id,
        "shielded": shield_hits > 0,
        "shield_hits": shield_hits,
        "shields_before": shields_before,
        "shields_after": player.ship.shields,
        "damage_applied": 0,
        "damage_shots": [],
        "target_destroyed": player.ship.destroyed,
    }
    if remaining_damage <= 0:
        return result

    damage_result = _apply_unshielded_damage(
        state,
        player,
        remaining_damage,
        apply_desperation=False,
        fixed_lane_roll=fixed_lane_roll,
    )
    result.update(damage_result)
    return result


def _resolve_cleanup_start_star_command(state: GameState) -> None:
    if not _star_command_enabled(state):
        return
    drifts = []
    for player in state.players.values():
        if player.captain_id == "danny_davos" and not player.eliminated and not player.ship.destroyed:
            before = {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing}
            q, r = move_forward(player.ship.q, player.ship.r, player.ship.facing, 2)
            player.ship.q, player.ship.r = clamp_to_board(q, r)
            drifts.append({"player_id": player.id, "before": before, "after": {"q": player.ship.q, "r": player.ship.r, "facing": player.ship.facing}})
    if drifts:
        state.event_log.append({"type": "captain_cleanup_movement", "round": state.round_number, "movements": drifts})
    if _active_starfall(state, "take_cover"):
        targets = []
        for player in state.players.values():
            if player.eliminated or player.ship.destroyed:
                continue
            if any(ship_inside_bauble(player.ship, bauble) for bauble in state.baubles):
                continue
            targets.append(player)
        results = []
        for player in targets:
            results.append(_apply_environmental_damage_to_player(state, player, 2))
        state.event_log.append({"type": "starfall_take_cover_damage", "round": state.round_number, "targets": results})


def _bauble_open_this_round(state: GameState, bauble) -> bool:
    if bauble.is_fang:
        return True
    if bauble.number == state.round_number:
        return True
    if _active_starfall(state, "most_dangerous_game") and 1 <= bauble.number <= 5:
        return True
    if _active_starfall(state, "stars_align") and bauble.number == state.starfall_bauble_number:
        return True
    return False


def _starfall_hit_bonus_vp(state: GameState, attacker_id: str, action_number: int) -> int:
    if not _active_starfall(state, "golden_bounty"):
        return 0
    for event in state.event_log:
        if (
            event.get("type") == "volley_resolved"
            and event.get("round") == state.round_number
            and event.get("action_number") == action_number
            and event.get("attacker_id") == attacker_id
            and event.get("hit")
        ):
            return 0
    return 1


def _apply_starfall_hit_desperation(state: GameState, attacker: PlayerState) -> None:
    if not _active_starfall(state, "jolly_roger"):
        return
    for event in state.event_log:
        if (
            event.get("type") == "starfall_jolly_roger_draw"
            and event.get("round") == state.round_number
            and event.get("player_id") == attacker.id
        ):
            return
    rng = _make_rng(state)
    drawn = draw_desperation_card(state.desperation_deck, rng)
    attacker.deck.insert(0, drawn)
    state.event_log.append(
        {
            "type": "starfall_jolly_roger_draw",
            "round": state.round_number,
            "player_id": attacker.id,
            "desperation_card_id": drawn.id,
        }
    )


def _apply_component_destroyed_captain_effects(state: GameState, target: PlayerState, component_type: str) -> None:
    if target.captain_id == "carlos_connor":
        target.victory_points += 1
        state.event_log.append(
            {
                "type": "captain_vp_awarded",
                "round": state.round_number,
                "player_id": target.id,
                "captain_id": target.captain_id,
                "vp_awarded": 1,
            }
        )
    if component_type not in {"bridge", "life_support"}:
        return
    rng = _make_rng(state)
    for player in state.players.values():
        if player.captain_id != "davey_locker" or player.eliminated:
            continue
        drawn = draw_desperation_card(state.desperation_deck, rng)
        player.deck.insert(0, drawn)
        player.victory_points += 2
        state.event_log.append(
            {
                "type": "captain_davey_reward",
                "round": state.round_number,
                "player_id": player.id,
                "vp_awarded": 2,
                "desperation_card_id": drawn.id,
            }
        )


# ---------------------------------------------------------------------------
# StarBreach cooperative expansion
# ---------------------------------------------------------------------------


def _assign_star_breach_roles(players: dict[str, PlayerState]) -> None:
    """Deal the four roles round-robin so every role ability is in play."""
    player_list = list(players.values())
    assigned: dict[str, list[str]] = {player.id: [] for player in player_list}
    for index, role_id in enumerate(sb_data.ROLE_ASSIGN_ORDER):
        assigned[player_list[index % len(player_list)].id].append(role_id)
    for player in player_list:
        player.roles = tuple(assigned[player.id])
        if "tank" in player.roles:
            player.ship.shields += 1


def _initialize_star_breach(state: GameState) -> None:
    nose_q, nose_r = sb_data.BOSS_START
    fleet = [
        FleetCraftState(
            id=craft_id,
            kind=kind,
            color=color,
            q=nose_q + offset_q,
            r=nose_r + offset_r,
            hp=sb_data.HUNTER_KILLER_HP,
            max_hp=sb_data.HUNTER_KILLER_HP,
        )
        for craft_id, kind, color, (offset_q, offset_r) in sb_data.FLEET_SCENARIO
    ]
    prey_player_id = next(iter(state.players))
    state.star_breach = StarBreachState(
        scenario_id=sb_data.SCENARIO_ID,
        prey_player_id=prey_player_id,
        anchor_q=nose_q,
        anchor_r=nose_r,
        facing=sb_data.BOSS_START_FACING,
        shield_hp=dict(sb_data.INITIAL_SHIELD_HP),
        fleet=fleet,
    )
    state.event_log.append(
        {
            "type": "expansion_enabled",
            "round": state.round_number,
            "expansion_id": STAR_BREACH_ID,
            "scenario_id": sb_data.SCENARIO_ID,
            "prey_player_id": prey_player_id,
            "roles": {player.id: list(player.roles) for player in state.players.values()},
            "fleet": [
                {"id": craft.id, "kind": craft.kind, "color": craft.color, "q": craft.q, "r": craft.r, "hp": craft.hp}
                for craft in fleet
            ],
        }
    )


def _player_with_role(state: GameState, role_id: str) -> PlayerState | None:
    for player in state.players.values():
        if role_id in player.roles and not player.eliminated and not player.ship.destroyed:
            return player
    return None


def _star_breach_result(state: GameState, *, final_round_complete: bool) -> GameResult | None:
    sb = state.star_breach
    assert sb is not None
    prey = state.players.get(sb.prey_player_id)
    if prey is None or prey.eliminated or prey.ship.destroyed:
        return GameResult(winner_ids=(), reason="star_breach_prey_destroyed")
    if final_round_complete:
        fang = _fang(state)
        if fang is not None and ship_inside_bauble(prey.ship, fang):
            return GameResult(winner_ids=tuple(state.players), reason="star_breach_victory")
        return GameResult(winner_ids=(), reason="star_breach_objective_failed")
    return None


def _check_star_breach_defeat(state: GameState) -> None:
    """The players lose the moment The Prey is destroyed."""
    if state.star_breach is None or state.result is not None:
        return
    prey = state.players.get(state.star_breach.prey_player_id)
    if prey is None or prey.eliminated or prey.ship.destroyed:
        state.result = GameResult(winner_ids=(), reason="star_breach_prey_destroyed")
        _change_phase(state, GamePhase.COMPLETE)


def _activate_star_breach_tiers(state: GameState) -> None:
    """Progress tiers reached during a round power up at the next round's
    start, so mid-round progress can't boost the boss late in the same round."""
    sb = state.star_breach
    if sb is None:
        return
    unlocked = sb_data.unlocked_tiers(sb.progress)
    newly_active = sorted(set(unlocked) - set(sb.active_tiers))
    if not newly_active:
        return
    sb.active_tiers = unlocked
    state.event_log.append(
        {
            "type": "boss_tiers_activated",
            "round": state.round_number,
            "tiers": newly_active,
            "active_tiers": list(sb.active_tiers),
            "progress": sb.progress,
        }
    )


def _star_breach_overdrive_exempt(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    if state.star_breach is None or not stack.cards:
        return False
    families = {
        _selected_card_family(card_by_id(selection.card_id), selection)
        for selection in stack.cards
    }
    if "treasure_hunter" in player.roles and families == {CardFamily.MOVE}:
        return True
    if "fighting_ace" in player.roles and families == {CardFamily.ATTACK}:
        return True
    return False


def _validate_star_breach_target(state: GameState, player: PlayerState, target: str) -> None:
    sb = state.star_breach
    assert sb is not None
    if target.startswith("boss:"):
        area = target.split(":", 1)[1]
        if area not in sb_data.AREAS:
            raise RulesError(f"Unknown StarBreacher target area: {area}")
        return
    if target.startswith("craft:"):
        craft_id = target.split(":", 1)[1]
        if not any(craft.id == craft_id for craft in sb.fleet):
            raise RulesError(f"Unknown enemy fleet craft: {craft_id}")
        return
    if target in state.players:
        if "engineer" not in player.roles:
            raise RulesError("Only the Engineer may target an allied ship (as a repair).")
        return
    raise RulesError(f"Unknown attack target: {target}")


def _boss_token_hexes(sb: StarBreachState) -> tuple[tuple[int, int], ...]:
    """The boss's three board hexes: nose, port flank, starboard flank."""
    return sb_data.boss_board_hexes(sb.anchor_q, sb.anchor_r, sb.facing)


def _boss_active(sb: StarBreachState) -> bool:
    """The boss fights while any internal hull hex survives."""
    return len(sb.destroyed_hexes) < len(sb_data.BOSS_FOOTPRINT)


def _boss_distance_to(sb: StarBreachState, q: int, r: int) -> int | None:
    """Shooting distance: to the nearest of the boss's three board hexes."""
    if not _boss_active(sb):
        return None
    return min(hex_distance(q, r, hex_q, hex_r) for hex_q, hex_r in _boss_token_hexes(sb))


def _living_players(state: GameState) -> list[PlayerState]:
    return [
        player
        for player in state.players.values()
        if not player.eliminated and not player.ship.destroyed
    ]


def _enemy_pick_target(state: GameState, distance_to: callable) -> PlayerState | None:
    """Shared enemy targeting: the Tank's Proximity Jammer overrides, else The
    Prey, else the nearest living player."""
    sb = state.star_breach
    assert sb is not None
    tank = _player_with_role(state, "tank")
    if tank is not None:
        tank_distance = distance_to(tank)
        if tank_distance is not None and tank_distance <= sb_data.TANK_PROXIMITY_JAMMER_RANGE:
            return tank
    prey = state.players.get(sb.prey_player_id)
    if prey is not None and not prey.eliminated and not prey.ship.destroyed:
        return prey
    living = _living_players(state)
    if not living:
        return None
    return min(living, key=lambda player: (distance_to(player) or 10**6, player.id))


def _roll_d8(state: GameState) -> int:
    rng = _make_rng(state)
    value = rng.randint(1, 8)
    state.rng_step += 1
    return value


def _roll_d6_sum(state: GameState, dice: int) -> int:
    rng = _make_rng(state)
    values = [rng.randint(1, 6) for _ in range(dice)]
    state.rng_step += dice
    return sum(values)


def _boss_active_slots(state: GameState, phase_key: str) -> list[dict]:
    sb = state.star_breach
    assert sb is not None
    destroyed_components = sb_data.destroyed_component_ids(sb.destroyed_hexes)
    # Tiers reached mid-round only power slots from the start of the next round.
    tiers = set(sb.active_tiers)
    for key, _kind, slots in sb_data.BOSS_PHASES:
        if key != phase_key:
            continue
        active: list[dict] = []
        for slot_type, detail in slots:
            if slot_type == "base":
                active.append({"slot": "base"})
            elif slot_type == "component" and detail not in destroyed_components:
                active.append({"slot": "component", "component_id": detail})
            elif slot_type == "tier" and detail in tiers:
                active.append({"slot": "tier", "tier": detail})
        return active
    return []


def _boss_phase_kind(phase_key: str) -> str:
    for key, kind, _slots in sb_data.BOSS_PHASES:
        if key == phase_key:
            return kind
    raise RulesError(f"Unknown boss phase: {phase_key}")


def _resolve_boss_phase(state: GameState, phase_key: str) -> None:
    sb = state.star_breach
    if sb is None or state.result is not None:
        return
    sb.boss_movement_this_action = 0
    for craft in sb.fleet:
        craft.movement_this_action = 0

    kind = _boss_phase_kind(phase_key)
    slot_results: list[dict] = []
    active_slots = _boss_active_slots(state, phase_key) if _boss_active(sb) else []
    if active_slots:
        # Header event first so the UI can announce the phase, its total
        # action count, and where each action charge is sourced.
        state.event_log.append(
            {
                "type": "boss_phase_started",
                "round": state.round_number,
                "boss_phase": phase_key,
                "kind": kind,
                "slots": [dict(slot) for slot in active_slots],
                "total_actions": len(active_slots),
                "progress": sb.progress,
                "active_tiers": list(sb.active_tiers),
            }
        )
    # Each active slot performs exactly one action: one attack, or one hex of
    # movement.
    for slot in active_slots:
        entry = dict(slot)
        entry["amount"] = 1
        if kind == "move":
            entry["movement"] = _move_boss_toward_prey(state, 1)
        else:
            entry["attacks"] = [_boss_attack(state)]
        slot_results.append(entry)
        _check_star_breach_defeat(state)
        if state.phase == GamePhase.COMPLETE:
            break

    craft_results: list[dict] = []
    if state.phase != GamePhase.COMPLETE and phase_key != "starbreach":
        for craft in sb.fleet:
            if craft.destroyed:
                continue
            if kind == "move":
                craft_results.append(_move_craft(state, craft))
            else:
                craft_results.append(_craft_attack(state, craft))
                _check_star_breach_defeat(state)
                if state.phase == GamePhase.COMPLETE:
                    break

    state.event_log.append(
        {
            "type": "boss_phase_resolved",
            "round": state.round_number,
            "boss_phase": phase_key,
            "kind": kind,
            "progress": sb.progress,
            "slots": slot_results,
            "fleet": craft_results,
        }
    )


def _occupied_ship_hexes(state: GameState, *, ignore_craft_id: str | None = None) -> set[tuple[int, int]]:
    sb = state.star_breach
    assert sb is not None
    occupied = {
        (player.ship.q, player.ship.r)
        for player in state.players.values()
        if not player.eliminated and not player.ship.destroyed
    }
    for craft in sb.fleet:
        if not craft.destroyed and craft.id != ignore_craft_id:
            occupied.add((craft.q, craft.r))
    return occupied


def _move_boss_toward_prey(state: GameState, steps: int) -> dict:
    """Move the boss token toward The Prey. The nose leads: facing becomes the
    direction of the last hex moved."""
    sb = state.star_breach
    assert sb is not None
    prey = state.players.get(sb.prey_player_id)
    before = {"anchor_q": sb.anchor_q, "anchor_r": sb.anchor_r, "facing": sb.facing}
    moved = 0
    pushed: list[dict] = []
    if prey is None or prey.eliminated or prey.ship.destroyed:
        target = _enemy_pick_target(state, lambda player: _boss_distance_to(sb, player.ship.q, player.ship.r))
    else:
        target = prey
    if target is None:
        return {"before": before, "after": dict(before), "moved": 0, "pushed": pushed}

    for _ in range(steps):
        current = _boss_distance_to(sb, target.ship.q, target.ship.r)
        if current is None or current <= 1:
            break
        # The nose leads: steer by nose distance (the flanks trail behind and
        # would otherwise stall the strict-improvement check). Prefer holding
        # the current heading on ties.
        best_direction = None
        best_distance = hex_distance(sb.anchor_q, sb.anchor_r, target.ship.q, target.ship.r)
        for direction in ((sb.facing + offset) % 6 for offset in range(6)):
            dq, dr = move_forward(0, 0, direction, 1)
            candidate_hexes = sb_data.boss_board_hexes(sb.anchor_q + dq, sb.anchor_r + dr, direction)
            if any(not is_within_board(hex_q, hex_r) for hex_q, hex_r in candidate_hexes):
                continue
            candidate = hex_distance(sb.anchor_q + dq, sb.anchor_r + dr, target.ship.q, target.ship.r)
            if candidate < best_distance:
                best_distance = candidate
                best_direction = direction
        if best_direction is None:
            break
        dq, dr = move_forward(0, 0, best_direction, 1)
        sb.anchor_q += dq
        sb.anchor_r += dr
        sb.facing = best_direction
        moved += 1
        sb.boss_movement_this_action += 1
        pushed.extend(_push_ships_out_of_boss(state, best_direction))
    return {
        "before": before,
        "after": {"anchor_q": sb.anchor_q, "anchor_r": sb.anchor_r, "facing": sb.facing},
        "moved": moved,
        "pushed": pushed,
    }


def _push_ships_out_of_boss(state: GameState, direction: int) -> list[dict]:
    """Ships caught under the advancing hull are shoved along its heading."""
    sb = state.star_breach
    assert sb is not None
    footprint = set(_boss_token_hexes(sb))
    moves: list[dict] = []

    def push(q: int, r: int, occupied: set[tuple[int, int]]) -> tuple[int, int]:
        for _ in range(40):
            if (q, r) not in footprint and (q, r) not in occupied and is_within_board(q, r):
                break
            q, r = move_forward(q, r, direction, 1)
            if not is_within_board(q, r):
                q, r = clamp_to_board(q, r)
                break
        return q, r

    for player in state.players.values():
        if player.eliminated or player.ship.destroyed:
            continue
        if (player.ship.q, player.ship.r) in footprint:
            occupied = _occupied_ship_hexes(state) - {(player.ship.q, player.ship.r)}
            new_q, new_r = push(player.ship.q, player.ship.r, occupied)
            moves.append({"ship": player.id, "from": [player.ship.q, player.ship.r], "to": [new_q, new_r]})
            player.ship.q, player.ship.r = new_q, new_r
    for craft in sb.fleet:
        if craft.destroyed:
            continue
        if (craft.q, craft.r) in footprint:
            occupied = _occupied_ship_hexes(state, ignore_craft_id=craft.id)
            new_q, new_r = push(craft.q, craft.r, occupied)
            moves.append({"ship": craft.id, "from": [craft.q, craft.r], "to": [new_q, new_r]})
            craft.q, craft.r = new_q, new_r
    return moves


def _move_craft(state: GameState, craft: FleetCraftState) -> dict:
    """Hunter-Killer movement: directly toward The Prey, never overshooting."""
    sb = state.star_breach
    assert sb is not None
    target = _enemy_pick_target(
        state, lambda player: hex_distance(craft.q, craft.r, player.ship.q, player.ship.r)
    )
    before = [craft.q, craft.r]
    if target is None:
        return {"craft_id": craft.id, "before": before, "after": before, "moved": 0}
    # The jammer redirects attacks, not pursuit: Hunter-Killers fly at The Prey.
    prey = state.players.get(sb.prey_player_id)
    if prey is not None and not prey.eliminated and not prey.ship.destroyed:
        target = prey
    boss_hexes = set(_boss_token_hexes(sb))
    moved = 0
    for _ in range(sb_data.HUNTER_KILLER_MOVE):
        distance = hex_distance(craft.q, craft.r, target.ship.q, target.ship.r)
        if distance <= 1:
            break
        occupied = _occupied_ship_hexes(state, ignore_craft_id=craft.id) | boss_hexes
        candidates = []
        for direction in range(6):
            q, r = move_forward(craft.q, craft.r, direction, 1)
            if not is_within_board(q, r) or (q, r) in occupied:
                continue
            candidates.append((hex_distance(q, r, target.ship.q, target.ship.r), direction, q, r))
        if not candidates:
            break
        best = min(candidates)
        if best[0] >= distance:
            break
        craft.q, craft.r = best[2], best[3]
        craft.movement_this_action += 1
        moved += 1
    return {"craft_id": craft.id, "before": before, "after": [craft.q, craft.r], "moved": moved}


def _resolve_enemy_shot(
    state: GameState,
    target: PlayerState,
    *,
    attacker_label: str,
    attacker_position: tuple[int, int],
    distance: int,
    aim_bonus: int,
) -> dict:
    dice = 1 if "tank" in target.roles else 2
    roll = _roll_d6_sum(state, dice)
    roll_total = roll + aim_bonus
    defense_threshold = distance + target.ship.movement_this_action + target.ship.defense_bonus_this_action
    hit = roll_total >= defense_threshold or (dice >= 2 and roll >= 12)
    event = {
        "type": "enemy_volley_resolved",
        "round": state.round_number,
        "phase": state.phase,
        "attacker": attacker_label,
        "attacker_position": {"q": attacker_position[0], "r": attacker_position[1]},
        "target_position": {"q": target.ship.q, "r": target.ship.r},
        "target_id": target.id,
        "dice": dice,
        "roll": roll,
        "aim_bonus": aim_bonus,
        "roll_total": roll_total,
        "distance": distance,
        "defense_threshold": defense_threshold,
        "hit": hit,
        "shielded": False,
        "damage_applied": 0,
    }
    if hit and target.ship.shields > 0:
        target.ship.shields -= 1
        event["shielded"] = True
    elif hit:
        damage_result = _apply_unshielded_damage(state, target, 1)
        event.update(damage_result)
    state.event_log.append(event)

    sb = state.star_breach
    if sb is not None and hit and target.id == sb.prey_player_id:
        _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_HIT)
        if target.ship.destroyed:
            _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_KILL - sb_data.PROGRESS_PER_PREY_HIT)
    return event


def _advance_boss_progress(state: GameState, amount: int) -> None:
    sb = state.star_breach
    assert sb is not None
    before_tiers = set(sb_data.unlocked_tiers(sb.progress))
    sb.progress += amount
    new_tiers = sorted(set(sb_data.unlocked_tiers(sb.progress)) - before_tiers)
    state.event_log.append(
        {
            "type": "boss_progress_advanced",
            "round": state.round_number,
            "amount": amount,
            "progress": sb.progress,
            "tiers_unlocked": new_tiers,
        }
    )


def _boss_attack(state: GameState) -> dict:
    sb = state.star_breach
    assert sb is not None
    target = _enemy_pick_target(state, lambda player: _boss_distance_to(sb, player.ship.q, player.ship.r))
    if target is None:
        return {"skipped": "no_target"}
    distance = _boss_distance_to(sb, target.ship.q, target.ship.r)
    if distance is None:
        return {"skipped": "boss_destroyed"}
    firing_hex = min(
        _boss_token_hexes(sb),
        key=lambda hex_: hex_distance(target.ship.q, target.ship.r, hex_[0], hex_[1]),
    )
    return _resolve_enemy_shot(
        state,
        target,
        attacker_label="starbreacher",
        attacker_position=firing_hex,
        distance=distance,
        aim_bonus=0,
    )


def _craft_attack(state: GameState, craft: FleetCraftState) -> dict:
    target = _enemy_pick_target(
        state, lambda player: hex_distance(craft.q, craft.r, player.ship.q, player.ship.r)
    )
    if target is None:
        return {"skipped": "no_target", "craft_id": craft.id}
    distance = hex_distance(craft.q, craft.r, target.ship.q, target.ship.r)
    event = _resolve_enemy_shot(
        state,
        target,
        attacker_label=craft.id,
        attacker_position=(craft.q, craft.r),
        distance=distance,
        aim_bonus=sb_data.HUNTER_KILLER_AIM,
    )
    event["craft_id"] = craft.id
    return event


# --- Players attacking the StarBreacher and its fleet ----------------------


def _resolve_star_breach_attacker(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    attack_cards: list[tuple[Card, OrderCardSelection]],
) -> bool:
    """Resolve one player's attack stack in cooperative mode. Returns True if
    any volley was resolved."""
    resolved = False
    u_turn_attack_count = sum(
        1
        for card, selection in attack_cards
        if (effect := _card_effect(card, selection, stack.seal_mode)).attack is not None
        and effect.attack.u_turn_attack
    )
    if u_turn_attack_count % 2:
        attacker.ship.facing = u_turn(attacker.ship.facing)
    volleys = [attack_cards]
    if _overdrive_copies_action(stack):
        copy_cards = _attack_cards_for_stack(stack, include_desperate=_overdrive_desperation_enabled())
        if copy_cards:
            volleys.append(copy_cards)
    for volley_index, cards in enumerate(volleys):
        targets = _star_breach_targets_for_attack(state, attacker, stack, cards)
        for target in targets:
            _resolve_star_breach_volley(
                state,
                action_number,
                stack,
                attacker,
                target,
                cards,
                overdrive_copy=volley_index > 0,
            )
            resolved = True
    return resolved


def _star_breach_targets_for_attack(
    state: GameState,
    attacker: PlayerState,
    stack: ActionStack,
    attack_cards: list[tuple[Card, OrderCardSelection]],
) -> list[str]:
    sb = state.star_breach
    assert sb is not None
    effects = [_card_effect(card, selection, stack.seal_mode) for card, selection in attack_cards]
    attack_effects = [effect.attack for effect in effects if effect.attack is not None]

    if any(effect.attacks_all for effect in attack_effects):
        targets = [f"craft:{craft.id}" for craft in sb.fleet if not craft.destroyed]
        area = _nearest_boss_area(sb, attacker.ship.q, attacker.ship.r)
        if area:
            targets.append(f"boss:{area}")
        return targets
    if any(effect.attacks_cone_120 for effect in attack_effects):
        targets = [
            f"craft:{craft.id}"
            for craft in sb.fleet
            if not craft.destroyed
            and _ship_in_facing_cone_120(attacker.ship, ShipState(q=craft.q, r=craft.r))
        ]
        token_areas = _boss_token_hex_areas(sb)
        cone_hexes = [
            hex_ for hex_ in token_areas
            if _ship_in_facing_cone_120(attacker.ship, ShipState(q=hex_[0], r=hex_[1]))
        ]
        if cone_hexes:
            nearest = min(cone_hexes, key=lambda h: hex_distance(attacker.ship.q, attacker.ship.r, h[0], h[1]))
            targets.append(f"boss:{token_areas[nearest]}")
        return targets

    for _card, selection in attack_cards:
        if selection.target_player_id:
            return [selection.target_player_id]
    forward = _first_star_breach_forward_target(state, attacker)
    return [forward] if forward else []


def _boss_token_hex_areas(sb: StarBreachState) -> dict[tuple[int, int], str]:
    """Map each board-token hex to the target area it counts as when struck."""
    if not _boss_active(sb):
        return {}
    return dict(zip(_boss_token_hexes(sb), sb_data.BOARD_HEX_AREAS))


def _nearest_boss_area(sb: StarBreachState, q: int, r: int) -> str | None:
    token_areas = _boss_token_hex_areas(sb)
    if not token_areas:
        return None
    nearest = min(token_areas, key=lambda h: hex_distance(q, r, h[0], h[1]))
    return token_areas[nearest]


def _first_star_breach_forward_target(state: GameState, attacker: PlayerState) -> str | None:
    """Untargeted attacks fire straight ahead at the first enemy: a fleet
    craft or the StarBreacher's hull. Allied ships are never hit in co-op."""
    sb = state.star_breach
    assert sb is not None
    boss_hexes = _boss_token_hex_areas(sb)
    crafts = {(craft.q, craft.r): craft.id for craft in sb.fleet if not craft.destroyed}
    distance = 1
    while True:
        q, r = move_forward(attacker.ship.q, attacker.ship.r, attacker.ship.facing, distance)
        if not is_within_board(q, r):
            return None
        if (q, r) in crafts:
            return f"craft:{crafts[(q, r)]}"
        if (q, r) in boss_hexes:
            return f"boss:{boss_hexes[(q, r)]}"
        distance += 1


def _resolve_star_breach_volley(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    target: str,
    attack_cards: list[tuple[Card, OrderCardSelection]],
    *,
    overdrive_copy: bool = False,
) -> None:
    if target.startswith("boss:"):
        _resolve_volley_vs_boss(state, action_number, stack, attacker, target.split(":", 1)[1], attack_cards, overdrive_copy)
    elif target.startswith("craft:"):
        _resolve_volley_vs_craft(state, action_number, stack, attacker, target.split(":", 1)[1], attack_cards, overdrive_copy)
    else:
        _resolve_repair_volley(state, action_number, stack, attacker, target, attack_cards, overdrive_copy)


def _collect_attack_profile(
    stack: ActionStack, attack_cards: list[tuple[Card, OrderCardSelection]]
) -> dict:
    effects = [
        effect.attack
        for card, selection in attack_cards
        if (effect := _card_effect(card, selection, stack.seal_mode)).attack is not None
    ]
    base_damage = max((effect.base_damage for effect in effects), default=1)
    if base_damage <= 1:
        base_damage = 1
    return {
        "damage": base_damage + sum(effect.damage_bonus for effect in effects),
        "aim_bonus": sum(effect.aim_bonus for effect in effects),
        "always_hits": any(effect.always_hits for effect in effects),
        "max_range": next((effect.max_range for effect in effects if effect.max_range is not None), None),
        "fixed_defense_threshold": next(
            (effect.fixed_defense_threshold for effect in effects if effect.fixed_defense_threshold is not None),
            None,
        ),
        "ramming": next((effect for effect in effects if effect.ramming_damage), None),
    }


def _resolve_volley_vs_boss(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    area: str,
    attack_cards: list[tuple[Card, OrderCardSelection]],
    overdrive_copy: bool,
) -> None:
    sb = state.star_breach
    assert sb is not None
    profile = _collect_attack_profile(stack, attack_cards)
    area_has_intact_hull = any(
        (q, r) not in sb.destroyed_hexes
        for q, r in sb_data.BOSS_FOOTPRINT
        if sb_data.region_of_hex(q, r) == area
    )
    if not area_has_intact_hull or not _boss_active(sb):
        state.event_log.append(
            {
                "type": "volley_skipped",
                "round": state.round_number,
                "action_number": action_number,
                "attacker_id": attacker.id,
                "target_id": f"boss:{area}",
                "reason": "area_destroyed",
            }
        )
        return
    # Shooting distance is always to the nearest of the boss's board hexes.
    distance = _boss_distance_to(sb, attacker.ship.q, attacker.ship.r) or 1
    struck_hex = min(
        _boss_token_hexes(sb),
        key=lambda hex_: hex_distance(attacker.ship.q, attacker.ship.r, hex_[0], hex_[1]),
    )
    threshold = (
        profile["fixed_defense_threshold"]
        if profile["fixed_defense_threshold"] is not None
        else distance + sb.boss_movement_this_action
    )
    roll = _roll_attack(state)
    roll_total = roll + profile["aim_bonus"]
    if attacker.captain_id == "malcolm_manderly":
        roll_total += 2
    in_range = profile["max_range"] is None or distance <= profile["max_range"]
    natural_auto_hit = roll >= (18 if _active_starfall(state, "clear_skies") else 12)
    hit = in_range and (profile["always_hits"] or natural_auto_hit or roll_total >= threshold)
    is_ace = "fighting_ace" in attacker.roles

    shots: list[dict] = []
    shields_absorbed = 0
    hexes_destroyed = 0
    components_destroyed: list[str] = []
    desperation_cards_drawn = 0
    if hit:
        generator_intact = _shield_generator_intact(sb, area)
        for _shot in range(profile["damage"]):
            if generator_intact and sb.shield_hp.get(area, 0) > 0:
                sb.shield_hp[area] -= 1
                shields_absorbed += 1
                shots.append({"result": "shield_absorbed", "shield_hp_left": sb.shield_hp[area]})
                continue
            lane_roll = _roll_d8(state)
            adjusted_roll, ace_shift = _fighting_ace_lane_choice(sb, area, lane_roll) if is_ace else (lane_roll, 0)
            if adjusted_roll == sb_data.GLANCING_BLOW_ROLL:
                rng = _make_rng(state)
                drawn = draw_desperation_card(state.desperation_deck, rng)
                attacker.deck.insert(0, drawn)
                desperation_cards_drawn += 1
                shots.append({"result": "glancing_blow", "roll": lane_roll, "ace_shift": ace_shift, "desperation_card_id": drawn.id})
                continue
            local = sb_data.first_intact_lane_hex(area, adjusted_roll, sb.destroyed_hexes)
            if local is None:
                shots.append({"result": "overpenetration", "roll": lane_roll, "ace_shift": ace_shift, "lane": adjusted_roll})
                continue
            sb.destroyed_hexes.add(local)
            hexes_destroyed += 1
            shot = {
                "result": "hull_destroyed",
                "roll": lane_roll,
                "ace_shift": ace_shift,
                "lane": adjusted_roll,
                "hex": [local[0], local[1]],
            }
            component = sb_data.BOSS_COMPONENT_BY_HEX.get(local)
            if component is not None:
                components_destroyed.append(component.id)
                shot["component_id"] = component.id
                shot["component_type"] = component.component_type
                if component.component_type == "shield_generator":
                    for arc in component.shield_arcs:
                        sb.shield_hp[arc] = 0
            shots.append(shot)

    vp_awarded = (1 if hexes_destroyed or shields_absorbed else 0) + len(components_destroyed)
    attacker.victory_points += vp_awarded
    state.event_log.append(
        {
            "type": "boss_volley_resolved",
            "round": state.round_number,
            "action_number": action_number,
            "attacker_id": attacker.id,
            "target_id": f"boss:{area}",
            "overdrive_copy": overdrive_copy,
            "card_ids": [card.id for card, _selection in attack_cards],
            "attacker_position": {"q": attacker.ship.q, "r": attacker.ship.r},
            "target_position": {"q": struck_hex[0], "r": struck_hex[1]},
            "distance": distance,
            "boss_movement": sb.boss_movement_this_action,
            "defense_threshold": threshold,
            "roll": roll,
            "roll_total": roll_total,
            "in_range": in_range,
            "hit": hit,
            "damage": profile["damage"],
            "shields_absorbed": shields_absorbed,
            "shield_hp_left": sb.shield_hp.get(area, 0),
            "hexes_destroyed": hexes_destroyed,
            "components_destroyed": components_destroyed,
            "desperation_cards_drawn": desperation_cards_drawn,
            "shots": shots,
            "vp_awarded": vp_awarded,
        }
    )


def _shield_generator_intact(sb: StarBreachState, area: str) -> bool:
    """Whether the arc's shield still has power. The nose (forward) charge is
    intrinsic — it only depletes; the other arcs die with their generator."""
    destroyed_components = sb_data.destroyed_component_ids(sb.destroyed_hexes)
    for component in sb_data.BOSS_COMPONENTS:
        if component.component_type == "shield_generator" and area in component.shield_arcs:
            return component.id not in destroyed_components
    return area == "forward"


def _fighting_ace_lane_choice(sb: StarBreachState, area: str, lane_roll: int) -> tuple[int, int]:
    """Deterministic Fighting Ace policy: shift the lane roll by ±1 when that
    turns a Glancing Blow into a strike or steers the hit onto a component."""

    def lane_score(roll: int) -> float:
        if roll < 1 or roll > 8:
            return -1.0
        if roll == sb_data.GLANCING_BLOW_ROLL:
            return 0.5  # a desperation card is worth something, hull damage more
        local = sb_data.first_intact_lane_hex(area, roll, sb.destroyed_hexes)
        if local is None:
            return 0.0
        return 3.0 if local in sb_data.BOSS_COMPONENT_BY_HEX else 1.0

    best_roll = lane_roll
    best_score = lane_score(lane_roll)
    for candidate in (lane_roll - 1, lane_roll + 1):
        score = lane_score(candidate)
        if score > best_score:
            best_score = score
            best_roll = candidate
    return best_roll, best_roll - lane_roll


def _resolve_volley_vs_craft(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    craft_id: str,
    attack_cards: list[tuple[Card, OrderCardSelection]],
    overdrive_copy: bool,
) -> None:
    sb = state.star_breach
    assert sb is not None
    craft = next((candidate for candidate in sb.fleet if candidate.id == craft_id), None)
    if craft is None or craft.destroyed:
        state.event_log.append(
            {
                "type": "volley_skipped",
                "round": state.round_number,
                "action_number": action_number,
                "attacker_id": attacker.id,
                "target_id": f"craft:{craft_id}",
                "reason": "target_not_active",
            }
        )
        return
    profile = _collect_attack_profile(stack, attack_cards)
    distance = hex_distance(attacker.ship.q, attacker.ship.r, craft.q, craft.r)
    threshold = (
        profile["fixed_defense_threshold"]
        if profile["fixed_defense_threshold"] is not None
        else distance + craft.movement_this_action
    )
    # Fighting Ace: one extra attack die against fleet craft.
    extra_dice = 1 if "fighting_ace" in attacker.roles else 0
    base_dice = 3 if _active_starfall(state, "clear_skies") else 2
    roll = _roll_d6_sum(state, base_dice + extra_dice)
    roll_total = roll + profile["aim_bonus"]
    if attacker.captain_id == "malcolm_manderly":
        roll_total += 2
    in_range = profile["max_range"] is None or distance <= profile["max_range"]
    hit = in_range and (profile["always_hits"] or roll_total >= threshold or roll >= 6 * (base_dice + extra_dice))
    damage_applied = 0
    if hit:
        damage_applied = min(craft.hp, profile["damage"])
        craft.hp -= damage_applied
        if craft.hp <= 0:
            craft.destroyed = True
    vp_awarded = 0
    if hit and damage_applied:
        vp_awarded = 3 if craft.destroyed else 1
        attacker.victory_points += vp_awarded
    state.event_log.append(
        {
            "type": "craft_volley_resolved",
            "round": state.round_number,
            "action_number": action_number,
            "attacker_id": attacker.id,
            "target_id": f"craft:{craft.id}",
            "overdrive_copy": overdrive_copy,
            "card_ids": [card.id for card, _selection in attack_cards],
            "attacker_position": {"q": attacker.ship.q, "r": attacker.ship.r},
            "target_position": {"q": craft.q, "r": craft.r},
            "distance": distance,
            "defense_threshold": threshold,
            "dice": base_dice + extra_dice,
            "roll": roll,
            "roll_total": roll_total,
            "in_range": in_range,
            "hit": hit,
            "damage": profile["damage"],
            "damage_applied": damage_applied,
            "craft_hp_left": craft.hp,
            "craft_destroyed": craft.destroyed,
            "vp_awarded": vp_awarded,
        }
    )


def _resolve_repair_volley(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    target_id: str,
    attack_cards: list[tuple[Card, OrderCardSelection]],
    overdrive_copy: bool,
) -> None:
    """Engineer: attack orders aimed at an ally resolve as 1d6 repairs."""
    sb = state.star_breach
    assert sb is not None
    target = state.players.get(target_id)
    skip_reason = None
    if target is None or target.eliminated or target.ship.destroyed:
        skip_reason = "target_not_active"
    elif "engineer" not in attacker.roles:
        skip_reason = "not_engineer"
    elif target_id in sb.repaired_ship_ids_this_action:
        skip_reason = "already_repaired_this_action"
    if skip_reason:
        state.event_log.append(
            {
                "type": "volley_skipped",
                "round": state.round_number,
                "action_number": action_number,
                "attacker_id": attacker.id,
                "target_id": target_id,
                "reason": skip_reason,
            }
        )
        return
    profile = _collect_attack_profile(stack, attack_cards)
    distance = hex_distance(attacker.ship.q, attacker.ship.r, target.ship.q, target.ship.r)
    threshold = distance + target.ship.movement_this_action + target.ship.defense_bonus_this_action
    roll = _roll_d6_sum(state, 1)
    roll_total = roll + profile["aim_bonus"]
    in_range = profile["max_range"] is None or distance <= profile["max_range"]
    hit = in_range and (profile["always_hits"] or roll_total >= threshold)
    restored_component_id = None
    shield_restored = False
    if hit:
        sb.repaired_ship_ids_this_action.append(target_id)
        restored_component_id = _repair_one_component(target)
        if restored_component_id is None:
            max_shields = 3 if "tank" in target.roles else 2
            if target.ship.shields < max_shields:
                target.ship.shields += 1
                shield_restored = True
    state.event_log.append(
        {
            "type": "repair_volley_resolved",
            "round": state.round_number,
            "action_number": action_number,
            "attacker_id": attacker.id,
            "target_id": target_id,
            "overdrive_copy": overdrive_copy,
            "card_ids": [card.id for card, _selection in attack_cards],
            "attacker_position": {"q": attacker.ship.q, "r": attacker.ship.r},
            "target_position": {"q": target.ship.q, "r": target.ship.r},
            "distance": distance,
            "defense_threshold": threshold,
            "roll": roll,
            "roll_total": roll_total,
            "in_range": in_range,
            "hit": hit,
            "restored_component_id": restored_component_id,
            "shield_restored": shield_restored,
        }
    )


def _repair_one_component(target: PlayerState) -> str | None:
    """Restore the first destroyed component still adjacent to intact hull."""
    destroyed = target.ship.destroyed_components
    for component in BASE_SHIP_COMPONENTS:
        if component.id not in destroyed:
            continue
        if not _component_adjacent_to_intact(component.id, destroyed):
            continue
        destroyed.discard(component.id)
        target.ship.component_hit_counts.pop(component.id, None)
        target.ship.damage_taken = max(0, target.ship.damage_taken - 1)
        target.ship.destroyed = is_ship_destroyed(target.ship.destroyed_components)
        return component.id
    return None


def _remove_ordered_cards_from_hand(player: PlayerState, orders: OrdersSubmission) -> None:
    ordered_ids = {selection.card_id for stack in orders.stacks for selection in stack.cards}
    remove_ordered_cards_from_hand(player, ordered_ids)


def _discard_unused_hand(state: GameState, player: PlayerState) -> None:
    discarded = discard_hand(player)
    if not discarded:
        return
    state.event_log.append(
        {
            "type": "hand_discarded",
            "round": state.round_number,
            "player_id": player.id,
            "card_ids": [card.id for card in discarded],
            "deck_count": len(player.deck),
            "hand_count": len(player.hand),
            "discard_count": len(player.discard),
        }
    )
