from __future__ import annotations

from starshot.rules.engine import (
    RulesError,
    _active_starfall,
    _apply_unshielded_damage,
    _attack_cards_for_stack,
    _card_effect,
    _change_phase,
    _component_adjacent_to_intact,
    _fang,
    _make_rng,
    _overdrive_copies_action,
    _overdrive_desperation_enabled,
    _roll_attack,
    _selected_card_family,
    _ship_in_facing_cone_120,
)
from starshot.rules.baubles import ship_inside_bauble
from starshot.rules.decks import card_by_id
from starshot.rules.models import ActionStack, Card, CardFamily, FleetCraftState, GamePhase, GameResult, GameState, OrderCardSelection, PlayerState, SealMode, ShipState, StarBreachState
from starshot.rules import star_breach as sb_data
from starshot.rules.star_breach import EXPANSION_ID
from starshot.rules.desperation import draw_desperation_card
from starshot.rules.hex import BOARD_RADIUS, DIRECTIONS, START_INSET_FROM_CORNER, clamp_to_board, hex_distance, is_within_board, move_forward
from starshot.rules.ship_layout import BASE_SHIP_COMPONENTS, is_ship_destroyed

# This module owns StarBreach behavior that plugs into the base StarShot engine.


_STAR_BREACH_START_DIRECTIONS = (5, 3, 0, 4)


def starting_ship(index: int) -> ShipState:
    return _starting_ship_star_breach(index)


def assign_roles(players: dict[str, PlayerState]) -> None:
    _assign_star_breach_roles(players)


def initialize(state: GameState) -> None:
    _initialize_star_breach(state)


def game_result(state: GameState, *, final_round_complete: bool) -> GameResult | None:
    return _star_breach_result(state, final_round_complete=final_round_complete)


def before_player_action(state: GameState, action_number: int) -> None:
    _resolve_boss_phase(state, sb_data.BOSS_PHASES_BY_PLAYER_ACTION[action_number])
    if state.star_breach is not None:
        state.star_breach.repaired_ship_ids_this_action = []


def before_award_baubles(state: GameState) -> None:
    _resolve_boss_phase(state, "3.5")
    if state.phase == GamePhase.COMPLETE:
        return
    _resolve_boss_phase(state, "starbreach")


def bauble_awarded(state: GameState, player: PlayerState, award: dict) -> bool:
    if "treasure_hunter" not in player.roles:
        return False
    award["treasure_hunter_bonus_draw"] = True
    return True


def after_award_baubles(state: GameState) -> None:
    _check_star_breach_defeat(state)


def activate_round(state: GameState) -> None:
    _activate_star_breach_tiers(state)


def overdrive_exempt(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    return _star_breach_overdrive_exempt(state, player, stack)


def validate_target(state: GameState, player: PlayerState, target: str) -> None:
    _validate_star_breach_target(state, player, target)


def resolve_attacker(
    state: GameState,
    action_number: int,
    stack: ActionStack,
    attacker: PlayerState,
    attack_cards: list[tuple[Card, OrderCardSelection]],
) -> bool:
    return _resolve_star_breach_attacker(state, action_number, stack, attacker, attack_cards)


def _starting_ship_star_breach(index: int) -> ShipState:
    direction = _STAR_BREACH_START_DIRECTIONS[index]
    distance = BOARD_RADIUS - START_INSET_FROM_CORNER
    dq, dr = DIRECTIONS[direction]
    return ShipState(q=dq * distance, r=dr * distance, facing=(direction + 3) % 6)


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
            "expansion_id": EXPANSION_ID,
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
    from starshot.rules import engine as base

    return base._roll_d8(state)


def _roll_d8_impl(state: GameState) -> int:
    rng = _make_rng(state)
    value = rng.randint(1, 8)
    state.rng_step += 1
    return value


def _roll_d6_sum(state: GameState, dice: int) -> int:
    from starshot.rules import engine as base

    return base._roll_d6_sum(state, dice)


def _roll_d6_sum_impl(state: GameState, dice: int) -> int:
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


