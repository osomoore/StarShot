"""Server-side AI pilots for StarShot v2.

Three personalities ported from the v1 client-side JS and improved:

- ``vault_runner`` — plans multi-stack routes to the current round's vaults,
  contests The Fang, and shoots opportunistically with leftover stacks.
- ``hunter_killer`` — commits to one prey, repositions until a volley is
  likely, then fires with overdrive and desperate faces on good odds.
- ``blaster``    — opportunist gunner: every action it fires at whichever
  enemy yields the best expected VP, repositioning only when no shot is worth
  taking, and kites to control range.

Improvements over the v1 JS AI:
- Hit odds use the same math as the engine (2d6 vs distance + movement +
  defense, max range, fixed thresholds, the natural-12 auto hit) with a
  *prediction* of the target's movement from its actual movement history,
  instead of reading the stale previous-action value.
- Own movement is counted as defense when weighing exposure to enemy fire.
- Desperate faces (Afterburners, Thrust/Turbo Ions, Crack Shot, Steady Shot,
  StarShot) are played when they swing the action.
- Overdrive is priced by the modern (0.3) economy: every overdriven stack is
  one fewer card drawn next round, so the AIs ration themselves to one
  overdrive per round — except the final round, when there is no next draw
  and overdrive is free tempo.
- Hands are discarded every cleanup, so the AIs never pass an action while
  holding a usable card: a low-odds shot or a positioning move always beats
  letting cards rot. The one exception is holding still inside a vault the
  ship wants to score at cleanup.

Candidate orders are interpreted with the engine's own ``interpret_card`` so
the AI can never disagree with the rules about what a card does. Movement
planning mirrors the engine exactly, including overdrive replaying a stack's
turns (an overdriven turning move curves) and Crazy Ivan's u-turn attack
flipping the ship's facing during combat.

The AIs intentionally have no model of movement-altering StarCommand captain
powers (Drifter's cleanup drift, Turbo's +1 move). AI seats simply never pick
those captains — see ``_choose_ai_captain`` in ``starshot.v2.service``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from random import Random

from starshot.rules.card_effects import CardEffect, interpret_card
from starshot.rules.deck_data import active_catalog
from starshot.rules.hex import (
    clamp_to_board,
    hex_distance,
    move_forward,
    turn_left,
    turn_right,
    u_turn,
)
from starshot.rules.vaults import FINAL_ROUND_NUMBER, VAULT_RADIUS
from starshot.rules.models import (
    ActionStack,
    Card,
    CardFamily,
    GameState,
    OrderCardSelection,
    OverdriveStyle,
    OrdersSubmission,
    PlayerState,
    SealMode,
)

AI_LEVELS = {
    "deck_hand": "Deck Hand",
    "buccaneer": "Buccaneer",
    "pirate_king": "Pirate King",
}

AI_TYPES = {
    "vault_runner": "Freebooter",
    "hunter_killer": "Bloodthirsty",
    "blaster": "Cannoneer",
}

AI_DISPLAY_NAMES = {
    "vault_runner": "Freebooter Ben Gunn",
    "hunter_killer": "Bloodthirsty Blackbeard",
    "blaster": "Cannoneer Israel Hands",
}

# P(2d6 >= n)
_P2D6 = {
    n: sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= n) / 36.0 for n in range(0, 16)
}


def p_2d6_at_least(needed: int) -> float:
    if needed <= 2:
        return 1.0
    if needed > 12:
        return 0.0
    return _P2D6[needed]


@dataclass(frozen=True)
class Pos:
    q: int
    r: int
    facing: int


@dataclass
class MoveUse:
    """One playable move interpretation of a card (face/mode/orientation)."""

    selection: OrderCardSelection
    effect: CardEffect
    is_desperate: bool


@dataclass
class AttackUse:
    """One playable attack interpretation of a card (target chosen later)."""

    selection: OrderCardSelection
    effect: CardEffect
    is_desperate: bool


@dataclass
class StackPlan:
    cards: list[OrderCardSelection] = field(default_factory=list)
    seal_mode: SealMode = SealMode.SEALED


@dataclass(frozen=True)
class AiRules:
    allow_mixed_stacks: bool
    overdrive_copies_action: bool
    overdrive_copies_cards: bool
    allow_overdrive_desperation: bool


def _active_ai_rules() -> AiRules:
    config = active_catalog().rules_config
    return AiRules(
        allow_mixed_stacks=config.allow_mixed_card_type_stacks,
        overdrive_copies_action=str(config.overdrive_style) == OverdriveStyle.COPY_ACTION.value,
        overdrive_copies_cards=str(config.overdrive_style) == OverdriveStyle.COMBINE_CARDS.value,
        allow_overdrive_desperation=config.allow_overdrive_desperation,
    )


# --------------------------------------------------------------------------
# Candidate enumeration
# --------------------------------------------------------------------------


def _try_interpret(card: Card, selection: OrderCardSelection) -> CardEffect | None:
    try:
        return interpret_card(card, selection, SealMode.SEALED)
    except ValueError:
        return None


def _card_uses(card: Card) -> tuple[list[MoveUse], list[AttackUse]]:
    """Every legal (face, mode, orientation) interpretation of a card."""
    moves: list[MoveUse] = []
    attacks: list[AttackUse] = []

    def add(face: str, mode: str | None, orientation: str, is_desperate: bool) -> None:
        selection = OrderCardSelection(card_id=card.id, face=face, orientation=orientation, mode=mode)
        effect = _try_interpret(card, selection)
        if effect is None:
            return
        if effect.family == CardFamily.MOVE and effect.move is not None:
            # Skip warp faces in AI planning; their value is too situational.
            if effect.move.warp_destination:
                return
            moves.append(MoveUse(selection, effect, is_desperate))
        elif effect.family == CardFamily.ATTACK and effect.attack is not None:
            # These special attacks need tactical/geometric judgment beyond the
            # simple volley scorer.
            if effect.attack.ramming_damage or effect.attack.attacks_cone_120:
                return
            attacks.append(AttackUse(selection, effect, is_desperate))

    def add_all_orientations(face: str, mode: str | None, is_desperate: bool) -> None:
        probe = _try_interpret(card, OrderCardSelection(card_id=card.id, face=face, mode=mode))
        options = probe.orientation_options if probe else ("forward",)
        seen: set[str] = set()
        for orientation in options or ("forward",):
            if orientation in seen:
                continue
            seen.add(orientation)
            add(face, mode, orientation, is_desperate)

    if not card.no_basic_face:
        if card.is_hybrid:
            add_all_orientations("front", "move", False)
            add("front", "attack", "up", False)
        elif card.family == CardFamily.MOVE:
            add_all_orientations("front", None, False)
        elif card.family == CardFamily.ATTACK:
            add("front", None, "up", False)

    face = card.desperate_face
    if face is not None:
        if face.family == CardFamily.HYBRID:
            add_all_orientations("desperate", "move", True)
            add("desperate", "attack", "up", True)
        elif face.u_turn_move or face.u_turn_attack:
            add("desperate", None, "u_turn_move", True)
            add("desperate", None, "u_turn_attack", True)
        elif face.family == CardFamily.MOVE:
            add_all_orientations("desperate", None, True)
        elif face.family == CardFamily.ATTACK:
            add("desperate", None, "up", True)

    return moves, attacks


def _apply_move(pos: Pos, use: MoveUse) -> tuple[Pos, int]:
    """Mirror of engine movement semantics; returns (new position, distance moved)."""
    move = use.effect.move
    assert move is not None
    q, r, facing = pos.q, pos.r, pos.facing
    choice = use.selection.orientation
    if choice in ("up",):
        choice = "forward"
    distance = move.distance
    if move.movement_disabled or move.warp_destination:
        return pos, 0
    if move.double_turn_right:
        facing = turn_right(turn_right(facing))
        q, r = move_forward(q, r, facing, distance)
    elif move.double_turn_after_move:
        q, r = move_forward(q, r, facing, distance)
        facing = (
            turn_left(turn_left(facing)) if choice == "turn_left" else turn_right(turn_right(facing))
        )
    elif move.u_turn_move:
        facing = u_turn(facing)
        q, r = move_forward(q, r, facing, distance)
    elif move.side_slip_direction:
        slip_facing = (facing + (-1 if choice == "slip_right" else 1)) % 6
        q, r = move_forward(q, r, slip_facing, distance)
    elif choice == "forward":
        q, r = move_forward(q, r, facing, distance)
    elif choice == "turn_left":
        facing = turn_left(facing)
        q, r = move_forward(q, r, facing, distance)
    elif choice == "turn_right":
        facing = turn_right(facing)
        q, r = move_forward(q, r, facing, distance)
    else:
        return pos, 0
    q, r = clamp_to_board(q, r)
    return Pos(q, r, facing), distance


@dataclass
class MoveStackOption:
    plan: StackPlan
    end: Pos
    moved: int
    desperate_count: int
    overdrive: bool


def _move_stack_options(
    hand_moves: list[MoveUse],
    pos: Pos,
    allow_overdrive: bool,
    rules: AiRules,
) -> list[MoveStackOption]:
    """All 1- and 2-card move stacks from the given position."""
    options: list[MoveStackOption] = []

    def record(uses: list[MoveUse], seal: SealMode) -> None:
        current, moved = pos, 0
        passes = 2 if seal == SealMode.OVERDRIVE and (rules.overdrive_copies_action or rules.overdrive_copies_cards) else 1
        for pass_index in range(passes):
            for use in uses:
                if (
                    pass_index > 0
                    and rules.overdrive_copies_action
                    and use.is_desperate
                    and not rules.allow_overdrive_desperation
                ):
                    continue  # desperate faces are not copied by overdrive
                current, step = _apply_move(current, use)
                moved += step
        options.append(
            MoveStackOption(
                plan=StackPlan(cards=[use.selection for use in uses], seal_mode=seal),
                end=current,
                moved=moved,
                desperate_count=sum(1 for use in uses if use.is_desperate),
                overdrive=seal == SealMode.OVERDRIVE,
            )
        )

    can_overdrive = allow_overdrive and (rules.overdrive_copies_action or rules.overdrive_copies_cards)
    seals = [SealMode.SEALED] + ([SealMode.OVERDRIVE] if can_overdrive else [])
    singles = hand_moves
    for use in singles:
        for seal in seals:
            if seal == SealMode.OVERDRIVE and use.is_desperate and not rules.allow_overdrive_desperation:
                continue
            record([use], seal)
    by_card: dict[str, list[MoveUse]] = {}
    for use in hand_moves:
        by_card.setdefault(use.selection.card_id, []).append(use)
    for first_id, second_id in itertools.permutations(by_card.keys(), 2):
        for first in by_card[first_id][:3]:
            for second in by_card[second_id][:3]:
                for seal in seals:
                    if (
                        seal == SealMode.OVERDRIVE
                        and not rules.allow_overdrive_desperation
                        and (first.is_desperate or second.is_desperate)
                    ):
                        continue
                    record([first, second], seal)
    return options


# --------------------------------------------------------------------------
# Situation model
# --------------------------------------------------------------------------


class Situation:
    def __init__(self, state: GameState, me: PlayerState, rng: Random, rules: AiRules) -> None:
        self.state = state
        self.me = me
        self.rng = rng
        self.rules = rules
        self.enemies = [
            player
            for player in state.players.values()
            if player.id != me.id and not player.eliminated and not player.ship.destroyed
        ]
        moves, attacks = [], []
        for card in me.hand:
            card_moves, card_attacks = _card_uses(card)
            moves.extend(card_moves)
            attacks.extend(card_attacks)
        self.hand_moves = moves
        self.hand_attacks = attacks
        self.pos = Pos(me.ship.q, me.ship.r, me.ship.facing)
        # Each overdriven stack costs one card off next round's draw, so ration
        # overdrive — except the final round, when there is no next draw.
        self.overdrive_budget = 3 if state.round_number >= FINAL_ROUND_NUMBER else 1
        self._movement_history: dict[str, list[int]] = {}
        for event in state.event_log[-200:]:
            if event.get("type") == "movement_resolved" and not event.get("overdrive_copy"):
                history = self._movement_history.setdefault(event.get("player_id", ""), [])
                history.append(int(event.get("movement_this_action", 0)))

    def expected_movement(self, player_id: str) -> float:
        """Predicted per-action movement of a ship (its defense against us).
        Early-round overdrive sprints rack up 6-8 movement in one action but
        say little about how much a ship moves once it settles near its goal,
        so the estimate is capped rather than taken at face value."""
        history = self._movement_history.get(player_id, [])[-4:]
        if not history:
            return 2.0
        return min(3.0, sum(history) / len(history))

    def volley_hit_chance(self, from_pos: Pos, enemy: PlayerState, attack_uses: list[AttackUse]) -> float:
        """Hit odds for a volley, using the engine's combat math: 2d6 + aim vs
        distance + target movement, honoring max range, fixed defense
        thresholds, always-hits, and the natural-12 auto hit."""
        attacks = [use.effect.attack for use in attack_uses if use.effect.attack]
        if not attacks:
            return 0.0
        distance = hex_distance(from_pos.q, from_pos.r, enemy.ship.q, enemy.ship.r)
        max_range = next((attack.max_range for attack in attacks if attack.max_range is not None), None)
        if max_range is not None and distance > max_range:
            return 0.0
        if any(attack.always_hits for attack in attacks):
            return 1.0
        aim = sum(attack.aim_bonus for attack in attacks)
        fixed = next(
            (attack.fixed_defense_threshold for attack in attacks if attack.fixed_defense_threshold is not None),
            None,
        )
        if fixed is not None:
            needed = fixed - aim
        else:
            lead = any(attack.lead_the_target for attack in attacks)
            predicted = 0.0 if lead else self.expected_movement(enemy.id)
            needed = distance + round(predicted) - aim
        # A natural 12 always hits, so no in-range shot is ever hopeless.
        return max(p_2d6_at_least(needed), 1.0 / 36.0)

    def kill_pressure(self, enemy: PlayerState) -> float:
        """How close the enemy is to death: 0 (fresh) .. ~1 (one hit away)."""
        if enemy.ship.shields > 0:
            return 0.0
        return min(1.0, len(enemy.ship.destroyed_components) / 6 + enemy.ship.damage_taken / 10)

    def attack_value(self, from_pos: Pos, enemy: PlayerState, attack_uses: list[AttackUse]) -> float:
        damage = max((use.effect.attack.base_damage for use in attack_uses if use.effect.attack), default=1)
        damage += sum(use.effect.attack.damage_bonus for use in attack_uses if use.effect.attack)
        p_hit = self.volley_hit_chance(from_pos, enemy, attack_uses)
        if enemy.ship.shields > 0:
            return p_hit * 1.0  # shield steal: guaranteed 1 VP on a hit
        return p_hit * (1.0 + 2.0 * self.kill_pressure(enemy) + 0.25 * (damage - 1))

    def exposure(self, pos: Pos, own_movement: int) -> float:
        """Expected number of enemy hits against us at this position, given how
        far we moved this action (movement is defense)."""
        total = 0.0
        for enemy in self.enemies:
            distance = hex_distance(pos.q, pos.r, enemy.ship.q, enemy.ship.r)
            total += p_2d6_at_least(distance + own_movement)
        return total

    def fragile(self) -> bool:
        ship = self.me.ship
        return ship.shields == 0 and (ship.damage_taken >= 3 or len(ship.destroyed_components) >= 3)


# --------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------


def _best_attack_uses(
    situation: Situation,
    available: list[AttackUse],
    from_pos: Pos,
    enemy: PlayerState,
    allow_desperate: bool,
) -> list[AttackUse]:
    """Pick up to two attack uses (one card each) maximizing volley value."""
    usable = [use for use in available if allow_desperate or not use.is_desperate]
    if not usable:
        return []
    best: list[AttackUse] = []
    best_value = -1.0
    candidates: list[list[AttackUse]] = [[use] for use in usable]
    for first, second in itertools.combinations(usable, 2):
        if first.selection.card_id != second.selection.card_id:
            candidates.append([first, second])
    for combo in candidates:
        value = situation.attack_value(from_pos, enemy, combo)
        # Spending a single-use desperate face should buy a real edge.
        value -= 0.15 * sum(1 for use in combo if use.is_desperate)
        if value > best_value:
            best_value = value
            best = combo
    return best


def _targeted(selection: OrderCardSelection, effect: CardEffect, target_id: str) -> OrderCardSelection:
    needs_target = effect.attack.requires_target if effect.attack else False
    return OrderCardSelection(
        card_id=selection.card_id,
        face=selection.face,
        orientation=selection.orientation,
        mode=selection.mode,
        target_player_id=target_id if needs_target else None,
    )


def _pos_after_attack_stack(pos: Pos, uses: list[AttackUse]) -> Pos:
    """Crazy Ivan u-turn attacks flip the attacker's facing during combat."""
    flips = sum(1 for use in uses if use.effect.attack and use.effect.attack.u_turn_attack)
    if flips % 2:
        return Pos(pos.q, pos.r, u_turn(pos.facing))
    return pos


