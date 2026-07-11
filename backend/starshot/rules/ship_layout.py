from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShipComponent:
    id: str
    name: str
    component_type: str
    q: int
    r: int
    anchor_x: float
    anchor_y: float


BASE_SHIP_LAYOUT_ID = "base_ship_0"

BASE_SHIP_COMPONENTS: tuple[ShipComponent, ...] = (
    ShipComponent("forward_ion_cannon", "Forward Ion Cannon", "weapon", 0, -2, 0.485, 0.200),
    ShipComponent("bone_room", "Bone Room", "crew", 0, -1, 0.485, 0.385),
    ShipComponent("command_bridge", "Command Bridge", "bridge", 0, 0, 0.485, 0.535),
    ShipComponent("docking_bay", "Docking Bay", "bay", 0, 1, 0.485, 0.697),
    ShipComponent("aft_engines", "Aft Engines", "engine", 0, 2, 0.485, 0.843),
    ShipComponent("port_shields", "Port Shields", "shield_generator", -1, -1, 0.340, 0.300),
    ShipComponent("port_inner_engines", "Port Inner Engines", "engine", -1, 0, 0.340, 0.495),
    ShipComponent("port_life_support", "Port Life Support", "life_support", -1, 1, 0.340, 0.645),
    ShipComponent("starboard_shields", "Starboard Shields", "shield_generator", 1, -2, 0.630, 0.300),
    ShipComponent("starboard_inner_engines", "Starboard Inner Engines", "engine", 1, -1, 0.630, 0.495),
    ShipComponent("starboard_life_support", "Starboard Life Support", "life_support", 1, 0, 0.630, 0.645),
    ShipComponent("port_ion_cannon", "Port Ion Cannon", "weapon", -2, 0, 0.175, 0.385),
    ShipComponent("port_outer_engines", "Port Outer Engines", "engine", -2, 2, 0.160, 0.690),
    ShipComponent("starboard_ion_cannon", "Starboard Ion Cannon", "weapon", 2, -2, 0.795, 0.385),
    ShipComponent("starboard_outer_engines", "Starboard Outer Engines", "engine", 2, 0, 0.810, 0.690),
)

BASE_SHIP_DAMAGE_LANES: dict[int, tuple[str, ...]] = {
    1: ("aft_engines", "docking_bay", "command_bridge", "bone_room", "forward_ion_cannon"),
    2: ("port_outer_engines", "port_life_support", "command_bridge", "starboard_inner_engines", "starboard_ion_cannon"),
    3: ("port_inner_engines", "bone_room", "starboard_shields"),
    4: ("port_ion_cannon", "port_inner_engines", "command_bridge", "starboard_life_support", "starboard_outer_engines"),
    5: ("port_shields", "bone_room", "starboard_inner_engines"),
    6: ("port_shields", "port_inner_engines", "port_life_support"),
    7: ("forward_ion_cannon", "bone_room", "command_bridge", "docking_bay", "aft_engines"),
    8: ("starboard_shields", "starboard_inner_engines", "starboard_life_support"),
    9: ("starboard_shields", "bone_room", "port_inner_engines"),
    10: ("starboard_ion_cannon", "starboard_inner_engines", "command_bridge", "port_life_support", "port_outer_engines"),
    11: ("starboard_inner_engines", "bone_room", "port_shields"),
    12: ("starboard_outer_engines", "starboard_life_support", "command_bridge", "port_inner_engines", "port_ion_cannon"),
}

BASE_SHIP_COMPONENT_BY_ID = {component.id: component for component in BASE_SHIP_COMPONENTS}
_BASE_SHIP_COMPONENT_ID_BY_COORD = {(component.q, component.r): component.id for component in BASE_SHIP_COMPONENTS}
_AXIAL_NEIGHBOR_OFFSETS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def components_to_dict() -> list[dict]:
    return [
        {
            "id": component.id,
            "name": component.name,
            "type": component.component_type,
            "q": component.q,
            "r": component.r,
            "anchor_x": component.anchor_x,
            "anchor_y": component.anchor_y,
        }
        for component in BASE_SHIP_COMPONENTS
    ]


def damage_lanes_to_dict() -> dict[str, list[str]]:
    return {str(roll): list(component_ids) for roll, component_ids in BASE_SHIP_DAMAGE_LANES.items()}


def first_intact_component_for_lane(lane_roll: int, destroyed_components: set[str]) -> ShipComponent | None:
    for component_id in BASE_SHIP_DAMAGE_LANES[lane_roll]:
        if component_id not in destroyed_components:
            return BASE_SHIP_COMPONENT_BY_ID[component_id]
    return None


def detached_component_ids(destroyed_components: set[str]) -> set[str]:
    """Return intact components no longer connected to the command bridge."""
    if "command_bridge" in destroyed_components:
        return set()

    connected = {"command_bridge"}
    frontier = ["command_bridge"]
    while frontier:
        component = BASE_SHIP_COMPONENT_BY_ID[frontier.pop()]
        for dq, dr in _AXIAL_NEIGHBOR_OFFSETS:
            neighbor_id = _BASE_SHIP_COMPONENT_ID_BY_COORD.get((component.q + dq, component.r + dr))
            if neighbor_id is None or neighbor_id in destroyed_components or neighbor_id in connected:
                continue
            connected.add(neighbor_id)
            frontier.append(neighbor_id)

    intact = {component.id for component in BASE_SHIP_COMPONENTS if component.id not in destroyed_components}
    return intact - connected


def is_ship_destroyed(destroyed_components: set[str]) -> bool:
    if "command_bridge" in destroyed_components:
        return True
    life_support_ids = {
        component.id for component in BASE_SHIP_COMPONENTS if component.component_type == "life_support"
    }
    return life_support_ids.issubset(destroyed_components)
