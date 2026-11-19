#!/usr/bin/env python3
"""Regenerate the fast-lane battle report from saved run directories."""
import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
import gzip
import json
import math
import re
from pathlib import Path
from statistics import mean, median

from verify_steering import pose

ATTACKS = {"strike", "attack", "bowshot", "firebolt", "shoot", "throw"}
RETREATS = {"back_off", "flee"}
DAMAGE = re.compile(r"(?:hit for (\d+)|blocked, (\d+) got through|killed .+ \((\d+)\))$")
DEFENCES = {"dodge", "block", "jump"}
# Historical USD per million tokens, as recorded in model_cost.py for this run's model.
FLASH_PRICES = (0.30, 0.007, 1.20)


def read_json(path):
    return json.loads(path.read_text())


def read_lines(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def share(met, blows):
    return {"met": met, "blows": blows, "pct": 100 * met / blows if blows else None}


def taken_from_samples(rows, prefix=""):
    return share(sum(r["defence"][prefix + "met"] for r in rows),
                 sum(r["defence"][prefix + "blows"] for r in rows))


def skill_snapshot(path, head, patches):
    # spawn_crowd returns new Walker IDs in ascending order. The first spawn
    # assigns fighters first, then the walker controls. Later spawns are refills.
    previous = {r["id"] for r in read_json(path / "chars-probe.json")}
    spawned = sorted(r["id"] for r in read_json(path / "chars.json")
                     if r["id"] not in previous and r["name"].startswith("Walker"))
    fighters = set(spawned[:head["battle"]] + spawned[head["battle"] + head["walkers"]:])
    uses = read_json(path / "skill-uses.json")
    defence_times = defaultdict(list)
    for row in sorted(uses, key=lambda r: r["accepted_ms"]):
        if row["accepted_ms"] and row["skill"] in DEFENCES:
            defence_times[row["actor"]].append(row["accepted_ms"])

    groups = defaultdict(list)
    pairs = defaultdict(list)
    unreleased = 0
    for row in uses:
        start, end = row["accepted_ms"], row["released_ms"]
        actor, target = row["actor"], row["target"]
        if not start or row["skill"] not in ATTACKS or target not in fighters:
            continue
        if end < start:
            unreleased += 1
            continue
        times = defence_times[target]
        index = bisect_left(times, start)
        met = index < len(times) and times[index] <= end
        groups["overall"].append(met)
        if target in patches:
            cohort = "after" if patches[target] <= start else "before"
            groups[cohort].append(met)
        if actor in fighters and actor != target:
            pairs[tuple(sorted((actor, target)))].append(start)

    # Observed fighter-pair bouts, split at a gap over five seconds.
    # Both ends can be censored by the retained export or per-actor retention.
    durations = []
    for times in pairs.values():
        times.sort()
        first = last = times[0]
        for at in times[1:]:
            if at - last > 5000:
                durations.append((last - first) / 1000)
                first = at
            last = at
        durations.append((last - first) / 1000)
    timestamps = [r["accepted_ms"] for r in uses if r["accepted_ms"]]
    return {
        "export_span_s": (max(timestamps) - min(timestamps)) / 1000 if timestamps else None,
        "unreleased_attacks": unreleased,
        "timed_defence": {key: share(sum(groups[key]), len(groups[key]))
                          for key in ("overall", "before", "after")},
        "fighter_pairs": len(pairs),
        "multi_attack_bouts": sum(duration > 0 for duration in durations),
        "multi_attack_span_s": percentiles([d for d in durations if d > 0]),
        "observed_bouts": len(durations),
        "bout_span_s_p50": median(durations) if durations else None,
    }


def percentiles(values):
    if not values:
        return None
    values = sorted(values)
    return {"p50": median(values), "p90": values[math.ceil(0.9 * len(values)) - 1]}


def recorded_cost(call):
    if call.get("cost_usd") is not None:
        return call["cost_usd"]
    if call.get("model") != "deepseek-v4-1-flash-1017":
        return None
    prompt, output = call.get("prompt_tokens"), call.get("completion_tokens")
    if prompt is None or output is None:
        return None
    cached = min(prompt, call.get("cached_tokens") or 0)
    regular, discount, completion = FLASH_PRICES
    return ((prompt - cached) * regular + cached * discount + output * completion) / 1_000_000


def fast_stats(path, minutes):
    calls = [row for file in sorted((path / "journal").glob("*.jsonl"))
             for row in read_lines(file) if row.get("purpose") == "fast"]
    costs = [recorded_cost(c) for c in calls]
    installed = {}
    phases = defaultdict(list)
    patch_file = path / "fast-patched.json"
    sample_coverage = []
    if patch_file.exists():
        # Both exports capture the same thought table but only the former has
        # actor/summary and only the latter has timing detail. Use only
        # unambiguous installs (at_ms and sent_ms present, one match per timestamp).
        by_time = defaultdict(list)
        for file in sorted(path.glob("fast-[0-9][0-9].json")):
            rows = read_json(file)
            sample_coverage.append(len(rows))
            by_time.clear()
            for row in rows:
                by_time[row["at_ms"]].append(json.loads(row["detail"]))
        for row in read_json(patch_file):
            if row["summary"].startswith(("kept", "refused")):
                continue
            at, actor = row["at_ms"], row["actor"]
            installed[actor] = min(at, installed.get(actor, at))
            matches = by_time[at]
            if len(matches) != 1 or "sent_ms" not in matches[0]:
                continue
            detail = matches[0]
            issued, picked, sent, model = (detail[k] for k in
                                          ("issued_ms", "picked_ms", "sent_ms", "model_ms"))
            phases["issue_to_install"].append(at - issued)
            phases["delivery"].append(picked - issued)
            phases["prompt_and_local_residual"].append(sent - picked - model)
            phases["model"].append(model)
            phases["admission"].append(at - sent)

    failed = sum(bool(c.get("error")) for c in calls)
    spend = sum(c for c in costs if c is not None)
    return installed, {
        "journal_calls": len(calls), "journal_failures": share(failed, len(calls)),
        "unpriced": costs.count(None), "estimated_usd": spend,
        "estimated_usd_per_min": spend / minutes,
        "patched_actors": len(installed), "fast_thought_samples": sample_coverage,
        "installed_timings": len(phases.get("issue_to_install", [])),
        "phase_ms": {key: percentiles(values) for key, values in phases.items()},
    }


def within_reach(positions, reach):
    """Find contact with any other live fighter in this free-for-all."""
    cells = defaultdict(list)
    touching = set()
    for actor, (x, y) in positions.items():
        cx, cy = math.floor(x / reach), math.floor(y / reach)
        for ix in range(cx - 1, cx + 2):
            for iy in range(cy - 1, cy + 2):
                for other, at in cells.get((ix, iy), []):
                    if math.dist((x, y), at) <= reach:
                        touching.update((actor, other))
        cells[cx, cy].append((actor, (x, y)))
    return touching


def combat_samples(path, head):
    file = path / "combat-samples.jsonl.gz"
    if not file.exists():
        return {"available": False, "reason": "historical run without combat samples"}

    setup = head["combat_sampling"]
    reach, radius = setup["strike_release_reach_m"], setup["away_radius_m"]
    max_gap = 2.5 * setup["period_s"] * 1000
    return_window = setup["reengage_s"] * 1000
    roster, uses, hurt, retreat_starts = {}, {}, {}, set()
    seconds = defaultdict(lambda: defaultdict(float))
    engagements = defaultdict(list)
    previous = None
    longest_gap = errors = samples = 0
    gaps = []
    coverage = []
    with gzip.open(file, "rt") as stream:
        for line in stream:
            sample = json.loads(line)
            if "error" in sample:
                errors += 1
                continue
            samples += 1
            at = sample["at_ms"]
            roster.update({int(i): began for i, began in sample["fighters"].items()})
            activities = {a["id"]: a for a in sample["activities"]}
            bodies = {b["id"]: b for b in sample["bodies"]}
            positions = {i: pose(b, at) for i, b in bodies.items()}
            contact = within_reach(positions, reach)
            for i, a in activities.items():
                if a["skill"] in RETREATS and a["started_ms"] >= roster[i]:
                    retreat_starts.add((i, a["started_ms"], a["skill"]))
            for row in sample["uses"]:
                uses[row["id"]] = row
            for row in sample["hurt"]:
                hurt[row["id"]] = row
            if previous:
                then, old_positions, old_contact, old_idle = previous
                gap = at - then
                longest_gap = max(longest_gap, gap)
                if gap > max_gap:
                    gaps.append((then, at))
                if 0 < gap <= max_gap:
                    if coverage and coverage[-1][1] == then:
                        coverage[-1] = (coverage[-1][0], at)
                    else:
                        coverage.append((then, at))
                    for i, position in old_positions.items():
                        delta = gap / 1000
                        away = math.dist(position, head["site"]) > radius
                        seconds[i]["observed"] += delta
                        seconds[i]["contact"] += delta * (i in old_contact)
                        seconds[i]["away"] += delta * away
                        seconds[i]["idle"] += delta * (i in old_idle)
                        seconds[i]["idle_or_away"] += delta * (away or i in old_idle)
                        if i in contact and i not in old_contact:
                            engagements[i].append(at)
            idle = {i for i in bodies if not bodies[i]["vx"] and not bodies[i]["vy"]
                    and (i not in activities or activities[i]["skill"] in ("wait", "wander"))}
            previous = (at, positions, contact, idle)

    if samples < 2:
        return {"available": False, "reason": "fewer than two usable samples",
                "samples": samples, "sample_errors": errors}

    totals = dict.fromkeys(("attacks_attempted", "engagements_started", "retreats",
                           "retreats_reengaged", "retreats_no_reengagement", "retreats_censored",
                           "damage_taken", "damage_dealt"), 0)
    totals["engagements_started"] = sum(map(len, engagements.values()))
    covered_counts = dict.fromkeys(totals, 0)
    covered_counts["engagements_started"] = totals["engagements_started"]
    coverage_starts = [start for start, _ in coverage]
    last_sample = previous[0]

    def tally(key, at, amount=1):
        totals[key] += amount
        index = bisect_right(coverage_starts, at) - 1
        if index >= 0 and at < coverage[index][1]:
            covered_counts[key] += amount
    retreats = []
    for actor, start, skill in sorted(retreat_starts, key=lambda r: (r[1], r[0], r[2])):
        if start >= last_sample:
            continue
        times = engagements[actor]
        index = bisect_right(times, start)
        deadline = start + return_window
        reengaged = index != len(times) and times[index] <= deadline
        full_window = deadline <= last_sample and not any(left < deadline and start < right
                                                            for left, right in gaps)
        status = "reengaged" if reengaged else "no_reengagement" if full_window else "censored"
        tally("retreats", start)
        tally(f"retreats_{status}", start)
        retreats.append({"actor": actor, "at_ms": start, "skill": skill, "result": status,
                         "reengaged_ms": times[index] if reengaged else None})

    def fighting(actor, at):
        return actor in roster and roster[actor] <= at < last_sample

    for use in uses.values():
        if use["skill"] not in ATTACKS or not use["accepted_ms"]:
            continue
        if fighting(use["actor"], use["accepted_ms"]):
            tally("attacks_attempted", use["accepted_ms"])
        damage = DAMAGE.search(use["outcome"])
        if not damage:
            continue
        amount = int(next(value for value in damage.groups() if value is not None))
        if fighting(use["actor"], use["outcome_ms"]):
            tally("damage_dealt", use["outcome_ms"], amount)
        # The aim is the actual victim for direct skills. A missile may hit another body.
        if use["skill"] not in ("bowshot", "firebolt") and fighting(use["target"], use["outcome_ms"]):
            tally("damage_taken", use["outcome_ms"], amount)
    for row in hurt.values():
        # Missile victim's own percept uses the same rounded damage phrasing.
        damage = DAMAGE.search(row["text"])
        if damage and fighting(row["observer"], row["at_ms"]):
            amount = int(next(value for value in damage.groups() if value is not None))
            tally("damage_taken", row["at_ms"], amount)

    observed = sum(values["observed"] for values in seconds.values())
    fighter_minutes = observed / 60
    time_keys = ("contact", "away", "idle", "idle_or_away")
    for key in time_keys:
        totals[f"{key}_seconds"] = sum(values[key] for values in seconds.values())
        covered_counts[f"{key}_seconds"] = totals[f"{key}_seconds"]
    fighter_shares = {}
    for actor in sorted(roster):
        values = seconds[actor]
        duration = values["observed"]
        fighter_shares[actor] = {"observed_seconds": duration,
                                 **{f"{key}_share": values[key] / duration if duration else None
                                    for key in time_keys}}
    return {
        "available": True, "method": setup, "samples": samples, "sample_errors": errors,
        "longest_sample_gap_s": longest_gap / 1000, "observed_fighter_minutes": fighter_minutes,
        "used_interval_seconds": sum(end - start for start, end in coverage) / 1000,
        "discarded_gap_seconds": sum(end - start for start, end in gaps) / 1000,
        "totals": totals,
        "observed_time_shares": {key: totals[f"{key}_seconds"] / observed if observed else None
                                 for key in time_keys},
        "per_fighter_minute": {key: value / fighter_minutes if fighter_minutes else None
                               for key, value in covered_counts.items()},
        "attacks_per_contact_minute": (60 * covered_counts["attacks_attempted"] / totals["contact_seconds"]
                                       if totals["contact_seconds"] else None),
        "damage_dealt_per_attempt": (covered_counts["damage_dealt"] / covered_counts["attacks_attempted"]
                                     if covered_counts["attacks_attempted"] else None),
        "fighters": fighter_shares,
        "retreats": retreats,
    }


def summarize(path):
    head = read_json(path / "diag-result.json")
    rows = list(read_lines(path / "diag.jsonl"))
    if head["status"] != "done" or not rows:
        raise ValueError(f"expected a completed battle with diagnostic samples in {path}")
    mid = [r for r in rows if r["t_min"] >= 2]
    start, end = rows[0], rows[-1]
    fighter_minutes = 0.0
    previous_fighters = head["battle"]
    hits = blocked = dodged = 0
    hit_windows = []
    seconds = 0.0
    for row in rows:
        bench = read_json(path / f"bench-{row['k']:02d}.json")
        span = bench["seconds"]
        fighter_minutes += span * (previous_fighters + row["fighters_alive"]) / 120
        previous_fighters = row["fighters_alive"]
        seconds += span
        hits += bench["combat"]["hits"]
        hit_windows.append(bench["combat"]["hits"])
        blocked += bench["combat"]["blocked"]
        dodged += bench["combat"]["dodged"]

    patches, fast = fast_stats(path, head.get("minutes", len(rows)))

    def rate(key, windows):
        return mean(r["diag_per_s"].get(key, 0) for r in windows) if windows else None

    tick_samples = [
        {"minute": row["t_min"], "ticks_per_s": row["ticks_per_s"],
         "over_budget": row["over_16_7"], "new_deaths": row["fighter_deaths"] - prev["fighter_deaths"],
         "remains_at_site": row["remains"].get("at_site")}
        for prev, row in zip(rows, rows[1:]) if row in mid
    ]
    return {
        "arm": head["arm"],
        "site": head["site"],
        "world_seed": head.get("world_seed"),
        "layout": head.get("layout"),
        "walker_layout": head.get("walker_layout"),
        "ambient_displaced": head.get("ambient_displaced"),
        "combat": combat_samples(path, head),
        "setup": {key: head[key] for key in ("battle", "walkers", "ambient_at_publish", "refill",
                                              "refill_gap", "refill_from", "keep_plans", "laws")},
        "sampled_defence": taken_from_samples(rows),
        "sampled_post_patch_defence": taken_from_samples(rows, "patched_"),
        "first_window_defence": taken_from_samples([start]),
        "last_five_defence": taken_from_samples(rows[-5:]),
        "skill_snapshot": skill_snapshot(path, head, patches),
        "bench_seconds": seconds, "estimated_bench_fighter_minutes": fighter_minutes,
        "world_hits": hits, "world_blocked": blocked, "world_dodged": dodged,
        "world_hits_first_four": sum(hit_windows[:4]),
        "world_hits_last_six": sum(hit_windows[4:]),
        "world_hits_per_estimated_fighter_min": hits / fighter_minutes,
        "world_hits_per_second": hits / seconds,
        "world_hits_per_resolved_nonmiss_pct": 100 * hits / (hits + blocked + dodged) if hits + blocked + dodged else None,
        "action_rates_per_s": {
            key: [rate(key, windows) for windows in (rows[:4], rows[4:])]
            for key in ("begin:ok:back_off", "begin:ok:flee", "begin:ok:keep_distance",
                        "begin:ok:heal", "act:complete:heal", "onlookers:fight", "noticed:structures")
        },
        "end_deaths": end["fighter_deaths"], "end_respawns": end["respawns"],
        "first_four_respawn_counts": [r["respawns"] for r in rows[:4]],
        "first_four_death_counts": [r["fighter_deaths"] for r in rows[:4]],
        "end_fighters": end["fighters_alive"], "end_arriving": end["arriving"],
        "ticks_per_s": mean(r["ticks_per_s"] for r in mid) if mid else None,
        "over_budget": sum(r["over_16_7"] for r in mid),
        "tick_samples": tick_samples,
        "end_remains_at_site": end["remains"].get("at_site"),
        "fast": fast,
    }


def adjust_ticks(arms, covariate):
    """One pooled within-arm slope, with a separate intercept for each arm."""
    pairs = []
    means = {}
    ranges = {}
    for arm, report in arms.items():
        rows = [row for row in report["tick_samples"] if row[covariate] is not None]
        if not rows:
            continue
        xs = [r[covariate] for r in rows]
        ys = [r["ticks_per_s"] for r in rows]
        mx, my = mean(xs), mean(ys)
        pairs.extend((x - mx, y - my) for x, y in zip(xs, ys))
        means[arm] = mx, my
        ranges[arm] = [min(xs), max(xs)]
    variance = sum(x * x for x, _ in pairs)
    if len(means) < 2 or not variance:
        return None
    slope = sum(x * y for x, y in pairs) / variance
    reference = mean(x for x, _ in means.values())
    return {"ranges": ranges, "slope": slope, "reference": reference,
            "adjusted_ticks_per_s": {arm: y + slope * (reference - x)
                                     for arm, (x, y) in means.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", metavar="RUN",
                        help="saved run directories, in any order")
    args = parser.parse_args()
    arms = {path.name: summarize(path) for path in args.runs}
    if len(arms) != len(args.runs):
        parser.error("run directory names must be distinct")
    by_size = defaultdict(dict)
    for name, arm in arms.items():
        by_size[arm["setup"]["battle"]][name] = arm
    result = {"arms": arms, "estimated_total_usd": sum(a["fast"]["estimated_usd"] for a in arms.values()),
              "tick_adjustments_by_size": {
                  size: {key: adjust_ticks(group, key) for key in ("new_deaths", "remains_at_site")}
                  for size, group in sorted(by_size.items())
              }}
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