def _attack_stack(
    situation: Situation,
    available: list[AttackUse],
    from_pos: Pos,
    enemy: PlayerState,
    allow_desperate: bool,
    overdrive_threshold: float,
    allow_overdrive: bool = True,
) -> tuple[StackPlan | None, list[AttackUse]]:
    """Build an attack stack against the enemy; returns (plan, uses consumed)."""
    combo = _best_attack_uses(situation, available, from_pos, enemy, allow_desperate)
    if not combo:
        return None, []
    p_hit = situation.volley_hit_chance(from_pos, enemy, combo)
    # Overdrive repeats the volley (desperate faces excluded from the copy).
    copies_help = any(not use.is_desperate for use in combo)
    overdrive_legal = situation.rules.allow_overdrive_desperation or not any(use.is_desperate for use in combo)
    seal = (
        SealMode.OVERDRIVE
        if (
            allow_overdrive
            and (situation.rules.overdrive_copies_action or situation.rules.overdrive_copies_cards)
            and overdrive_legal
            and copies_help
            and p_hit >= overdrive_threshold
        )
        else SealMode.SEALED
    )
    cards = [_targeted(use.selection, use.effect, enemy.id) for use in combo]
    return StackPlan(cards=cards, seal_mode=seal), combo


def _mixed_move_attack_stack(
    situation: Situation,
    moves: list[MoveUse],
    attacks: list[AttackUse],
    from_pos: Pos,
    enemy: PlayerState,
    allow_desperate: bool,
) -> tuple[StackPlan | None, MoveUse | None, AttackUse | None, Pos, float]:
    """Try a legal move+attack stack. Movement resolves before combat, so this
    is valuable when a single move creates a better shot in the same action."""
    if not situation.rules.allow_mixed_stacks:
        return None, None, None, from_pos, -1.0
    move_pool = [use for use in moves if allow_desperate or not use.is_desperate]
    attack_pool = [use for use in attacks if allow_desperate or not use.is_desperate]
    if not move_pool or not attack_pool:
        return None, None, None, from_pos, -1.0

    baseline = 0.0
    baseline_combo = _best_attack_uses(situation, attacks, from_pos, enemy, allow_desperate)
    if baseline_combo:
        baseline = situation.attack_value(from_pos, enemy, baseline_combo)

    best: tuple[StackPlan | None, MoveUse | None, AttackUse | None, Pos, float] = (None, None, None, from_pos, -1.0)
    for move_use in move_pool:
        moved_pos, moved = _apply_move(from_pos, move_use)
        for attack_use in attack_pool:
            if move_use.selection.card_id == attack_use.selection.card_id:
                continue
            value = situation.attack_value(moved_pos, enemy, [attack_use])
            value -= 0.04 * max(0, moved)
            value -= 0.16 * int(move_use.is_desperate or attack_use.is_desperate)
            if value <= baseline + 0.08:
                continue
            # Never overdrive a mixed stack: the overdrive copy replays the
            # move as well, which drags the ship past the firing position the
            # shot was priced at.
            plan = StackPlan(
                cards=[
                    move_use.selection,
                    _targeted(attack_use.selection, attack_use.effect, enemy.id),
                ],
                seal_mode=SealMode.SEALED,
            )
            if value > best[4]:
                best = (plan, move_use, attack_use, moved_pos, value)
    return best


