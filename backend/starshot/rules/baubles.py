from __future__ import annotations

from random import Random

from starshot.rules.hex import hex_distance, is_within_board, iter_board_hexes
from starshot.rules.models import BaubleState, PlayerState, ShipState

BAUBLE_VP_BY_NUMBER = {1: 4, 2: 3, 3: 3, 4: 4, 5: 4}
FANG_VP = 1
FANG_FINAL_ROUND_VP = 6
FINAL_ROUND_NUMBER = 6
BAUBLE_MAX_CENTER_DISTANCE = {1: 14, 2: 12, 3: 10, 4: 8, 5: 6}
BAUBLE_RADIUS = 1
BAUBLE_SPACING_BUFFER_RADIUS = 2
EARLY_BAUBLE_PLAYER_BUFFER = 3


class BaublePlacementError(ValueError):
    """Raised when board constraints leave no valid bauble position."""


def create_baubles(rng: Random, players: dict[str, PlayerState]) -> list[BaubleState]:
    occupied: set[tuple[int, int]] = set(bauble_buffer_hexes(0, 0))
    baubles: list[BaubleState] = []
    player_hexes = tuple((player.ship.q, player.ship.r) for player in players.values() if not player.eliminated)

    for number in range(1, 6):
        for copy_number in range(1, 3):
            q, r = _choose_bauble_hex(rng, number, occupied, player_hexes)
            occupied.update(bauble_buffer_hexes(q, r))
            baubles.append(
                BaubleState(
                    id=f"bauble_{number}_{copy_number}",
                    number=number,
                    q=q,
                    r=r,
                    victory_points=BAUBLE_VP_BY_NUMBER[number],
                )
            )

    baubles.append(BaubleState(id="fang", number=6, q=0, r=0, victory_points=FANG_VP, is_fang=True))
    return baubles


def bauble_hexes(q: int, r: int) -> tuple[tuple[int, int], ...]:
    return hex_disk(q, r, BAUBLE_RADIUS)


def bauble_buffer_hexes(q: int, r: int) -> tuple[tuple[int, int], ...]:
    return hex_disk(q, r, BAUBLE_SPACING_BUFFER_RADIUS)


def hex_disk(q: int, r: int, radius: int) -> tuple[tuple[int, int], ...]:
    hexes: list[tuple[int, int]] = []
    for dq in range(-radius, radius + 1):
        dr_min = max(-radius, -dq - radius)
        dr_max = min(radius, -dq + radius)
        for dr in range(dr_min, dr_max + 1):
            hexes.append((q + dq, r + dr))
    return tuple(hexes)


def ship_inside_bauble(ship: ShipState, bauble: BaubleState) -> bool:
    return hex_distance(ship.q, ship.r, bauble.q, bauble.r) <= BAUBLE_RADIUS


def fang_vp_for_round(round_number: int) -> int:
    return FANG_FINAL_ROUND_VP if round_number == FINAL_ROUND_NUMBER else FANG_VP


def bauble_event_payload(bauble: BaubleState) -> dict:
    return {
        "id": bauble.id,
        "number": bauble.number,
        "q": bauble.q,
        "r": bauble.r,
        "victory_points": bauble.victory_points,
        "is_fang": bauble.is_fang,
        "claimed_by": list(bauble.claimed_by),
    }


def _choose_bauble_hex(
    rng: Random,
    number: int,
    occupied: set[tuple[int, int]],
    player_hexes: tuple[tuple[int, int], ...],
) -> tuple[int, int]:
    max_center_distance = BAUBLE_MAX_CENTER_DISTANCE[number]
    candidates = [
        (q, r)
        for q, r in iter_board_hexes()
        if _is_bauble_footprint_available(q, r, occupied)
        and hex_distance(0, 0, q, r) <= max_center_distance
        and _is_bauble_far_enough_from_players(number, q, r, player_hexes)
    ]
    if not candidates:
        raise BaublePlacementError(f"Could not place bauble {number}; no valid board hexes remain.")
    return rng.choice(candidates)


def _is_bauble_footprint_available(q: int, r: int, occupied: set[tuple[int, int]]) -> bool:
    footprint = bauble_hexes(q, r)
    return all(is_within_board(hex_q, hex_r) and (hex_q, hex_r) not in occupied for hex_q, hex_r in footprint)


def _is_bauble_far_enough_from_players(
    number: int,
    q: int,
    r: int,
    player_hexes: tuple[tuple[int, int], ...],
) -> bool:
    if number > 2:
        return True
    return all(hex_distance(q, r, player_q, player_r) > EARLY_BAUBLE_PLAYER_BUFFER for player_q, player_r in player_hexes)
