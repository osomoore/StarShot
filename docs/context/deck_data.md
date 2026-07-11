# StarShot Deck Data

The starting deck and shared Desperation deck are loaded from TOML files. The default deck set is:

```text
resources/decks/core_0_2/
```

It contains:

- `manifest.toml`: deck set id, display name, and rules version.
- `base_deck.toml`: cards copied into each player's starting deck.
- `desperation_deck.toml`: cards used for the shared Desperation deck.

## Selecting A Deck Set

By default the server uses `resources/decks/core_0_2`.

To start the dev server with a different deck set:

```powershell
python scripts\server_control.py start --deck-set path\to\deck_set
```

The lower-level CLI accepts the same deck-set path:

```powershell
python -m starshot.cli --deck-set path\to\deck_set new-game --players red blue
```

You can also set the environment variable directly:

```powershell
$env:STARSHOT_DECK_SET = "path\to\deck_set"
```

`GET /api/health` reports the active `deck_set_id` and filesystem path.

## Editing Cards

Cards are defined as prototypes. You provide the English name and copy count; concrete card ids are generated from the name:

```toml
copy_id_style = "always_suffix"

[[cards]]
name = "Controlled Move 1"
copies = 3
side_a_type = "Basic"
side_a_1 = "Move 1"
side_b_type = "Basic"
side_b_1 = "Turn Left, Move 1"
side_b_2 = "Turn Right, Move 1"
```

`copies` can be a number. Generated ids use a slug made from the card name plus `_a`, `_b`, `_c`, and so on. By default, one-copy cards keep the base slug, e.g. `desp_turbo_ions`. If the file sets `copy_id_style = "always_suffix"`, one-copy cards also get a suffix, e.g. `targeted_attack_aim_2_a`.

Desperation cards use the same side fields:

```toml
[[cards]]
name = "Steady Shot"
copies = 3
side_a_type = "Basic"
side_a_1 = "Move 2"
side_a_2 = "Attack Aim +2"
side_b_type = "Desperate"
side_b_1 = "Attack Aim +2, Damage +1"
```

Deferred Desperate faces are represented by omitting a Desperate side. Playing that Desperate face is rejected by the rules engine.

For cards with no basic face, omit any Basic side and provide only Desperate sides. The loader automatically returns these cards to the Desperation deck after they are played.

```toml
[[cards]]
name = "Afterburners"
copies = 5
side_a_type = "Desperate"
side_a_1 = "Move 3"
side_b_type = "Desperate"
side_b_1 = "Turn Right, Move 3"
side_b_2 = "Turn Left, Move 3"
```

## Supported Card Text

The card-text parser is controlled English, not free-form prose. Supported primitive phrases are:

- `Move N`
- `Move N Right`
- `Move N Left`
- `Turn Right Twice then Move N`
- `U-Turn then Move N`
- `Attack`
- `Targeted Attack`
- `Attack Aim +N`
- `Targeted Attack Aim +N`
- `Attack Damage +N`
- `Targeted Attack Damage +N`
- `Aim +N`
- `Damage +N`
- `Defense +N`
- `Range N`
- `Always Hits`
- `Attack All`
- `Warp behind VP leader`
- `Move Overheat to Discard`
- `Lead the Target`

Use multiple `side_a_N` / `side_b_N` entries for choices on the same side:

```toml
side_a_type = "Basic"
side_a_1 = "Move 2"
side_a_2 = "Attack Aim +2"

side_b_type = "Desperate"
side_b_1 = "U-Turn then Move 3"
side_b_2 = "U-Turn Attack Aim +3"
```

The older compact `basic = "Move 2 or Attack Aim +2"` and `desperate = [...]` fields are still accepted, but the side fields are the preferred deck-authoring format.

Use comma-separated phrases for ordered effects:

```toml
side_b_1 = "Turn Left, Move 2"
```

Simple double-basic, double-desperate, mixed move/attack, and mixed orientation sides are supported. Advanced or bespoke effects should stay as named code-backed phrases added to the parser and rules engine.

## Load-Time Validation

The loader rejects invalid data before gameplay starts. It checks for:

- Missing `manifest.toml`, `base_deck.toml`, or `desperation_deck.toml`.
- Duplicate concrete card ids.
- Card ids appearing in both base and Desperation decks.
- Unknown families, orientations, or warp destinations.
- Wrong value types such as string numbers or boolean numbers.
- Negative card values or invalid Desperate-face damage.
- No-basic-face cards without a Desperate face.

The loader also smoke-tests each card through the existing card-effect interpreter.

## Save-Game Compatibility

New games store their `deck_set_id`. Submitting orders or resolving a game fails if the saved game's deck set does not match the active server deck set.

This is intentional: order resolution still uses card ids plus the active catalog. Restart the server with the original deck set to continue an old game.
