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
from starshot.rules.vaults import VAULT_RADIUS, ship_inside_vault
from starshot.rules.decks import card_by_id
from starshot.rules.models import ActionStack, Card, CardFamily, FleetCraftState, GameConfig, GamePhase, GameResult, GameState, OrderCardSelection, PlayerState, SealMode, ShipState, StarBreachState
from starshot.rules import star_breach as sb_data
from starshot.rules import star_breach_spec as sb_spec
from starshot.rules.star_breach import EXPANSION_ID
from starshot.rules.desperation import draw_desperation_card
from starshot.rules.hex import BOARD_RADIUS, DIRECTIONS, START_INSET_FROM_CORNER, hex_distance, is_within_board, move_forward
from starshot.rules.ship_layout import layout_for_ship
from starshot.rules.player_ships import (
    SIGNAL_JAMMER_DEFENSE_BONUS,
    SIGNAL_JAMMER_TYPE,
    TARGETING_SENSORS_AIM_BONUS,
    TARGETING_SENSORS_TYPE,
)


def _sensor_aim_bonus(attacker: PlayerState) -> int:
    """Designed-ship Aim passives: +2 per intact legacy Targeting Sensors
    plus the flat StarDock "aim" upgrade bonus."""
    layout = layout_for_ship(attacker.ship)
    return layout.aim_bonus + TARGETING_SENSORS_AIM_BONUS * layout.intact_count_of_type(
        TARGETING_SENSORS_TYPE, attacker.ship.destroyed_components
    )


def _jammer_defense_bonus(target: PlayerState) -> int:
    """Designed-ship defense passives: +2 per intact legacy Signal Jammer
    plus the flat StarDock "defense" upgrade bonus."""
    layout = layout_for_ship(target.ship)
    return layout.defense_bonus + SIGNAL_JAMMER_DEFENSE_BONUS * layout.intact_count_of_type(
        SIGNAL_JAMMER_TYPE, target.ship.destroyed_components
    )

# This module owns StarBreach behavior that plugs into the base StarShot engine.


_STAR_BREACH_START_DIRECTIONS = (5, 3, 0, 4)


def starting_ship(index: int) -> ShipState:
    return _starting_ship_star_breach(index)


def assign_roles(players: dict[str, PlayerState], preferences: dict | None = None) -> None:
    _assign_star_breach_roles(players, preferences)


def initialize(state: GameState, config: GameConfig | None = None) -> None:
    _initialize_star_breach(state, config)


def game_result(state: GameState, *, final_round_complete: bool) -> GameResult | None:
    return _star_breach_result(state, final_round_complete=final_round_complete)


def before_player_action(state: GameState, action_number: int) -> None:
    _resolve_boss_phase(state, sb_data.BOSS_PHASES_BY_PLAYER_ACTION[action_number])
    if state.star_breach is not None:
        state.star_breach.repaired_ship_ids_this_action = []
        state.star_breach.progressed_source_ids_this_action = []


def before_award_vaults(state: GameState) -> None:
    if state.star_breach is not None:
        state.star_breach.progressed_source_ids_this_action = []
    _resolve_boss_phase(state, "3.5")
    if state.phase == GamePhase.COMPLETE:
        return
    _resolve_boss_phase(state, "starbreach")


def vault_awarded(state: GameState, player: PlayerState, award: dict) -> bool:
    # Dynamic enemy AI reacts to bauble grabs: hunt the collector.
    _dynamic_directive_switch(state, player, "bauble_pickup")
    if "vault_runner" not in player.roles:
        return False
    award["vault_runner_bonus_draw"] = True
    return True


def after_award_vaults(state: GameState) -> None:
    _check_star_breach_defeat(state)
    _check_star_breach_victory(state)


def activate_round(state: GameState) -> None:
    _activate_star_breach_tiers(state)
    sb = state.star_breach
    if sb is not None:
        # Round-scoped Super effects wear off when a new round begins.
        sb.immobilized_player_ids = []
        sb.marked_player_ids = []


