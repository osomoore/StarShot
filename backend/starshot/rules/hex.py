from __future__ import annotations

BOARD_RADIUS = 12
START_INSET_FROM_CORNER = 3

DIRECTIONS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)

START_CORNER_DIRECTIONS: tuple[int, ...] = (3, 0, 2, 5)


def move_forward(q: int, r: int, facing: int, distance: int) -> tuple[int, int]:
    dq, dr = DIRECTIONS[facing % 6]
    return q + dq * distance, r + dr * distance


def hex_distance(a_q: int, a_r: int, b_q: int, b_r: int) -> int:
    a_s = -a_q - a_r
    b_s = -b_q - b_r
    return max(abs(a_q - b_q), abs(a_r - b_r), abs(a_s - b_s))


def turn_left(facing: int) -> int:
    return (facing + 1) % 6


def turn_right(facing: int) -> int:
    return (facing - 1) % 6


def u_turn(facing: int) -> int:
    return (facing + 3) % 6


def corner_start(index: int) -> tuple[int, int, int]:
    corner_direction = START_CORNER_DIRECTIONS[index]
    distance_from_center = BOARD_RADIUS - START_INSET_FROM_CORNER
    dq, dr = DIRECTIONS[corner_direction]
    facing = (corner_direction + 3) % 6
    return dq * distance_from_center, dr * distance_from_center, facing
