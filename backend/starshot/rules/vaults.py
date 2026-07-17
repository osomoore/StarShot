from __future__ import annotations

from random import Random

from starshot.rules.hex import BOARD_RADIUS, hex_distance, is_within_board, iter_board_hexes
from starshot.rules.models import VaultState, PlayerState, ShipState

VAULT_VP_BY_NUMBER = {number: 2 for number in range(1, 6)}
FANG_VP = 1
FANG_FINAL_ROUND_VP = 6
FINAL_ROUND_NUMBER = 6
VAULT_MAX_CENTER_DISTANCE = {1: 14, 2: 12, 3: 10, 4: 8, 5: 6}
VAULT_PERIMETER_INSET = 6
VAULT_MAX_RANDOM_DISTANCE = BOARD_RADIUS - VAULT_PERIMETER_INSET
VAULT_RADIUS = 1
VAULT_SPACING_BUFFER_RADIUS = 2
EARLY_VAULT_PLAYER_BUFFER = 3


class VaultPlacementError(ValueError):
    """Raised when board constraints leave no valid vault position."""


def create_vaults(rng: Random, players: dict[str, PlayerState]) -> list[VaultState]:
    """Randomly place the ten numbered vaults plus The Fang.

    High numbers have the tightest center-distance rings, so they are placed
    FIRST (most-constrained-first); and because random placement can still
    paint itself into a corner, a dead-end restarts the whole layout instead
    of failing game creation.
    """
    last_error: VaultPlacementError | None = None
    for _attempt in range(25):
        try:
            return _create_vaults_once(rng, players)
        except VaultPlacementError as exc:
            last_error = exc
    raise last_error  # effectively unreachable; kept for safety


def _create_vaults_once(rng: Random, players: dict[str, PlayerState]) -> list[VaultState]:
    occupied: set[tuple[int, int]] = set(vault_buffer_hexes(0, 0))
    vaults: list[VaultState] = []
    player_hexes = tuple((player.ship.q, player.ship.r) for player in players.values() if not player.eliminated)

    for number in range(5, 0, -1):
        for copy_number in range(1, 3):
            q, r = _choose_vault_hex(rng, number, occupied, player_hexes)
            occupied.update(vault_buffer_hexes(q, r))
            vaults.append(
                VaultState(
                    id=f"vault_{number}_{copy_number}",
                    number=number,
                    q=q,
                    r=r,
                    victory_points=VAULT_VP_BY_NUMBER[number],
                )
            )

    vaults.sort(key=lambda vault: vault.id)
    vaults.append(VaultState(id="fang", number=6, q=0, r=0, victory_points=FANG_VP, is_fang=True))
    return vaults


def vault_hexes(q: int, r: int) -> tuple[tuple[int, int], ...]:
    return hex_disk(q, r, VAULT_RADIUS)


def vault_buffer_hexes(q: int, r: int) -> tuple[tuple[int, int], ...]:
    return hex_disk(q, r, VAULT_SPACING_BUFFER_RADIUS)


def hex_disk(q: int, r: int, radius: int) -> tuple[tuple[int, int], ...]:
    hexes: list[tuple[int, int]] = []
    for dq in range(-radius, radius + 1):
        dr_min = max(-radius, -dq - radius)
        dr_max = min(radius, -dq + radius)
        for dr in range(dr_min, dr_max + 1):
            hexes.append((q + dq, r + dr))
    return tuple(hexes)


def ship_inside_vault(ship: ShipState, vault: VaultState) -> bool:
    return hex_distance(ship.q, ship.r, vault.q, vault.r) <= VAULT_RADIUS


def fang_vp_for_round(round_number: int) -> int:
    return FANG_FINAL_ROUND_VP if round_number == FINAL_ROUND_NUMBER else FANG_VP


def vault_event_payload(vault: VaultState) -> dict:
    return {
        "id": vault.id,
        "number": vault.number,
        "q": vault.q,
        "r": vault.r,
        "victory_points": vault.victory_points,
        "is_fang": vault.is_fang,
        "claimed_by": list(vault.claimed_by),
    }


def _choose_vault_hex(
    rng: Random,
    number: int,
    occupied: set[tuple[int, int]],
    player_hexes: tuple[tuple[int, int], ...],
) -> tuple[int, int]:
    max_center_distance = min(VAULT_MAX_CENTER_DISTANCE[number], VAULT_MAX_RANDOM_DISTANCE)
    candidates = [
        (q, r)
        for q, r in iter_board_hexes()
        if _is_vault_footprint_available(q, r, occupied)
        and hex_distance(0, 0, q, r) <= max_center_distance
        and _is_vault_far_enough_from_players(number, q, r, player_hexes)
    ]
    if not candidates:
        raise VaultPlacementError(f"Could not place vault {number}; no valid board hexes remain.")
    return rng.choice(candidates)


def _is_vault_footprint_available(q: int, r: int, occupied: set[tuple[int, int]]) -> bool:
    footprint = vault_hexes(q, r)
    return all(is_within_board(hex_q, hex_r) and (hex_q, hex_r) not in occupied for hex_q, hex_r in footprint)


def _is_vault_far_enough_from_players(
    number: int,
    q: int,
    r: int,
    player_hexes: tuple[tuple[int, int], ...],
) -> bool:
    if number > 2:
        return True
    return all(hex_distance(q, r, player_q, player_r) > EARLY_VAULT_PLAYER_BUFFER for player_q, player_r in player_hexes)