def overdrive_exempt(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    return _star_breach_overdrive_exempt(state, player, stack)


def move_distance_multiplier(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    selection: OrderCardSelection,
    card: Card,
    *,
    overdrive_copy: bool,
) -> int:
    return _star_breach_move_distance_multiplier(state, player, stack, selection, card, overdrive_copy=overdrive_copy)


def move_defense_distance(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    selection: OrderCardSelection,
    card: Card,
    distance: int,
    *,
    overdrive_copy: bool,
) -> int:
    if state.star_breach is not None and "vault_runner" in player.roles:
        return 0
    return distance


def adjust_player_action_landing(
    state: GameState,
    player: PlayerState,
    movement_path: list[tuple[int, int]],
) -> dict | None:
    _detonate_mines(state, player, movement_path)
    if state.phase == GamePhase.COMPLETE:
        return None
    return _adjust_player_action_landing(state, player, movement_path)


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


def _assign_star_breach_roles(players: dict[str, PlayerState], preferences: dict | None = None) -> None:
    """Deal the four roles so every role ability is in play. Players who
    requested a role get it first (first seat wins a conflict); leftover
    roles go round-robin to whoever holds the fewest, in seat order."""
    player_list = list(players.values())
    assigned: dict[str, list[str]] = {player.id: [] for player in player_list}
    taken: set[str] = set()
    for player in player_list:
        wanted = (preferences or {}).get(player.id)
        if wanted in sb_data.ROLES_BY_ID and wanted not in taken:
            assigned[player.id].append(wanted)
            taken.add(wanted)
    for role_id in sb_data.ROLE_ASSIGN_ORDER:
        if role_id in taken:
            continue
        target = min(range(len(player_list)), key=lambda index: (len(assigned[player_list[index].id]), index))
        assigned[player_list[target].id].append(role_id)
    for player in player_list:
        player.roles = tuple(assigned[player.id])
        if "tank" in player.roles:
            player.ship.shields += 1


def _initialize_star_breach(state: GameState, config: GameConfig | None = None) -> None:
    nose_q, nose_r = sb_data.BOSS_START
    design = config.star_breach_boss_design if config is not None else None
    boss_spec = sb_spec.spec_from_design(design) if design else None
    spec = boss_spec or sb_spec.default_spec()
    fleet = [
        FleetCraftState(
            id=craft["id"],
            kind=craft["kind"],
            color=craft["color"],
            q=nose_q + craft["offset"][0],
            r=nose_r + craft["offset"][1],
            hp=craft["hp"],
            max_hp=craft["hp"],
        )
        for craft in spec["fleet"]
    ]
    requested_prey = config.star_breach_prey_player_id if config is not None else None
    prey_player_id = requested_prey if requested_prey in state.players else next(iter(state.players))
    scenario_id = f"design:{design['id']}" if design else sb_data.SCENARIO_ID
    state.star_breach = StarBreachState(
        scenario_id=scenario_id,
        prey_player_id=prey_player_id,
        anchor_q=nose_q,
        anchor_r=nose_r,
        facing=sb_data.BOSS_START_FACING,
        shield_hp=dict(spec["initial_shield_hp"]),
        fleet=fleet,
        boss_spec=boss_spec,
    )
    state.event_log.append(
        {
            "type": "expansion_enabled",
            "round": state.round_number,
            "expansion_id": EXPANSION_ID,
            "scenario_id": scenario_id,
            "boss_name": spec["name"],
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


def _player_vault_captures(state: GameState) -> int:
    """Total vault captures by the crew (each player's claim counts once)."""
    return sum(
        sum(1 for claimant in vault.claimed_by if claimant != "starbreacher")
        for vault in state.vaults
        if not vault.is_fang
    )


def _goal_reached(state: GameState) -> bool:
    """Whether an immediate-win goal (vault haul / fleet wipe) is satisfied."""
    sb = state.star_breach
    goal = sb_spec.boss_goal(sb_spec.spec_for(sb))
    if goal["kind"] == "capture_vaults":
        return _player_vault_captures(state) >= int(goal.get("count", 8))
    if goal["kind"] == "destroy_fleet":
        return bool(sb.fleet) and all(craft.destroyed for craft in sb.fleet)
    return False


def _star_breach_result(state: GameState, *, final_round_complete: bool) -> GameResult | None:
    sb = state.star_breach
    assert sb is not None
    prey = state.players.get(sb.prey_player_id)
    if prey is None or prey.eliminated or prey.ship.destroyed:
        return GameResult(winner_ids=(), reason="star_breach_prey_destroyed")
    goal = sb_spec.boss_goal(sb_spec.spec_for(sb))
    if goal["kind"] != "escape_fang" and _goal_reached(state):
        return GameResult(winner_ids=tuple(state.players), reason="star_breach_victory")
    if final_round_complete:
        if goal["kind"] == "escape_fang":
            fang = _fang(state)
            if fang is not None and ship_inside_vault(prey.ship, fang):
                return GameResult(winner_ids=tuple(state.players), reason="star_breach_victory")
        return GameResult(winner_ids=(), reason="star_breach_objective_failed")
    return None


def _check_star_breach_victory(state: GameState) -> None:
    """Immediate-win goals complete the game the moment they are met."""
    if state.star_breach is None or state.result is not None:
        return
    if _goal_reached(state):
        state.result = GameResult(winner_ids=tuple(state.players), reason="star_breach_victory")
        _change_phase(state, GamePhase.COMPLETE)


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
    unlocked = sb_spec.unlocked_tiers(sb_spec.spec_for(sb), sb.progress)
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


_SPAWN_COLORS = ("red", "purple", "orange", "blue", "green", "yellow")


def _spawn_anchor_hex(state: GameState, location: str) -> tuple[int, int]:
    """Board hex a spawn clusters around: directly in front of the boss nose,
    the current round's vault, or The Fang."""
    sb = state.star_breach
    assert sb is not None
    if location == "vault":
        for vault in state.vaults:
            if not vault.is_fang and vault.number == min(state.round_number, 5):
                return (vault.q, vault.r)
    elif location == "fang":
        fang = _fang(state)
        if fang is not None:
            return (fang.q, fang.r)
    dq, dr = DIRECTIONS[sb.facing % 6]
    return (sb.anchor_q + dq, sb.anchor_r + dr)


def _nearest_free_hexes(state: GameState, center: tuple[int, int], count: int) -> list[tuple[int, int]]:
    """The `count` on-board unoccupied hexes nearest to `center` (spiral out)."""
    sb = state.star_breach
    assert sb is not None
    occupied = _occupied_ship_hexes(state) | set(_boss_token_hexes(sb))
    found: list[tuple[int, int]] = []
    for radius in range(0, BOARD_RADIUS * 2 + 1):
        ring: list[tuple[int, int]] = []
        cq, cr = center
        if radius == 0:
            ring = [(cq, cr)]
        else:
            q, r = cq + DIRECTIONS[4][0] * radius, cr + DIRECTIONS[4][1] * radius
            for direction in range(6):
                for _ in range(radius):
                    ring.append((q, r))
                    q, r = q + DIRECTIONS[direction][0], r + DIRECTIONS[direction][1]
        for q, r in ring:
            if is_within_board(q, r) and (q, r) not in occupied and (q, r) not in found:
                found.append((q, r))
                if len(found) >= count:
                    return found
    return found


def _spawn_fleet_craft(state: GameState, tier: int | str, spawn: dict) -> dict:
    """A spawn_fleet progression step: new craft join the boss's fleet."""
    sb = state.star_breach
    assert sb is not None
    center = _spawn_anchor_hex(state, spawn.get("location", "boss_front"))
    positions = _nearest_free_hexes(state, center, int(spawn.get("count", 1)))
    spawned = []
    for index, (q, r) in enumerate(positions):
        color = _SPAWN_COLORS[(len(sb.fleet) + index) % len(_SPAWN_COLORS)]
        craft = FleetCraftState(
            id=f"spawn_t{tier}_{index + 1}",
            kind=spawn.get("kind", "hunter_killer"),
            color=color,
            q=q,
            r=r,
            hp=int(spawn.get("hp", sb_data.HUNTER_KILLER_HP)),
            max_hp=int(spawn.get("hp", sb_data.HUNTER_KILLER_HP)),
        )
        sb.fleet.append(craft)
        spawned.append(
            {"id": craft.id, "kind": craft.kind, "color": craft.color, "q": craft.q, "r": craft.r, "hp": craft.hp}
        )
    state.event_log.append(
        {
            "type": "boss_fleet_spawned",
            "round": state.round_number,
            "tier": tier,
            "location": spawn.get("location", "boss_front"),
            "craft": spawned,
        }
    )
    return {"spawned": spawned, "location": spawn.get("location", "boss_front")}


def _star_breach_overdrive_exempt(state: GameState, player: PlayerState, stack: ActionStack) -> bool:
    if state.star_breach is None or not stack.cards:
        return False
    families = {
        _selected_card_family(card_by_id(selection.card_id), selection)
        for selection in stack.cards
    }
    if "fighting_ace" in player.roles and families == {CardFamily.ATTACK}:
        return True
    return False


def _star_breach_move_distance_multiplier(
    state: GameState,
    player: PlayerState,
    stack: ActionStack,
    selection: OrderCardSelection,
    card: Card,
    *,
    overdrive_copy: bool,
) -> int:
    if state.star_breach is None:
        return 1
    if player.id in state.star_breach.immobilized_player_ids:
        return 0  # Immobilizer Shot: movement cancelled for the rest of the round
    if "vault_runner" not in player.roles or overdrive_copy:
        return 1
    effect = _card_effect(card, selection, stack.seal_mode)
    if effect.family == CardFamily.MOVE and effect.move is not None and not effect.is_desperate_face:
        return 2
    return 1


def _validate_star_breach_target(state: GameState, player: PlayerState, target: str) -> None:
    sb = state.star_breach
    assert sb is not None
    if target.startswith("boss:"):
        area = target.split(":", 1)[1]
        if area not in sb_spec.spec_for(sb)["areas"]:
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
    return len(sb.destroyed_hexes) < sb_spec.hull_size(sb_spec.spec_for(sb))


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


def _boss_ai(sb: StarBreachState) -> str:
    return sb_spec.boss_ai(sb_spec.spec_for(sb))


def _fleet_ai(sb: StarBreachState) -> str:
    return sb_spec.fleet_ai(sb_spec.spec_for(sb))


def _living_prey(state: GameState) -> PlayerState | None:
    prey = state.players.get(state.star_breach.prey_player_id)
    if prey is not None and not prey.eliminated and not prey.ship.destroyed:
        return prey
    return None


def _nearest_living_player(state: GameState, distance_to: callable) -> PlayerState | None:
    living = _living_players(state)
    if not living:
        return None
    return min(living, key=lambda player: (distance_to(player) or 10**6, player.id))


def _directive_player(state: GameState, scope: str) -> PlayerState | None:
    """The dynamic AI's current hunt target, if it is still in the fight."""
    sb = state.star_breach
    target_id = sb.boss_ai_target_id if scope == "boss" else sb.fleet_ai_target_id
    player = state.players.get(target_id) if target_id else None
    if player is not None and not player.eliminated and not player.ship.destroyed:
        return player
    return None


def _primary_enemy_target(state: GameState, distance_to: callable, scope: str) -> PlayerState | None:
    """AI-program targeting, before the Tank's Proximity Jammer redirect."""
    sb = state.star_breach
    ai = _boss_ai(sb) if scope == "boss" else _fleet_ai(sb)
    if ai == "dynamic":
        directive = _directive_player(state, scope)
        if directive is not None:
            return directive
    if ai in ("blaster", "vault_runner"):
        return _nearest_living_player(state, distance_to)
    return _living_prey(state) or _nearest_living_player(state, distance_to)


def _enemy_pick_target(state: GameState, distance_to: callable, *, scope: str = "boss") -> PlayerState | None:
    """Enemy attack targeting: the AI program picks a primary target, then
    the Tank's Proximity Jammer applies — if the target is within 3 hexes of
    the Tank, the Tank steps in and takes the hit instead."""
    sb = state.star_breach
    assert sb is not None
    primary = _primary_enemy_target(state, distance_to, scope)
    if primary is None:
        return None
    tank = _player_with_role(state, "tank")
    if (
        tank is not None
        and tank.id != primary.id
        and not tank.eliminated
        and not tank.ship.destroyed
        and hex_distance(tank.ship.q, tank.ship.r, primary.ship.q, primary.ship.r) <= sb_data.TANK_PROXIMITY_JAMMER_RANGE
    ):
        return tank
    return primary


def _enemy_move_target(state: GameState, distance_to: callable, scope: str) -> PlayerState | None:
    """Pursuit targeting: the jammer redirects attacks, not movement."""
    return _primary_enemy_target(state, distance_to, scope)


def _dynamic_directive_switch(
    state: GameState,
    player: PlayerState | None,
    reason: str,
    scopes: tuple[str, ...] = ("boss", "fleet"),
) -> None:
    """Dynamic AI programs react to player activity — hitting the enemy,
    healing, grabbing a bauble, or opening a damage lane to a Core — by
    hunting that player. Each program may switch at most once per round."""
    sb = state.star_breach
    if sb is None or state.result is not None or player is None:
        return
    if player.eliminated or player.ship.destroyed:
        return
    for scope in scopes:
        ai = _boss_ai(sb) if scope == "boss" else _fleet_ai(sb)
        if ai != "dynamic":
            continue
        current = sb.boss_ai_target_id if scope == "boss" else sb.fleet_ai_target_id
        switch_round = sb.boss_ai_switch_round if scope == "boss" else sb.fleet_ai_switch_round
        if current == player.id or switch_round >= state.round_number:
            continue
        if scope == "boss":
            sb.boss_ai_target_id = player.id
            sb.boss_ai_switch_round = state.round_number
        else:
            sb.fleet_ai_target_id = player.id
            sb.fleet_ai_switch_round = state.round_number
        state.event_log.append(
            {
                "type": "boss_directive_changed",
                "round": state.round_number,
                "scope": scope,
                "target_id": player.id,
                "reason": reason,
            }
        )


def _roll_d8(state: GameState) -> int:
    from starshot.rules import engine as base

    return base._roll_d8(state)


def _roll_d8_impl(state: GameState) -> int:
    rng = _make_rng(state)
    value = rng.randint(1, 8)
    state.rng_step += 1
    return value


def _roll_lane_die(state: GameState, sides: int) -> int:
    """Damage-lane roll for a shield area. Areas with the classic 7 lanes go
    through the shared d8 path (kept for test stubs and replay parity);
    larger regions roll their own (lane_count + 1)-sided die."""
    if sides == 8:
        return _roll_d8(state)
    rng = _make_rng(state)
    value = rng.randint(1, max(2, sides))
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
    # Tiers reached mid-round only power slots from the start of the next round.
    return [
        dict(slot)
        for slot in sb_spec.active_phase_slots(
            sb_spec.spec_for(sb),
            phase_key,
            sb.destroyed_hexes,
            set(sb.active_tiers),
            state.round_number,
        )
    ]


def _resolve_boss_phase(state: GameState, phase_key: str) -> None:
    sb = state.star_breach
    if sb is None or state.result is not None:
        return
    sb.progressed_source_ids_this_action = []
    sb.boss_movement_this_action = 0
    for craft in sb.fleet:
        craft.movement_this_action = 0

    spec = sb_spec.spec_for(sb)
    kind = sb_spec.phase_kind(spec, phase_key)
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
    # movement. Designed bosses may mix kinds within one stack, so slots can
    # carry their own kind; stock slots fall back to the phase kind.
    for slot in active_slots:
        entry = dict(slot)
        entry["amount"] = 1
        slot_kind = slot.get("kind", kind)
        if slot_kind == "move":
            entry["movement"] = _move_boss(state, 1, phase_key)
        elif slot_kind == "super":
            entry["super"] = _fire_super_slot(state, slot, phase_key)
        elif slot_kind == "spawn":
            spawn = slot.get("spawn") or {
                "count": 1,
                "location": "boss_front",
                "kind": "hunter_killer",
                "hp": sb_data.HUNTER_KILLER_HP,
            }
            entry["spawn"] = _spawn_fleet_craft(state, slot.get("tier", slot.get("component_id", "docking_bay")), spawn)
        else:
            entry["attacks"] = [_boss_attack(state)]
        slot_results.append(entry)
        _check_star_breach_defeat(state)
        if state.phase == GamePhase.COMPLETE:
            break

    craft_results: list[dict] = []
    if state.phase != GamePhase.COMPLETE:
        for craft_kind in sb_spec.fleet_action_kinds(spec, phase_key):
            if state.phase == GamePhase.COMPLETE:
                break
            for craft in sb.fleet:
                if craft.destroyed:
                    continue
                if craft_kind == "move":
                    craft_results.append(_move_craft(state, craft, phase_key))
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


def _player_enemy_hexes(state: GameState) -> set[tuple[int, int]]:
    sb = state.star_breach
    assert sb is not None
    enemies = {
        (craft.q, craft.r)
        for craft in sb.fleet
        if not craft.destroyed
    }
    if _boss_active(sb):
        enemies.update(_boss_token_hexes(sb))
    return enemies


def _adjust_player_action_landing(
    state: GameState,
    player: PlayerState,
    movement_path: list[tuple[int, int]],
) -> dict | None:
    """StarBreach ships may pass through enemies, but cannot end an action
    exactly on an enemy ship."""
    if state.star_breach is None or not movement_path:
        return None
    if (player.ship.q, player.ship.r) not in _player_enemy_hexes(state):
        return None
    stop_q, stop_r = movement_path[-2] if len(movement_path) >= 2 else movement_path[0]
    if (stop_q, stop_r) == (player.ship.q, player.ship.r):
        return None
    attempted = {"q": player.ship.q, "r": player.ship.r}
    player.ship.q, player.ship.r = stop_q, stop_r
    return {
        "reason": "enemy_occupied_final_hex",
        "attempted": attempted,
        "stopped_at": {"q": stop_q, "r": stop_r},
    }


def _remaining_boss_move_slots(state: GameState, phase_key: str) -> int:
    """Move actions still ahead of the boss this round (this phase onward)."""
    sb = state.star_breach
    assert sb is not None
    spec = sb_spec.spec_for(sb)
    keys = [phase["key"] for phase in spec["phases"]]
    if phase_key not in keys:
        return 0
    remaining = 0
    for key in keys[keys.index(phase_key):]:
        default_kind = sb_spec.phase_kind(spec, key)
        for slot in sb_spec.active_phase_slots(
            spec, key, sb.destroyed_hexes, set(sb.active_tiers), state.round_number
        ):
            if slot.get("kind", default_kind) == "move":
                remaining += 1
    return remaining


def _remaining_fleet_move_hexes(state: GameState, phase_key: str) -> int:
    """Hexes of movement a fleet craft still has ahead of it this round."""
    sb = state.star_breach
    assert sb is not None
    spec = sb_spec.spec_for(sb)
    keys = [phase["key"] for phase in spec["phases"]]
    if phase_key not in keys:
        return 0
    actions = 0
    for key in keys[keys.index(phase_key):]:
        actions += sum(1 for kind in spec["fleet_actions"].get(key, ()) if kind == "move")
    return actions * int(spec["fleet_move"])


def _vault_goal_hex(state: GameState, distance_to_hex, reach: int) -> tuple[int, int] | None:
    """Vault Runner AI: harvest the current round's vault; if it is out of
    reach with this round's remaining movement (or already snatched), head
    for next round's vault instead. The Fang is never a target."""

    def vault_for(number: int):
        for vault in state.vaults:
            if not vault.is_fang and vault.number == number and "starbreacher" not in vault.claimed_by:
                return vault
        return None

    current = vault_for(min(state.round_number, 5))
    nxt = vault_for(min(state.round_number + 1, 5))
    if nxt is not None and current is not None and nxt.id == current.id:
        nxt = None
    if current is not None:
        needed = max(0, distance_to_hex(current.q, current.r) - VAULT_RADIUS)
        if needed <= reach or nxt is None:
            return (current.q, current.r)
    if nxt is not None:
        return (nxt.q, nxt.r)
    return None


def _move_boss(state: GameState, steps: int, phase_key: str) -> dict:
    """Move the boss token per its AI program. The nose leads: facing becomes
    the direction of the last hex moved. The boss token can share a hex with
    other ships; it does not push them."""
    sb = state.star_breach
    assert sb is not None
    before = {"anchor_q": sb.anchor_q, "anchor_r": sb.anchor_r, "facing": sb.facing}
    moved = 0
    goal: tuple[int, int] | None = None
    goal_is_vault = False
    if _boss_ai(sb) == "vault_runner":
        goal = _vault_goal_hex(
            state,
            lambda q, r: hex_distance(sb.anchor_q, sb.anchor_r, q, r),
            _remaining_boss_move_slots(state, phase_key),
        )
        goal_is_vault = goal is not None
    if goal is None:
        target = _enemy_move_target(
            state, lambda player: _boss_distance_to(sb, player.ship.q, player.ship.r), "boss"
        )
        if target is None:
            return {"before": before, "after": dict(before), "moved": 0}
        goal = (target.ship.q, target.ship.r)

    for _ in range(steps):
        if goal_is_vault:
            if hex_distance(sb.anchor_q, sb.anchor_r, goal[0], goal[1]) <= VAULT_RADIUS:
                break
        else:
            current = _boss_distance_to(sb, goal[0], goal[1])
            if current is None or current <= 1:
                break
        # The nose leads: steer by nose distance (the flanks trail behind and
        # would otherwise stall the strict-improvement check). Prefer holding
        # the current heading on ties.
        best_direction = None
        best_distance = hex_distance(sb.anchor_q, sb.anchor_r, goal[0], goal[1])
        for direction in ((sb.facing + offset) % 6 for offset in range(6)):
            dq, dr = move_forward(0, 0, direction, 1)
            candidate_hexes = sb_data.boss_board_hexes(sb.anchor_q + dq, sb.anchor_r + dr, direction)
            if any(not is_within_board(hex_q, hex_r) for hex_q, hex_r in candidate_hexes):
                continue
            candidate = hex_distance(sb.anchor_q + dq, sb.anchor_r + dr, goal[0], goal[1])
            if candidate < best_distance:
                best_distance = candidate
                best_direction = direction
        if best_direction is None:
            break
        dq, dr = move_forward(0, 0, best_direction, 1)
        next_hexes = sb_data.boss_board_hexes(sb.anchor_q + dq, sb.anchor_r + dr, best_direction)
        player_hexes = {
            (player.ship.q, player.ship.r)
            for player in state.players.values()
            if not player.eliminated and not player.ship.destroyed
        }
        if any(hex_ in player_hexes for hex_ in next_hexes):
            break
        sb.anchor_q += dq
        sb.anchor_r += dr
        sb.facing = best_direction
        moved += 1
        sb.boss_movement_this_action += 1
        _collect_enemy_vaults(state, "boss", _boss_token_hexes(sb), label="starbreacher")
    return {
        "before": before,
        "after": {"anchor_q": sb.anchor_q, "anchor_r": sb.anchor_r, "facing": sb.facing},
        "moved": moved,
    }


def _move_craft(state: GameState, craft: FleetCraftState, phase_key: str = "1.5") -> dict:
    """Fleet craft movement per the fleet AI program, never overshooting."""
    sb = state.star_breach
    assert sb is not None
    before = [craft.q, craft.r]
    goal: tuple[int, int] | None = None
    stop_at = 1
    if _fleet_ai(sb) == "vault_runner":
        goal = _vault_goal_hex(
            state,
            lambda q, r: hex_distance(craft.q, craft.r, q, r),
            _remaining_fleet_move_hexes(state, phase_key),
        )
        if goal is not None:
            stop_at = VAULT_RADIUS
    if goal is None:
        target = _enemy_move_target(
            state, lambda player: hex_distance(craft.q, craft.r, player.ship.q, player.ship.r), "fleet"
        )
        if target is None:
            return {"craft_id": craft.id, "before": before, "after": before, "moved": 0}
        goal = (target.ship.q, target.ship.r)
    boss_hexes = set(_boss_token_hexes(sb))
    moved = 0
    for _ in range(sb_spec.spec_for(sb)["fleet_move"]):
        distance = hex_distance(craft.q, craft.r, goal[0], goal[1])
        if distance <= stop_at:
            break
        occupied = _occupied_ship_hexes(state, ignore_craft_id=craft.id) | boss_hexes
        candidates = []
        for direction in range(6):
            q, r = move_forward(craft.q, craft.r, direction, 1)
            if not is_within_board(q, r) or (q, r) in occupied:
                continue
            candidates.append((hex_distance(q, r, goal[0], goal[1]), direction, q, r))
        if not candidates:
            break
        best = min(candidates)
        if best[0] >= distance:
            break
        craft.q, craft.r = best[2], best[3]
        craft.movement_this_action += 1
        moved += 1
    _collect_enemy_vaults(state, "fleet", ((craft.q, craft.r),), label=craft.id)
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
    sb = state.star_breach
    # Mark the Prey: -5 defense against enemy shots for the rest of the round.
    marked_penalty = 5 if sb is not None and target.id in sb.marked_player_ids else 0
    defense_threshold = (
        distance
        + target.ship.movement_this_action
        + target.ship.defense_bonus_this_action
        + _jammer_defense_bonus(target)
        - marked_penalty
    )
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
        "marked_penalty": marked_penalty,
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

    if sb is not None:
        triggers = sb_spec.progress_triggers(sb_spec.spec_for(sb))
        source_key = str(attacker_label)
        if triggers is None:
            # Stock scenario rules: hitting The Prey's shields or hull advances
            # once per enemy source per player action.
            if hit and target.id == sb.prey_player_id and source_key not in sb.progressed_source_ids_this_action:
                sb.progressed_source_ids_this_action.append(source_key)
                _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_HIT)
                if target.ship.destroyed:
                    _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_KILL - sb_data.PROGRESS_PER_PREY_HIT)
        else:
            # Designer-selected triggers: hull damage means damage got through.
            # Chain/Scatter Super shots ("starbreacher_*") count as the boss.
            source = "boss" if str(attacker_label).startswith("starbreacher") else "fleet"
            if (
                hit
                and target.id == sb.prey_player_id
                and event.get("damage_applied", 0) > 0
                and f"prey_hull_damage_{source}" in triggers
            ):
                _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_HIT)
            if hit and target.ship.destroyed and "player_kill" in triggers:
                _advance_boss_progress(state, sb_data.PROGRESS_PER_PREY_KILL)
    return event


