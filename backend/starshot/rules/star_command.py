from __future__ import annotations

from dataclasses import dataclass


EXPANSION_ID = "star_command"


@dataclass(frozen=True, slots=True)
class Captain:
    id: str
    name: str
    callsign: str
    text: str


@dataclass(frozen=True, slots=True)
class Starfall:
    id: str
    name: str
    text: str
    animation: str


CAPTAINS: tuple[Captain, ...] = (
    Captain("malcolm_manderly", 'Malcolm "Sarge" Manderly', "Sarge", "+2 to all Attack Rolls."),
    Captain("anya_andrews", 'Anya "Fura" Andrews', "Fura", "No Shields. Her fourth action is not implemented in this build."),
    Captain("riley_rounder", 'Riley "Turbo" Rounder', "Turbo", "+1 Move from Move cards, but no bonus defense from movement."),
    Captain("danny_davos", 'Danny "Drifter" Davos', "Drifter", "Moves 2 tiles forward at the beginning of Cleanup."),
    Captain("carlos_connor", 'Carlos "Danger" Connor', "Danger", "Gains 1 VP whenever he loses a ship component."),
    Captain("knute_knuckles", 'Knute "Rocky" Knuckles', "Rocky", "Bridge and Life Support components take 2 hits to destroy."),
    Captain("beto_briego", 'Beto "Golden" Briego', "Golden", "+1 VP and +1 Desperation card from Baubles."),
    Captain("davey_locker", 'Davey "Jones" Locker', "Jones", "Gets 2 VP and a Desperation card whenever any Bridge or Life Support is destroyed."),
)


STARFALLS: tuple[Starfall, ...] = (
    Starfall("solar_storm", "Solar Storm", "Roll a single damage die. It applies to all players and penetrates shields.", "storm"),
    Starfall("gravity_burst", "Gravity Burst", "Move all ships 2 tiles towards The Fang.", "gravity"),
    Starfall("clear_skies", "Clear Skies", "All ships roll 3d6 for attacks instead of 2d6 this round.", "clear"),
    Starfall("stars_align", "Stars Align", "Roll a d6, rerolling 6s. The matching round's Baubles open this round.", "align"),
    Starfall("take_cover", "Take Cover", "At the end of this round, deal 2 damage to all players outside of a Bauble's range.", "cover"),
    Starfall("golden_bounty", "Golden Bounty", "This turn, first hits during each Action gain 1 additional VP.", "gold"),
    Starfall("most_dangerous_game", "Most Dangerous Game", "All Baubles 1-5 open this round.", "danger"),
    Starfall("gusty_winds", "Gusty Winds", "All movement cards move players 1 additional tile this round.", "wind"),
    Starfall("jolly_roger", "Jolly Roger", "Attackers gain a Desperation Card the first time they hit an opponent this round.", "roger"),
    Starfall("safe_harbor", "Safe Harbor", "Each ship regains one shield charge, to a maximum of 2.", "harbor"),
)


CAPTAINS_BY_ID = {captain.id: captain for captain in CAPTAINS}
STARFALLS_BY_ID = {starfall.id: starfall for starfall in STARFALLS}


def captain_to_dict(captain: Captain) -> dict:
    return {
        "id": captain.id,
        "name": captain.name,
        "callsign": captain.callsign,
        "text": captain.text,
    }


def starfall_to_dict(starfall: Starfall) -> dict:
    return {
        "id": starfall.id,
        "name": starfall.name,
        "text": starfall.text,
        "animation": starfall.animation,
    }
