#!/usr/bin/env python3
"""How far do life_feel's columns, or an LLM judge, agree with the owner's ratings of the same lives?
(docs/TRIALS.md, "Player-likeness measures")

  feel_tune.py fit   --ratings R [--key K] [--excerpts E] [--out DIR]
  feel_tune.py judge --ratings R [--key K] [--excerpts E] [--out DIR] [--dry-run | --run]
                     [--base-url URL] [--model M] [--key-env NAME] [--env-file PATH] [--max-calls N]
  feel_tune.py synth --key K --out ratings.synthetic.json [--seed 0]
  feel_tune.py compare --owner R --proxy P [--key K] [--excerpts E] [--out DIR]
  feel_tune.py score BATCH_DIR... [--model tune_result*.json] [--baseline ARM] [--windows 6] [--residents 12]

score. The fit's in-sample window ridge applied to every thinking character's windows in each batch,
per arm, ALWAYS beside three guards over the same lives: false replies per minute (greet_report.py's
false_replies, loaded from the batch's own checkout when it has one; n/a otherwise), the share of
own lines that repeat an own line of the last 10 minutes, and the share of addressed lines that led
to something within 180 s (a trade, lesson, gift, help, hosting or agreement in its percepts, or a
plan of its own or of the addressee naming the other: lenient, an upper bound). Against a baseline
arm (a "control" arm, else "default", else the first), an arm whose score rises while any guard gets
worse is reported "LOST". The score is never printed alone. A proxy-fitted model prints the PROXY
banner and CIRCULARITY: the proxy said being answered mattered most, so a proxy-tuned score resting
on heard/answered shows the rubric applied consistently, not the owner's judgement.

fit --probe COL[,COL] keeps those columns out of every model and reports their rho with the rating
and with the window ridge's leave-one-out residual, per excerpt: a check on a new measure that
claims no agreement. judge refuses proxy ratings outright (no prompts, no call): it waits for the
owner's own ratings.

Proxy ratings. A document whose rater starts with "proxy:" (or that names `proxy_for`) is someone
rating on the owner's behalf. Without --proxy, fit and judge refuse such documents (counted by id)
and use only the owner's; with --proxy they use only proxy documents, every output carries "PROXY
RATINGS (general coordinator, rating for the owner); not the owner's judgement", reports say
"proxy" where they would say "owner", and files get a _proxy suffix (tune_report_proxy.md, ...).
Nothing in proxy mode reports agreement with the owner. The rating page (feel_page.py) writes the
owner's ratings to the collection `owner_ratings` and never touches `ratings`, where proxy ratings
are kept; dump both with an ArtifactData list (out_dir) and run `compare --owner <owner_ratings dump>
--proxy <ratings dump, or the saved copy>`:
Spearman, exact, within-one and mean difference on the excerpts both rated, and every excerpt with
both scores and both reasons.

Inputs (written by feel_excerpts.py): the KEY (default .local/living/feel/excerpts_key.json; private:
source, run, window and life_feel columns per excerpt id), the EXCERPTS (default
.local/living/feel/excerpts.json; the blind text the rating page shows) and the RATINGS: a file
{"synthetic"?, "rater", "ratings": {eid: {"score": 1..5, "reason", "at"}}} or a dump of the rating
page's "owner_ratings" collection, or of "ratings" for proxy ratings (a list, or {"documents"|"docs"|"items": [...]}, of {"id", "data"},
{"path": "ratings/<eid>", "data"} or flat {"id", "score", "reason"} documents), or the directory an
ArtifactData list with out_dir writes (one <eid>.json per document, searched recursively). Documents whose id is
not an excerpt of the key (a "meta" document) are counted and printed, never joined; a score that is
null, not a whole number or outside 1..5 is counted as skipped, by name.

fit. Per life_feel column, for the excerpt-window values (feel_window) and the whole-run values
(feel_run) separately: n, Spearman rho with the rating (average ranks for ties), a two-sided
permutation p (5000 shuffles, random.Random(0)) and the direction that goes with higher ratings.
A column with fewer than 5 values or one value is "not testable". Then leave-one-out predictors:
ridge on standardized columns (training-fold median imputation, mean/sd; clipped to 1..5; lambda chosen by an inner
leave-one-out inside every outer training fold, so the outer number is honest), monotone (isotonic
regression on one column; the top 3 columns by |rho| are found inside each training fold and the one
with the lowest inner leave-one-out error is used, so choosing the column is part of the fit),
and two baselines: the mean of the other ratings and feel0 (feel_excerpts' provisional composite)
through an isotonic fit. Every predictor is scored on its leave-one-out predictions: Spearman with
the ratings and a one-sided permutation p (H1: rho > 0; with no signal a leave-one-out rho leans
negative, since each prediction leans away from its held-out rating), within-one
(|round(pred) - rating| <= 1), exact and MAE. That p holds the fitted predictions fixed;
--pipeline-perms N instead reruns the whole fit on N rating shuffles and tests the best predictor's
rho, so fitting and the choice of predictor are inside the p (about 1 s per shuffle at n = 20). A final
ridge on all excerpts gives standardized coefficients, in-sample, for interpretation only. Excerpts
where the ridge is off by 1.5 or more, or the best column's rank-implied score (its rank mapped to
1..5 in its direction) by 2 or more, are listed with the key's source, the owner's reason verbatim
and the excerpt's first lines (this report is for the coordinator, not the owner). Writes
<out>/tune_report.md (also printed) and <out>/tune_result.json.

judge. A rubric from the owner's reasons, verbatim (score >= 4: what felt like a player; <= 2: what
felt like an NPC), and up to 4 anchor excerpts with their owner scores, spread across the scale.
The rubric and anchors used for excerpt X never contain X's own rating or reason (leave-one-out).
--dry-run (the default) writes <out>/judge_prompts.jsonl and estimates tokens (chars / 4) and cost
(trials.PRICES); no network. --run posts to {base_url}/chat/completions, journals every exchange to
<out>/judge_journal.jsonl (appended, one "run" id per call of the tool), and writes
<out>/judge_report.md with the same agreement measures and the excerpts where the judge and the owner
differ by 2 or more. The key is read from the environment or --env-file and never printed or written.

Refusals (exit 2). fit and judge --run refuse with "no ratings: no agreement claim" when the ratings
are missing, empty or have fewer than 5 usable ratings joined to the key; with 5..9 they run with a
loud warning. Synthetic ratings ("synthetic": true, or "synthetic" in the file name) put a banner on
every output: they prove the plumbing, nothing else. judge --run refuses synthetic ratings, and needs
an explicit --base-url or FEEL_JUDGE_PAID=1 (the paid default: Mistral's API, DeepSeek V4.1 Flash,
MISTRAL_API_KEY); a --base-url on 127.0.0.1/localhost is a fake server: synthetic ratings are allowed,
no key is sent even when one is set, and everything is labelled "FAKE JUDGE — plumbing only".
Redirects are never followed; a key with whitespace or control characters is refused unshown;
call errors are recorded with the key scrubbed. Collection dumps whose reasons start "[synthetic]"
(synth's output) or whose rater says "synthetic" count as synthetic.
"""
import argparse
import datetime
import http.client
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (trials.PRICES, trials.cost)

ROOT = Path(__file__).resolve().parents[2]
FEEL = ROOT / ".local/living/feel"
PROXY_BANNER = "PROXY RATINGS (general coordinator, rating for the owner); not the owner's judgement."
# The proxy's rubric said being answered mattered most, so a fit that finds heard/answered is the rubric
# applied consistently, not the owner's taste: said wherever a proxy-tuned score appears.
CIRCULAR = ("CIRCULARITY: the proxy rater stated that being answered mattered most, so a proxy-tuned score that "
            "rests on heard/answered shows the rubric was applied consistently, not that it is the owner's judgement.")
SYNTH_BANNER = "SYNTHETIC RATINGS — this proves the plumbing only; nothing here measures agreement with the owner."
FAKE_BANNER = "FAKE JUDGE — plumbing only"
REFUSE = "no ratings: no agreement claim"
SETS = ("feel_window", "feel_run")
LAMBDAS = [0.1, 0.3, 1, 3, 10, 30, 100]
N_PERM = 5000
JUDGE_MODEL = "deepseek-v4-1-flash-1017"
JUDGE_URL = "https://api.mistral.ai/v1"


# ---- small statistics ------------------------------------------------------------------

def num(v):
    if isinstance(v, bool):
        return float(v)
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def mean(xs):
    return sum(xs) / len(xs)