def _remove_uses(pool: list, consumed: list) -> list:
    used_ids = {use.selection.card_id for use in consumed}
    return [use for use in pool if use.selection.card_id not in used_ids]


def _consume_plan(plan: StackPlan, moves: list[MoveUse], attacks: list[AttackUse]) -> tuple[list[MoveUse], list[AttackUse]]:
    """Remove a played stack's cards from BOTH pools — hybrid cards appear in
    each, and a card may only be ordered once per round."""
    used_ids = {selection.card_id for selection in plan.cards}
    return (
        [use for use in moves if use.selection.card_id not in used_ids],
        [use for use in attacks if use.selection.card_id not in used_ids],
    )


def _defensive_move(situation: Situation, moves: list[MoveUse], pos: Pos) -> tuple[StackPlan | None, list[MoveUse], Pos]:
    """Pick the move stack that minimizes exposure (movement itself is defense)."""
    options = _move_stack_options(
        [use for use in moves if not use.is_desperate],
        pos,
        allow_overdrive=False,
        rules=situation.rules,
    )
    if not options:
        return None, moves, pos
    best = min(options, key=lambda option: (situation.exposure(option.end, option.moved), -option.moved))
    consumed = [use for use in moves if use.selection.card_id in {c.card_id for c in best.plan.cards}]
    return best.plan, _remove_uses(moves, consumed), best.end