def _advance_boss_progress(state: GameState, amount: int) -> None:
    sb = state.star_breach
    assert sb is not None
    spec = sb_spec.spec_for(sb)
    before_tiers = set(sb_spec.unlocked_tiers(spec, sb.progress))
    before_progress = sb.progress
    max_progress = sb_spec.max_progress(spec)
    sb.progress = min(max_progress, sb.progress + amount) if max_progress > 0 else sb.progress
    actual_amount = sb.progress - before_progress
    if actual_amount <= 0:
        return
    new_tiers = sorted(set(sb_spec.unlocked_tiers(spec, sb.progress)) - before_tiers)
    state.event_log.append(
        {
            "type": "boss_progress_advanced",
            "round": state.round_number,
            "amount": actual_amount,
            "progress": sb.progress,
            "tiers_unlocked": new_tiers,
        }
    )


def _collect_enemy_vaults(
    state: GameState, source: str, positions: tuple[tuple[int, int], ...], *, label: str
) -> None:
    """Enemies may snatch vaults: the boss token (or a fleet craft) covering
    a vault claims it once. Claiming advances the progress track only when
    the matching vault-pickup trigger is enabled; a Vault Runner AI harvests
    vaults even without the trigger. The Fang is never taken."""
    sb = state.star_breach
    assert sb is not None
    triggers = sb_spec.progress_triggers(sb_spec.spec_for(sb))
    trigger_on = triggers is not None and f"vault_pickup_{source}" in triggers
    ai = _boss_ai(sb) if source == "boss" else _fleet_ai(sb)
    if not trigger_on and ai != "vault_runner":
        return

    for vault in state.vaults:
        if vault.is_fang or "starbreacher" in vault.claimed_by:
            continue
        if any(
            hex_distance(q, r, vault.q, vault.r) <= VAULT_RADIUS for q, r in positions
        ):
            vault.claimed_by.append("starbreacher")
            state.event_log.append(
                {
                    "type": "boss_vault_pickup",
                    "round": state.round_number,
                    "source": source,
                    "collector": label,
                    "vault_id": vault.id,
                }
            )
            if trigger_on:
                _advance_boss_progress(state, 1)


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
        aim_bonus=sb_spec.boss_aim_bonus(
            sb_spec.spec_for(sb), sb.destroyed_hexes, set(sb.active_tiers)
        ),
    )