def median(xs):
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def ranks(xs):
    """1-based ranks, ties get their average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(a, b):
    ma, mb = mean(a), mean(b)
    ca, cb = [x - ma for x in a], [y - mb for y in b]
    sa, sb = math.sqrt(sum(x * x for x in ca)), math.sqrt(sum(y * y for y in cb))
    return None if sa < 1e-12 or sb < 1e-12 else sum(x * y for x, y in zip(ca, cb)) / (sa * sb)


def spearman(a, b):
    return pearson(ranks(a), ranks(b)) if len(a) >= 3 else None


def perm_p(a, b, n_perm=N_PERM, greater=False):
    """Permutation p of Spearman's rho: shuffle b's ranks against a's (random.Random(0)). Two-sided, or
    with greater=True one-sided for H1 rho > 0 (leave-one-out predictions: only positive agreement counts)."""
    ra, rb = ranks(a), ranks(b)
    ma, mb = mean(ra), mean(rb)
    ca, cb = [x - ma for x in ra], [y - mb for y in rb]
    den = math.sqrt(sum(x * x for x in ca) * sum(y * y for y in cb))
    if den < 1e-12:
        return None
    stat = (lambda v: v) if greater else abs
    obs = stat(sum(x * y for x, y in zip(ca, cb))) / den
    rng, hits = random.Random(0), 0
    for _ in range(n_perm):
        rng.shuffle(cb)
        if stat(sum(x * y for x, y in zip(ca, cb))) / den >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def solve(A, b):
    """Gaussian elimination with partial pivoting (A is small and, here, symmetric positive definite)."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def isotonic(xs, ys):
    """Pool-adjacent-violators, non-decreasing in x; equal x are pooled first. Returns [(x, fit)]."""
    g = defaultdict(lambda: [0.0, 0])
    for x, y in zip(xs, ys):
        g[x][0] += y
        g[x][1] += 1
    blocks = []  # [xs in block, sum, weight]
    for x in sorted(g):
        blocks.append([[x], g[x][0], g[x][1]])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            last = blocks.pop()
            blocks[-1][0] += last[0]
            blocks[-1][1] += last[1]
            blocks[-1][2] += last[2]
    return [(x, s / w) for b, s, w in blocks for x in b]