def _finalize(plans: list[StackPlan]) -> OrdersSubmission:
    while len(plans) < 3:
        plans.append(StackPlan())
    stacks = tuple(
        ActionStack(action_number=index + 1, seal_mode=plan.seal_mode, cards=tuple(plan.cards))
        for index, plan in enumerate(plans[:3])
    )
    return OrdersSubmission(stacks=stacks)  # type: ignore[arg-type]


def fallback_orders() -> OrdersSubmission:
    return _finalize([])


# --------------------------------------------------------------------------
# Vault targets
# --------------------------------------------------------------------------


def _round_vaults(state: GameState, me: PlayerState, include_upcoming: bool = False) -> list:
    """Vaults worth chasing this round, best value first. With
    ``include_upcoming``, next round's vaults are worth camping early at a
    discount (they only score at next round's cleanup)."""
    ship = me.ship
    scored = []
    for vault in state.vaults:
        active = vault.is_fang or vault.number == state.round_number
        upcoming = include_upcoming and not active and vault.number == state.round_number + 1
        if not active and not upcoming:
            continue
        # The Fang re-awards every round the ship holds it; numbered vaults
        # pay once, so skip ones this ship already claimed.
        if not vault.is_fang and me.id in vault.claimed_by:
            continue
        distance = max(0, hex_distance(ship.q, ship.r, vault.q, vault.r) - VAULT_RADIUS)
        value = float(vault.victory_points + (0 if vault.is_fang else 1))  # numbered: + desperation card
        if vault.is_fang and state.round_number < FINAL_ROUND_NUMBER:
            value = max(1.0, value - 1.0)  # Fang bites back before the payoff round
        if upcoming:
            value *= 0.5
        scored.append((value / (1.0 + distance), distance, vault))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _plan_route(
    situation: Situation,
    moves: list[MoveUse],
    goal_q: int,
    goal_r: int,
    stacks_available: int,
    allow_desperate: bool,
    overdrive_budget: int = 0,
) -> list[MoveStackOption] | None:
    """Beam search across up to `stacks_available` stacks to land within the
    vault's claim radius. Returns the stack options per action; if no card
    combination gets all the way there, returns the cheapest route that makes
    real progress (without spending overdrive on a non-arrival), or None when
    no move helps at all."""

    def goal_distance(pos: Pos) -> int:
        return max(0, hex_distance(pos.q, pos.r, goal_q, goal_r) - VAULT_RADIUS)

    start_distance = goal_distance(situation.pos)
    if start_distance == 0:
        return []
    # pos, plans, used card ids, cost, overdriven stacks
    Beam = tuple[Pos, list[MoveStackOption], frozenset[str], int, int]
    beams: list[Beam] = [(situation.pos, [], frozenset(), 0, 0)]
    best_finish: list[MoveStackOption] | None = None
    best_cost = 10**9
    best_partial: tuple[int, int, list[MoveStackOption]] | None = None  # (distance, cost, plans)
    for _ in range(stacks_available):
        next_beams: list[Beam] = []
        for pos, plans, used, cost, overdriven in beams:
            pool = [
                use
                for use in moves
                if use.selection.card_id not in used and (allow_desperate or not use.is_desperate)
            ]
            options = _move_stack_options(pool, pos, allow_overdrive=overdrive_budget > 0, rules=situation.rules)
            options.sort(key=lambda option: goal_distance(option.end))
            for option in options[:12]:
                if option.overdrive and overdriven >= overdrive_budget:
                    continue
                option_cost = (
                    cost
                    + (2 if option.overdrive else 0)
                    + 3 * option.desperate_count
                    + len(option.plan.cards)
                )
                new_plans = plans + [option]
                end_distance = goal_distance(option.end)
                if end_distance == 0 and option_cost < best_cost:
                    best_cost = option_cost
                    best_finish = new_plans
                    continue
                # Overdrive that does not finish the route just burns next
                # round's card; only sealed/desperate stacks count as progress.
                if not option.overdrive and end_distance < start_distance:
                    if best_partial is None or (end_distance, option_cost) < best_partial[:2]:
                        best_partial = (end_distance, option_cost, new_plans)
                new_used = used | {c.card_id for c in option.plan.cards}
                next_beams.append(
                    (option.end, new_plans, new_used, option_cost, overdriven + (1 if option.overdrive else 0))
                )
        next_beams.sort(key=lambda beam: (goal_distance(beam[0]), beam[3]))
        beams = next_beams[:10]
        if not beams:
            break
    if best_finish is not None:
        return best_finish
    if best_partial is not None:
        return best_partial[2]
    return None


