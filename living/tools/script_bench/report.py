#!/usr/bin/env python3
"""Markdown tables from a run.sh output directory (and stdb_energy.py results).
usage: report.py OUT_DIR"""
import json
import os
import re
import sys
from collections import defaultdict

out = sys.argv[1]


def load(name):
    p = os.path.join(out, name)
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


native = {(d["engine"], d["law"]): d for d in load("native.jsonl") if "law" in d}
fuel = {(d["engine"], d["law"]): d for d in load("wasm-fuel.jsonl") if "law" in d}
nofuel = {(d["engine"], d["law"]): d for d in load("wasm-no-fuel.jsonl") if "law" in d}
ENGINES = ["native", "rhai", "rhai-lean", "rhai-map-only", "rune", "wasmi", "wasmi-fuel", "piccolo", "koto", "mlua"]
LAWS = ["rates", "strike", "cooldown"]


def us(ns):
    if ns is None:
        return "—"
    if ns < 1000:
        return f"{ns / 1000:.3f}"
    return f"{ns / 1000:.2f}" if ns < 10000 else f"{ns / 1000:.1f}"


print("### Time per call under SpacetimeDB's wasmtime configuration (fuel on), µs\n")
print("| engine | rates p50 | rates p99 | strike p50 | strike p99 | cooldown p50 | cooldown p99 | × native (rates) |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
base = fuel.get(("native", "rates"), {}).get("p50_ns")
for e in ENGINES:
    if (e, "rates") not in fuel:
        continue
    r = [fuel[(e, l)] for l in LAWS]
    ratio = f"{r[0]['p50_ns'] / base:.0f}×" if base else ""
    print(f"| {e} | " + " | ".join(f"{us(x['p50_ns'])} | {us(x['p99_ns'])}" for x in r) + f" | {ratio} |")

print("\n### Fuel (WASM instructions) per call, and the cost of metering\n")
print("| engine | rates fuel | strike fuel | cooldown fuel | rates p50 no fuel (µs) | strike p50 no fuel (µs) | metering overhead (rates) |")
print("|---|---:|---:|---:|---:|---:|---:|")
for e in ENGINES:
    if (e, "rates") not in fuel:
        continue
    f = [fuel[(e, l)]["fuel_per_call"] for l in LAWS]
    nf = [nofuel.get((e, l), {}).get("p50_ns") for l in LAWS]
    oh = f"{fuel[(e, 'rates')]['p50_ns'] / nf[0] - 1:+.0%}" if nf[0] else "—"
    print(f"| {e} | {f[0]:,.0f} | {f[1]:,.0f} | {f[2]:,.0f} | {us(nf[0])} | {us(nf[1])} | {oh} |")

print("\n### Native x86_64 reference, µs (p50; same code, same fixtures)\n")
print("| engine | rates | strike | cooldown | WASM/native (rates) | compile/load ms |")
print("|---|---:|---:|---:|---:|---:|")
for e in ENGINES:
    if (e, "rates") not in native:
        continue
    n = [native[(e, l)]["p50_ns"] for l in LAWS]
    w = fuel.get((e, "rates"), {}).get("p50_ns")
    ratio = f"{w / n[0]:.1f}×" if w else "does not build"
    print(f"| {e} | {us(n[0])} | {us(n[1])} | {us(n[2])} | {ratio} | {native[(e, 'rates')]['init_ms']:.2f} |")

print("\n### Load time, module size and linear memory (wasm32, fuel on)\n")
sizes = {}
for line in open(os.path.join(out, "sizes.txt")):
    m = re.search(r"\s(\d+)\s+\w+\s+\d+\s+[\d:]+\s+(\S+)\.wasm$", line)
    if m:
        sizes[m.group(2)] = int(m.group(1))
module_of = {"native": "none", "rhai": "rhai", "rhai-lean": "rhai", "rhai-map-only": "rhai", "rune": "rune", "wasmi": "wasmi", "wasmi-fuel": "wasmi", "piccolo": "piccolo", "koto": "koto"}
print("| engine | module size | + over baseline | compile/load (ms) | compile/load fuel | memory after load | + after runs |")
print("|---|---:|---:|---:|---:|---:|---:|")
for e in ENGINES:
    if (e, "rates") not in fuel:
        continue
    d = fuel[(e, "rates")]
    last = fuel[(e, "cooldown")]
    size = sizes.get(module_of[e], 0)
    print(
        f"| {e} | {size / 1024:,.0f} KiB | {(size - sizes['none']) / 1024:,.0f} KiB | {d['init_ms']:.2f} | {d['init_fuel']:,} | "
        f"{(d['mem_after_init'] - d['mem_before_init']) / 1024:,.0f} KiB | {(last['mem_after_run'] - d['mem_after_init']) / 1024:,.0f} KiB |"
    )
print(f"\nBaseline module (fixtures + native laws only): {sizes.get('none', 0) / 1024:,.0f} KiB; its linear memory after fixtures: {fuel[('native', 'rates')]['mem_base'] / 1024:,.0f} KiB.")

st = load("stdb-energy.jsonl")
if st:
    names = {0: "native", 1: "rhai", 9: "rhai-lean", 3: "rune", 4: "wasmi"}
    groups = defaultdict(list)
    base = {}
    for d in st:
        if "error" in d:
            continue
        k = (names.get(d["engine"], str(d["engine"])), LAWS[d["law"]])
        if d["n"] == 0:
            base[k] = d
        else:
            groups[k].append(d)
    print("\n### Calibration: the same calls in a real SpacetimeDB 2.14.1 reducer\n")
    print("Energy is the reducer's `energy_quanta_used` (= wasmtime fuel); time is its host execution duration. Both are per call: (N-call reducer − empty reducer) / N, median of 5.\n")
    print("| engine | law | N | energy/call (host) | fuel/call (harness) | host µs/call | harness µs/call (p50) | host/harness time |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    for (e, l), ds in groups.items():
        b = base.get((e, l), {"energy": 0, "host_us": 0})
        n = ds[0]["n"]
        en = sorted((d["energy"] - b["energy"]) / n for d in ds)[len(ds) // 2]
        t = sorted((d["host_us"] - b["host_us"]) / n for d in ds)[len(ds) // 2]
        h = fuel.get((e, l), {})
        hf = h.get("fuel_per_call")
        ht = h.get("p50_ns")
        print(f"| {e} | {l} | {n:,} | {en:,.0f} | {hf:,.0f} | {t:.3f} | {ht / 1000:.3f} | {t * 1000 / ht:.2f} |")
