# My body and the world's clock at the rules' precision

Perception parity, phase 0 (the audit's class **A\***: facts a character's graphs read more precisely than the player's HUD showed them). Graphs test hunger and energy against any number (`{"hunger": {"above": 55}}`, `{"energy": {"below": 25}}`), and weigh them continuously (`brain.rs` `desires`: `hunger / 100`, `starving` at 90 or more, `exhausted` at 10 or less). They test the hour against any number (`{"hour": {"above": 17.5, "below": 22}}`) and the season (`winter`). The HUD showed hunger and energy only as pills, the hour only as the sky, and no season. Two quiet items now give these facts at that precision. Nothing in the rules changed.

- **The body's tooltip** (`ui/cluster.rs` `body_tip`, the shared tooltip through the `prim::Tip` primitive): with the cursor on the meters or the pills (tag `body`), "Body" lists every meter of the world's `meters()`. That includes those with `shown: false`, such as energy and hunger, which stay off the bars. Each meter is a whole number over its max, cut down rather than rounded. A graph compares the exact value, so a shown N means at least N and under N + 1: `below N` holds exactly when the shown number is under N, and `above N` when it is N or more (except at exactly N). Each line carries the rules' word for that meter (`status_of`'s status that names it, a plain one too: "Peckish", "A little tired"). The words are the rules' own, which read whole numbers rounded (`BodyFacts`). The pills are unchanged.
- **The clock** (`ui/top.rs` `clock`, tag `clock`): a small chip left of the compass shows a sun, or a moon when the rules' `daylight` law says it is night, then the world's hour to the minute and the season. The hour comes from `living_rules::hour_of` on the `world` row at the displayed server time, cut down so 05:59.6 is not shown as dawn. The `daylight` law is read per game minute. Hovered, its tooltip reads "Day N · HH:MM", then "Season, day k of n. It is day." or "… night.", with the season's days cut as `season_of` cuts the world's `year_days`.

The dump carries both: `me.body` (each meter's name, label, value, max, `shown` and `word`), `me.body_tip` (the tooltip's text as built), and `clock` (`hour`, `text`, `night`, `season`, `season_word`, `day`, `season_day`, `season_days`, `tip`). `extra.tooltip` is the tooltip shown, and the tags hold `body` and `clock`.

## Driving it with drive.py

- **Vitals.** `--sync 'v=sql|UPDATE vitals SET hunger = 62.0, energy = 22.0, at_ms = {now_ms}, rate_key = 0 WHERE id = {me}'` (owner SQL, a scene fixture; `{now_ms}` is the authority's `clock.last_ms`), then `cursor:@body;wait:0.6;dump:v`.
- **Clock.** `{epoch_at:23.5}` makes it 23:30 today, and `{epoch_at:12:7}` noon on the world's day 7, which on the island's 8-day year is winter's first day: `--sync 'w=sql|UPDATE world SET epoch_ms = {epoch_at:12:7} WHERE id = 0'`, then `cursor:@clock`.
- Scenario: `check.py --run $R body-clock` (37 checks). Five states cross every pill word and the graphs' cut points (hunger 15 40 45 50 55 60 80 88 90 97, energy 10 12 20 25 30 50 60 70 85 90). Each checks the tooltip as built, that hunger and energy are in it but on no bar, the numbers within the rates' drift, every cut point's side, the rules' words, and the pills unchanged. Then come noon (12:15), 23:30 (night, the moon), autumn's last day and winter's first, with the clock's tooltip. The scene puts the world's epoch back and resets the vitals to fed and rested at its end (`sync:back`).

## Gotchas

- The world's minutes go on between dumps (the island's day is short): compare a tooltip with the clock of its own dump.
- The night still is dark by design, and the sky is the only other sign of the hour.
- A day of 1 needs an hour at or after 07:00: the world starts at 07:00 on day 1, so an earlier hour is on day 2 (`{epoch_at:5:2}`).
- Bedtime, evening and working hours (the private `rhythm` table, the audit's class C) are not shown: a player has no rhythm row and sets their own day.