# --------------------------------------------------------------------------
# Personalities
# --------------------------------------------------------------------------


def _plan_vault_runner(situation: Situation) -> OrdersSubmission:
    state, me = situation.state, situation.me
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos
    overdrive_budget = situation.overdrive_budget

    targets = _round_vaults(state, me, include_upcoming=True)
    goal = None
    for vault in targets[:3]:
        route = _plan_route(
            situation, moves, vault.q, vault.r, 3, allow_desperate=True, overdrive_budget=overdrive_budget
        )
        if route is not None:
            goal = vault
            for option in route[:3]:
                plans.append(option.plan)
                moves, attacks = _consume_plan(option.plan, moves, attacks)
                pos = option.end
                if option.overdrive:
                    overdrive_budget -= 1
            break

    def holding_vault() -> bool:
        """Standing inside a vault we mean to score: cleanup checks the final
        position, so later stacks must not wander off it."""
        return any(
            hex_distance(pos.q, pos.r, vault.q, vault.r) <= VAULT_RADIUS
            for vault in ([goal] if goal is not None else targets[:3])
        )

    # Fill remaining stacks. Hands are discarded at cleanup, so an unplayed
    # attack card is a wasted card: take the best shot available even on poor
    # odds. Only sitting inside a vault justifies standing still.
    while len(plans) < 3:
        best_enemy, best_value = None, 0.0
        for enemy in situation.enemies:
            combo = _best_attack_uses(situation, attacks, pos, enemy, allow_desperate=False)
            if combo:
                value = situation.attack_value(pos, enemy, combo)
                if value > best_value:
                    best_value, best_enemy = value, enemy
        if not holding_vault():
            for enemy in situation.enemies:
                mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
                    situation, moves, attacks, pos, enemy, allow_desperate=False
                )
                if mixed_plan and mixed_value > max(best_value, 0.55):
                    plans.append(mixed_plan)
                    moves, attacks = _consume_plan(mixed_plan, moves, attacks)
                    pos = _pos_after_attack_stack(mixed_pos, [mixed_attack] if mixed_attack else [])
                    break
            else:
                mixed_plan = None
            if mixed_plan:
                continue
        if best_enemy is not None:
            plan, consumed = _attack_stack(
                situation,
                attacks,
                pos,
                best_enemy,
                allow_desperate=False,
                overdrive_threshold=0.6,
                allow_overdrive=overdrive_budget > 0,
            )
            if plan:
                if plan.seal_mode == SealMode.OVERDRIVE:
                    overdrive_budget -= 1
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                pos = _pos_after_attack_stack(pos, consumed)
                continue
        if holding_vault():
            # Park on the loot; never move off before cleanup scores it.
            plans.append(StackPlan())
            continue
        if situation.fragile() and moves:
            plan, moves, pos = _defensive_move(situation, moves, pos)
            if plan:
                moves, attacks = _consume_plan(plan, moves, attacks)
                plans.append(plan)
                continue
        # No route landed on the vault: still grind toward it greedily.
        if targets and moves:
            goal_vault = goal or targets[0]
            options = _move_stack_options(
                [use for use in moves if not use.is_desperate],
                pos,
                allow_overdrive=False,
                rules=situation.rules,
            )
            if options:
                best = min(
                    options,
                    key=lambda option: hex_distance(option.end.q, option.end.r, goal_vault.q, goal_vault.r),
                )
                if hex_distance(best.end.q, best.end.r, goal_vault.q, goal_vault.r) < hex_distance(
                    pos.q, pos.r, goal_vault.q, goal_vault.r
                ):
                    plans.append(best.plan)
                    moves, attacks = _consume_plan(best.plan, moves, attacks)
                    pos = best.end
                    continue
        plans.append(StackPlan())
    return _finalize(plans)