def _craft_attack(state: GameState, craft: FleetCraftState) -> dict:
    target = _enemy_pick_target(
        state,
        lambda player: hex_distance(craft.q, craft.r, player.ship.q, player.ship.r),
        scope="fleet",
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
        aim_bonus=sb_spec.spec_for(state.star_breach)["fleet_aim"],
    )
    event["craft_id"] = craft.id
    return event


# --- Boss Super effects -----------------------------------------------------
# Showpiece abilities synced to a Core. A Super occupies an action-stack slot
# like any other boss action and fires every round in its stack while its
# Core is alive and its round/progression requirement is met (the gate itself
# lives in sb_spec.slot_is_active).


SUPER_LABELS = {
    "immobilizer_shot": "Immobilizer Shot",
    "tractor_beam": "Tractor Beam",
    "knockback": "Knockback",
    "inferno_zone": "Inferno Zone",
    "infuser": "Infuser",
    "chain_shot": "Chain Shot",
    "scattershot": "ScatterShot",
    "mark_the_prey": "Mark the Prey",
    "mine_dropper": "Mine Dropper",
}


def _fire_super_slot(state: GameState, slot: dict, phase_key: str) -> dict:
    """Resolve one active Super slot: announce it, apply its effect."""
    sb = state.star_breach
    assert sb is not None
    name = SUPER_LABELS.get(slot["effect"], slot["effect"])
    state.event_log.append(
        {
            "type": "boss_super_activated",
            "round": state.round_number,
            "boss_phase": phase_key,
            "super_id": slot.get("super_id"),
            "effect": slot["effect"],
            "name": name,
            "core_hex": list(slot.get("core_hex") or ()) or None,
            "boss_position": {"q": sb.anchor_q, "r": sb.anchor_r, "facing": sb.facing},
        }
    )
    detail = _resolve_super_effect(state, slot["effect"])
    state.event_log.append(
        {
            "type": "boss_super_resolved",
            "round": state.round_number,
            "boss_phase": phase_key,
            "super_id": slot.get("super_id"),
            "effect": slot["effect"],
            "name": name,
            "detail": detail,
        }
    )
    return {"super_id": slot.get("super_id"), "effect": slot["effect"], "detail": detail}


