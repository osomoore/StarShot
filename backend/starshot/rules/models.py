from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GamePhase(StrEnum):
    GIVE_ORDERS = "give_orders"
    COOLDOWN = "cooldown"
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


@dataclass(frozen=True, slots=True)
class DesperateFace:
    family: CardFamily
    value: int = 0
    orientation_options: tuple[str, ...] = ("forward",)
    requires_target: bool = False
    aim_bonus: int = 0
    damage_bonus: int = 0
    defense_bonus: int = 0
    always_hits: bool = False
    movement_disabled: bool = False


@dataclass(frozen=True, slots=True)
class GameConfig:
    player_ids: tuple[str, ...]
    seed: int | None = None
    debug_start_with_attack_desperation_card: bool = False
    debug_start_with_split_desperation_cards: bool = False


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    name: str
    family: CardFamily
    value: int
    is_base: bool = True
    orientation_options: tuple[str, ...] = ("forward", "turn_left", "turn_right", "u_turn")
    requires_target: bool = True
    is_hybrid: bool = False
    desperate_face: DesperateFace | None = None


@dataclass(frozen=True, slots=True)
class OrderCardSelection:
    card_id: str
    face: str = "front"
    orientation: str = "up"
    target_player_id: str | None = None
    mode: str | None = None


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
    destroyed: bool = False
    movement_this_action: int = 0
    defense_bonus_this_action: int = 0


@dataclass(slots=True)
class PlayerState:
    id: str
    deck: list[Card]
    overheat: list[Card] = field(default_factory=list)
    prepared_orders: OrdersSubmission | None = None
    victory_points: int = 0
    ship: ShipState = field(default_factory=ShipState)
    eliminated: bool = False


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
    baubles: list[BaubleState] = field(default_factory=list)
    desperation_deck: DesperationDeck = field(default_factory=DesperationDeck)
    round_number: int = 1
    phase: GamePhase = GamePhase.GIVE_ORDERS
    starting_player_id: str = ""
    rng_seed: int | None = None
    rng_step: int = 0
    event_log: list[dict] = field(default_factory=list)
    result: GameResult | None = None

    @property
    def active_player_ids(self) -> tuple[str, ...]:
        return tuple(player_id for player_id, player in self.players.items() if not player.eliminated)