def _pick_prey(situation: Situation) -> PlayerState | None:
    """Committed target: whoever we shot most recently, else nearest weakest."""
    state, me = situation.state, situation.me
    living = {enemy.id: enemy for enemy in situation.enemies}
    if not living:
        return None
    for event in reversed(state.event_log):
        if (
            event.get("type") == "volley_resolved"
            and event.get("attacker_id") == me.id
            and event.get("target_id") in living
        ):
            return living[event["target_id"]]
    return min(
        living.values(),
        key=lambda enemy: (
            hex_distance(me.ship.q, me.ship.r, enemy.ship.q, enemy.ship.r)
            - 2 * situation.kill_pressure(enemy),
            enemy.ship.shields,
        ),
    )


def _chase_move(
    situation: Situation,
    moves: list[MoveUse],
    pos: Pos,
    enemy: PlayerState,
    allow_desperate: bool,
    allow_overdrive: bool = False,
) -> MoveStackOption | None:
    pool = [use for use in moves if allow_desperate or not use.is_desperate]
    options = _move_stack_options(pool, pos, allow_overdrive=allow_overdrive, rules=situation.rules)
    if not options:
        return None

    def score(option: MoveStackOption) -> tuple:
        distance = hex_distance(option.end.q, option.end.r, enemy.ship.q, enemy.ship.r)
        # Ideal firing range is close but not point-blank next action.
        range_penalty = abs(distance - 2)
        # Overdrive doubles the stack's movement but costs a card next round;
        # spend it only when it genuinely closes range, not as a tiebreaker.
        return (range_penalty, 3 * option.desperate_count + (2 if option.overdrive else 0), -option.moved)

    return min(options, key=score)


def _plan_hunter_killer(situation: Situation) -> OrdersSubmission:
    prey = _pick_prey(situation)
    if prey is None:
        return fallback_orders()
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    overdrive_budget = situation.overdrive_budget
    attack_stacks_wanted = min(2, max(1, len({use.selection.card_id for use in attacks})))
    for action in range(3):
        remaining = 3 - action
        combo = _best_attack_uses(situation, attacks, pos, prey, allow_desperate=True)
        p_hit = situation.volley_hit_chance(pos, prey, combo) if combo else 0.0
        must_attack = remaining <= attack_stacks_wanted and combo
        good_shot = combo and p_hit >= 0.5
        allow_mixed_desperate = situation.kill_pressure(prey) > 0.4 or p_hit < 0.25
        mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
            situation, moves, attacks, pos, prey, allow_desperate=allow_mixed_desperate
        )
        pure_value = situation.attack_value(pos, prey, combo) if combo else 0.0
        if mixed_plan and (mixed_value >= 0.55 or mixed_value > pure_value + 0.15):
            plans.append(mixed_plan)
            moves, attacks = _consume_plan(mixed_plan, moves, attacks)
            pos = _pos_after_attack_stack(mixed_pos, [mixed_attack] if mixed_attack else [])
            attack_stacks_wanted -= 1
            continue
        if good_shot or must_attack:
            # Spend desperate firepower only when it makes the kill likely.
            allow_desperate = situation.kill_pressure(prey) > 0.4 or p_hit < 0.35
            plan, consumed = _attack_stack(
                situation,
                attacks,
                pos,
                prey,
                allow_desperate=allow_desperate,
                overdrive_threshold=0.45,
                allow_overdrive=overdrive_budget > 0,
            )
            if plan:
                if plan.seal_mode == SealMode.OVERDRIVE:
                    overdrive_budget -= 1
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                pos = _pos_after_attack_stack(pos, consumed)
                if consumed:
                    attack_stacks_wanted -= 1
                continue
        far_from_prey = hex_distance(pos.q, pos.r, prey.ship.q, prey.ship.r) > 4
        option = _chase_move(
            situation,
            moves,
            pos,
            prey,
            allow_desperate=p_hit < 0.2,
            allow_overdrive=overdrive_budget > 0 and far_from_prey,
        )
        if option:
            if option.overdrive:
                overdrive_budget -= 1
            plans.append(option.plan)
            moves, attacks = _consume_plan(option.plan, moves, attacks)
            pos = option.end
            continue
        # Out of moves: a poor shot still beats discarding the cards unplayed.
        plan, consumed = _attack_stack(
            situation, attacks, pos, prey, allow_desperate=False, overdrive_threshold=2.0
        )
        if plan:
            plans.append(plan)
            moves, attacks = _consume_plan(plan, moves, attacks)
            pos = _pos_after_attack_stack(pos, consumed)
        else:
            plans.append(StackPlan())
    return _finalize(plans)