def _resolve_super_effect(state: GameState, effect: str) -> dict:
    sb = state.star_breach
    assert sb is not None

    def boss_distance(player: PlayerState):
        return _boss_distance_to(sb, player.ship.q, player.ship.r)

    if effect == "immobilizer_shot":
        target = _enemy_pick_target(state, boss_distance)
        if target is None:
            return {"skipped": "no_target"}
        if target.id not in sb.immobilized_player_ids:
            sb.immobilized_player_ids.append(target.id)
        return {"target_id": target.id}
    if effect in ("tractor_beam", "knockback"):
        target = _enemy_pick_target(state, boss_distance)
        if target is None:
            return {"skipped": "no_target"}
        return _drag_player(state, target, 2, inward=effect == "tractor_beam")
    if effect == "inferno_zone":
        return _inferno_zone(state)
    if effect == "infuser":
        moves = []
        for _ in range(3):
            for craft in sb.fleet:
                if not craft.destroyed:
                    moves.append(_move_craft(state, craft, "starbreach"))
        return {"fleet_moves": moves}
    if effect == "chain_shot":
        return _chain_shot(state)
    if effect == "scattershot":
        return _scattershot(state)
    if effect == "mark_the_prey":
        target = _living_prey(state) or _enemy_pick_target(state, boss_distance)
        if target is None:
            return {"skipped": "no_target"}
        if target.id not in sb.marked_player_ids:
            sb.marked_player_ids.append(target.id)
        return {"target_id": target.id, "defense_penalty": 5}
    if effect == "mine_dropper":
        return _drop_mine(state)
    return {"skipped": "unknown_effect"}


