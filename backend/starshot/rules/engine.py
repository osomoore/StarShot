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
from starshot.rules.expansion_modules import expansion_module
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
)
from starshot.rules.ship_layout import ShipLayout, layout_for_ship
from starshot.rules.player_ships import (
    SIGNAL_JAMMER_DEFENSE_BONUS,
    SIGNAL_JAMMER_TYPE,
    TARGETING_SENSORS_AIM_BONUS,
    TARGETING_SENSORS_TYPE,
    compile_layout_spec,
)
from starshot.rules.star_command import EXPANSION_ID as STAR_COMMAND_ID

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
STAR_BREACH_ID = "star_breach"


def create_initial_state(config: GameConfig) -> GameState:
    player_ids = tuple(dict.fromkeys(config.player_ids))
    star_breach = _expansion_module_if_configured(config.active_expansions, STAR_BREACH_ID)
    minimum_players = 1 if star_breach is not None else 2
    if len(player_ids) < minimum_players or len(player_ids) > 4:
        if star_breach is not None:
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
            ship=star_breach.starting_ship(index) if star_breach is not None else _starting_ship(index),
        )
        for index, player_id in enumerate(player_ids)
    }
    for player_id, design in (config.player_ship_designs or {}).items():
        player = players.get(player_id)
        if player is None or not design:
            continue
        spec = compile_layout_spec(design)
        player.ship.layout = spec
        player.ship.shields = int(spec.get("max_shields", player.ship.shields))
    if config.seed is None:
        for player in players.values():
            setup_rng.shuffle(player.deck)
    if config.debug_start_with_attack_desperation_card:
        from starshot.rules.desperation import desperation_card_by_id

        for player in players.values():
            player.deck.append(desperation_card_by_id("desp_steady_shot_a"))
    if star_breach is not None:
        star_breach.assign_roles(players, config.star_breach_role_preferences)
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
    if star_breach is not None:
        star_breach.initialize(state, config)
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
    return expansion_module(STAR_COMMAND_ID).choose_captain(state, player_id, captain_id)


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
    star_breach = _active_expansion_module(state, STAR_BREACH_ID)
    if star_breach is not None:
        return star_breach.game_result(state, final_round_complete=state.round_number > 6)
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
    star_breach = _active_expansion_module(state, STAR_BREACH_ID)
    if star_breach is not None:
        star_breach.before_player_action(state, action_number)
        if state.phase == GamePhase.COMPLETE:
            return
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


def _expansion_module_if_configured(active_expansions: tuple[str, ...], expansion_id: str):
    if expansion_id not in active_expansions:
        return None
    return expansion_module(expansion_id)


def _active_expansion_module(state: GameState, expansion_id: str):
    return _expansion_module_if_configured(state.active_expansions, expansion_id)


def _active_expansion_modules(state: GameState) -> list:
    return [
        expansion_module(expansion_id)
        for expansion_id in state.active_expansions
        if expansion_id in {STAR_BREACH_ID, STAR_COMMAND_ID}
    ]