def _plan_blaster(situation: Situation) -> OrdersSubmission:
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    overdrive_budget = situation.overdrive_budget
    for _ in range(3):
        # A shot is "worth taking" from where we stand at 0.25+ value; below
        # that, repositioning for next action is better — unless there is no
        # move left, in which case any shot beats discarding the cards.
        best_enemy, best_combo, best_value = None, None, 0.25
        best_mixed: tuple[StackPlan | None, AttackUse | None, Pos, float] = (None, None, pos, 0.25)
        for enemy in situation.enemies:
            combo = _best_attack_uses(situation, attacks, pos, enemy, allow_desperate=True)
            if combo:
                value = situation.attack_value(pos, enemy, combo)
                # Prefer finishing wounded prey and stealing the last shields.
                value += 0.5 * situation.kill_pressure(enemy) - 0.05 * enemy.ship.shields
                if value > best_value:
                    best_enemy, best_combo, best_value = enemy, combo, value
            mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
                situation, moves, attacks, pos, enemy, allow_desperate=True
            )
            mixed_value += 0.5 * situation.kill_pressure(enemy) - 0.05 * enemy.ship.shields
            if mixed_plan and mixed_value > best_mixed[3]:
                best_mixed = (mixed_plan, mixed_attack, mixed_pos, mixed_value)
        if best_mixed[0] and best_mixed[3] > best_value + 0.08:
            plans.append(best_mixed[0])
            moves, attacks = _consume_plan(best_mixed[0], moves, attacks)
            pos = _pos_after_attack_stack(best_mixed[2], [best_mixed[1]] if best_mixed[1] else [])
            continue
        if best_enemy is not None and best_combo:
            allow_desperate = best_value > 1.0 or situation.kill_pressure(best_enemy) > 0.5
            plan, consumed = _attack_stack(
                situation,
                attacks,
                pos,
                best_enemy,
                allow_desperate=allow_desperate,
                overdrive_threshold=0.5,
                allow_overdrive=overdrive_budget > 0,
            )
            if plan:
                if plan.seal_mode == SealMode.OVERDRIVE:
                    overdrive_budget -= 1
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                pos = _pos_after_attack_stack(pos, consumed)
                continue
        # No worthwhile shot: reposition toward the juiciest target, kiting if hurt.
        target = min(
            situation.enemies,
            key=lambda enemy: hex_distance(pos.q, pos.r, enemy.ship.q, enemy.ship.r)
            - 3 * situation.kill_pressure(enemy),
            default=None,
        )
        if target is not None and moves:
            if situation.fragile():
                plan, moves, pos = _defensive_move(situation, moves, pos)
                if plan:
                    moves, attacks = _consume_plan(plan, moves, attacks)
                    plans.append(plan)
                    continue
            far_from_target = hex_distance(pos.q, pos.r, target.ship.q, target.ship.r) > 4
            option = _chase_move(
                situation,
                moves,
                pos,
                target,
                allow_desperate=False,
                allow_overdrive=overdrive_budget > 0 and far_from_target,
            )
            if option:
                if option.overdrive:
                    overdrive_budget -= 1
                plans.append(option.plan)
                moves, attacks = _consume_plan(option.plan, moves, attacks)
                pos = option.end
                continue
        # Out of moves: take the least-bad shot rather than passing.
        fallback_enemy = min(
            situation.enemies,
            key=lambda enemy: hex_distance(pos.q, pos.r, enemy.ship.q, enemy.ship.r),
            default=None,
        )
        if fallback_enemy is not None:
            plan, consumed = _attack_stack(
                situation, attacks, pos, fallback_enemy, allow_desperate=False, overdrive_threshold=2.0
            )
            if plan:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                pos = _pos_after_attack_stack(pos, consumed)
                continue
        plans.append(StackPlan())
    return _finalize(plans)


# --------------------------------------------------------------------------
# StarBreach co-op planner
# --------------------------------------------------------------------------


def _coop_boss_target(state: GameState, pos: Pos) -> tuple[str, tuple[int, int]] | None:
    """Nearest intact boss token area."""
    sb = state.star_breach
    if sb is None:
        return None
    from starshot.rules import star_breach as sb_data
    from starshot.rules import star_breach_spec as sb_spec

    spec = sb_spec.spec_for(sb)
    if len(sb.destroyed_hexes) >= sb_spec.hull_size(spec):
        return None
    token = sb_data.boss_board_hexes(sb.anchor_q, sb.anchor_r, sb.facing)
    areas = dict(zip(token, sb_spec.board_hex_areas(spec)))
    if not areas:
        return None
    hex_q, hex_r = min(areas, key=lambda h: hex_distance(pos.q, pos.r, h[0], h[1]))
    return f"boss:{areas[(hex_q, hex_r)]}", (hex_q, hex_r)


