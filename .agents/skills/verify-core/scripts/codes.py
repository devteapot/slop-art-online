#!/usr/bin/env python3
"""Stable presentation codes across script installs (docs/COMBAT.md, "Presentation codes").

    codes.py RUN    # after `verify.py launch --run RUN`

Installs the shipped script plus a combat skill and a shown skill that sort first, then swaps
them for two that sort last, then the shipped script again, and checks `skill_card` and
`act_card` codes: existing codes never change, new skills take fresh codes, removed codes are
not reused. Admin reducer: `install_script`. Python standard library only.
"""
import json, subprocess, sys, pathlib
V = ".agents/skills/verify/scripts/verify.py"; R = sys.argv[1]
base = pathlib.Path("living/scripts/skills.rhai").read_text()
def sql(q):
    out = subprocess.run(["python3", V, "sql", "--run", R, q, "--as-admin"], capture_output=True, text=True, check=True).stdout
    return {r["skill"]: r["code"] for r in json.loads(out[out.index("["):])}
def install(src):
    p = subprocess.run(["python3", V, "call", "--run", R, "install_script", json.dumps([src]), "--as-admin"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
def snap(): return sql("SELECT skill, code FROM skill_card"), sql("SELECT skill, code FROM act_card")
ADD_A = '\nfn aaa_test_combat() { #{ aim: "creature", timed: true } }\nfn aaa_look_shows() { #{ look: "gesture" } }\n'
ADD_Z = '\nfn zzz_test_combat() { #{ aim: "creature", timed: true } }\nfn zzz_look_shows() { #{ look: "gesture" } }\n'
s0 = snap()
install(base + ADD_A); s1 = snap()
install(base + ADD_Z); s2 = snap()
install(base); s3 = snap()
ok = True
def check(name, cond, detail=""):
    global ok; ok &= cond; print(("PASS " if cond else "FAIL ") + name, detail)
for i, space in enumerate(["skill_card", "act_card"]):
    a, b, c, d = s0[i], s1[i], s2[i], s3[i]
    check(f"{space}: existing skills keep their codes after adding one that sorts first", all(b[k] == v for k, v in a.items()), "")
    new_a = b.get("aaa_test" if i == 0 else "aaa_look")
    check(f"{space}: the added skill takes a fresh code", new_a is not None and new_a not in a.values(), f"code {new_a}")
    new_z = c.get("zzz_test" if i == 0 else "zzz_look")
    check(f"{space}: after removing it, a new skill does not reuse its code", new_z is not None and new_z != new_a and new_z not in a.values(), f"zzz {new_z}, removed {new_a}")
    check(f"{space}: existing codes unchanged through all installs", all(c[k] == v and d[k] == v for k, v in a.items()), "")
    check(f"{space}: the removed skills' cards are gone", ("aaa_test" if i == 0 else "aaa_look") not in c and ("zzz_test" if i == 0 else "zzz_look") not in d, "")
print("SNAPSHOTS", json.dumps({"before": s0, "added_aaa": s1, "aaa_to_zzz": s2, "back": s3}))
sys.exit(0 if ok else 1)
