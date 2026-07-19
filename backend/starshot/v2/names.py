"""Display-name policy: validation, objectionable-name screening, and the
random piratey name generator.

A display name is what other captains see in lobbies, battles, and
leaderboards; the login username stays the stable account id. Names that trip
the screen are still allowed, but the account is flagged: hidden from
leaderboards and excluded from player matchmaking until renamed.
"""

from __future__ import annotations

import random
import re

# Letters, digits, spaces, and light punctuation. 3-24 chars, no edge spaces.
DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9_'.\-][A-Za-z0-9 _'.\-]{1,22}[A-Za-z0-9_'.\-]$")

# Unambiguous slurs/profanity: matched as substrings of the normalized name,
# so separators and leetspeak don't dodge the screen.
_SUBSTRING_BLOCK = (
    "fuck", "cunt", "shit", "nigg", "fagot", "faggot", "kike", "spick", "wetback",
    "chink", "gook", "tranny", "dyke", "coon", "beaner", "raghead", "porch",
    "holocaust", "hitler", "nazi", "swastika", "rapist", "pedo", "paedo",
    "childporn", "cp4", "molest", "goatse", "blowjob", "cumshot", "jizz",
    "dildo", "penis", "vagin", "clitor", "boobs", "titties", "porn",
)

# Innocent words that happen to contain a blocked substring; dropped from the
# name before the substring pass (the Scunthorpe problem).
_ALLOWED_TOKENS = {"scunthorpe", "mishit", "cockpit", "hancock", "matchit"}

# Shorter/ambiguous words: only objectionable as whole words ("Class Act"
# must stay legal), checked token-by-token.
_WORD_BLOCK = {
    "ass", "arse", "bitch", "whore", "slut", "cock", "dick", "prick",
    "twat", "wank", "wanker", "tit", "tits", "cum", "anal", "anus", "rape",
    "sex", "nude", "naked", "hoe", "fag", "spic", "negro", "retard",
    "retarded", "spaz", "kkk", "isis",
}

_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "6": "g", "7": "t",
    "8": "b", "9": "g", "@": "a", "$": "s", "!": "i", "+": "t",
})


def valid_display_name(name: str) -> bool:
    return bool(DISPLAY_NAME_RE.match(name or ""))


# Reserved system identities. Matched as whole normalized tokens, and the
# high-impersonation-risk ones also as substrings so "XxAdminxX" or
# "St4rShot Official" can't pose as staff or system messages.
_RESERVED_TOKENS = {
    "admin", "administrator", "moderator", "mod", "guest", "starshot",
    "system", "server", "official", "staff", "gamemaster",
}
_RESERVED_SUBSTRINGS = ("admin", "moderator", "starshot")


def is_reserved_name(name: str) -> bool:
    """True for names that impersonate admins, system messages, or guests."""
    tokens = _normalized_tokens(name)
    if any(token in _RESERVED_TOKENS for token in tokens):
        return True
    collapsed = "".join(tokens)
    return any(term in collapsed for term in _RESERVED_SUBSTRINGS)


def _normalized_tokens(name: str) -> list[str]:
    lowered = (name or "").lower().translate(_LEET)
    return re.findall(r"[a-z]+", lowered)


def name_is_objectionable(name: str) -> bool:
    """True when the name should hide the player from leaderboards/matchmaking."""
    tokens = _normalized_tokens(name)
    collapsed = "".join(token for token in tokens if token not in _ALLOWED_TOKENS)
    if any(term in collapsed for term in _SUBSTRING_BLOCK):
        return True
    return any(token in _WORD_BLOCK for token in tokens)


# ── random piratey names ───────────────────────────────────────────────────

_FIRST = (
    "Salty", "Rusty", "Crimson", "Barnacle", "Grog", "Peg-Leg", "One-Eye",
    "Stormy", "Dread", "Scurvy", "Iron", "Blacktooth", "Foggy", "Bilge",
    "Cutlass", "Kraken", "Powder-Keg", "Squid-Grip", "Marrow", "Rum-Soaked",
)

_LAST = (
    "Beard", "Hook", "Bones", "Flint", "Silver", "Gale", "Marrow", "Tides",
    "Vane", "Plank", "Anchor", "Mast", "Doubloon", "Keelhaul", "Broadside",
)

# Bad puns, as requested. No real people, keep it family-friendly.
_PUNS = (
    "Captain Obvious",
    "Sir Loots-a-Lot",
    "Long Jane Silverware",
    "Salty McSaltface",
    "Arrrchibald",
    "Captain Hindsight",
    "Walk-the-Plankton",
    "First Mate Checkmate",
    "Chairman of the Board'd",
    "The Dread Pirate Snacks",
    "Boaty McBountyface",
    "Grand Theft Argo",
    "Yo-Ho-Ho-Hum",
    "Captain Quesadilla",
    "Blunder the Sea",
    "Squawk Like a Parrot",
    "Pieces of Eight-ish",
    "Doubloon or Nothing",
    "The Booty Collector",
    "Man O' Warts",
    "Cannonball Runner",
    "Seas the Day",
    "Ships McGee",
    "Aye Aye Ron",
    "Swashbuckle Up",
    "Fishful Thinking",
    "The Kraken Accountant",
    "Plunder Struck",
    "Anchor Management",
    "Wreck-It Ralphina",
)


def random_guest_name(rng: random.Random | None = None) -> str:
    """A system-assigned guest name; the 'Guest' prefix marks temporary
    players everywhere their name appears (players can't take it themselves —
    'guest' is a reserved token)."""
    rng = rng or random.Random()
    for _ in range(50):
        name = f"Guest {rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if len(name) <= 24 and valid_display_name(name):
            return name
    return "Guest Salty Bones"


def random_pirate_name(rng: random.Random | None = None) -> str:
    """A random piratey display name — half puns, half generated titles."""
    rng = rng or random.Random()
    for _ in range(20):
        if rng.random() < 0.5:
            name = rng.choice(_PUNS)
        else:
            first, last = rng.choice(_FIRST), rng.choice(_LAST)
            name = rng.choice((f"Captain {first} {last}", f"{first} {last}", f"{first}beard {last}"))
        if valid_display_name(name) and not name_is_objectionable(name):
            return name
    return "Captain Salty Bones"
