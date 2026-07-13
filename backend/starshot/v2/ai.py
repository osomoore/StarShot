"""Server-side AI pilots for StarShot v2.

Three personalities ported from the v1 client-side JS and improved:

- ``bauble_runner`` — plans multi-stack routes to the current round's baubles,
  contests The Fang, and shoots opportunistically with leftover stacks.
- ``hunter_killer`` — commits to one prey, repositions until a volley is
  likely, then fires with overdrive and desperate faces on good odds.
- ``blaster``    — opportunist gunner: every action it fires at whichever
  enemy yields the best expected VP, repositioning only when no shot is worth
  taking, and kites to control range.

Improvements over the v1 JS AI:
- Hit odds use the same math as the engine (2d6 vs distance + movement +
  defense) with a *prediction* of the target's movement from its actual
  movement history, instead of reading the stale previous-action value.
- Own movement is counted as defense when weighing exposure to enemy fire.
- Desperate faces (Afterburners, Thrust/Turbo Ions, Crack Shot, Steady Shot,
  StarShot) are played when they swing the action.
- Overdrive pricing accounts for the 0.3 rules (no overheat pile — the cost is
  drawing the seal card next round).

Candidate orders are interpreted with the engine's own ``interpret_card`` so
the AI can never disagree with the rules about what a card does.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
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

AI_TYPES = {
    "bauble_runner": "Salvage Captain",
    "hunter_killer": "Corsair",
    "blaster": "Gunner",
}

AI_DISPLAY_NAMES = {
    "bauble_runner": "Salvage Captain Morrigan",
    "hunter_killer": "Corsair Blackvane",
    "blaster": "Gunner Redbeard",
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
    if move.double_turn_after_move:
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
        self._movement_history: dict[str, list[int]] = {}
        for event in state.event_log[-200:]:
            if event.get("type") == "movement_resolved" and not event.get("overdrive_copy"):
                history = self._movement_history.setdefault(event.get("player_id", ""), [])
                history.append(int(event.get("movement_this_action", 0)))

    def expected_movement(self, player_id: str) -> float:
        history = self._movement_history.get(player_id, [])[-6:]
        if not history:
            return 2.0
        return sum(history) / len(history)

    def hit_chance(self, from_pos: Pos, enemy: PlayerState, aim: int, lead_target: bool, always_hits: bool) -> float:
        if always_hits:
            return 1.0
        distance = hex_distance(from_pos.q, from_pos.r, enemy.ship.q, enemy.ship.r)
        predicted = 0.0 if lead_target else self.expected_movement(enemy.id)
        needed = distance + round(predicted) - aim
        return p_2d6_at_least(needed)

    def kill_pressure(self, enemy: PlayerState) -> float:
        """How close the enemy is to death: 0 (fresh) .. ~1 (one hit away)."""
        if enemy.ship.shields > 0:
            return 0.0
        return min(1.0, len(enemy.ship.destroyed_components) / 6 + enemy.ship.damage_taken / 10)

    def attack_value(self, from_pos: Pos, enemy: PlayerState, attack_uses: list[AttackUse]) -> float:
        aim = sum(use.effect.attack.aim_bonus for use in attack_uses if use.effect.attack)
        always = any(use.effect.attack.always_hits for use in attack_uses if use.effect.attack)
        lead = any(use.effect.attack.lead_the_target for use in attack_uses if use.effect.attack)
        damage = max((use.effect.attack.base_damage for use in attack_uses if use.effect.attack), default=1)
        damage += sum(use.effect.attack.damage_bonus for use in attack_uses if use.effect.attack)
        p_hit = self.hit_chance(from_pos, enemy, aim, lead, always)
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


def _attack_stack(
    situation: Situation,
    available: list[AttackUse],
    from_pos: Pos,
    enemy: PlayerState,
    allow_desperate: bool,
    overdrive_threshold: float,
) -> tuple[StackPlan | None, list[AttackUse]]:
    """Build an attack stack against the enemy; returns (plan, uses consumed)."""
    combo = _best_attack_uses(situation, available, from_pos, enemy, allow_desperate)
    if not combo:
        return None, []
    aim = sum(use.effect.attack.aim_bonus for use in combo if use.effect.attack)
    always = any(use.effect.attack.always_hits for use in combo if use.effect.attack)
    lead = any(use.effect.attack.lead_the_target for use in combo if use.effect.attack)
    p_hit = situation.hit_chance(from_pos, enemy, aim, lead, always)
    # Overdrive repeats the volley (desperate faces excluded from the copy).
    copies_help = any(not use.is_desperate for use in combo)
    overdrive_legal = situation.rules.allow_overdrive_desperation or not any(use.is_desperate for use in combo)
    seal = (
        SealMode.OVERDRIVE
        if (
            (situation.rules.overdrive_copies_action or situation.rules.overdrive_copies_cards)
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
    overdrive_threshold: float,
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
            p_hit = situation.hit_chance(
                moved_pos,
                enemy,
                attack_use.effect.attack.aim_bonus if attack_use.effect.attack else 0,
                attack_use.effect.attack.lead_the_target if attack_use.effect.attack else False,
                attack_use.effect.attack.always_hits if attack_use.effect.attack else False,
            )
            overdrive_legal = (
                situation.rules.allow_overdrive_desperation
                or not (move_use.is_desperate or attack_use.is_desperate)
            )
            seal = (
                SealMode.OVERDRIVE
                if (
                    (situation.rules.overdrive_copies_action or situation.rules.overdrive_copies_cards)
                    and overdrive_legal
                    and not move_use.is_desperate
                    and not attack_use.is_desperate
                    and p_hit >= overdrive_threshold
                )
                else SealMode.SEALED
            )
            plan = StackPlan(
                cards=[
                    move_use.selection,
                    _targeted(attack_use.selection, attack_use.effect, enemy.id),
                ],
                seal_mode=seal,
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
# Bauble targets
# --------------------------------------------------------------------------


def _round_baubles(state: GameState, me: PlayerState) -> list:
    """Baubles worth chasing this round, best value first."""
    ship = me.ship
    scored = []
    for bauble in state.baubles:
        active = bauble.is_fang or bauble.number == state.round_number
        if not active or me.id in bauble.claimed_by:
            continue
        distance = max(0, hex_distance(ship.q, ship.r, bauble.q, bauble.r) - 1)
        value = bauble.victory_points + (0 if bauble.is_fang else 1)  # numbered: + desperation card
        if bauble.is_fang and state.round_number < 6:
            value = max(1, value - 1)  # Fang bites back before the payoff round
        scored.append((value / (1.0 + distance), distance, bauble))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _plan_route(
    situation: Situation,
    moves: list[MoveUse],
    goal_q: int,
    goal_r: int,
    stacks_available: int,
    allow_desperate: bool,
) -> list[MoveStackOption] | None:
    """Beam search across up to `stacks_available` stacks to land within 1 hex
    of the goal. Returns the stack options per action, or None."""

    def goal_distance(pos: Pos) -> int:
        return max(0, hex_distance(pos.q, pos.r, goal_q, goal_r) - 1)

    Beam = tuple[Pos, list[MoveStackOption], frozenset[str], int]  # pos, plans, used card ids, cost
    beams: list[Beam] = [(situation.pos, [], frozenset(), 0)]
    if goal_distance(situation.pos) == 0:
        return []
    best_finish: list[MoveStackOption] | None = None
    best_cost = 10**9
    for _ in range(stacks_available):
        next_beams: list[Beam] = []
        for pos, plans, used, cost in beams:
            pool = [
                use
                for use in moves
                if use.selection.card_id not in used and (allow_desperate or not use.is_desperate)
            ]
            options = _move_stack_options(pool, pos, allow_overdrive=True, rules=situation.rules)
            options.sort(key=lambda option: goal_distance(option.end))
            for option in options[:12]:
                option_cost = (
                    cost
                    + (2 if option.overdrive else 0)
                    + 3 * option.desperate_count
                    + len(option.plan.cards)
                )
                new_plans = plans + [option]
                if goal_distance(option.end) == 0 and option_cost < best_cost:
                    best_cost = option_cost
                    best_finish = new_plans
                    continue
                new_used = used | {c.card_id for c in option.plan.cards}
                next_beams.append((option.end, new_plans, new_used, option_cost))
        next_beams.sort(key=lambda beam: (goal_distance(beam[0]), beam[3]))
        beams = next_beams[:10]
        if not beams:
            break
    return best_finish


# --------------------------------------------------------------------------
# Personalities
# --------------------------------------------------------------------------


def _plan_bauble_runner(situation: Situation) -> OrdersSubmission:
    state, me = situation.state, situation.me
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    targets = _round_baubles(state, me)
    route: list[MoveStackOption] | None = None
    for bauble in targets[:3]:
        route = _plan_route(situation, moves, bauble.q, bauble.r, 3, allow_desperate=True)
        if route is not None:
            break
    if route:
        for option in route[:3]:
            plans.append(option.plan)
            moves, attacks = _consume_plan(option.plan, moves, attacks)
            pos = option.end

    # Fill remaining stacks: shoot on solid odds, else keep closing on loot.
    while len(plans) < 3:
        best_enemy = None
        best_value = 0.55
        played_mixed_stack = False
        for enemy in situation.enemies:
            combo = _best_attack_uses(situation, attacks, pos, enemy, allow_desperate=False)
            if combo:
                value = situation.attack_value(pos, enemy, combo)
                if value > best_value:
                    best_value, best_enemy = value, enemy
            mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
                situation,
                moves,
                attacks,
                pos,
                enemy,
                allow_desperate=False,
                overdrive_threshold=0.6,
            )
            if mixed_plan and mixed_value > best_value:
                plans.append(mixed_plan)
                moves, attacks = _consume_plan(mixed_plan, moves, attacks)
                pos = mixed_pos
                played_mixed_stack = True
                break
        if played_mixed_stack:
            continue
        if best_enemy is not None:
            plan, consumed = _attack_stack(
                situation, attacks, pos, best_enemy, allow_desperate=False, overdrive_threshold=0.6
            )
            if plan:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                continue
        if situation.fragile() and moves:
            plan, moves, pos = _defensive_move(situation, moves, pos)
            if plan:
                moves, attacks = _consume_plan(plan, moves, attacks)
                plans.append(plan)
                continue
        # No route landed on the bauble: still grind toward it greedily.
        if targets and moves:
            goal = targets[0]
            options = _move_stack_options(
                [use for use in moves if not use.is_desperate],
                pos,
                allow_overdrive=True,
                rules=situation.rules,
            )
            if options:
                best = min(
                    options,
                    key=lambda option: (
                        hex_distance(option.end.q, option.end.r, goal.q, goal.r),
                        1 if option.overdrive else 0,
                    ),
                )
                if hex_distance(best.end.q, best.end.r, goal.q, goal.r) < hex_distance(pos.q, pos.r, goal.q, goal.r):
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


def _chase_move(situation: Situation, moves: list[MoveUse], pos: Pos, enemy: PlayerState, allow_desperate: bool) -> MoveStackOption | None:
    pool = [use for use in moves if allow_desperate or not use.is_desperate]
    options = _move_stack_options(pool, pos, allow_overdrive=True, rules=situation.rules)
    if not options:
        return None

    def score(option: MoveStackOption) -> tuple:
        distance = hex_distance(option.end.q, option.end.r, enemy.ship.q, enemy.ship.r)
        # Ideal firing range is close but not point-blank next action.
        range_penalty = abs(distance - 2)
        return (range_penalty, 3 * option.desperate_count + (1 if option.overdrive else 0), -option.moved)

    return min(options, key=score)


def _plan_hunter_killer(situation: Situation) -> OrdersSubmission:
    prey = _pick_prey(situation)
    if prey is None:
        return fallback_orders()
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    attack_stacks_wanted = min(2, max(1, len({use.selection.card_id for use in attacks})))
    for action in range(3):
        remaining = 3 - action
        combo = _best_attack_uses(situation, attacks, pos, prey, allow_desperate=True)
        p_hit = 0.0
        if combo:
            aim = sum(use.effect.attack.aim_bonus for use in combo if use.effect.attack)
            always = any(use.effect.attack.always_hits for use in combo if use.effect.attack)
            lead = any(use.effect.attack.lead_the_target for use in combo if use.effect.attack)
            p_hit = situation.hit_chance(pos, prey, aim, lead, always)
        must_attack = remaining <= attack_stacks_wanted and combo
        good_shot = combo and p_hit >= 0.5
        allow_mixed_desperate = situation.kill_pressure(prey) > 0.4 or p_hit < 0.25
        mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
            situation,
            moves,
            attacks,
            pos,
            prey,
            allow_desperate=allow_mixed_desperate,
            overdrive_threshold=0.45,
        )
        pure_value = situation.attack_value(pos, prey, combo) if combo else 0.0
        if mixed_plan and (mixed_value >= 0.55 or mixed_value > pure_value + 0.15):
            plans.append(mixed_plan)
            moves, attacks = _consume_plan(mixed_plan, moves, attacks)
            pos = mixed_pos
            attack_stacks_wanted -= 1
            continue
        if good_shot or must_attack:
            # Spend desperate firepower only when it makes the kill likely.
            allow_desperate = situation.kill_pressure(prey) > 0.4 or p_hit < 0.35
            plan, consumed = _attack_stack(
                situation, attacks, pos, prey, allow_desperate=allow_desperate, overdrive_threshold=0.45
            )
            if plan:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
                if consumed:
                    attack_stacks_wanted -= 1
                continue
        option = _chase_move(situation, moves, pos, prey, allow_desperate=p_hit < 0.2)
        if option:
            plans.append(option.plan)
            moves, attacks = _consume_plan(option.plan, moves, attacks)
            pos = option.end
        else:
            plans.append(StackPlan())
    return _finalize(plans)


def _plan_blaster(situation: Situation) -> OrdersSubmission:
    moves = list(situation.hand_moves)
    attacks = list(situation.hand_attacks)
    plans: list[StackPlan] = []
    pos = situation.pos

    for _ in range(3):
        best_enemy, best_combo, best_value = None, None, 0.35
        best_mixed: tuple[StackPlan | None, Pos, float] = (None, pos, 0.35)
        for enemy in situation.enemies:
            combo = _best_attack_uses(situation, attacks, pos, enemy, allow_desperate=True)
            if not combo:
                continue
            value = situation.attack_value(pos, enemy, combo)
            # Prefer finishing wounded prey and stealing the last shields.
            value += 0.5 * situation.kill_pressure(enemy) - 0.05 * enemy.ship.shields
            if value > best_value:
                best_enemy, best_combo, best_value = enemy, combo, value
            mixed_plan, mixed_move, mixed_attack, mixed_pos, mixed_value = _mixed_move_attack_stack(
                situation,
                moves,
                attacks,
                pos,
                enemy,
                allow_desperate=True,
                overdrive_threshold=0.5,
            )
            mixed_value += 0.5 * situation.kill_pressure(enemy) - 0.05 * enemy.ship.shields
            if mixed_plan and mixed_value > best_mixed[2]:
                best_mixed = (mixed_plan, mixed_pos, mixed_value)
        if best_mixed[0] and best_mixed[2] > best_value + 0.08:
            plans.append(best_mixed[0])
            moves, attacks = _consume_plan(best_mixed[0], moves, attacks)
            pos = best_mixed[1]
            continue
        if best_enemy is not None and best_combo:
            allow_desperate = best_value > 1.0 or situation.kill_pressure(best_enemy) > 0.5
            plan, consumed = _attack_stack(
                situation, attacks, pos, best_enemy, allow_desperate=allow_desperate, overdrive_threshold=0.5
            )
            if plan:
                plans.append(plan)
                moves, attacks = _consume_plan(plan, moves, attacks)
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
            option = _chase_move(situation, moves, pos, target, allow_desperate=False)
            if option:
                plans.append(option.plan)
                moves, attacks = _consume_plan(option.plan, moves, attacks)
                pos = option.end
                continue
        plans.append(StackPlan())
    return _finalize(plans)


_PLANNERS = {
    "bauble_runner": _plan_bauble_runner,
    "hunter_killer": _plan_hunter_killer,
    "blaster": _plan_blaster,
}


def build_ai_orders(state: GameState, player_id: str, ai_type: str) -> OrdersSubmission:
    me = state.players[player_id]
    seed_material = (state.rng_seed or 1) * 31 + len(state.event_log)
    situation = Situation(state, me, Random(seed_material), _active_ai_rules())
    planner = _PLANNERS.get(ai_type, _plan_blaster)
    try:
        return planner(situation)
    except Exception:
        return fallback_orders()