def _drag_player(state: GameState, target: PlayerState, steps: int, *, inward: bool) -> dict:
    """Tractor Beam / Knockback: force the target along the line to the boss
    nose, one hex at a time, clamped to the board."""
    sb = state.star_breach
    assert sb is not None
    before = {"q": target.ship.q, "r": target.ship.r, "facing": target.ship.facing}
    moved = 0
    for _ in range(steps):
        distance = hex_distance(target.ship.q, target.ship.r, sb.anchor_q, sb.anchor_r)
        if inward and distance <= 1:
            break
        candidates = []
        for direction in range(6):
            q, r = move_forward(target.ship.q, target.ship.r, direction, 1)
            if not is_within_board(q, r):
                continue
            candidates.append((hex_distance(q, r, sb.anchor_q, sb.anchor_r), q, r))
        if not candidates:
            break
        best = min(candidates) if inward else max(candidates)
        if (inward and best[0] >= distance) or (not inward and best[0] <= distance):
            break
        target.ship.q, target.ship.r = best[1], best[2]
        moved += 1
    return {
        "target_id": target.id,
        "before": before,
        "after": {"q": target.ship.q, "r": target.ship.r, "facing": target.ship.facing},
        "moved": moved,
    }


def _inferno_zone(state: GameState) -> dict:
    """One damage to every player ship within 3 hexes of the boss token."""
    sb = state.star_breach
    assert sb is not None
    targets = []
    for player in _living_players(state):
        distance = _boss_distance_to(sb, player.ship.q, player.ship.r)
        if distance is None or distance > 3:
            continue
        entry: dict = {
            "player_id": player.id,
            "position": {"q": player.ship.q, "r": player.ship.r},
            "distance": distance,
            "shielded": False,
            "damage_applied": 0,
        }
        if player.ship.shields > 0:
            player.ship.shields -= 1
            entry["shielded"] = True
        else:
            entry.update(_apply_unshielded_damage(state, player, 1))
        targets.append(entry)
    return {"radius": 3, "targets": targets}


