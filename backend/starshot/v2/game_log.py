"""Plaintext game log export for debugging v2 battles."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def build_debug_log(state: dict, match: dict | None = None, *, game_id: str | None = None) -> str:
    events = state.get("event_log") or []
    players = state.get("players") or {}
    name_map = _name_map(match, players)
    card_names = _card_name_map(players)
    rounds = sorted({int(event.get("round") or 1) for event in events} | {int(state.get("round_number") or 1)})
    positions = _round_positions(state, rounds)
    components = _round_components(state, rounds)

    lines: list[str] = []
    lines.append("StarShot Debug Log")
    lines.append(f"Exported: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    if game_id:
        lines.append(f"Game ID: {game_id}")
    if match:
        lines.append(f"Match: {match.get('name')} ({match.get('id')})")
        seats = [
            f"{seat.get('player_id')}={seat.get('display_name')}"
            for seat in match.get("seat_list") or []
        ]
        lines.append(f"Seats: {', '.join(seats)}")
    lines.append(f"Deck set: {(state.get('deck_set') or {}).get('name') or state.get('deck_set_id')} ({state.get('deck_set_id')})")
    lines.append(f"Phase: round {state.get('round_number')} / {state.get('phase')}")
    lines.append(f"Starting player: {name_map.get(state.get('starting_player_id'), state.get('starting_player_id'))}")
    if state.get("active_expansions"):
        lines.append(f"Expansions: {', '.join(state.get('active_expansions') or [])}")
    lines.append("")

    lines.append("Players")
    for player_id in players:
        player = players[player_id]
        captain = player.get("captain") or {}
        ship = player.get("ship") or {}
        lines.append(
            f"- {name_map.get(player_id, player_id)} [{player_id}]: "
            f"{player.get('victory_points', 0)} VP, captain={captain.get('name') or player.get('captain_id') or 'none'}, "
            f"pos=({_pos_text(ship)}), shields={ship.get('shields')}, "
            f"destroyed={ship.get('destroyed')}, eliminated={player.get('eliminated')}"
        )
        lines.append(
            "  piles: "
            f"hand={_cards(player.get('hand'), card_names)}, deck={len(player.get('deck') or [])}, "
            f"discard={_cards(player.get('discard'), card_names)}, overheat={_cards(player.get('overheat'), card_names)}"
        )
        lines.append(f"  final components: {_component_summary(ship)}")
    lines.append("")

    lines.append("Baubles")
    for bauble in state.get("baubles") or []:
        claimed = ", ".join(name_map.get(pid, pid) for pid in bauble.get("claimed_by") or []) or "unclaimed"
        label = "Fang" if bauble.get("is_fang") else f"#{bauble.get('number')}"
        lines.append(
            f"- {label} {bauble.get('id')}: q={bauble.get('q')} r={bauble.get('r')} "
            f"VP={bauble.get('victory_points')} claimed_by={claimed}"
        )
    lines.append("")

    for round_number in rounds:
        lines.append(f"Round {round_number}")
        if positions.get(round_number):
            lines.append("  Beginning positions:")
            for player_id, pos in positions[round_number]["begin"].items():
                lines.append(f"    - {name_map.get(player_id, player_id)}: {_pos_text(pos)}")
            lines.append("  End positions:")
            for player_id, pos in positions[round_number]["end"].items():
                lines.append(f"    - {name_map.get(player_id, player_id)}: {_pos_text(pos)}")
        if components.get(round_number):
            lines.append("  Beginning components:")
            for player_id, destroyed in components[round_number]["begin"].items():
                lines.append(f"    - {name_map.get(player_id, player_id)}: {_destroyed_text(destroyed)}")
            lines.append("  End components:")
            for player_id, destroyed in components[round_number]["end"].items():
                lines.append(f"    - {name_map.get(player_id, player_id)}: {_destroyed_text(destroyed)}")
        round_events = [event for event in events if int(event.get("round") or 1) == round_number]
        _append_round_orders(lines, round_events, name_map, card_names)
        _append_round_baubles(lines, round_events, name_map)
        _append_round_combat(lines, round_events, name_map, card_names)
        lines.append("")

    lines.append("Event Log JSON")
    lines.append(json.dumps(events, indent=2, sort_keys=True))
    return "\n".join(lines) + "\n"


def _name_map(match: dict | None, players: dict) -> dict[str, str]:
    names = {player_id: player_id for player_id in players}
    for seat in (match or {}).get("seat_list") or []:
        if seat.get("player_id"):
            names[seat["player_id"]] = seat.get("display_name") or seat["player_id"]
    return names


def _card_name_map(players: dict) -> dict[str, str]:
    names = {}
    for player in players.values():
        for pile_name in ("hand", "deck", "discard", "overheat"):
            for card in player.get(pile_name) or []:
                names[card.get("id")] = card.get("name") or card.get("id")
        orders = player.get("prepared_orders") or {}
        for stack in orders.get("stacks") or []:
            for selection in stack.get("cards") or []:
                names.setdefault(selection.get("card_id"), selection.get("card_id"))
    return names


def _cards(cards: list[dict] | None, card_names: dict[str, str]) -> str:
    values = [card_names.get(card.get("id"), card.get("id")) for card in cards or []]
    return ", ".join(values) if values else "-"


def _selection_text(selection: dict, card_names: dict[str, str]) -> str:
    bits = [card_names.get(selection.get("card_id"), selection.get("card_id"))]
    for key in ("face", "mode", "orientation", "target_player_id"):
        if selection.get(key):
            bits.append(f"{key}={selection.get(key)}")
    return " [" + ", ".join(bits) + "]"


def _round_positions(state: dict, rounds: list[int]) -> dict[int, dict]:
    players = state.get("players") or {}
    current = {pid: _ship_pos(player.get("ship") or {}) for pid, player in players.items()}
    for event in state.get("event_log") or []:
        for player_id, before, _after in _movement_changes(event):
            current.setdefault(player_id, before)
            if player_id in players and current[player_id] == _ship_pos(players[player_id].get("ship") or {}):
                current[player_id] = before
    by_round = {round_number: {"begin": dict(current), "end": dict(current)} for round_number in rounds}
    for round_number in rounds:
        begin = dict(current)
        for event in state.get("event_log") or []:
            if int(event.get("round") or 1) != round_number:
                continue
            for player_id, before, after in _movement_changes(event):
                begin.setdefault(player_id, before)
                current[player_id] = after
        by_round[round_number] = {"begin": begin, "end": dict(current)}
    return by_round


def _movement_changes(event: dict) -> list[tuple[str, dict, dict]]:
    changes = []
    if event.get("type") == "movement_resolved" and event.get("steps"):
        steps = event.get("steps") or []
        changes.append((event.get("player_id"), steps[0].get("before") or {}, steps[-1].get("after") or {}))
    if event.get("type") == "captain_cleanup_movement":
        for movement in event.get("movements") or []:
            changes.append((movement.get("player_id"), movement.get("before") or {}, movement.get("after") or {}))
    if event.get("type") == "starfall_revealed":
        for movement in event.get("movement") or []:
            changes.append((movement.get("player_id"), movement.get("before") or {}, movement.get("after") or {}))
    if event.get("type") == "ramming_resolved" and event.get("attacker_id"):
        changes.append((event.get("attacker_id"), event.get("before") or {}, event.get("after") or {}))
    return [(pid, before, after) for pid, before, after in changes if pid]


def _round_components(state: dict, rounds: list[int]) -> dict[int, dict]:
    players = state.get("players") or {}
    destroyed = {pid: set() for pid in players}
    by_round = {}
    for round_number in rounds:
        begin = {pid: set(values) for pid, values in destroyed.items()}
        for event in state.get("event_log") or []:
            if int(event.get("round") or 1) != round_number:
                continue
            _apply_component_event(destroyed, event)
        by_round[round_number] = {
            "begin": {pid: sorted(values) for pid, values in begin.items()},
            "end": {pid: sorted(values) for pid, values in destroyed.items()},
        }
    return by_round


def _apply_component_event(destroyed: dict[str, set], event: dict) -> None:
    if event.get("type") == "volley_resolved":
        _apply_damage_result(destroyed, event.get("target_id"), event)
    elif event.get("type") == "ramming_resolved":
        _apply_damage_result(destroyed, event.get("target_id"), event.get("target_damage") or {})
        _apply_damage_result(destroyed, event.get("attacker_id"), event.get("attacker_damage") or {})
    elif event.get("type") == "starfall_revealed":
        for target in event.get("targets") or []:
            _apply_damage_result(destroyed, target.get("player_id"), target)
    elif event.get("type") == "starfall_take_cover_damage":
        for target in event.get("targets") or []:
            _apply_damage_result(destroyed, target.get("player_id"), target)
    elif event.get("type") == "engineering_resolved":
        player_set = destroyed.setdefault(event.get("player_id"), set())
        for restored in event.get("repairs") or []:
            for component_id in restored.get("restored_component_ids") or []:
                player_set.discard(component_id)
        for moved in event.get("reconfigures") or []:
            for component_id in moved.get("from_component_ids") or []:
                player_set.discard(component_id)
            for component_id in moved.get("to_component_ids") or []:
                player_set.add(component_id)


def _apply_damage_result(destroyed: dict[str, set], player_id: str | None, result: dict) -> None:
    if not player_id:
        return
    player_set = destroyed.setdefault(player_id, set())
    for shot in result.get("damage_shots") or []:
        if not shot.get("destroyed"):
            continue
        if shot.get("component_id"):
            player_set.add(shot["component_id"])
        player_set.update(shot.get("detached_component_ids") or [])


def _append_round_orders(lines: list[str], events: list[dict], name_map: dict[str, str], card_names: dict[str, str]) -> None:
    order_events = [event for event in events if event.get("type") in {"orders_submitted", "action_revealed"}]
    if not order_events:
        return
    lines.append("  Cards played / orders:")
    for event in order_events:
        player = name_map.get(event.get("player_id"), event.get("player_id"))
        stacks = event.get("stacks") or [{"action_number": event.get("action_number"), "seal_mode": event.get("seal_mode"), "cards": event.get("cards") or []}]
        for stack in stacks:
            cards = "".join(_selection_text(selection, card_names) for selection in stack.get("cards") or []) or " empty"
            lines.append(f"    - {player} action {stack.get('action_number')} {stack.get('seal_mode')}: {cards}")


def _append_round_baubles(lines: list[str], events: list[dict], name_map: dict[str, str]) -> None:
    awards = [event for event in events if event.get("type") == "bauble_awarded"]
    if not awards:
        return
    lines.append("  Bauble awards:")
    for event in awards:
        bauble = event.get("bauble") or {}
        winners = ", ".join(
            f"{name_map.get(award.get('player_id'), award.get('player_id'))} +{award.get('vp_awarded')} VP"
            for award in event.get("awards") or []
        )
        lines.append(f"    - #{bauble.get('number')} at q={bauble.get('q')} r={bauble.get('r')}: {winners or 'none'}")


def _append_round_combat(lines: list[str], events: list[dict], name_map: dict[str, str], card_names: dict[str, str]) -> None:
    combat = [event for event in events if event.get("type") in {"volley_resolved", "ramming_resolved", "starfall_revealed", "starfall_take_cover_damage"}]
    if not combat:
        return
    lines.append("  Damage/combat:")
    for event in combat:
        if event.get("type") == "volley_resolved":
            lines.append(
                f"    - {name_map.get(event.get('attacker_id'), event.get('attacker_id'))} -> "
                f"{name_map.get(event.get('target_id'), event.get('target_id'))}: "
                f"cards={', '.join(card_names.get(cid, cid) for cid in event.get('card_ids') or []) or '-'}, "
                f"roll={event.get('roll')}+{event.get('aim_bonus')} vs {event.get('defense_threshold')}, "
                f"hit={event.get('hit')}, shielded={event.get('shielded')}, damage={event.get('damage_applied', 0)}, "
                f"shots={_damage_shots(event)}"
            )
        elif event.get("type") == "ramming_resolved":
            lines.append(
                f"    - Ram {name_map.get(event.get('attacker_id'), event.get('attacker_id'))} -> "
                f"{name_map.get(event.get('target_id'), event.get('target_id'))}: hit={event.get('hit')}, "
                f"target={_damage_shots(event.get('target_damage') or {})}, attacker={_damage_shots(event.get('attacker_damage') or {})}"
            )
        elif event.get("type") == "starfall_revealed":
            lines.append(f"    - Starfall {event.get('starfall')}: {event.get('text')}")
            for target in event.get("targets") or []:
                lines.append(f"      {name_map.get(target.get('player_id'), target.get('player_id'))}: {_damage_shots(target)}")
        elif event.get("type") == "starfall_take_cover_damage":
            lines.append("    - Take Cover damage:")
            for target in event.get("targets") or []:
                lines.append(f"      {name_map.get(target.get('player_id'), target.get('player_id'))}: {_damage_shots(target)}")


def _damage_shots(event: dict) -> str:
    shots = []
    for shot in event.get("damage_shots") or []:
        component = shot.get("component_id") or "none"
        detached = shot.get("detached_component_ids") or []
        shots.append(f"d12={shot.get('roll')} {component}{' + detached ' + ','.join(detached) if detached else ''}")
    return "; ".join(shots) or "-"


def _ship_pos(ship: dict) -> dict:
    return {"q": ship.get("q"), "r": ship.get("r"), "facing": ship.get("facing")}


def _pos_text(pos: dict) -> str:
    return f"q={pos.get('q')} r={pos.get('r')} facing={pos.get('facing')}"


def _component_summary(ship: dict) -> str:
    return _destroyed_text(ship.get("destroyed_components") or [])


def _destroyed_text(destroyed: list[str] | set[str]) -> str:
    values = sorted(destroyed)
    return ", ".join(values) if values else "all intact"
