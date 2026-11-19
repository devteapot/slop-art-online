# The cluster and the skill bar

The bars over the slots are the world's `meters()` (the shown ones, in order: health and stamina in the shipped script, and focus under the world's word, "Mana", only while it is short (`while_short`); energy and hunger are `shown: false`, off the screen while they still feed the statuses), each moved along its rate between updates; the pills are its `status_of` statuses, none plain (the body's words when all is well). The dump's `me` has both.

The cluster at the bottom: the meters (health, stamina; mana while short) over the skill bar. Which skill sits where is the rules' (`living_rules::ui::bar_places` over the world's script: declared `place`/`order` first, then by aim); each slot's label and look come from the skill's `UiSpec` (`<skill>_ui()` in `skills.rhai`, else its defaults). The slot primitive (`ui/prim.rs`) draws the glyph, the key, a count, a cooldown sweep, a held ring, greying with a reason and the refusal flash; the tooltip over a slot gives its label, why it is greyed, and the skill's help. The weapon (`weapon.rs`) is a client-side restriction: sheathed, the hostile slots are greyed and the first hostile press draws; X toggles.

## Sub-features

- `places`: LMB primary (strike), RMB secondary (bow shot), Q E R the skill keys (block, heal, fire bolt), Space jump, a double tap dodge; an extra row (4–9) when the bar has more.
- `labels-looks`: declared labels ("Bow shot", "Fire bolt") and icons; the jump has its own icon (`jump`, appended to `ICONS`).
- `sheathe-draw`: sheathed at first ("sheathed" under the weapon slot), hostile slots greyed with "Sheathed: X draws your weapon", X draws and sheathes, the auto-draw when something attacks you (Settings › Play › Weapon: a hit the authority tells, or someone newly hostile to me, `weapon.rs`).
- `refusal`: a press the rules refuse flashes its slot red and is noted in the rules' words ("No one there to strike"). Grey is a hint: a greyed slot's press is still sent.
- `committed`: a windup or a dash, once started, runs its whole course (committed-moves): movement keys wait (the authority holds the walk and resumes it after); a press over it starts nothing but a dash over a windup, and the client predicts nothing of it (no clip, no raised guard: `combat::held`, the authority's `held_by`); the refusal ("in the middle of a dodge") is a quiet note, once. `check.py committed`: a fire bolt with W held in its windup (the dump's `me_at`: drawn and the authority's row stay put, then walk; the bolt's outcome told), then `dodge:D` and Q mid-dodge (the note once, the dodge's 1.5 m+, "sent, not predicted" in client.log).
- `own-outcomes`: with the world's `force_outcomes` law (mind-act-outcome-far), each strike, shot or cast also gets an `own` row in `my_act_outcomes` and an `own` experience line ("You finished: bowshot. …", "it flew out of your sight"). The client makes notes and Log events only from `act` and `record` rows, so `own` rows show nowhere: the bar's refusal stays the one word on a strike, and there is no line per blow. `check.py own` draws, strikes three times at no one, shoots and casts at the ground, opens the Log, and checks the rows exist while no note or Log event (`extra.events` in the dump: the Log's last 12) repeats them.
- `moved`: an act my own move broke off (talk-turns: `act_outcome` code `moved`, its `why` the rules' `moved_off(skill)`, "The look stopped: you moved off before it was done.") is a quiet note, once, whichever way it was sent (a gesture key too: `verbs::outcomes` takes a `moved` row as mine), and one Log event. A skill done on the move (the rules' `on_the_move`: wave, nod) is not broken off, and the client keeps drawing its gesture while the body walks (`town.rs`: only a gesture not done on the move ends when its body moves 0.5 m). `check.py move-off`: at noon on the cleared spot (300, 330), a resident held 2.5 m off; `gesture:appraise:<id>` then W held 0.4 s later (one `moved` row, owner SQL; the note once in the dump's `notes`, its `note_ok` null; once in `extra.events`); then `gesture:wave:<id>` and W 0.4 s later (no `moved` row for the wave, one ok; the dump's `extra.onces` has `wave` for me while `me_at.drawn` has moved over 0.5 m; no failure note).
- `held`: Q held raises the guard; its slot shows the held ring.
- `tooltip`: hovering a slot.

## How to get to it (user POV)

- Always on screen while playing. Hover a slot with the cursor; X; LMB, RMB, Q E R, Space, a double tap of W A S D.

## Driving it with drive.py

Preconditions: baseline. No scene: the player alone on the square.

- **The rules' places.** The client log's `combat: bar places primary Some("strike"), secondary Some("bowshot"), keys [Some("block"), Some("heal"), Some("firebolt")], jump Some("jump"), dodge Some("dodge"), more [...]` (`more` is the extra row).
- **Slots as drawn.** `dump:` → `extra.slots["bar:<Place>"]` (`Primary`, `Secondary`, `Skill1`–`Skill3`, `Jump`, `Dodge`, `Weapon`, `Extra4`–`Extra9`): `label`, `key`, `off` (why greyed), `held`, `refused`, `count`, `caption`; `extra.drawn`.
- **Tooltip.** `cursor:@bar:Primary;wait:0.5;dump:NN` → `extra.tooltip.title` "Strike", `text` starting "Sheathed: X draws your weapon".
- **Draw.** `key:KeyX:tap` (or `weapon:draw`) → `drawn` true, the weapon slot's caption "drawn", Primary not greyed.
- **Refused.** With the weapon drawn and nobody under the cursor, `tap` → `slots["bar:Primary"].refused` true and `notes` has the rules' words.
- **Held.** `key:KeyQ:down;wait:0.5;dump:NN;key:KeyQ:up` → `slots["bar:Skill1"].held` true.
- Scenario: `check.py --run $R bar` (14 checks: 13 of its own and `notes_clear`).

## Gotchas

- `refused` lasts about a second; dump within 0.4 s of the press.
- The cursor at `0.5,0.3` is over the square, not a person, so a tap there strikes the air; over a peaceful person a sheathed tap talks instead.
- Costs on the slots show only in the Walnut theme (`Theme.chips`).