def _overdrive_exempt_by_expansion(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    for module in _active_expansion_modules(state):
        overdrive_exempt = getattr(module, "overdrive_exempt", None)
        if overdrive_exempt is not None and overdrive_exempt(state, player, stack):
            return True
    return False


def _move_distance_multiplier_by_expansion(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    selection: OrderCardSelection,
    card: Card,
    *,
    overdrive_copy: bool,
) -> int:
    multiplier = 1
    for module in _active_expansion_modules(state):
        move_distance_multiplier = getattr(module, "move_distance_multiplier", None)
        if move_distance_multiplier is not None:
            multiplier *= int(
                move_distance_multiplier(
                    state,
                    player,
                    stack,
                    selection,
                    card,
                    overdrive_copy=overdrive_copy,
                )
            )
    return max(1, multiplier)


def _move_defense_distance_by_expansion(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    selection: OrderCardSelection,
    card: Card,
    distance: int,
    *,
    overdrive_copy: bool,
) -> int:
    defense_distance = distance
    for module in _active_expansion_modules(state):
        move_defense_distance = getattr(module, "move_defense_distance", None)
        if move_defense_distance is not None:
            defense_distance = int(
                move_defense_distance(
                    state,
                    player,
                    stack,
                    selection,
                    card,
                    defense_distance,
                    overdrive_copy=overdrive_copy,
                )
            )
    return max(0, defense_distance)


def _star_breach_overdrive_exempt(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    module = expansion_module(STAR_BREACH_ID)
    return module.overdrive_exempt(state, player, stack)


def _first_star_breach_forward_target(state: GameState, attacker: PlayerState) -> str | None:
    module = expansion_module(STAR_BREACH_ID)
    return module._first_star_breach_forward_target(state, attacker)


def _fighting_ace_lane_choice(sb, area: str, lane_roll: int) -> tuple[int, int]:
    module = expansion_module(STAR_BREACH_ID)
    return module._fighting_ace_lane_choice(sb, area, lane_roll)


def _roll_d8(state: GameState) -> int:
    module = expansion_module(STAR_BREACH_ID)
    return module._roll_d8_impl(state)


def _roll_d6_sum(state: GameState, dice: int) -> int:
    module = expansion_module(STAR_BREACH_ID)
    return module._roll_d6_sum_impl(state, dice)


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
                distance *= _move_distance_multiplier_by_expansion(
                    state,
                    player,
                    stack,
                    selection,
                    card,
                    overdrive_copy=overdrive_copy,
                )
            defense_distance = _move_defense_distance_by_expansion(
                state,
                player,
                stack,
                selection,
                card,
                0 if move_effect.movement_disabled or move_effect.warp_destination else distance,
                overdrive_copy=overdrive_copy,
            )
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
                player.ship.movement_this_action += defense_distance
            elif move_effect.double_turn_after_move:
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                if move_choice == "turn_left":
                    player.ship.facing = turn_left(turn_left(player.ship.facing))
                else:
                    player.ship.facing = turn_right(turn_right(player.ship.facing))
                player.ship.movement_this_action += defense_distance
            elif move_effect.u_turn_move:
                player.ship.facing = u_turn(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += defense_distance
            elif move_effect.side_slip_direction:
                slip_facing = (player.ship.facing + (_SLIP_RIGHT_OFFSET if move_choice == "slip_right" else _SLIP_LEFT_OFFSET)) % 6
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, slip_facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += defense_distance
            elif move_choice == "forward":
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += defense_distance
            elif move_choice == "turn_left":
                player.ship.facing = turn_left(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += defense_distance
            elif move_choice == "turn_right":
                player.ship.facing = turn_right(player.ship.facing)
                attempted_q, attempted_r = move_forward(player.ship.q, player.ship.r, player.ship.facing, distance)
                player.ship.q, player.ship.r = attempted_q, attempted_r
                player.ship.movement_this_action += defense_distance
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
            count = _engineering_component_count(effect.repair_components, stack)
            before = sorted(player.ship.destroyed_components)
            restored = _repair_components(player, selection.repair_component_ids, count)
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
            count = _engineering_component_count(effect.reconfigure_components, stack)
            before = sorted(player.ship.destroyed_components)
            moved = _reconfigure_components(
                player,
                selection.reconfigure_from_component_ids,
                selection.reconfigure_to_component_ids,
                count,
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


def _engineering_component_count(base_count: int, stack: ActionStack) -> int:
    return base_count * 2 if _overdrive_copies_action(stack) else base_count


def _repair_components(player: PlayerState, component_ids: tuple[str, ...], count: int) -> list[str]:
    if not component_ids:
        return []
    layout = layout_for_ship(player.ship)
    _ensure_unique_component_ids(component_ids, layout)
    if len(component_ids) > count:
        raise RulesError(f"Hull Repair can restore at most {count} component(s).")
    current = set(player.ship.destroyed_components)
    for component_id in component_ids:
        if component_id not in current:
            continue
        current.remove(component_id)
    _ensure_intact_components_connected(current, layout)
    for component_id in component_ids:
        player.ship.destroyed_components.discard(component_id)
        player.ship.component_hit_counts.pop(component_id, None)
    player.ship.damage_taken = max(0, player.ship.damage_taken - len(component_ids))
    player.ship.destroyed = layout.is_ship_destroyed(player.ship.destroyed_components)
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
    layout = layout_for_ship(player.ship)
    _ensure_unique_component_ids(from_component_ids, layout)
    _ensure_unique_component_ids(to_component_ids, layout)
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
        if not _component_adjacent_to_intact(component_id, interim, layout):
            raise RulesError(f"Reconfigure destination is not adjacent to an undamaged component: {component_id}")
    final_destroyed = set(interim).union(to_component_ids)
    _ensure_intact_components_connected(final_destroyed, layout)
    player.ship.destroyed_components = final_destroyed
    for component_id in from_component_ids:
        player.ship.component_hit_counts.pop(component_id, None)
    for component_id in to_component_ids:
        player.ship.component_hit_counts[component_id] = max(1, player.ship.component_hit_counts.get(component_id, 0))
    player.ship.destroyed = layout.is_ship_destroyed(player.ship.destroyed_components)
    return {"from": list(from_component_ids), "to": list(to_component_ids)}


def _ensure_unique_component_ids(component_ids: tuple[str, ...], layout: ShipLayout) -> None:
    if len(set(component_ids)) != len(component_ids):
        raise RulesError("Component selections must not contain duplicates.")
    unknown = [component_id for component_id in component_ids if component_id not in layout.component_by_id]
    if unknown:
        raise RulesError(f"Unknown ship component: {unknown[0]}")


def _component_adjacent_to_intact(component_id: str, destroyed_components: set[str], layout: ShipLayout) -> bool:
    component = layout.component_by_id[component_id]
    for other in layout.components:
        if other.id in destroyed_components:
            continue
        if hex_distance(component.q, component.r, other.q, other.r) == 1:
            return True
    return False


def _ensure_intact_components_connected(destroyed_components: set[str], layout: ShipLayout) -> None:
    if layout.detached_component_ids(destroyed_components):
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

    if stack.seal_mode == SealMode.OVERDRIVE and not _overdrive_exempt_by_expansion(state, player, stack):
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

        star_breach = _active_expansion_module(state, STAR_BREACH_ID)
        if star_breach is not None:
            if star_breach.resolve_attacker(state, action_number, stack, attacker, attack_cards):
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
    # Designed-ship passives: intact Targeting Sensors sharpen the attacker's
    # aim; intact Signal Jammers on the target raise its defense threshold.
    sensor_aim_bonus = TARGETING_SENSORS_AIM_BONUS * layout_for_ship(attacker.ship).intact_count_of_type(
        TARGETING_SENSORS_TYPE, attacker.ship.destroyed_components
    )
    aim_bonus += sensor_aim_bonus
    jammer_defense_bonus = SIGNAL_JAMMER_DEFENSE_BONUS * layout_for_ship(target.ship).intact_count_of_type(
        SIGNAL_JAMMER_TYPE, target.ship.destroyed_components
    )
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
        else distance + target_movement + target.ship.defense_bonus_this_action + jammer_defense_bonus
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
        "sensor_aim_bonus": sensor_aim_bonus,
        "jammer_defense_bonus": jammer_defense_bonus,
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
    layout = layout_for_ship(target.ship)

    for shot_number in range(1, damage + 1):
        lane_roll = fixed_lane_roll if fixed_lane_roll is not None else _roll_d12(state)
        component = layout.first_intact_component_for_lane(lane_roll, target.ship.destroyed_components)
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
            detached_ids = sorted(layout.detached_component_ids(target.ship.destroyed_components))
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
            target.ship.destroyed = layout.is_ship_destroyed(target.ship.destroyed_components)
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
    star_breach = _active_expansion_module(state, STAR_BREACH_ID)
    if star_breach is not None:
        star_breach.before_award_baubles(state)
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
            elif star_breach is not None and star_breach.bauble_awarded(state, player, award):
                for crew_member in state.players.values():
                    if not crew_member.eliminated:
                        crew_member.bonus_draws_pending += 1
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
    if star_breach is not None:
        star_breach.after_award_baubles(state)
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
        bonus_draws_pending = player.bonus_draws_pending
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
                    "bonus_draws": bonus_draws_pending,
                }
            )
    state.event_log.append(
        {
            "type": "round_advanced",
            "round": state.round_number,
            "starting_player_id": state.starting_player_id,
        }
    )
    for module in _active_expansion_modules(state):
        activate_round = getattr(module, "activate_round", None)
        if activate_round is not None:
            activate_round(state)
    _reveal_starfall_for_round(state)
    _change_phase(state, GamePhase.GIVE_ORDERS)


def _move_resolved_order_cards(state: GameState, player: PlayerState) -> None:
    assert player.prepared_orders is not None
    for stack in player.prepared_orders.stacks:
        _move_resolved_stack_cards(state, player, stack.action_number, stack)


def _round_completion_result(state: GameState) -> GameResult | None:
    star_breach = _active_expansion_module(state, STAR_BREACH_ID)
    if star_breach is not None:
        return star_breach.game_result(state, final_round_complete=state.round_number >= 6)
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
        _validate_engineering_selection(player, selection, effect, stack)
        if effective_family == CardFamily.MOVE:
            move_choice = _normalize_move_choice(selection.orientation)
            if move_choice not in _card_orientation_options(card, selection):
                raise RulesError(f"Move choice {move_choice} is not valid for card {card.id}.")
        if effective_family == CardFamily.ATTACK and selection.target_player_id:
            star_breach = _active_expansion_module(state, STAR_BREACH_ID)
            if star_breach is not None:
                star_breach.validate_target(state, player, selection.target_player_id)
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


def _validate_engineering_selection(player: PlayerState, selection: OrderCardSelection, effect, stack: ActionStack) -> None:
    layout = layout_for_ship(player.ship)
    if effect.repair_components:
        count = _engineering_component_count(effect.repair_components, stack)
        ids = selection.repair_component_ids
        if len(ids) != count:
            raise RulesError(f"Hull Repair must select {count} damaged component(s).")
        _ensure_unique_component_ids(ids, layout)
        destroyed = set(player.ship.destroyed_components)
        for component_id in ids:
            if component_id not in destroyed:
                raise RulesError(f"Hull Repair component is not damaged: {component_id}")
        final_destroyed = destroyed - set(ids)
        _ensure_intact_components_connected(final_destroyed, layout)
    if effect.reconfigure_components:
        _reconfigure_components_preview(
            player,
            selection.reconfigure_from_component_ids,
            selection.reconfigure_to_component_ids,
            _engineering_component_count(effect.reconfigure_components, stack),
        )


def _reconfigure_components_preview(
    player: PlayerState,
    from_component_ids: tuple[str, ...],
    to_component_ids: tuple[str, ...],
    count: int,
) -> None:
    if len(from_component_ids) != count or len(to_component_ids) != count:
        raise RulesError(f"Reconfigure must move exactly {count} damage marker(s).")
    layout = layout_for_ship(player.ship)
    _ensure_unique_component_ids(from_component_ids, layout)
    _ensure_unique_component_ids(to_component_ids, layout)
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
        if not _component_adjacent_to_intact(component_id, interim, layout):
            raise RulesError(f"Reconfigure destination is not adjacent to an undamaged component: {component_id}")
    _ensure_intact_components_connected(set(interim).union(to_component_ids), layout)


def _star_command_enabled(state: GameState) -> bool:
    return expansion_module(STAR_COMMAND_ID).enabled(state)


def _initialize_star_command(state: GameState) -> None:
    expansion_module(STAR_COMMAND_ID).initialize(state)


def _captain_choice_pending(state: GameState, player_id: str) -> bool:
    return expansion_module(STAR_COMMAND_ID).captain_choice_pending(state, player_id)


def _any_captain_choice_pending(state: GameState) -> bool:
    return expansion_module(STAR_COMMAND_ID).any_captain_choice_pending(state)


def _apply_captain_setup(player: PlayerState) -> None:
    expansion_module(STAR_COMMAND_ID).apply_captain_setup(player)


def _reveal_starfall_for_round(state: GameState) -> None:
    expansion_module(STAR_COMMAND_ID).reveal_starfall_for_round(state)


def _active_starfall(state: GameState, starfall_id: str) -> bool:
    return expansion_module(STAR_COMMAND_ID).active_starfall(state, starfall_id)


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
    expansion_module(STAR_COMMAND_ID).cleanup_start(state)


def _bauble_open_this_round(state: GameState, bauble) -> bool:
    if _star_command_enabled(state):
        return expansion_module(STAR_COMMAND_ID).bauble_open_this_round(state, bauble)
    return bauble.is_fang or bauble.number == state.round_number


def _starfall_hit_bonus_vp(state: GameState, attacker_id: str, action_number: int) -> int:
    if not _star_command_enabled(state):
        return 0
    return expansion_module(STAR_COMMAND_ID).starfall_hit_bonus_vp(state, attacker_id, action_number)


def _apply_starfall_hit_desperation(state: GameState, attacker: PlayerState) -> None:
    if _star_command_enabled(state):
        expansion_module(STAR_COMMAND_ID).apply_starfall_hit_desperation(state, attacker)


def _apply_component_destroyed_captain_effects(state: GameState, target: PlayerState, component_type: str) -> None:
    if _star_command_enabled(state):
        expansion_module(STAR_COMMAND_ID).apply_component_destroyed_captain_effects(state, target, component_type)


# ---------------------------------------------------------------------------
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
