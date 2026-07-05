from __future__ import annotations

from collections import Counter
from random import Random
from statistics import mean
from typing import Literal

from starshot.rules.ship_layout import (
    BASE_SHIP_COMPONENTS,
    first_intact_component_for_lane,
    is_ship_destroyed,
)

EliminationReason = Literal["bridge", "life_support", "weapons_and_engines", "max_steps"]


def simulate_ship_kills(
    *,
    runs: int = 1000,
    seed: int | None = 1,
    damage_per_volley: int = 1,
    initial_shields: int = 0,
    defense_threshold: int = 7,
    aim_bonus: int = 0,
    attack_dice_count: int = 2,
    attack_die_sides: int = 12,
    double_max_auto_hit: bool = False,
    max_steps: int = 500,
) -> dict:
    """Run repeated ship-destruction simulations using the canonical damage lanes.

    One step represents one incoming shot/volley. The shot rolls configurable
    attack dice plus aim against the ship defense; shields and component damage
    only apply on hits.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1.")
    if runs > 100_000:
        raise ValueError("runs cannot exceed 100000.")
    if damage_per_volley < 1:
        raise ValueError("damage_per_volley must be at least 1.")
    if damage_per_volley > 50:
        raise ValueError("damage_per_volley cannot exceed 50.")
    if initial_shields < 0:
        raise ValueError("initial_shields cannot be negative.")
    if defense_threshold < 0:
        raise ValueError("defense_threshold cannot be negative.")
    if attack_dice_count < 1:
        raise ValueError("attack_dice_count must be at least 1.")
    if attack_dice_count > 20:
        raise ValueError("attack_dice_count cannot exceed 20.")
    if attack_die_sides < 2:
        raise ValueError("attack_die_sides must be at least 2.")
    if attack_die_sides > 100:
        raise ValueError("attack_die_sides cannot exceed 100.")
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1.")

    rng = Random(seed)
    component_first_hits: dict[str, list[int]] = {component.id: [] for component in BASE_SHIP_COMPONENTS}
    component_destroyed_counts: Counter[str] = Counter()
    component_kill_shots: dict[str, list[int]] = {component.id: [] for component in BASE_SHIP_COMPONENTS}
    elimination_reasons: Counter[str] = Counter()
    death_steps: list[int] = []
    attack_rolls: Counter[int] = Counter()
    damage_rolls: Counter[int] = Counter()
    total_hits = 0
    total_misses = 0
    total_auto_hits = 0
    total_shield_blocks = 0
    total_component_hits = 0

    for _ in range(runs):
        destroyed_components: set[str] = set()
        first_hit_step: dict[str, int] = {}
        shields = initial_shields
        step = 0

        while not is_ship_destroyed(destroyed_components) and step < max_steps:
            step += 1
            attack_die_results = [rng.randint(1, attack_die_sides) for _die in range(attack_dice_count)]
            attack_roll = sum(attack_die_results)
            attack_rolls[attack_roll] += 1
            is_auto_hit = double_max_auto_hit and all(result == attack_die_sides for result in attack_die_results)
            if attack_roll + aim_bonus < defense_threshold and not is_auto_hit:
                total_misses += 1
                continue

            total_hits += 1
            if is_auto_hit:
                total_auto_hits += 1
            if shields > 0:
                shields -= 1
                total_shield_blocks += 1
                continue

            for _shot in range(damage_per_volley):
                if is_ship_destroyed(destroyed_components):
                    break

                lane_roll = rng.randint(1, 12)
                damage_rolls[lane_roll] += 1
                component = first_intact_component_for_lane(lane_roll, destroyed_components)
                if component is None:
                    continue

                destroyed_components.add(component.id)
                first_hit_step.setdefault(component.id, step)
                component_destroyed_counts[component.id] += 1
                component_kill_shots[component.id].append(step)
                total_component_hits += 1

        death_steps.append(step)
        elimination_reasons[_elimination_reason(destroyed_components)] += 1
        for component_id, hit_step in first_hit_step.items():
            component_first_hits[component_id].append(hit_step)

    return {
        "config": {
            "runs": runs,
            "seed": seed,
            "damage_per_volley": damage_per_volley,
            "initial_shields": initial_shields,
            "defense_threshold": defense_threshold,
            "aim_bonus": aim_bonus,
            "attack_dice_count": attack_dice_count,
            "attack_die_sides": attack_die_sides,
            "double_max_auto_hit": double_max_auto_hit,
            "max_steps": max_steps,
        },
        "summary": {
            "average_steps_to_kill": round(mean(death_steps), 2),
            "min_steps_to_kill": min(death_steps),
            "max_steps_to_kill": max(death_steps),
            "total_shots": sum(attack_rolls.values()),
            "total_hits": total_hits,
            "total_misses": total_misses,
            "total_auto_hits": total_auto_hits,
            "hit_rate": round(total_hits / sum(attack_rolls.values()), 4) if attack_rolls else 0,
            "total_shield_blocks": total_shield_blocks,
            "total_component_hits": total_component_hits,
            "elimination_reasons": dict(elimination_reasons),
            "attack_rolls": {
                str(roll): attack_rolls[roll]
                for roll in range(attack_dice_count, attack_dice_count * attack_die_sides + 1)
            },
            "damage_rolls": {str(roll): damage_rolls[roll] for roll in range(1, 13)},
        },
        "components": [_component_summary(component, component_first_hits, component_kill_shots, component_destroyed_counts, runs) for component in BASE_SHIP_COMPONENTS],
    }


def _component_summary(component, component_first_hits, component_kill_shots, component_destroyed_counts, runs: int) -> dict:
    first_hits = component_first_hits[component.id]
    kill_steps = component_kill_shots[component.id]
    destroyed_count = component_destroyed_counts[component.id]
    return {
        "id": component.id,
        "name": component.name,
        "type": component.component_type,
        "q": component.q,
        "r": component.r,
        "anchor_x": component.anchor_x,
        "anchor_y": component.anchor_y,
        "destroyed_count": destroyed_count,
        "destroyed_rate": round(destroyed_count / runs, 4),
        "average_first_hit_step": round(mean(first_hits), 2) if first_hits else None,
        "average_destroyed_step": round(mean(kill_steps), 2) if kill_steps else None,
    }


def _elimination_reason(destroyed_components: set[str]) -> EliminationReason:
    if "command_bridge" in destroyed_components:
        return "bridge"

    life_support_ids = {
        component.id for component in BASE_SHIP_COMPONENTS if component.component_type == "life_support"
    }
    if life_support_ids.issubset(destroyed_components):
        return "life_support"

    weapon_ids = {component.id for component in BASE_SHIP_COMPONENTS if component.component_type == "weapon"}
    engine_ids = {component.id for component in BASE_SHIP_COMPONENTS if component.component_type == "engine"}
    if weapon_ids.issubset(destroyed_components) and engine_ids.issubset(destroyed_components):
        return "weapons_and_engines"

    return "max_steps"
