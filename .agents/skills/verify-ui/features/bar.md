# The cluster and the skill bar

The bars over the slots are the world's `meters()` (the shown ones, in order: health and energy in the shipped script; stamina and mana appear from a world's rows), each moved along its rate between updates; the pills are its `status_of` statuses, none plain (the body's words when all is well). The dump's `me` has both.

The cluster at the bottom: the meters (health, energy) over the skill bar. Which skill sits where is the rules' (`living_rules::ui::bar_places` over the world's script: declared `place`/`order` first, then by aim); each slot's label and look come from the skill's `UiSpec` (`<skill>_ui()` in `skills.rhai`, else its defaults). The slot primitive (`ui/prim.rs`) draws the glyph, the key, a count, a cooldown sweep, a held ring, greying with a reason and the refusal flash; the tooltip over a slot gives its label, why it is greyed, and the skill's help. The weapon (`weapon.rs`) is a client-side restriction: sheathed, the hostile slots are greyed and the first hostile press draws; X toggles.

## Sub-features

- `places`: LMB primary (strike), RMB secondary (bow shot), Q E R the skill keys (block, heal, fire bolt), Space jump, a double tap dodge; an extra row (4–9) when the bar has more.
- `labels-looks`: declared labels ("Bow shot", "Fire bolt") and icons; the jump has its own icon (`jump`, appended to `ICONS`).
- `sheathe-draw`: sheathed at first ("sheathed" under the weapon slot), hostile slots greyed with "Sheathed: X draws your weapon", X draws and sheathes, the auto-draw when someone turns hostile (Settings › Play).
- `refusal`: a press the rules refuse flashes its slot red and is noted in the rules' words ("No one there to strike"). Grey is a hint: a greyed slot's press is still sent.
- `held`: Q held raises the guard; its slot shows the held ring.
- `tooltip`: hovering a slot.

## How to get to it (user POV)

- Always on screen while playing. Hover a slot with the cursor; X; LMB, RMB, Q E R, Space, a double tap of W A S D.

## Driving it with drive.py

Preconditions: baseline. No scene: the player alone on the square.

- **The rules' places.** The client log's `combat: bar places primary Some("strike"), secondary Some("bowshot"), keys [Some("block"), Some("heal"), Some("firebolt")], jump Some("jump"), dodge Some("dodge")`.
- **Slots as drawn.** `dump:` → `extra.slots["bar:<Place>"]` (`Primary`, `Secondary`, `Skill1`–`Skill3`, `Jump`, `Dodge`, `Weapon`, `Extra4`–`Extra9`): `label`, `key`, `off` (why greyed), `held`, `refused`, `count`, `caption`; `extra.drawn`.
- **Tooltip.** `cursor:@bar:Primary;wait:0.5;dump:NN` → `extra.tooltip.title` "Strike", `text` starting "Sheathed: X draws your weapon".
- **Draw.** `key:KeyX:tap` (or `weapon:draw`) → `drawn` true, the weapon slot's caption "drawn", Primary not greyed.
- **Refused.** With the weapon drawn and nobody under the cursor, `tap` → `slots["bar:Primary"].refused` true and `notes` has the rules' words.
- **Held.** `key:KeyQ:down;wait:0.5;dump:NN;key:KeyQ:up` → `slots["bar:Skill1"].held` true.
- Scenario: `check.py --run $R bar` (11 checks).

## Gotchas

- `refused` lasts about a second; dump within 0.4 s of the press.
- The cursor at `0.5,0.3` is over the square, not a person, so a tap there strikes the air; over a peaceful person a sheathed tap talks instead.
- Costs on the slots show only in the Walnut theme (`Theme.chips`).
