from __future__ import annotations

from copy import deepcopy

from starshot.rules.baubles import ship_inside_bauble
from starshot.rules.desperation import draw_desperation_card
from starshot.rules.hex import clamp_to_board, move_forward
from starshot.rules.models import GameState, PlayerState
from starshot.rules.star_command import CAPTAINS, CAPTAINS_BY_ID, EXPANSION_ID, STARFALLS, STARFALLS_BY_ID


def initialize(state: GameState) -> None:
    from starshot.rules import engine as base

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
            "expansion_id": EXPANSION_ID,
        }
    )
    reveal_starfall_for_round(state)


def choose_captain(state: GameState, player_id: str, captain_id: str) -> GameState:
    from starshot.rules import engine as base

    base._validate_active_deck_set(state)
    if not enabled(state):
        raise base.RulesError("StarCommand is not active for this game.")
    next_state = deepcopy(state)
    player = base._player(next_state, player_id)
    if player.captain_id:
        raise base.RulesError("Captain already chosen.")
    if captain_id not in player.captain_options:
        raise base.RulesError("That captain is not one of this player's options.")
    player.captain_id = captain_id
    apply_captain_setup(player)
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


def enabled(state: GameState) -> bool:
    return EXPANSION_ID in state.active_expansions


def captain_choice_pending(state: GameState, player_id: str) -> bool:
    from starshot.rules import engine as base

    if not enabled(state):
        return False
    player = base._player(state, player_id)
    return bool(player.captain_options) and not player.captain_id


def any_captain_choice_pending(state: GameState) -> bool:
    return enabled(state) and any(
        bool(player.captain_options) and not player.captain_id
        for player in state.players.values()
        if not player.eliminated
    )


def apply_captain_setup(player: PlayerState) -> None:
    if player.captain_id == "anya_andrews":
        player.ship.shields = 0


def reveal_starfall_for_round(state: GameState) -> None:
    from starshot.rules import engine as base

    if not enabled(state) or state.active_starfall_round == state.round_number:
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
        lane_roll = base._roll_d12(state)
        event["damage_roll"] = lane_roll
        event["targets"] = base._deal_environmental_damage(state, 1, penetrates_shields=True, fixed_lane_roll=lane_roll)
    elif starfall_id == "gravity_burst":
        event["movement"] = base._pull_all_ships_toward_fang(state, 2)
    elif starfall_id == "stars_align":
        state.starfall_bauble_number = base._roll_d6_no_six(state)
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


def active_starfall(state: GameState, starfall_id: str) -> bool:
    return state.active_starfall_id == starfall_id and state.active_starfall_round == state.round_number


def cleanup_start(state: GameState) -> None:
    from starshot.rules import engine as base

    if not enabled(state):
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
    if active_starfall(state, "take_cover"):
        targets = []
        for player in state.players.values():
            if player.eliminated or player.ship.destroyed:
                continue
            if any(ship_inside_bauble(player.ship, bauble) for bauble in state.baubles):
                continue
            targets.append(player)
        results = [base._apply_environmental_damage_to_player(state, player, 2) for player in targets]
        state.event_log.append({"type": "starfall_take_cover_damage", "round": state.round_number, "targets": results})


def bauble_open_this_round(state: GameState, bauble) -> bool:
    if bauble.is_fang:
        return True
    if bauble.number == state.round_number:
        return True
    if active_starfall(state, "most_dangerous_game") and 1 <= bauble.number <= 5:
        return True
    if active_starfall(state, "stars_align") and bauble.number == state.starfall_bauble_number:
        return True
    return False


def starfall_hit_bonus_vp(state: GameState, attacker_id: str, action_number: int) -> int:
    if not active_starfall(state, "golden_bounty"):
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


def apply_starfall_hit_desperation(state: GameState, attacker: PlayerState) -> None:
    from starshot.rules import engine as base

    if not active_starfall(state, "jolly_roger"):
        return
    for event in state.event_log:
        if (
            event.get("type") == "starfall_jolly_roger_draw"
            and event.get("round") == state.round_number
            and event.get("player_id") == attacker.id
        ):
            return
    rng = base._make_rng(state)
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


def apply_component_destroyed_captain_effects(state: GameState, target: PlayerState, component_type: str) -> None:
    from starshot.rules import engine as base

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
    rng = base._make_rng(state)
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


def _shuffle_values(state: GameState, values: list[str]) -> None:
    from starshot.rules import engine as base

    rng = base._make_rng(state)
    rng.shuffle(values)
    state.rng_step += len(values)