def _coop_craft_target(state: GameState, pos: Pos) -> tuple[str, tuple[int, int]] | None:
    """Nearest living enemy fleet craft."""
    sb = state.star_breach
    if sb is None:
        return None
    crafts = [craft for craft in sb.fleet if not craft.destroyed]
    if not crafts:
        return None
    nearest = min(crafts, key=lambda craft: hex_distance(pos.q, pos.r, craft.q, craft.r))
    return f"craft:{nearest.id}", (nearest.q, nearest.r)


def _coop_enemy_target(state: GameState, pos: Pos, ai_type: str) -> tuple[str, tuple[int, int]] | None:
    if ai_type == "blaster":
        return _coop_boss_target(state, pos) or _coop_craft_target(state, pos)
    return _coop_craft_target(state, pos) or _coop_boss_target(state, pos)


def _coop_repair_plan(
    state: GameState,
    me: PlayerState,
    pos: Pos,
    attacks: list[AttackUse],
) -> StackPlan | None:
    """Engineer repair is ally-only: choose living player ships, never boss/fleet targets."""
    if "engineer" not in me.roles or not attacks:
        return None
    candidates = [
        player
        for player in state.players.values()
        if not player.eliminated
        and not player.ship.destroyed
        and (player.ship.destroyed_components or player.ship.shields == 0)
        and hex_distance(pos.q, pos.r, player.ship.q, player.ship.r) <= 4
    ]
    if not candidates:
        return None
    patient = max(candidates, key=lambda player: (len(player.ship.destroyed_components), -hex_distance(pos.q, pos.r, player.ship.q, player.ship.r)))
    use = next((candidate for candidate in attacks if not candidate.is_desperate), attacks[0])
    return StackPlan(cards=[_targeted(use.selection, use.effect, patient.id)])


def _coop_attack_plan(target_id: str, attacks: list[AttackUse]) -> StackPlan | None:
    usable = [use for use in attacks if not use.is_desperate] or list(attacks)
    if not usable:
        return None
    cards: list[OrderCardSelection] = []
    used_ids: set[str] = set()
    for use in usable:
        if use.selection.card_id in used_ids:
            continue
        cards.append(_targeted(use.selection, use.effect, target_id))
        used_ids.add(use.selection.card_id)
        if len(cards) == 2:
            break
    return StackPlan(cards=cards) if cards else None


def _coop_move_toward(
    situation: Situation,
    moves: list[MoveUse],
    pos: Pos,
    target_hex: tuple[int, int],
) -> tuple[StackPlan | None, Pos]:
    options = _move_stack_options(
        [use for use in moves if not use.is_desperate],
        pos,
        allow_overdrive=False,
        rules=situation.rules,
    )
    if not options:
        return None, pos
    best = min(options, key=lambda option: hex_distance(option.end.q, option.end.r, target_hex[0], target_hex[1]))
    return best.plan, best.end


def _plan_star_breach(situation: Situation, ai_type: str) -> OrdersSubmission:
    state, me = situation.state, situation.me
    sb = state.star_breach
    assert sb is not None
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    if ai_type == "vault_runner":
        fang = next((vault for vault in state.vaults if vault.is_fang), None)
        targets = _round_vaults(state, me)
        goal = (targets[0].q, targets[0].r) if targets else ((fang.q, fang.r) if fang else None)
        if goal:
            route = _plan_route(situation, moves, goal[0], goal[1], 3, allow_desperate=True)
            if route:
                for option in route[:3]:
                    plans.append(option.plan)
                    moves, attacks = _consume_plan(option.plan, moves, attacks)
                    pos = option.end

    while len(plans) < 3:
        repair = _coop_repair_plan(state, me, pos, attacks)
        if repair is not None:
            plans.append(repair)
            moves, attacks = _consume_plan(repair, moves, attacks)
            continue

        target = _coop_enemy_target(state, pos, ai_type)
        if target is not None and attacks:
            target_id, target_hex = target
            plan = _coop_attack_plan(target_id, attacks)
            if plan is not None:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                continue
        if target is not None and moves:
            target_hex = target[1]
            plan, new_pos = _coop_move_toward(situation, moves, pos, target_hex)
            if plan is not None:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                pos = new_pos
                continue
        plans.append(StackPlan())
    return _finalize(plans)


_PLANNERS = {
    "vault_runner": _plan_vault_runner,
    "hunter_killer": _plan_hunter_killer,
    "blaster": _plan_blaster,
}


def build_ai_orders(state: GameState, player_id: str, ai_type: str, ai_level: str = "pirate_king") -> OrdersSubmission:
    me = state.players[player_id]
    seed_material = (state.rng_seed or 1) * 31 + len(state.event_log)
    situation = Situation(state, me, Random(seed_material), _active_ai_rules())
    planner = (lambda s: _plan_star_breach(s, ai_type)) if state.star_breach is not None else _PLANNERS.get(ai_type, _plan_blaster)
    try:
        orders = planner(situation)
        if ai_level == "deck_hand":
            # Deck Hands know the personality's broad plan, but they avoid
            # advanced tempo spending. Buccaneers and Pirate Kings use the
            # full planner today; this keeps the level model explicit without
            # rewriting each personality into three separate bots.
            orders = OrdersSubmission(
                stacks=tuple(
                    replace(stack, seal_mode=SealMode.SEALED)
                    for stack in orders.stacks
                )  # type: ignore[arg-type]
            )
        return orders
    except Exception:
        return fallback_orders()
