from __future__ import annotations

from dataclasses import dataclass, field


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
_AXIAL_NEIGHBOR_OFFSETS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

BASE_MAX_SHIELDS = 2
BASE_HAND_SIZE = 5

# Component types whose loss ends the ship: the ship dies when its bridge is
# destroyed or when every life_support component is gone.
BRIDGE_TYPE = "bridge"
LIFE_SUPPORT_TYPE = "life_support"


@dataclass(frozen=True)
class ShipLayout:
    """A ship board: component hexes plus the d12 damage-lane table.

    The base ship is the singleton BASE_SHIP_LAYOUT; designed player ships
    build one from the compiled layout spec stored on their ShipState.
    """

    layout_id: str
    components: tuple[ShipComponent, ...]
    damage_lanes: dict[int, tuple[str, ...]]
    max_shields: int = BASE_MAX_SHIELDS
    base_draw: int = BASE_HAND_SIZE
    # Flat StarDock upgrade bonuses applied to every action (0 for the base ship).
    aim_bonus: int = 0
    defense_bonus: int = 0
    component_by_id: dict[str, ShipComponent] = field(default_factory=dict, compare=False)
    _id_by_coord: dict[tuple[int, int], str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        self.component_by_id.update({component.id: component for component in self.components})
        self._id_by_coord.update({(component.q, component.r): component.id for component in self.components})

    @property
    def bridge_id(self) -> str | None:
        for component in self.components:
            if component.component_type == BRIDGE_TYPE:
                return component.id
        return None

    def first_intact_component_for_lane(self, lane_roll: int, destroyed_components: set[str]) -> ShipComponent | None:
        for component_id in self.damage_lanes.get(lane_roll, ()):
            if component_id not in destroyed_components:
                return self.component_by_id[component_id]
        return None

    def detached_component_ids(self, destroyed_components: set[str]) -> set[str]:
        """Return intact components no longer connected to the bridge."""
        bridge_id = self.bridge_id
        if bridge_id is None or bridge_id in destroyed_components:
            return set()

        connected = {bridge_id}
        frontier = [bridge_id]
        while frontier:
            component = self.component_by_id[frontier.pop()]
            for dq, dr in _AXIAL_NEIGHBOR_OFFSETS:
                neighbor_id = self._id_by_coord.get((component.q + dq, component.r + dr))
                if neighbor_id is None or neighbor_id in destroyed_components or neighbor_id in connected:
                    continue
                connected.add(neighbor_id)
                frontier.append(neighbor_id)

        intact = {component.id for component in self.components if component.id not in destroyed_components}
        return intact - connected

    def is_ship_destroyed(self, destroyed_components: set[str]) -> bool:
        bridge_id = self.bridge_id
        if bridge_id is not None and bridge_id in destroyed_components:
            return True
        life_support_ids = {
            component.id for component in self.components if component.component_type == LIFE_SUPPORT_TYPE
        }
        return life_support_ids.issubset(destroyed_components)

    def intact_count_of_type(self, component_type: str, destroyed_components: set[str]) -> int:
        return sum(
            1
            for component in self.components
            if component.component_type == component_type and component.id not in destroyed_components
        )

    def components_to_dict(self) -> list[dict]:
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
            for component in self.components
        ]

    def damage_lanes_to_dict(self) -> dict[str, list[str]]:
        return {str(roll): list(component_ids) for roll, component_ids in self.damage_lanes.items()}


BASE_SHIP_LAYOUT = ShipLayout(
    layout_id=BASE_SHIP_LAYOUT_ID,
    components=BASE_SHIP_COMPONENTS,
    damage_lanes=BASE_SHIP_DAMAGE_LANES,
)


def layout_from_spec(spec: dict) -> ShipLayout:
    """Build a ShipLayout from a compiled layout spec (see
    starshot.rules.player_ships.compile_layout_spec)."""
    components = tuple(
        ShipComponent(
            id=entry["id"],
            name=entry["name"],
            component_type=entry["type"],
            q=int(entry["q"]),
            r=int(entry["r"]),
            anchor_x=float(entry.get("anchor_x", 0.5)),
            anchor_y=float(entry.get("anchor_y", 0.5)),
        )
        for entry in spec.get("components", [])
    )
    damage_lanes = {
        int(roll): tuple(component_ids) for roll, component_ids in (spec.get("damage_lanes") or {}).items()
    }
    return ShipLayout(
        layout_id=str(spec.get("layout_id", "custom_ship")),
        components=components,
        damage_lanes=damage_lanes,
        max_shields=int(spec.get("max_shields", BASE_MAX_SHIELDS)),
        base_draw=int(spec.get("base_draw", BASE_HAND_SIZE)),
        aim_bonus=int(spec.get("aim_bonus", 0)),
        defense_bonus=int(spec.get("defense_bonus", 0)),
    )


def layout_for_ship(ship) -> ShipLayout:
    """The layout governing a ShipState: its custom spec, or the base ship."""
    spec = getattr(ship, "layout", None)
    if spec:
        return layout_from_spec(spec)
    return BASE_SHIP_LAYOUT


# ── base-layout module functions (kept for existing callers/tests) ──────────


def components_to_dict() -> list[dict]:
    return BASE_SHIP_LAYOUT.components_to_dict()


def damage_lanes_to_dict() -> dict[str, list[str]]:
    return BASE_SHIP_LAYOUT.damage_lanes_to_dict()


def first_intact_component_for_lane(lane_roll: int, destroyed_components: set[str]) -> ShipComponent | None:
    return BASE_SHIP_LAYOUT.first_intact_component_for_lane(lane_roll, destroyed_components)


def detached_component_ids(destroyed_components: set[str]) -> set[str]:
    """Return intact components no longer connected to the command bridge."""
    return BASE_SHIP_LAYOUT.detached_component_ids(destroyed_components)


def is_ship_destroyed(destroyed_components: set[str]) -> bool:
    return BASE_SHIP_LAYOUT.is_ship_destroyed(destroyed_components)