def iso_predict(pts, x):
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, f0), (x1, f1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return f0 + (f1 - f0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def rnd(p):
    return min(5, max(1, math.floor(p + 0.5)))


def metrics(preds, ys, rho_ok=True, n_perm=N_PERM):
    """Agreement of predictions with ratings; the permutation p is one-sided (H1: rho > 0)."""
    pairs = [(p, y) for p, y in zip(preds, ys) if p is not None]
    if not pairs:
        return {"n": 0}
    ps, ts = [p for p, _ in pairs], [y for _, y in pairs]
    rho = spearman(ps, ts) if rho_ok else None
    return {"n": len(pairs), "rho": rho, "p": perm_p(ps, ts, n_perm, greater=True) if rho is not None else None,
            "within1": sum(abs(rnd(p) - y) <= 1 for p, y in pairs) / len(pairs),
            "exact": sum(rnd(p) == y for p, y in pairs) / len(pairs),
            "mae": sum(abs(p - y) for p, y in pairs) / len(pairs)}


def f2(v, d=2):
    return "–" if v is None else f"{v:.{d}f}"


def fp(p):
    return "–" if p is None else "<0.001" if p < 0.001 else f"{p:.3f}"


# ---- inputs ----------------------------------------------------------------------------

def parse_score(v, integer=True):
    """1..5, or None. Owner ratings must be whole numbers (the page offers 1..5); 4.0 and "4" pass."""
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 1 <= v <= 5:
        return None
    if float(v).is_integer():
        return int(v)
    return None if integer else float(v)


def is_proxy(rater, body=None):
    """A proxy rating: its rater names a proxy ("proxy:<who>") or it says whom it stands in for."""
    return str(rater or "").startswith("proxy:") or bool((body or {}).get("proxy_for"))


def load_ratings(path, proxy=False):
    """Normalise a ratings file or a collection dump. None when missing, empty or not JSON.
    proxy=False keeps only ratings that are not proxies (the owner's); proxy=True keeps only proxy
    ratings. The other kind is counted, by id, and never joined."""
    p = Path(path)
    if p.is_dir():  # an ArtifactData read with out_dir: <dir>[/ratings]/<excerpt id>.json, one document each
        files = sorted(p.rglob("*.json"))
        if not files:
            return None
        data = []
        for f in files:
            try:
                data.append({"id": f.stem, "data": json.loads(f.read_text())})
            except json.JSONDecodeError:
                data.append({"id": f.stem, "data": {}})
    elif not p.is_file() or not p.read_text().strip():
        return None
    else:
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    out = {"synthetic": "synthetic" in p.name.lower(), "rater": None, "ratings": {}, "skipped": [], "docs": 0,
           "proxy": proxy, "other_kind": [], "raters": Counter()}
    file_rater = None
    entries, docs = [], []
    if isinstance(data, dict):
        out["synthetic"] |= data.get("synthetic") is True
        out["rater"] = file_rater = data.get("rater")
        r = data.get("ratings")
        if isinstance(r, dict):
            entries = list(r.items())
        else:
            docs = r if isinstance(r, list) else next((data[k] for k in ("documents", "docs", "items", "rows", "results")
                                                       if isinstance(data.get(k), list)), [])
    elif isinstance(data, list):
        docs = data
    for d in docs:
        if not isinstance(d, dict):
            continue
        eid = d.get("id") or d.get("doc_id") or d.get("_id") or d.get("path")
        body = d.get("data", d)
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                body = {}
        if eid is not None:
            entries.append((str(eid).rsplit("/", 1)[-1], body if isinstance(body, dict) else {}))
    for eid, body in entries:
        out["docs"] += 1
        body = body if isinstance(body, dict) else {"score": body}
        if body.get("synthetic") is True:
            out["synthetic"] = True
        out["rater"] = out["rater"] or (body.get("rater") if "score" not in body else None)
        if "score" in body and is_proxy(body.get("rater") or file_rater, body) != proxy:
            out["other_kind"].append(eid)  # a proxy rating in an owner fit, or the owner's in a proxy fit
            continue
        if "score" in body:
            out["raters"][str(body.get("rater") or file_rater or "unnamed")] += 1
        s = parse_score(body.get("score"))
        if s is None:
            out["skipped"].append(eid)
            continue
        out["ratings"][eid] = {"score": s, "reason": str(body.get("reason") or "").strip(), "at": body.get("at")}
    # A collection dump carries no top-level flag: synth's reasons and rater name still mark it.
    if "synthetic" in str(out["rater"] or "").lower() or any(
            r["reason"].lower().startswith("[synthetic]") for r in out["ratings"].values()):
        out["synthetic"] = True
    return out


def load_inputs(a, need_excerpts=False):
    key = json.loads(Path(a.key).read_text())
    ex_path = Path(a.excerpts)
    excerpts = {e["id"]: e for e in json.loads(ex_path.read_text()).get("excerpts", [])} if ex_path.is_file() else {}
    if need_excerpts and not excerpts:
        sys.exit(f"judge needs the excerpts file ({ex_path})")
    R = load_ratings(a.ratings, proxy=getattr(a, "proxy", False))
    return key, excerpts, R


def joined(key, R, excerpts=None):
    ke = key.get("excerpts", {})
    eids = sorted(e for e in R["ratings"] if e in ke and (excerpts is None or e in excerpts))
    foreign = sorted({e for e in list(R["ratings"]) + R["skipped"] if e not in ke})
    R["skipped_in_key"] = [e for e in R["skipped"] if e in ke]
    R["no_excerpt"] = sorted(e for e in R["ratings"] if e in ke and excerpts is not None and e not in excerpts)
    return eids, foreign


def accounting(R, n, foreign):
    """One line: what was joined and what was left out, by name."""
    parts = [f"{n} ratings joined to the key",
             f"{len(R['skipped_in_key'])} skipped (null, not a whole number, or outside 1..5)"
             + (f": {', '.join(R['skipped_in_key'])}" if R["skipped_in_key"] else ""),
             f"{len(foreign)} documents not in the key ignored" + (f": {', '.join(foreign)}" if foreign else "")]
    if R.get("other_kind"):
        parts.append(f"{len(R['other_kind'])} " + ("of the owner's own ratings left out of this proxy fit" if R.get("proxy")
                                                   else "proxy ratings refused (not the owner's; use --proxy)"))
    if R.get("no_excerpt"):
        parts.append(f"{len(R['no_excerpt'])} in the key but not in the excerpts file, left out: {', '.join(R['no_excerpt'])}")
    return "; ".join(parts) + "."


def who(R):
    """How reports name the rater: "proxy" for proxy ratings, never "owner"."""
    return "proxy" if R and R.get("proxy") else "owner"


def raters(R):
    return ", ".join(f"{r} {k}" for r, k in R["raters"].most_common()) or (R["rater"] or "unnamed")


def banner(R, n, fake=False):
    if R.get("proxy"):
        lines = ([SYNTH_BANNER] if R["synthetic"] else []) + [PROXY_BANNER, CIRCULAR, f"Proxy ratings: {n} excerpts rated (rater {raters(R)})."]
    else:
        lines = [SYNTH_BANNER if R["synthetic"] else f"Owner ratings: {n} excerpts rated (rater {raters(R)})."]
    return lines + ([FAKE_BANNER] if fake else [])


def suffix(R):
    return "_proxy" if R and R.get("proxy") else ""


def refuse(R, why):
    if R and R["synthetic"]:
        print(SYNTH_BANNER)
    if R and R.get("proxy"):
        print(PROXY_BANNER)
    if R and R.get("other_kind") and not R.get("proxy"):
        why += f"; {len(R['other_kind'])} proxy ratings refused: they are not the owner's (fit them with --proxy)"
    print(f"{REFUSE} ({why})", file=sys.stderr)
    sys.exit(2)


def small_n(n):
    return [f"**WARNING: n = {n} is too small to conclude anything; every number below is noise-dominated.**", ""] if n < 10 else []


# ---- fit -------------------------------------------------------------------------------

def feats(key, eids, fs, cols):
    ke = key["excerpts"]
    return [[num((ke[e].get(fs) or {}).get(c)) for c in cols] for e in eids]


def col_rho(X, ys, j, idx):
    pts = [(X[i][j], ys[i]) for i in idx if X[i][j] is not None]
    if len(pts) < 5 or len({x for x, _ in pts}) < 2:
        return None
    return spearman([x for x, _ in pts], [y for _, y in pts])


def prep(X, idx):
    """Per column (median, mean, sd) on the rows idx after median imputation; dropped columns left out."""
    spec = []
    for j in range(len(X[0]) if X else 0):
        vs = [X[i][j] for i in idx if X[i][j] is not None]
        if not vs:
            continue
        med = median(vs)
        full = [X[i][j] if X[i][j] is not None else med for i in idx]
        m = mean(full)
        sd = math.sqrt(sum((v - m) ** 2 for v in full) / len(full))
        if sd > 1e-12:
            spec.append((j, med, m, sd))
    return spec


def zrow(row, spec):
    return [((row[j] if row[j] is not None else med) - m) / sd for j, med, m, sd in spec]


def ridge(Z, y, lams):
    """Ridge with an unpenalised intercept, dual form (rows are few). Returns {lam: (ybar, beta)}."""
    ybar = mean(y)
    yc = [v - ybar for v in y]
    p = len(Z[0]) if Z else 0
    if p == 0:
        return {l: (ybar, []) for l in lams}
    K = [[sum(a * b for a, b in zip(r, s)) for s in Z] for r in Z]
    out = {}
    for l in lams:
        alpha = solve([[K[i][k] + (l if i == k else 0) for k in range(len(Z))] for i in range(len(Z))], yc)
        out[l] = (ybar, [sum(alpha[i] * Z[i][c] for i in range(len(Z))) for c in range(p)])
    return out


def ridge_predict(model, z):
    return model[0] + sum(b * v for b, v in zip(model[1], z))


def ridge_fold(X, ys, T):
    """Choose lambda by leave-one-out inside T, then fit on T. Returns (lam, spec, model)."""
    sse = Counter()
    for j in T:
        inner = [i for i in T if i != j]
        spec = prep(X, inner)
        models = ridge([zrow(X[i], spec) for i in inner], [ys[i] for i in inner], LAMBDAS)
        zj = zrow(X[j], spec)
        for l, m in models.items():
            sse[l] += (ridge_predict(m, zj) - ys[j]) ** 2
    lam = min(LAMBDAS, key=lambda l: (sse[l], -l))
    spec = prep(X, T)
    return lam, spec, ridge([zrow(X[i], spec) for i in T], [ys[i] for i in T], [lam])[lam]


def mono_fit(X, ys, j, sign, T):
    pts = [(sign * X[i][j], ys[i]) for i in T if X[i][j] is not None]
    med = median([x for x, _ in pts])
    return isotonic([x for x, _ in pts], [y for _, y in pts]), med


def mono_pred(model, x, sign):
    pts, med = model
    return iso_predict(pts, sign * x if x is not None else med)


def mono_fold(X, ys, T, cols):
    """Top 3 columns by |rho| on T; keep the one with the lowest inner leave-one-out MAE."""
    cands = [(abs(r), cols[j], j, 1 if r > 0 else -1) for j in range(len(cols)) if (r := col_rho(X, ys, j, T))]
    best = None
    for _, _, j, sign in sorted(cands, key=lambda c: (-c[0], c[1]))[:3]:
        err, ok = 0.0, True
        for k in T:
            inner = [i for i in T if i != k]
            if sum(X[i][j] is not None for i in inner) < 2:
                ok = False
                break
            err += abs(mono_pred(mono_fit(X, ys, j, sign, inner), X[k][j], sign) - ys[k])
        if ok and (best is None or err < best[0]):
            best = (err, j, sign)
    return best


def loo_preds(X, ys, f0, cols):
    """Every leave-one-out predictor: {name: [pred per excerpt]}, plus the lambdas and columns chosen per fold."""
    n = len(ys)
    preds = defaultdict(lambda: [None] * n)
    lam_used, mono_used = defaultdict(Counter), defaultdict(Counter)
    for i in range(n):
        T = [k for k in range(n) if k != i]
        preds["mean"][i] = mean([ys[k] for k in T])
        tf = [k for k in T if f0[k] is not None]
        if len(tf) >= 2:
            preds["feel0 (isotonic)"][i] = iso_predict(isotonic([f0[k] for k in tf], [ys[k] for k in tf]),
                                                       f0[i] if f0[i] is not None else median([f0[k] for k in tf]))
        for fs in SETS:
            tag = fs.split("_")[1]
            if not prep(X[fs], T):
                continue
            lam, spec, model = ridge_fold(X[fs], ys, T)
            lam_used[tag][lam] += 1
            preds[f"ridge ({tag})"][i] = min(5.0, max(1.0, ridge_predict(model, zrow(X[fs][i], spec))))
            m = mono_fold(X[fs], ys, T, cols)
            if m:
                _, j, sign = m
                mono_used[tag][f"{'' if sign > 0 else '-'}{cols[j]}"] += 1
                preds[f"monotone ({tag})"][i] = mono_pred(mono_fit(X[fs], ys, j, sign, T), X[fs][i][j], sign)
    return preds, lam_used, mono_used


def best_rho(preds, ys):
    """The highest leave-one-out Spearman over the fitted predictors (the mean is not one)."""
    rs = []
    for name, ps in preds.items():
        pairs = [(p, y) for p, y in zip(ps, ys) if p is not None]
        if name != "mean" and len(pairs) >= 3:
            r = spearman([p for p, _ in pairs], [y for _, y in pairs])
            if r is not None:
                rs.append(r)
    return max(rs) if rs else None


def cmd_fit(a):
    key, excerpts, R = load_inputs(a)
    if R is None:
        refuse(R, "the ratings file is missing, empty or not JSON")
    eids, foreign = joined(key, R)
    if len(eids) < 5:
        refuse(R, "fewer than five usable ratings joined to the key")
    ke, n = key["excerpts"], len(eids)
    ys = [R["ratings"][e]["score"] for e in eids]
    cols = key.get("columns") or sorted({c for e in ke.values() for c in (e.get("feel_window") or {})})
    probes = [c for c in (a.probe or "").split(",") if c]
    cols = [c for c in cols if c not in probes]  # a probe column is in no model: reported beside them only
    out = banner(R, n) + [""] + small_n(n)
    W = who(R)
    out += [f"# {'Proxy' if R.get('proxy') else 'Owner'}-rating fit (leave-one-out)", ""]
    out += [line for line in banner(R, n)] + [""]
    out.append(accounting(R, n, foreign))
    out.append(f"Ratings: " + ", ".join(f"{s}: {c}" for s, c in sorted(Counter(ys).items())) + ".")
    result = {"banner": banner(R, n), "synthetic": R["synthetic"], "proxy": bool(R.get("proxy")), "rated_by": W, "n": n, "ignored": foreign, "skipped": R["skipped_in_key"],
              "columns": {}, "metrics": {}, "coefficients": {}, "predictions": {e: {"score": y} for e, y in zip(eids, ys)}}

    # Per column.
    X = {fs: feats(key, eids, fs, cols) for fs in SETS}
    best_col = None
    for fs in SETS:
        rows, untestable = [], []
        for j, c in enumerate(cols):
            pts = [(X[fs][i][j], ys[i]) for i in range(n) if X[fs][i][j] is not None]
            rho = col_rho(X[fs], ys, j, range(n))
            if rho is None:
                untestable.append(c)
                result["columns"].setdefault(fs, {})[c] = {"n": len(pts), "testable": False}
                continue
            p = perm_p([x for x, _ in pts], [y for _, y in pts])
            rows.append((c, len(pts), rho, p, j))
            result["columns"].setdefault(fs, {})[c] = {"n": len(pts), "rho": rho, "p": p, "direction": 1 if rho > 0 else -1, "testable": True}
        rows.sort(key=lambda r: (-abs(r[2]), r[0]))
        if fs == "feel_window" and rows:
            best_col = rows[0]
        out += ["", f"## Columns: {fs} (Spearman with the rating, {N_PERM}-shuffle permutation p)", "",
                "| column | n | rho | p | higher ratings go with |", "| --- | ---: | ---: | ---: | --- |"]
        out += [f"| {c} | {m} | {rho:+.2f} | {fp(p)} | {'higher' if rho > 0 else 'lower'} {c} |" for c, m, rho, p, _ in rows]
        out.append(f"\nNot testable (fewer than 5 values, or one value): {', '.join(untestable) or 'none'}.")
        out.append(f"{len(rows)} columns tested: expect about {0.05 * len(rows):.1f} with p < 0.05 by chance alone.")

    # Leave-one-out predictors.
    f0 = [num(ke[e].get("feel0")) for e in eids]
    preds, lam_used, mono_used = loo_preds(X, ys, f0, cols)
    notes = {}
    for tag, cnt in mono_used.items():
        notes[f"monotone ({tag})"] = "column chosen in each fold: " + ", ".join(f"{c} {k}/{n}" for c, k in cnt.most_common())
    for tag, cnt in lam_used.items():
        notes[f"ridge ({tag})"] = "lambda chosen in each fold: " + ", ".join(f"{l:g} {k}/{n}" for l, k in sorted(cnt.items()))
    notes["mean"] = "rho not shown: the mean of the others falls as the held-out rating rises"
    out += ["", "## Leave-one-out agreement with the ratings", "",
            "perm p is one-sided (H1: rho > 0). With no signal a leave-one-out rho is often negative, even strongly: "
            "each prediction leans away from its own held-out rating (the others' mean falls as it rises). "
            "A negative rho here is not agreement, reversed or otherwise.", "",
            "| predictor | n | Spearman | perm p | within one | exact | MAE | note |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for name in sorted(preds, key=lambda k: (k != "mean", k)):
        mt = metrics(preds[name], ys, rho_ok=name != "mean")
        result["metrics"][name] = dict(mt, note=notes.get(name, ""))
        out.append(f"| {name} | {mt['n']} | {f2(mt.get('rho'))} | {fp(mt.get('p'))} | {f2(mt.get('within1'))} | "
                   f"{f2(mt.get('exact'))} | {f2(mt.get('mae'))} | {notes.get(name, '')} |")
        for i, e in enumerate(eids):
            result["predictions"][e][name] = preds[name][i]
    scored = [(k, m) for k, m in result["metrics"].items() if m.get("rho") is not None]
    pipe = None
    if scored and a.pipeline_perms > 0:
        # Shuffle the ratings through the whole leave-one-out pipeline: fitting, lambda and column choice and
        # picking the best predictor are all inside, so this p is calibrated for all of them.
        obs, rng, hits = best_rho(preds, ys), random.Random(0), 0
        for _ in range(a.pipeline_perms):
            yp = ys[:]
            rng.shuffle(yp)
            b = best_rho(loo_preds(X, yp, f0, cols)[0], yp)
            hits += b is not None and b >= obs - 1e-12
        pipe = (hits + 1) / (a.pipeline_perms + 1)
        result["pipeline_p"] = {"shuffles": a.pipeline_perms, "best_rho": obs, "p": pipe}
    if scored:
        k, m = max(scored, key=lambda km: (km[1]["rho"], km[0]))
        if m["rho"] <= 0:
            verdict = "no predictor agrees positively with the ratings at this n"
        elif (pipe if pipe is not None else m["p"]) >= 0.05:
            verdict = "not distinguishable from chance at this n"
        elif pipe is not None:
            verdict = ("distinguishable from chance by the whole-pipeline shuffle (selection included); "
                       "still one sample of ratings: check it on new ratings")
        else:
            verdict = (f"p < 0.05, but {len(scored)} predictors were compared and the p ignores fitting: "
                       "a lead to check on new ratings (or with --pipeline-perms), not a finding")
        out.append(f"\nHighest leave-one-out Spearman: {k}, rho {m['rho']:+.2f} (n = {m['n']}, one-sided permutation p {fp(m['p'])}"
                   + (f"; whole-pipeline p {fp(pipe)} over {a.pipeline_perms} shuffles" if pipe is not None else "")
                   + f"): {verdict}.")
        if pipe is None:
            out.append("The permutation p shuffles ratings against fixed predictions; it ignores that the predictions were "
                       "fitted and that the best of several was picked. --pipeline-perms N reruns the whole fit on N shuffles.")

    # In-sample ridge for interpretation.
    for fs in SETS:
        spec = prep(X[fs], range(n))
        if not spec:
            continue
        sse = Counter()
        for j in range(n):
            sp = prep(X[fs], [i for i in range(n) if i != j])
            models = ridge([zrow(X[fs][i], sp) for i in range(n) if i != j], [ys[i] for i in range(n) if i != j], LAMBDAS)
            for l, mdl in models.items():
                sse[l] += (ridge_predict(mdl, zrow(X[fs][j], sp)) - ys[j]) ** 2
        lam = min(LAMBDAS, key=lambda l: (sse[l], -l))
        ybar, beta = ridge([zrow(X[fs][i], spec) for i in range(n)], ys, [lam])[lam]
        result.setdefault("model", {})[fs] = {"lambda": lam, "intercept": ybar, "terms": [
            {"column": cols[j], "median": med, "mean": m, "sd": sd, "beta": b} for (j, med, m, sd), b in zip(spec, beta)]}
        co = sorted(((cols[j], b) for (j, *_), b in zip(spec, beta)), key=lambda cb: (-abs(cb[1]), cb[0]))
        result["coefficients"][fs] = {"lambda": lam, "intercept": ybar, "beta": dict(co)}
        out += ["", f"## Ridge on all {n} ({fs}, lambda {lam:g}): in-sample, for interpretation only", "",
                "Rating points per standard deviation of the column (intercept " + f"{ybar:.2f}):", ""]
        out.append(", ".join(f"{c} {b:+.2f}" for c, b in co))

    # Disagreements.
    rp = preds.get("ridge (window)", [None] * n)
    implied = [None] * n
    if best_col:
        c, _, rho, _, j = best_col
        idx = [i for i in range(n) if X["feel_window"][i][j] is not None]
        rk = ranks([X["feel_window"][i][j] for i in idx])
        for i, r in zip(idx, rk):
            s = 1 + 4 * (r - 1) / (len(idx) - 1)
            implied[i] = s if rho > 0 else 6 - s
    out += ["", "## Disagreements",
            "", f"Ridge (window) leave-one-out off by 1.5 or more, or {best_col[0] if best_col else 'the best column'}'s "
            "rank-implied score off by 2 or more.", ""]
    dis = [i for i in range(n) if (rp[i] is not None and abs(rp[i] - ys[i]) >= 1.5) or (implied[i] is not None and abs(implied[i] - ys[i]) >= 2)]
    dis_set = set(dis)
    result["disagreements"] = [eids[i] for i in dis]
    for i in dis:
        e, k = eids[i], ke[eids[i]]
        out.append(f"### {e}: {W} {ys[i]}")
        out.append(f"- {k.get('source')} {k.get('kind')} {k.get('run')} ({k.get('variant')}) {k.get('character')}, "
                   f"minutes {k.get('window_min')}; {k.get('batch_dir')}")
        out.append("- predictions: " + ", ".join(f"{nm} {f2(preds[nm][i])}" for nm in sorted(preds) if nm != "mean")
                   + (f", {best_col[0]} rank-implied {f2(implied[i])}" if best_col else "") + f", feel0 {f2(f0[i])}")
        out.append(f"- {W}'s reason: {R['ratings'][e]['reason'] or '(none given)'}")
        ex = excerpts.get(e)
        if ex:
            out.append(f"- excerpt \"{ex.get('title', '')}\":")
            out += [f"    {ln.get('t', '')} {ln.get('kind', '')}: {ln.get('text', '')}" for ln in ex.get("lines", [])[:6]]
        out.append("")
    if not dis:
        out.append("None.")

    # Per source.
    out += ["", "## Per source", "", f"| source | variant | n | mean {W} | mean ridge (window) LOO |", "| --- | --- | ---: | ---: | ---: |"]
    result["per_source"] = []
    for group in (lambda k: (k.get("source"), "all"), lambda k: (k.get("source"), k.get("variant"))):
        g = defaultdict(list)
        for i, e in enumerate(eids):
            g[group(ke[e])].append(i)
        for (s, v), idx in sorted(g.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            rr = [rp[i] for i in idx if rp[i] is not None]
            out.append(f"| {s} | {v} | {len(idx)} | {mean([ys[i] for i in idx]):.2f} | {f2(mean(rr) if rr else None)} |")
            result["per_source"].append({"source": s, "variant": v, "n": len(idx), W: mean([ys[i] for i in idx]),
                                         "ridge_window": mean(rr) if rr else None})
    if probes:
        out += probe_section(key, eids, ys, preds, probes, dis_set, W, result)
    out += kind_section(key, eids, ys, X, cols, W, result)
    out += ["", *banner(R, n)]
    report = "\n".join(out) + "\n"
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    rp_, rj_ = od / f"tune_report{suffix(R)}.md", od / f"tune_result{suffix(R)}.json"
    rp_.write_text(report)
    rj_.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(report)
    print(f"wrote {rp_} and {rj_}")


def probe_section(key, eids, ys, preds, probes, dis, W, result):
    """Columns kept out of every model: do they track the rating, or what the window ridge missed?"""
    ke = key["excerpts"]
    rp = preds.get("ridge (window)")
    resid = [y - p for y, p in zip(ys, rp)] if rp else None
    out = ["", "## Probe columns (in no model; nothing here is refitted)", "",
           f"Residual = {W} rating minus the window ridge's leave-one-out prediction: a probe that tracks the residual "
           "explains what the fitted columns missed. Values per excerpt, then the disagreements.", "",
           "| probe | n | rho with rating | p | rho with residual | p |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    result["probes"] = {}
    for c in probes:
        v = [num((ke[e].get("feel_window") or {}).get(c)) for e in eids]
        idx = [i for i in range(len(eids)) if v[i] is not None]
        xs = [v[i] for i in idx]
        ok = len(idx) >= 5 and len(set(xs)) > 1
        r1 = spearman(xs, [ys[i] for i in idx]) if ok else None
        p1 = perm_p(xs, [ys[i] for i in idx]) if ok else None
        r2 = spearman(xs, [resid[i] for i in idx]) if ok and resid else None
        p2 = perm_p(xs, [resid[i] for i in idx]) if ok and resid else None
        result["probes"][c] = {"rho": r1, "p": p1, "rho_residual": r2, "p_residual": p2, "values": {eids[i]: v[i] for i in idx}}
        out.append(f"| {c} | {len(idx)} | {f2(r1)} | {fp(p1)} | {f2(r2)} | {fp(p2)} |")
    out += ["", f"| excerpt | {W} | ridge (window) LOO | " + " | ".join(probes) + " | disagreement |",
            "| --- | ---: | ---: |" + " ---: |" * len(probes) + " --- |"]
    for i in sorted(range(len(eids)), key=lambda i: (-ys[i], eids[i])):
        e = eids[i]
        out.append(f"| {e} ({ke[e].get('source')}, {ke[e].get('kind')}) | {ys[i]} | {f2(rp[i]) if rp else '–'} | "
                   + " | ".join(f2(num((ke[e].get('feel_window') or {}).get(c))) for c in probes) + f" | {'yes' if i in dis else ''} |")
    return out


def auc(pos, neg):
    """P(a value from pos exceeds one from neg), ties half: 0.5 is no separation."""
    if not pos or not neg:
        return None
    return sum((x > y) + 0.5 * (x == y) for x in pos for y in neg) / (len(pos) * len(neg))


def auc_p(vals, labels, n_perm=N_PERM):
    """Two-sided permutation p of |AUC - 0.5| for labels shuffled over vals."""
    pos = [v for v, l in zip(vals, labels) if l]
    neg = [v for v, l in zip(vals, labels) if not l]
    obs = auc(pos, neg)
    if obs is None:
        return None, None
    rng, hits, lab = random.Random(0), 0, list(labels)
    for _ in range(n_perm):
        rng.shuffle(lab)
        a_ = auc([v for v, l in zip(vals, lab) if l], [v for v, l in zip(vals, lab) if not l])
        hits += abs(a_ - 0.5) >= abs(obs - 0.5) - 1e-12
    return obs, (hits + 1) / (n_perm + 1)


def kind_section(key, eids, ys, X, cols, W, result):
    """Do the ratings, and the columns, tell excerpts where everyone thinks from single-thinker lives?"""
    ke = key["excerpts"]
    lab = [ke[e].get("kind") == "all-minds" for e in eids]
    if all(lab) or not any(lab):
        return []
    out = ["", "## Single-thinker lives against worlds where everyone thinks", "",
           "AUC = P(an all-minds excerpt's value exceeds a single-thinker one's), ties half; 0.5 = no separation, "
           f"1 = every all-minds excerpt higher. p: two-sided, {N_PERM} label shuffles. Within-kind rho: the column's "
           "Spearman with the rating inside each kind, which says whether it tracks the rating beyond telling the kinds apart.", ""]
    a_, p_ = auc_p(ys, lab)
    m1 = mean([y for y, l in zip(ys, lab) if l])
    m0 = mean([y for y, l in zip(ys, lab) if not l])
    out.append(f"{W} rating: all-minds {sum(lab)} excerpts, mean {m1:.2f}; single-thinker {len(lab) - sum(lab)}, mean {m0:.2f}; "
               f"AUC {a_:.2f} (p {fp(p_)}).")
    result["kinds"] = {"rating": {"all_minds_mean": m1, "single_mean": m0, "auc": a_, "p": p_}, "columns": {}}
    for fs in SETS:
        rows = []
        for j, c in enumerate(cols):
            idx = [i for i in range(len(eids)) if X[fs][i][j] is not None]
            vals = [X[fs][i][j] for i in idx]
            if len(set(vals)) < 2 or not any(lab[i] for i in idx) or all(lab[i] for i in idx):
                continue
            ac, pc = auc_p(vals, [lab[i] for i in idx], n_perm=2000)
            within = []
            for k in (True, False):
                ii = [i for i in idx if lab[i] == k]
                xv, yv = [X[fs][i][j] for i in ii], [ys[i] for i in ii]
                within.append(spearman(xv, yv) if len(ii) >= 5 and len(set(xv)) > 1 and len(set(yv)) > 1 else None)
            rows.append((c, ac, pc, within))
            result["kinds"]["columns"].setdefault(fs, {})[c] = {"auc": ac, "p": pc, "rho_all_minds": within[0], "rho_single": within[1]}
        rows.sort(key=lambda r: (-abs(r[1] - 0.5), r[0]))
        out += ["", f"### {fs}", "", "| column | AUC (all-minds higher) | p | rho with rating, all-minds | rho, single-thinker |",
                "| --- | ---: | ---: | ---: | ---: |"]
        out += [f"| {c} | {ac:.2f} | {fp(pc)} | {f2(w[0])} | {f2(w[1])} |" for c, ac, pc, w in rows]
    return out


# ---- score -----------------------------------------------------------------------------

OUTCOME = re.compile(r"taught you|^You taught|gave you|^You gave|\bgave .* to you|agree|accepted your terms|takes you in|took you in|"
                     r"tended your|^You tended|hosts? you|\bheal", re.I)
LED_S, REPEAT_S = 180, 600


def greet_report_for(bd):
    """greet_report.py from the batch's own checkout (read-only), when it has one; else None."""
    p = Path(bd).resolve().parents[3] / "living/tools/greet_report.py"
    if not p.is_file():
        p = ROOT / "living/tools/greet_report.py"
    if not p.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"greet_report_{abs(hash(str(p)))}", p)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # its imports may not resolve here; then false replies are n/a
        print(f"greet_report.py at {p} did not load ({type(e).__name__}); false replies n/a", file=sys.stderr)
        return None
    return mod


def guards(life, by_name):
    """Over the run so far: own lines, the share that repeat an own line of the last 10 minutes (word
    Jaccard 0.6+), and of lines addressed to someone, the share that led to something within LED_S:
    a trade, lesson, gift, help, hosting or agreement in its own percepts, or a plan of its own or of
    the addressee (when the addressee thinks) that names the other."""
    said = []
    for ms, kind, raw in life.percepts:
        if kind == "said" or raw.startswith("You said"):
            m = re.match(r"You said(?: to ([^:“]+))?: “(.*)”?", raw, re.S)
            said.append((ms, (m[1] or "").strip() if m else "", set(re.findall(r"[a-z']+", (m[2] if m else raw).lower()))))
    rep = 0
    for i, (ms, _, ws) in enumerate(said):
        if any(ms - REPEAT_S * 1000 <= o <= ms and ws | ow and len(ws & ow) / len(ws | ow) >= 0.6 for o, _, ow in said[:i]):
            rep += 1
    events = [ms for ms, _, raw in life.percepts if OUTCOME.search(raw) and not raw.startswith("You said") and "said to" not in raw]
    me = life.name.split()[0]
    addressed = [(ms, to) for ms, to, _ in said if to and not to.startswith(("a ", "an ", "someone"))] + \
                [(ms, to) for ms, to, _ in said if to.startswith(("a ", "an ", "someone"))]
    led = 0
    for ms, to in addressed:
        win = lambda t: ms <= t <= ms + LED_S * 1000
        first = to.split()[0] if to and not to.startswith(("a ", "an ", "someone")) else None
        if any(win(t) for t in events) or (first and any(win(t) and re.search(rf"\b{re.escape(first)}\b", p) for t, p in life.plans)) \
                or (to in by_name and any(win(t) and re.search(rf"\b{re.escape(me)}\b", p) for t, p in by_name[to].plans)):
            led += 1
    return {"lines": len(said), "repeated": rep, "addressed": len(addressed), "led": led}


def cmd_score(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import feel_excerpts as FE
    model = json.loads(Path(a.model).read_text())
    m = (model.get("model") or {}).get("feel_window")
    if not m:
        sys.exit(f"score: {a.model} has no window model (rerun fit to write one)")
    proxy = bool(model.get("proxy"))
    head = ([PROXY_BANNER, CIRCULAR, "PROXY-TUNED SCORE: the window ridge fitted on the proxy ratings (in-sample, "
             f"lambda {m['lambda']:g}); a score the proxy's rubric would give, not the owner's."] if proxy else
            [f"Owner-tuned score: the window ridge fitted on the owner's ratings (in-sample, lambda {m['lambda']:g})."])
    head += ["Never read the score alone: an arm that raises it while false replies or repeated lines rise, or the share "
             "of talk that led to something falls, LOST: the score can be raised by chatter."]
    FE.RESIDENTS_PER_RUN = a.residents
    w_ms = int(a.window * 60000)
    tmp = Path(__import__("tempfile").mkdtemp(prefix="feel-score-"))
    arms = defaultdict(lambda: {"scores": [], "lives": 0, "runs": set(), "lines": 0, "repeated": 0, "addressed": 0, "led": 0,
                                "false": [], "minutes": 0.0})
    try:
        for bd in a.batches:
            bd = Path(bd).expanduser()
            label = bd.name
            lives = FE.lives_of(label, [bd], random.Random(0))
            gr = greet_report_for(bd)
            runs_seen = set()
            for life in lives:
                arm = arms[(label, life.variant)]
                by_name = {l.name: l for l in lives if l.run == life.run}
                for start in FE.windows(life, w_ms, a.windows):
                    f = FE.feel(FE.feel_dir(life, start, start + w_ms, tmp / "x" / "y"))
                    sc = m["intercept"] + sum(t["beta"] * (((num(f.get(t["column"])) if num(f.get(t["column"])) is not None else t["median"])
                                                             - t["mean"]) / t["sd"]) for t in m["terms"])
                    arm["scores"].append(min(5.0, max(1.0, sc)))
                g = guards(life, by_name)
                for k2 in ("lines", "repeated", "addressed", "led"):
                    arm[k2] += g[k2]
                arm["lives"] += 1
                if life.run not in runs_seen:
                    runs_seen.add(life.run)
                    arm["runs"].add(life.run)
                    if gr is not None:
                        try:
                            r = gr.run(life.d)
                            arm["false"].append(r.get("false_replies") or 0)
                            arm["minutes"] += r.get("minutes") or 0
                        except Exception as e:
                            print(f"greet_report on {life.d.name}: {type(e).__name__}; false replies n/a for it", file=sys.stderr)
    finally:
        __import__("shutil").rmtree(tmp, ignore_errors=True)
    rows = {}
    for (b, v), x in arms.items():
        rows[(b, v)] = {"score": mean(x["scores"]) if x["scores"] else None, "windows": len(x["scores"]), "lives": x["lives"],
                        "runs": len(x["runs"]), "false_min": (sum(x["false"]) / x["minutes"]) if x["false"] and x["minutes"] else None,
                        "repeated": x["repeated"] / x["lines"] if x["lines"] else None, "led": x["led"] / x["addressed"] if x["addressed"] else None,
                        "lines": x["lines"], "addressed": x["addressed"]}
    out = head + ["", "| batch | arm | score (mean over windows) | windows | lives | false replies / min | repeated lines | talk that led to something | vs baseline |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for b in sorted({b for b, _ in rows}):
        vs = sorted(v for bb, v in rows if bb == b)
        base = a.baseline if a.baseline in vs else next((v for v in vs if "control" in v), next((v for v in vs if v == "default"), vs[0]))
        B = rows[(b, base)]
        for v in vs:
            R_ = rows[(b, v)]
            if v == base:
                verdict = "baseline"
            elif R_["score"] is None or B["score"] is None or R_["score"] <= B["score"]:
                verdict = "no score gain"
            else:
                worse = [n for n, k2, bad in (("false replies", "false_min", 1), ("repeated lines", "repeated", 1), ("talk that led to something", "led", -1))
                         if R_[k2] is not None and B[k2] is not None and (R_[k2] - B[k2]) * bad > 1e-9]
                verdict = f"LOST: score up but {', '.join(worse)} worse" if worse else "score up; false replies, repeats and outcomes held"
            out.append(f"| {b} | {v} | {f2(R_['score'])} | {R_['windows']} | {R_['lives']} | {f2(R_['false_min'], 3) if R_['false_min'] is not None else 'n/a'} | "
                       f"{f2(R_['repeated'])} of {R_['lines']} | {f2(R_['led'])} of {R_['addressed']} | {verdict} |")
    out += ["", f"Score: {a.windows} windows of {a.window:g} real minutes per thinking character (residents: up to {a.residents} per run), "
            "columns as life_feel defines them, clipped to 1..5. False replies: greet_report.py's false_replies over the runs' minutes "
            "(n/a without it). Repeated lines: own lines that repeat one of its own from the last 10 minutes. Talk that led to "
            f"something: addressed lines followed within {LED_S} s by a trade, lesson, gift, help, hosting or agreement in its percepts, "
            "or by a plan of its own or of the addressee that names the other.", "", *head[:2]]
    report = "\n".join(out) + "\n"
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    rp_ = od / f"score_report{'_proxy' if proxy else ''}.md"
    rp_.write_text(report)
    print(report)
    print(f"wrote {rp_}")


# ---- compare ---------------------------------------------------------------------------

def cmd_compare(a):
    """The owner's ratings against the proxy's, on the excerpts both rated."""
    key = json.loads(Path(a.key).read_text())
    ex_path = Path(a.excerpts)
    excerpts = {e["id"]: e for e in json.loads(ex_path.read_text()).get("excerpts", [])} if ex_path.is_file() else {}
    O = load_ratings(a.owner, proxy=False)
    P = load_ratings(a.proxy, proxy=True)
    if P is None or not P["ratings"]:
        sys.exit("compare: no proxy ratings in " + a.proxy)
    if O is None or not O["ratings"]:
        print(PROXY_BANNER)
        print(f"compare: no owner ratings yet in {a.owner}" + (f" ({len(O['other_kind'])} proxy ratings there are not the owner's)"
                                                              if O and O["other_kind"] else "") + "; nothing to compare.", file=sys.stderr)
        sys.exit(2)
    ke = key.get("excerpts", {})
    both = sorted(e for e in O["ratings"] if e in P["ratings"] and e in ke)
    out = ([SYNTH_BANNER] if O["synthetic"] or P["synthetic"] else []) + ["# The owner's ratings against the proxy's", "",
           f"Owner ratings: {len(O['ratings'])} (rater {raters(O)}). {PROXY_BANNER} Proxy ratings: {len(P['ratings'])} (rater {raters(P)}).",
           f"Both rated: {len(both)}. Owner-only: {len([e for e in O['ratings'] if e not in P['ratings']])}; "
           f"proxy-only: {len([e for e in P['ratings'] if e not in O['ratings']])}.", ""]
    res = {"both": len(both), "rows": []}
    if both:
        po, pp = [O["ratings"][e]["score"] for e in both], [P["ratings"][e]["score"] for e in both]
        d = [x - y for x, y in zip(po, pp)]
        rho = spearman(po, pp) if len(both) >= 3 and len(set(po)) > 1 and len(set(pp)) > 1 else None
        p = perm_p(pp, po, greater=True) if rho is not None else None
        out += ["| n | Spearman (owner, proxy) | one-sided p | exact | within one | mean owner - proxy | MAE |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                f"| {len(both)} | {f2(rho)} | {fp(p)} | {f2(mean([x == 0 for x in d]))} | {f2(mean([abs(x) <= 1 for x in d]))} | "
                f"{mean(d):+.2f} | {f2(mean([abs(x) for x in d]))} |", ""]
        res.update(rho=rho, p=p, exact=mean([x == 0 for x in d]), within1=mean([abs(x) <= 1 for x in d]), mean_diff=mean(d))
        if len(both) < 10:
            out += small_n(len(both))
        out += ["## Every excerpt both rated, largest difference first", ""]
        for e in sorted(both, key=lambda e: (-abs(O["ratings"][e]["score"] - P["ratings"][e]["score"]), e)):
            k = ke[e]
            o, q = O["ratings"][e], P["ratings"][e]
            out += [f"### {e}: owner {o['score']}, proxy {q['score']}",
                    f"- {k.get('source')} {k.get('run')} ({k.get('variant')}) {k.get('character')}, minutes {k.get('window_min')}",
                    f"- owner's reason: {o['reason'] or '(none given)'}", f"- proxy's reason: {q['reason'] or '(none given)'}", ""]
            res["rows"].append({"id": e, "owner": o["score"], "proxy": q["score"]})
    report = "\n".join(out) + "\n"
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    (od / "compare_report.md").write_text(report)
    (od / "compare_result.json").write_text(json.dumps(res, indent=1) + "\n")
    print(report)
    print(f"wrote {od / 'compare_report.md'}")


# ---- judge -----------------------------------------------------------------------------

# The scale exactly as the rating page words it; every criterion beyond it comes from the owner's reasons.
PREAMBLE = """You rate short excerpts from the life of one character in a persistent world, told from the
character's side: what they noticed, said and did over about ten minutes.
The question, as the owner was asked it: does this feel like a player living their own life?
1 = an NPC getting by, 3 = could go either way, 5 = clearly a player living their own life.
The owner of the game rated other excerpts; what made them feel one way or the other, in the owner's own words:"""
PROXY_PREAMBLE = PREAMBLE.replace(
    "The owner of the game rated other excerpts; what made them feel one way or the other, in the owner's own words:",
    "Another rater, rating on the owner's behalf (not the owner), rated other excerpts; what made them feel one way or "
    "the other, in that rater's words:")
CAP_REASON, CAP_LIST, ANCHOR_LINES = 240, 15, 30
ASK = 'Reply with JSON {"score": 1-5, "why": "one line"}'


def render(ex, max_lines=None):
    lines = ex.get("lines", [])
    shown = lines if max_lines is None else lines[:max_lines]
    # As the rating page shows it: the intro, then each line's time and text (the kind is only styling there).
    text = [t for t in (ex.get("title", ""), ex.get("intro", "")) if t] + [f"{ln.get('t', ''):>6}  {ln.get('text', '')}".rstrip() for ln in shown]
    if len(shown) < len(lines):
        text.append(f"… ({len(lines) - len(shown)} more lines)")
    return "\n".join(text)


def rubric(R, others):
    def bucket(pred):
        seen, out = set(), []
        for e in others:
            r = R["ratings"][e]
            t = " ".join(r["reason"].split())[:CAP_REASON]
            if t and pred(r["score"]) and t.lower() not in seen:
                seen.add(t.lower())
                out.append(f"- ({r['score']}) {t}")
        return out[:CAP_LIST] or ["- (no reasons given)"]
    W = "rater" if R.get("proxy") else "owner"
    return "\n".join([PROXY_PREAMBLE if R.get("proxy") else PREAMBLE, "", f"What made it feel like a player ({W} scores 4-5):",
                      *bucket(lambda s: s >= 4), "", f"What made it feel like an NPC ({W} scores 1-2):", *bucket(lambda s: s <= 2)])


def anchors(R, others):
    c = sorted(others, key=lambda e: (R["ratings"][e]["score"], e))
    if len(c) <= 4:
        return c
    picks = []
    for k in range(4):
        e = c[round(k * (len(c) - 1) / 3)]
        if e not in picks:
            picks.append(e)
    return picks


def prompt_for(e, R, rated, excerpts):
    others = [o for o in rated if o != e]
    msgs = [{"role": "system", "content": rubric(R, others)}]
    for o in anchors(R, others):
        r = R["ratings"][o]
        msgs.append({"role": "user", "content": render(excerpts[o], ANCHOR_LINES) + "\n\n" + ASK})
        msgs.append({"role": "assistant", "content": json.dumps({"score": r["score"], "why": r["reason"][:CAP_REASON] or ("the rater's rating" if R.get("proxy") else "the owner's rating")})})
    msgs.append({"role": "user", "content": render(excerpts[e]) + "\n\n" + ASK})
    return msgs


def parse_reply(text):
    m = re.search(r"\{.*?\}", text or "", re.S)
    for cand in ([m.group(0)] if m else []) + [text or ""]:
        try:
            d = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(d, dict):
            s = parse_score(d.get("score"), integer=False)
            return (s, str(d.get("why", ""))) if s is not None else (None, "score missing or outside 1..5")
    return None, "unparsable reply"


def read_env_file(path):
    vals = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        vals[k.strip()] = v.strip().strip("'\"")
    return vals


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it would carry the Authorization header, or leave the fake server's host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener(fake):
    # No proxies for a fake server, so "127.0.0.1" really is this machine.
    return urllib.request.build_opener(NoRedirect, *([urllib.request.ProxyHandler({})] if fake else []))


def scrub(text, secret):
    return text.replace(secret, "<key>") if secret else text


def retry_after(headers):
    try:
        return min(30.0, max(0.0, float(headers.get("Retry-After") or 3)))
    except (TypeError, ValueError):
        return 3.0


def call(base, model, key, msgs, fake):
    """POST one chat completion. Returns (status or None, text); never raises, never echoes the key."""
    body = json.dumps({"model": model, "messages": msgs, "temperature": 0, "max_tokens": 300,
                       "response_format": {"type": "json_object"}}).encode()
    headers = {"Content-Type": "application/json"} | ({"Authorization": f"Bearer {key}"} if key else {})
    op = opener(fake)
    for attempt in range(2):
        try:
            req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, headers=headers)
            with op.open(req, timeout=60) as r:
                return r.status, r.read().decode(errors="replace")
        except urllib.error.HTTPError as err:
            if attempt == 0 and (err.code == 429 or err.code >= 500):
                time.sleep(retry_after(err.headers))
                continue
            try:
                text = err.read().decode(errors="replace")
            except Exception:  # noqa: BLE001  (a body that cannot be read is still an HTTP failure)
                text = ""
            return err.code, scrub(text, key)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
            if attempt == 0:
                time.sleep(3)
                continue
            return None, scrub(f"{type(err).__name__}: {err}", key)
        except Exception as err:  # noqa: BLE001  (e.g. ValueError for a bad header: its message can hold the key)
            return None, f"{type(err).__name__} (message withheld: it may contain request headers)"
    return None, "no attempt made"


def cmd_judge(a):
    if a.proxy:
        print(PROXY_BANNER)
        print("judge refused on proxy ratings: the LLM judge waits for the owner's own ratings (no prompts built, no call made)", file=sys.stderr)
        sys.exit(2)
    key_data, excerpts, R = load_inputs(a, need_excerpts=True)
    host = urllib.parse.urlparse(a.base_url).hostname if a.base_url else None
    fake = host in ("127.0.0.1", "localhost", "::1")
    if R is None:
        refuse(R, "the ratings file is missing, empty or not JSON")
    rated, foreign = joined(key_data, R, excerpts)
    n = len(rated)
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    head = banner(R, n, fake=a.run and fake)
    W, sx = who(R), suffix(R)
    if not a.run:
        if not rated:
            refuse(R, "no rated excerpt is in both the key and the excerpts")
        rows = [{"id": e, W: R["ratings"][e]["score"], "synthetic": R["synthetic"], "proxy": bool(R.get("proxy")),
                 "messages": prompt_for(e, R, rated, excerpts)} for e in rated]
        with open(od / f"judge_prompts{sx}.jsonl", "w") as f:
            f.write(json.dumps({"meta": {"banner": head, "synthetic": R["synthetic"], "proxy": bool(R.get("proxy")), "prompts": len(rows)}},
                               ensure_ascii=False) + "\n")
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        chars = sum(len(m["content"]) for r in rows for m in r["messages"])
        tin, tout = chars // 4, 80 * len(rows)
        c = trials.cost(JUDGE_MODEL, tin, tout, 0)
        print("\n".join(head + small_n(n)))
        print(accounting(R, n, foreign))
        print(f"judge dry run: {len(rows)} prompts, one per rated excerpt (first line of the file is a meta row) "
              f"-> {od / f'judge_prompts{sx}.jsonl'}")
        print(f"estimated {tin} input tokens (chars / 4), about {tout} output tokens; "
              f"estimated ${c:.4f} on {JUDGE_MODEL} (trials.PRICES, an estimate, not an invoice). No network call was made.")
        return
    if R["synthetic"] and not fake:
        print(SYNTH_BANNER)
        print("judge --run refused: synthetic ratings may be judged only by a fake server (--base-url on 127.0.0.1/localhost)", file=sys.stderr)
        sys.exit(2)
    if n < 5:
        refuse(R, "fewer than five usable ratings joined to the key and the excerpts")
    if not a.base_url and os.environ.get("FEEL_JUDGE_PAID") != "1":
        print("judge --run refused: give --base-url explicitly, or set FEEL_JUDGE_PAID=1 to opt in to the paid default "
              f"({JUDGE_URL}, {JUDGE_MODEL})", file=sys.stderr)
        sys.exit(2)
    base = a.base_url or JUDGE_URL
    # A fake server never gets a key, even when one is set.
    secret = None
    if not fake:
        secret = (os.environ.get(a.key_env) or (read_env_file(a.env_file).get(a.key_env) if a.env_file else None) or "").strip()
        if not secret:
            print(f"judge --run refused: {a.key_env} is not set (environment or --env-file)", file=sys.stderr)
            sys.exit(2)
        if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in secret):
            print(f"judge --run refused: {a.key_env} contains whitespace or control characters (not shown)", file=sys.stderr)
            sys.exit(2)
    print("\n".join(head), file=sys.stderr)
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    todo = rated[: a.max_calls if a.max_calls is not None else n]
    results, used = {}, Counter()
    with open(od / "judge_journal.jsonl", "a") as jf:
        for e in todo:
            msgs = prompt_for(e, R, rated, excerpts)
            t0 = time.monotonic()
            status, raw = call(base, a.model, secret, msgs, fake)
            ms = round((time.monotonic() - t0) * 1000)
            content, usage = None, None
            try:
                resp = json.loads(raw)
                content, usage = resp["choices"][0]["message"]["content"], resp.get("usage")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass
            score, why = (parse_reply(content) if content is not None else
                          (None, f"no reply content (HTTP {status})" + (f": {raw[:160]}" if status is None else "")))
            results[e] = (score, why)
            for k in ("prompt_tokens", "completion_tokens"):
                used[k] += (usage or {}).get(k) or 0
            jf.write(json.dumps({"run": run_id, "id": e, "fake": fake, "synthetic": R["synthetic"], "base_url": base, "model": a.model,
                                 "messages": msgs, "status": status, "raw": raw, "score": score, "why": why, "latency_ms": ms,
                                 "usage": usage, W: R["ratings"][e]["score"], "proxy": bool(R.get("proxy"))}, ensure_ascii=False) + "\n")
            print(f"{e}: judge {score if score is not None else 'FAILED'} {W} {R['ratings'][e]['score']} ({ms} ms)", file=sys.stderr)
    ok = [e for e in todo if results[e][0] is not None]
    fails = [e for e in todo if results[e][0] is None]
    out = head + [""] + (small_n(len(ok)) if len(ok) >= 5 else []) + [f"# LLM judge against the {'proxy ratings' if R.get('proxy') else 'owner'} (leave-one-out rubric and anchors)", ""] + head + [""]
    out.append(accounting(R, n, foreign))
    out.append(f"Run {run_id}: {a.model} at {base}; {len(todo)} calls, {len(ok)} scored, {len(fails)} failed "
               f"(unparsable or score outside 1..5; journal {od / 'judge_journal.jsonl'}).")
    c = trials.cost(a.model, used["prompt_tokens"], used["completion_tokens"], 0)
    out.append(f"Tokens reported by the server: {used['prompt_tokens']} in, {used['completion_tokens']} out"
               + (f"; about ${c:.4f} at trials.PRICES (an estimate)." if c is not None and not fake else "."))
    if len(ok) >= 5:
        mt = metrics([results[e][0] for e in ok], [R["ratings"][e]["score"] for e in ok])
        out += ["", "perm p is one-sided (H1: rho > 0); a constant judge has no rho.", "",
                "| n | Spearman | perm p | within one | exact | MAE |", "| ---: | ---: | ---: | ---: | ---: | ---: |",
                f"| {mt['n']} | {f2(mt['rho'])} | {fp(mt['p'])} | {f2(mt['within1'])} | {f2(mt['exact'])} | {f2(mt['mae'])} |"]
        if mt["rho"] is not None and mt["rho"] <= 0:
            out.append(f"\nThe judge does not agree positively with the {'proxy ratings' if R.get('proxy') else 'owner'} at this n.")
        elif mt["p"] is None or mt["p"] >= 0.05:
            out.append("\nNot distinguishable from chance at this n.")
    else:
        out.append(f"\nFewer than five scored replies: {REFUSE}.")
    out += ["", f"## Disagreements (|judge - {W}| >= 2)", ""]
    dis = [e for e in ok if abs(results[e][0] - R["ratings"][e]["score"]) >= 2]
    for e in dis:
        k = key_data["excerpts"][e]
        out += [f"### {e}: {W} {R['ratings'][e]['score']}, judge {results[e][0]}",
                f"- {k.get('source')} {k.get('run')} {k.get('character')}, minutes {k.get('window_min')}",
                f"- {W}'s reason: {R['ratings'][e]['reason'] or '(none given)'}", f"- judge's why: {results[e][1]}", ""]
    out += ["None." if not dis else ""] + ([f"Failed: " + ", ".join(f"{e} ({results[e][1]})" for e in fails)] if fails else [])
    report = "\n".join(out) + "\n"
    (od / f"judge_report{sx}.md").write_text(report)
    print(report)
    print(f"wrote {od / f'judge_report{sx}.md'}")


# ---- synth -----------------------------------------------------------------------------

FAKE_REASONS = ["kept to its own plan for the whole stretch", "only ate and slept", "asked people things and followed up",
                "repeated the same failed act", "wandered off to look at the ridge", "talked but nobody answered", ""]


def cmd_synth(a):
    key = json.loads(Path(a.key).read_text())
    rng = random.Random(a.seed)
    ratings = {}
    for e in sorted(key["excerpts"]):
        f0 = num(key["excerpts"][e].get("feel0"))
        s = min(5, max(1, round(1 + 4 * (f0 if f0 is not None else 0.5) + rng.gauss(0, 0.8))))
        why = rng.choice(FAKE_REASONS)
        ratings[e] = {"score": s, "reason": f"[synthetic] {why}" if why else "", "at": key.get("built")}
    Path(a.out).write_text(json.dumps({"synthetic": True, "rater": "synthetic (not the owner)",
                                       "note": f"Generated by feel_tune.py synth --seed {a.seed}: score = 1 + 4*feel0 + noise (sd 0.8). "
                                               "For plumbing tests only; it measures nothing about the owner.",
                                       "ratings": ratings}, indent=1) + "\n")
    print(SYNTH_BANNER)
    print(f"wrote {len(ratings)} synthetic ratings to {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fit", "judge"):
        p = sub.add_parser(name)
        p.add_argument("--ratings", required=True)
        p.add_argument("--key", default=str(FEEL / "excerpts_key.json"))
        p.add_argument("--excerpts", default=str(FEEL / "excerpts.json"))
        p.add_argument("--out", default=str(FEEL))
        p.add_argument("--proxy", action="store_true", help="use ratings whose rater starts with 'proxy:' (and only those); "
                       "every output says PROXY RATINGS and none calls them the owner's")
    sub.choices["fit"].add_argument("--probe", metavar="COL[,COL]", help="columns kept out of every model and reported "
                                    "beside it: their rho with the rating and with the window ridge's residual")
    sub.choices["fit"].add_argument("--pipeline-perms", type=int, default=0, metavar="N",
                                    help="rerun the whole leave-one-out fit on N rating shuffles for a p that includes "
                                         "fitting and selection (about 1 s per shuffle at n = 20)")
    j = sub.choices["judge"]
    g = j.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True, help="build prompts and estimate cost (default)")
    g.add_argument("--run", action="store_true", help="call the model")
    j.add_argument("--base-url")
    j.add_argument("--model", default=JUDGE_MODEL)
    j.add_argument("--key-env", default="MISTRAL_API_KEY")
    j.add_argument("--env-file")
    j.add_argument("--max-calls", type=int)
    sc = sub.add_parser("score", help="the tuned score per arm of batches, always beside false replies, repeats and outcomes")
    sc.add_argument("batches", nargs="+", help="batch directories (read-only)")
    sc.add_argument("--model", default=str(FEEL / "proxy-fit/tune_result_proxy.json"), help="a fit's tune_result*.json")
    sc.add_argument("--baseline", help="the arm others are judged against (default: a 'control' arm, else 'default', else the first)")
    sc.add_argument("--window", type=float, default=10.0)
    sc.add_argument("--windows", type=int, default=6, help="windows per character")
    sc.add_argument("--residents", type=int, default=12, help="thinking residents per run")
    sc.add_argument("--out", default=str(FEEL))
    c = sub.add_parser("compare", help="the owner's ratings against the proxy's, on the excerpts both rated")
    c.add_argument("--owner", required=True, help="ratings (file or dump directory); proxy documents in it are ignored")
    c.add_argument("--proxy", required=True, help="proxy ratings (file or dump directory, e.g. the copy saved before the owner rated)")
    c.add_argument("--key", default=str(FEEL / "excerpts_key.json"))
    c.add_argument("--excerpts", default=str(FEEL / "excerpts.json"))
    c.add_argument("--out", default=str(FEEL))
    s = sub.add_parser("synth")
    s.add_argument("--key", default=str(FEEL / "excerpts_key.json"))
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    {"fit": cmd_fit, "judge": cmd_judge, "synth": cmd_synth, "compare": cmd_compare, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
