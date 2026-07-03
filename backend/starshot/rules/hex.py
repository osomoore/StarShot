from __future__ import annotations

DIRECTIONS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)


def move_forward(q: int, r: int, facing: int, distance: int) -> tuple[int, int]:
    dq, dr = DIRECTIONS[facing % 6]
    return q + dq * distance, r + dr * distance


def turn_left(facing: int) -> int:
    return (facing - 1) % 6


def turn_right(facing: int) -> int:
    return (facing + 1) % 6


def u_turn(facing: int) -> int:
    return (facing + 3) % 6
