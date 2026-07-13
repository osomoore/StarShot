from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GamePhase(StrEnum):
    GIVE_ORDERS = "give_orders"
    ACTION_1 = "action_1"
    ACTION_2 = "action_2"
    ACTION_3 = "action_3"
    AWARD_BAUBLES = "award_baubles"
    CLEANUP = "cleanup"
    COMPLETE = "complete"


class CardFamily(StrEnum):
    MOVE = "move"
    ATTACK = "attack"
    HYBRID = "hybrid"


class SealMode(StrEnum):
    SEALED = "sealed"
    OVERDRIVE = "overdrive"


class OverdriveStyle(StrEnum):
    COPY_ACTION = "copy_action"
    COMBINE_CARDS = "combine_cards"


@dataclass(frozen=True, slots=True)
class DesperateFace:
    family: CardFamily
    value: int = 0
    base_damage: int = 1
    orientation_options: tuple[str, ...] = ("forward",)
    requires_target: bool = False
    aim_bonus: int = 0
    damage_bonus: int = 0
    defense_bonus: int = 0
    always_hits: bool = False
    movement_disabled: bool = False
    warp_destination: str | None = None
    max_range: int | None = None
    fixed_defense_threshold: int | None = None
    attacks_all: bool = False
    # Side Slip: lateral move without turning; "right" or "left" relative to facing
    side_slip_direction: str | None = None
    # Drift King: turn right twice then move forward
    double_turn_right: bool = False
    # Drift King 0.3: move forward, then turn twice in the selected direction.
    double_turn_after_move: bool = False
    # Crazy Ivan move face: 180° flip then move forward
    u_turn_move: bool = False
    # Crazy Ivan attack face: 180° flip then untargeted attack
    u_turn_attack: bool = False
    # Active Cooling: move Overheat pile to Discard after moving
    active_cooling: bool = False
    # Lead the Target: ignore target's movement_this_action in defense calc
    lead_the_target: bool = False
    # Holdo Maneuver: move forward during combat and deal unblockable collision damage.
    ramming_distance: int = 0
    ramming_damage: int = 0
    # ScatterShot: attack every enemy in a facing-based 120 degree cone.
    attacks_cone_120: bool = False
    # Engineering faces that directly move/clear component damage.
    repair_components: int = 0
    reconfigure_components: int = 0


@dataclass(frozen=True, slots=True)
class GameConfig:
    player_ids: tuple[str, ...]
    seed: int | None = None
    deck_set_id: str | None = None
    debug_start_with_attack_desperation_card: bool = False
    active_expansions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RulesConfig:
    overheat_pile: bool = True
    allow_mixed_card_type_stacks: bool = False
    overdrive_style: OverdriveStyle = OverdriveStyle.COPY_ACTION
    allow_overdrive_desperation: bool = False


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    name: str
    family: CardFamily
    value: int
    is_base: bool = True
    orientation_options: tuple[str, ...] = ("forward", "turn_left", "turn_right")
    requires_target: bool = True
    is_hybrid: bool = False
    desperate_face: DesperateFace | None = None
    # True for cards with no basic face (Afterburners, Crack Shot);
    # these always return to the Desperation deck regardless of which face is played.
    no_basic_face: bool = False


@dataclass(frozen=True, slots=True)
class OrderCardSelection:
    card_id: str
    face: str = "front"
    orientation: str = "up"
    target_player_id: str | None = None
    mode: str | None = None
    repair_component_ids: tuple[str, ...] = ()
    reconfigure_from_component_ids: tuple[str, ...] = ()
    reconfigure_to_component_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionStack:
    action_number: int
    seal_mode: SealMode
    cards: tuple[OrderCardSelection, ...] = ()


@dataclass(frozen=True, slots=True)
class OrdersSubmission:
    stacks: tuple[ActionStack, ActionStack, ActionStack]


@dataclass(slots=True)
class ShipState:
    q: int = 0
    r: int = 0
    facing: int = 0
    shields: int = 2
    damage_taken: int = 0
    destroyed_components: set[str] = field(default_factory=set)
    component_hit_counts: dict[str, int] = field(default_factory=dict)
    destroyed: bool = False
    knocked_out_round: int | None = None
    knocked_out_action_number: int | None = None
    knocked_out_phase: GamePhase | None = None
    movement_this_action: int = 0
    defense_bonus_this_action: int = 0


@dataclass(slots=True)
class PlayerState:
    id: str
    deck: list[Card]
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    overheat: list[Card] = field(default_factory=list)
    prepared_orders: OrdersSubmission | None = None
    victory_points: int = 0
    ship: ShipState = field(default_factory=ShipState)
    eliminated: bool = False
    overdrive_seals_pending: int = 0
    captain_id: str | None = None
    captain_options: tuple[str, ...] = ()


@dataclass(slots=True)
class BaubleState:
    id: str
    number: int
    q: int
    r: int
    victory_points: int
    is_fang: bool = False
    claimed_by: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DesperationDeck:
    """Shared desperation deck.  Cards are drawn from index 0 (bottom).
    The shuffle marker is a sentinel: when drawn it triggers a reshuffle
    and is placed back on top (end of list).
    """

    cards: list[Card] = field(default_factory=list)
    # True when the "Shuffle Desperately" marker sits on top (end of list).
    shuffle_marker_on_top: bool = True


@dataclass(frozen=True, slots=True)
class GameResult:
    winner_ids: tuple[str, ...]
    reason: str
    is_tie: bool = False


@dataclass(slots=True)
class GameState:
    players: dict[str, PlayerState]
    deck_set_id: str = ""
    baubles: list[BaubleState] = field(default_factory=list)
    desperation_deck: DesperationDeck = field(default_factory=DesperationDeck)
    round_number: int = 1
    phase: GamePhase = GamePhase.GIVE_ORDERS
    starting_player_id: str = ""
    rng_seed: int | None = None
    rng_step: int = 0
    event_log: list[dict] = field(default_factory=list)
    result: GameResult | None = None
    active_expansions: tuple[str, ...] = ()
    starfall_deck: list[str] = field(default_factory=list)
    active_starfall_id: str | None = None
    active_starfall_round: int | None = None
    starfall_bauble_number: int | None = None

    @property
    def active_player_ids(self) -> tuple[str, ...]:
        return tuple(player_id for player_id, player in self.players.items() if not player.eliminated)