def _chain_shot(state: GameState) -> dict:
    """An attack that arcs between player ships within 4 hexes of each other,
    rolling to hit on each; no ship is struck twice."""
    sb = state.star_breach
    assert sb is not None
    spec = sb_spec.spec_for(sb)
    aim = sb_spec.boss_aim_bonus(spec, sb.destroyed_hexes, set(sb.active_tiers))
    target = _enemy_pick_target(state, lambda player: _boss_distance_to(sb, player.ship.q, player.ship.r))
    if target is None:
        return {"skipped": "no_target"}
    attacker_pos = min(
        _boss_token_hexes(sb),
        key=lambda hex_: hex_distance(target.ship.q, target.ship.r, hex_[0], hex_[1]),
    )
    links = []
    visited: set[str] = set()
    while target is not None:
        distance = max(1, hex_distance(attacker_pos[0], attacker_pos[1], target.ship.q, target.ship.r))
        event = _resolve_enemy_shot(
            state,
            target,
            attacker_label="starbreacher_chain",
            attacker_position=attacker_pos,
            distance=distance,
            aim_bonus=aim,
        )
        visited.add(target.id)
        links.append({"target_id": target.id, "hit": event["hit"]})
        _check_star_breach_defeat(state)
        if state.phase == GamePhase.COMPLETE:
            break
        attacker_pos = (target.ship.q, target.ship.r)
        candidates = [
            player
            for player in _living_players(state)
            if player.id not in visited
            and hex_distance(player.ship.q, player.ship.r, attacker_pos[0], attacker_pos[1]) <= 4
        ]
        target = (
            min(
                candidates,
                key=lambda player: (
                    hex_distance(player.ship.q, player.ship.r, attacker_pos[0], attacker_pos[1]),
                    player.id,
                ),
            )
            if candidates
            else None
        )
    return {"links": links}


def _scattershot(state: GameState) -> dict:
    """Attack every player ship inside the boss's forward 120° spread."""
    sb = state.star_breach
    assert sb is not None
    spec = sb_spec.spec_for(sb)
    aim = sb_spec.boss_aim_bonus(spec, sb.destroyed_hexes, set(sb.active_tiers))
    nose = ShipState(q=sb.anchor_q, r=sb.anchor_r, facing=sb.facing)
    shots = []
    for player in _living_players(state):
        if not _ship_in_facing_cone_120(nose, player.ship):
            continue
        distance = max(1, hex_distance(sb.anchor_q, sb.anchor_r, player.ship.q, player.ship.r))
        event = _resolve_enemy_shot(
            state,
            player,
            attacker_label="starbreacher_scatter",
            attacker_position=(sb.anchor_q, sb.anchor_r),
            distance=distance,
            aim_bonus=aim,
        )
        shots.append({"target_id": player.id, "hit": event["hit"]})
        _check_star_breach_defeat(state)
        if state.phase == GamePhase.COMPLETE:
            break
    return {"shots": shots}


def _drop_mine(state: GameState) -> dict:
    """Deploy a proximity mine directly in front of the boss nose."""
    sb = state.star_breach
    assert sb is not None
    dq, dr = DIRECTIONS[sb.facing % 6]
    q, r = sb.anchor_q + dq, sb.anchor_r + dr
    if not is_within_board(q, r):
        q, r = sb.anchor_q, sb.anchor_r
    drop_number = 1 + sum(
        1 for event in state.event_log
        if event.get("type") == "boss_super_resolved" and event.get("effect") == "mine_dropper"
    )
    mine = {"id": f"mine_{drop_number}", "q": q, "r": r}
    sb.mines.append(mine)
    return {"mine": dict(mine)}


MINE_TRIGGER_RANGE = 2
MINE_DAMAGE = 3


