#!/usr/bin/env python3
"""Stable presentation codes across script installs (docs/COMBAT.md, "Presentation codes").

    codes.py RUN    # after `verify.py launch --run RUN`

Installs the shipped script plus a combat skill and a shown skill that sort first, then swaps
them for two that sort last, then the shipped script again, and checks `skill_card` and
`act_card` codes: existing codes never change, new skills take fresh codes, removed codes are
not reused. Then offers three scripts the install checks must refuse (a law reading a field the
engine does not provide, a skill whose effects fail, a law past the operation limit) and checks
that each refusal names its function and leaves the script row and the cards as they were.
Admin reducer: `install_script`. Python standard library only.
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
def refused(src, text):
    p = subprocess.run(["python3", V, "call", "--run", R, "install_script", json.dumps([src]), "--as-admin", "--expect-refusal", text], capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()[-300:]
def revision():
    out = subprocess.run(["python3", V, "sql", "--run", R, "SELECT revision FROM script", "--as-admin"], capture_output=True, text=True, check=True).stdout
    return json.loads(out[out.index("["):])[0]["revision"]
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
# The install checks: a refused script changes nothing (docs/SCRIPT_ENGINES.md, "Install checks").
rev = revision()
renamed = lambda name: base.replace(f"fn {name}(", f"fn old_{name}(")
for label, src, text in [
    ("a law reading a field the engine does not provide", renamed("rates") + '\nfn rates(a) { #{ hunger: a.actor.hungr, energy: 0.0, hp: 0.0 } }\n', "rates reads `a.actor.hungr`"),
    ("a skill whose effects fail", base + '\nfn zap_check(a) { "" }\nfn zap_done(a) { [#{ op: "damage", amount: a.qty / 0 }] }\n', "`zap_done` failed"),
    ("a law past the operation limit", base + '\nfn zap_duration(a) { let n = 0; while true { n += 1; } n }\n', "`zap_duration` failed"),
]:
    ok_refused, detail = refused(src, text)
    check(f"install refused: {label}, naming the function", ok_refused, detail)
check("refused installs left the script revision and the cards as they were", revision() == rev and snap() == s3, f"revision {rev} -> {revision()}")
print("SNAPSHOTS", json.dumps({"before": s0, "added_aaa": s1, "aaa_to_zzz": s2, "back": s3}))
sys.exit(0 if ok else 1)