def _detonate_mines(state: GameState, player: PlayerState, movement_path: list[tuple[int, int]]) -> None:
    """A mine blows for 3 damage when a player ship passes within 2 hexes of
    it (checked along the whole movement path, landing hex included)."""
    sb = state.star_breach
    if sb is None or not sb.mines or not movement_path or player.ship.destroyed:
        return
    for mine in list(sb.mines):
        if not any(
            hex_distance(q, r, mine["q"], mine["r"]) <= MINE_TRIGGER_RANGE for q, r in movement_path
        ):
            continue
        sb.mines.remove(mine)
        shields_absorbed = min(player.ship.shields, MINE_DAMAGE)
        player.ship.shields -= shields_absorbed
        event = {
            "type": "mine_detonated",
            "round": state.round_number,
            "player_id": player.id,
            "mine": dict(mine),
            "target_position": {"q": player.ship.q, "r": player.ship.r},
            "damage": MINE_DAMAGE,
            "shields_absorbed": shields_absorbed,
            "damage_applied": 0,
        }
        remaining = MINE_DAMAGE - shields_absorbed
        if remaining and not player.ship.destroyed:
            event.update(_apply_unshielded_damage(state, player, remaining))
        state.event_log.append(event)
        _check_star_breach_defeat(state)
        if player.ship.destroyed or state.phase == GamePhase.COMPLETE:
            return


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
        if state.result is not None:
            break
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
            if state.result is not None:
                break
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
    return dict(zip(_boss_token_hexes(sb), sb_spec.board_hex_areas(sb_spec.spec_for(sb))))


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
    spec = sb_spec.spec_for(sb)
    profile = _collect_attack_profile(stack, attack_cards)
    area_has_intact_hull = sb_spec.area_has_intact_hull(spec, area, sb.destroyed_hexes)
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
    boss_defense_bonus = sb_spec.boss_defense_bonus(spec, sb.destroyed_hexes, set(sb.active_tiers))
    threshold = (
        profile["fixed_defense_threshold"]
        if profile["fixed_defense_threshold"] is not None
        else distance + sb.boss_movement_this_action + boss_defense_bonus
    )
    roll = _roll_attack(state)
    roll_total = roll + profile["aim_bonus"] + _sensor_aim_bonus(attacker)
    if attacker.captain_id == "malcolm_manderly":
        roll_total += 2
    in_range = profile["max_range"] is None or distance <= profile["max_range"]
    natural_auto_hit = roll >= (18 if _active_starfall(state, "clear_skies") else 12)
    hit = in_range and (profile["always_hits"] or natural_auto_hit or roll_total >= threshold)
    is_ace = "fighting_ace" in attacker.roles
    # The Ace may pre-commit a preferred damage lane; the ±1 shift steers
    # toward it when the roll lands adjacent.
    ace_preference = next(
        (
            selection.ace_lane_preference
            for _card, selection in attack_cards
            if selection.ace_lane_preference is not None
        ),
        None,
    )

    shots: list[dict] = []
    shields_absorbed = 0
    hexes_destroyed = 0
    components_destroyed: list[str] = []
    desperation_cards_drawn = 0
    core_lane_was_open = _open_core_lane_exists(spec, sb.destroyed_hexes)
    if hit:
        generator_intact = _shield_generator_intact(sb, area)
        for _shot in range(profile["damage"]):
            if generator_intact and sb.shield_hp.get(area, 0) > 0:
                sb.shield_hp[area] -= 1
                shields_absorbed += 1
                shots.append({"result": "shield_absorbed", "shield_hp_left": sb.shield_hp[area]})
                continue
            lane_die = sb_spec.lane_die(spec, area)
            lane_roll = _roll_lane_die(state, lane_die)
            # Regions may define fewer lanes than their die allows; an
            # unassigned roll is rerolled (a glancing blow always stands).
            # The stock boss defines every lane, so this never triggers there.
            defined_lanes = spec["damage_lanes"].get(area, {})
            rerolls = 0
            while (
                lane_roll != sb_data.GLANCING_BLOW_ROLL
                and str(lane_roll) not in defined_lanes
                and rerolls < 16
            ):
                lane_roll = _roll_lane_die(state, lane_die)
                rerolls += 1
            adjusted_roll, ace_shift = (
                _fighting_ace_lane_choice(sb, area, lane_roll, preferred=ace_preference)
                if is_ace
                else (lane_roll, 0)
            )
            reroll_note = {"rerolls": rerolls} if rerolls else {}
            if adjusted_roll == sb_data.GLANCING_BLOW_ROLL:
                rng = _make_rng(state)
                drawn = draw_desperation_card(state.desperation_deck, rng)
                attacker.deck.insert(0, drawn)
                desperation_cards_drawn += 1
                shots.append({"result": "glancing_blow", "roll": lane_roll, "ace_shift": ace_shift, "desperation_card_id": drawn.id, **reroll_note})
                continue
            local = sb_spec.first_intact_lane_hex(spec, area, adjusted_roll, sb.destroyed_hexes)
            if local is None:
                shots.append({"result": "overpenetration", "roll": lane_roll, "ace_shift": ace_shift, "lane": adjusted_roll, **reroll_note})
                continue
            sb.destroyed_hexes.add(local)
            hexes_destroyed += 1
            shot = {
                "result": "hull_destroyed",
                "roll": lane_roll,
                "ace_shift": ace_shift,
                "lane": adjusted_roll,
                "hex": [local[0], local[1]],
                **reroll_note,
            }
            component = sb_spec.component_by_hex(spec, local[0], local[1])
            if component is not None:
                components_destroyed.append(component["id"])
                shot["component_id"] = component["id"]
                shot["component_type"] = component["type"]
                if component["type"] == "shield_generator":
                    for arc in component["shield_arcs"]:
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
            "boss_defense_bonus": boss_defense_bonus,
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
    if hit:
        # Dynamic boss AI: whoever hits the boss becomes its quarry.
        _dynamic_directive_switch(state, attacker, "boss_hit", scopes=("boss",))
        # If this volley just opened a damage lane straight to a Core, the
        # whole enemy force turns on the attacker who opened it.
        if not core_lane_was_open and _open_core_lane_exists(spec, sb.destroyed_hexes):
            _dynamic_directive_switch(state, attacker, "core_lane_open")


def _open_core_lane_exists(spec: dict, destroyed_hexes: set[tuple[int, int]]) -> bool:
    """True when some damage lane's first intact hex is a Core: one clean hit
    on that lane would strike the Core directly."""
    core_hexes = {
        (component["q"], component["r"])
        for component in spec["components"]
        if component["type"] == "core" and (component["q"], component["r"]) not in destroyed_hexes
    }
    if not core_hexes:
        return False
    for area, lanes in spec["damage_lanes"].items():
        for roll in lanes:
            if sb_spec.first_intact_lane_hex(spec, area, int(roll), destroyed_hexes) in core_hexes:
                return True
    return False


def _shield_generator_intact(sb: StarBreachState, area: str) -> bool:
    """Whether the arc's shield still has power. Arcs with no assigned
    generator carry an intrinsic charge — it only depletes; the rest die with
    their generator hex."""
    return sb_spec.shield_generator_intact(sb_spec.spec_for(sb), area, sb.destroyed_hexes)


def _fighting_ace_lane_choice(
    sb: StarBreachState, area: str, lane_roll: int, preferred: int | None = None
) -> tuple[int, int]:
    """Deterministic Fighting Ace policy: shift the lane roll by ±1 when that
    turns a Glancing Blow into a strike or steers the hit onto a component.
    A player-chosen preferred lane wins whenever it is within ±1 of the roll
    and would still strike intact hull."""

    spec = sb_spec.spec_for(sb)
    if (
        preferred is not None
        and abs(preferred - lane_roll) <= 1
        and preferred != sb_data.GLANCING_BLOW_ROLL
        and sb_spec.first_intact_lane_hex(spec, area, preferred, sb.destroyed_hexes) is not None
    ):
        return preferred, preferred - lane_roll

    die = sb_spec.lane_die(spec, area)

    def lane_score(roll: int) -> float:
        if roll < 1 or roll > die:
            return -1.0
        if roll == sb_data.GLANCING_BLOW_ROLL:
            return 0.5  # a desperation card is worth something, hull damage more
        local = sb_spec.first_intact_lane_hex(spec, area, roll, sb.destroyed_hexes)
        if local is None:
            return 0.0
        return 3.0 if sb_spec.component_by_hex(spec, local[0], local[1]) else 1.0

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
    roll_total = roll + profile["aim_bonus"] + _sensor_aim_bonus(attacker)
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
    if hit and damage_applied:
        # Dynamic fleet AI: whoever hits the fleet becomes its quarry.
        _dynamic_directive_switch(state, attacker, "craft_hit", scopes=("fleet",))
    if craft.destroyed:
        _check_star_breach_victory(state)


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
    if hit:
        # Dynamic enemy AI: a healer draws the enemy's attention.
        _dynamic_directive_switch(state, attacker, "player_heal")


def _repair_one_component(target: PlayerState) -> str | None:
    """Restore the first destroyed component still adjacent to intact hull."""
    destroyed = target.ship.destroyed_components
    layout = layout_for_ship(target.ship)
    for component in layout.components:
        if component.id not in destroyed:
            continue
        if not _component_adjacent_to_intact(component.id, destroyed, layout):
            continue
        destroyed.discard(component.id)
        target.ship.component_hit_counts.pop(component.id, None)
        target.ship.damage_taken = max(0, target.ship.damage_taken - 1)
        target.ship.destroyed = layout.is_ship_destroyed(target.ship.destroyed_components)
        return component.id
    return None
