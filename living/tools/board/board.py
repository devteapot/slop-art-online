#!/usr/bin/env python3
"""The asset board: every generated asset family photographed in the game's own renderer in fixed
shots, beside the version the owner last accepted, with what changed made visible, and the owner's
decisions and the full history kept as small records in git. docs/ASSET_BOARD.md is the guide.

    board.py publish --family building:cone --model cone=out/cone.glb --generator G --seed 1 [...]
    board.py publish --manifest pass.json
    board.py import  --family character:adult-man --member man=page/img/ours-{shot}.jpg [...]
    board.py decide  FAMILY VERSION|latest accept|reject --words "the owner's words" [--note ...]
    board.py status  [FAMILY]
    board.py build
    board.py pack    [--out FILE.tar.gz]

Records (tracked): <repo>/living/assets/board/<family>/{family.json, versions/<id>.json,
decisions/<date>-<id>-<verdict>.json}; one file each, so tracks and coordinators never edit the
same file. The board's home ($ASSET_BOARD_HOME, default ~/archive/asset-board) mirrors every
record under records/ and holds the media (media/<family>/<id>/) and the pages (index.html,
family/<family>.html), all linked by relative paths, so the folder can be packed and opened
anywhere.
"""

import argparse
import datetime
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOL_DIR)
import capture as C  # noqa: E402
import glb as G  # noqa: E402

TOOL_REPO = os.path.normpath(os.path.join(TOOL_DIR, "..", "..", ".."))
RECORDS = os.path.join("living", "assets", "board")
SCHEMA = 1
FILE_LIMIT = 64 << 20  # model files kept with a version for re-rendering, up to this size


# ---------------------------------------------------------------------------------------------
# Places


def board_home():
    return os.path.abspath(os.path.expanduser(os.environ.get("ASSET_BOARD_HOME") or "~/archive/asset-board"))


def repo_root(given=None):
    if given:
        return os.path.abspath(given)
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else TOOL_REPO


def slug(family):
    if not re.fullmatch(r"[a-z0-9]+:[a-z0-9][a-z0-9_.-]*", family):
        sys.exit(f"board: family names are kind:name in lower case, for example building:cone (got {family!r})")
    return family.replace(":", "-")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def today():
    return datetime.date.today().isoformat()


def git(repo, *args):
    return C.git(repo, *args)


# ---------------------------------------------------------------------------------------------
# Records: repo copy (tracked) and the home's mirror; reads take the union.


def record_dirs(repo):
    # ASSET_BOARD_RECORDS replaces the repository's copy (for trial runs that must not touch git).
    return [os.path.abspath(os.environ.get("ASSET_BOARD_RECORDS") or os.path.join(repo, RECORDS)), os.path.join(board_home(), "records")]


def write_record(repo, rel, data):
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    for base in record_dirs(repo):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    return os.path.join(record_dirs(repo)[0], rel)


def load_all(repo):
    """{family: {"family": {...}, "versions": {id: {...}}, "decisions": [...]}} from both places;
    where both hold a file, the repo's copy wins."""
    out = {}
    for base in reversed(record_dirs(repo)):  # home first, then the repo overrides
        for p in glob.glob(os.path.join(base, "*", "family.json")) + glob.glob(os.path.join(base, "*", "versions", "*.json")) + glob.glob(os.path.join(base, "*", "decisions", "*.json")):
            try:
                d = json.load(open(p))
            except (OSError, json.JSONDecodeError) as e:
                print(f"board: skipping {p}: {e}", file=sys.stderr)
                continue
            fam = d.get("family") or d.get("name")
            if not fam:
                continue
            f = out.setdefault(fam, {"family": {"name": fam}, "versions": {}, "decisions": {}})
            kind = os.path.basename(os.path.dirname(p))
            if os.path.basename(p) == "family.json":
                f["family"] = d
            elif kind == "versions":
                f["versions"][d["id"]] = d
            elif kind == "decisions":
                f["decisions"][os.path.basename(p)] = d
    for f in out.values():
        f["decisions"] = sorted(f["decisions"].values(), key=lambda d: (d.get("date", ""), d.get("recorded", "")))
    return out


def standing(fam):
    """Each version's last verdict, the accepted version (the most recent accept still standing),
    the one accepted before it, and the latest published version."""
    last = {}
    accepts = []
    for d in fam["decisions"]:
        last[d["version"]] = d
        if d["verdict"] == "accept":
            accepts = [a for a in accepts if a["version"] != d["version"]] + [d]
    standing_accepts = [a for a in accepts if last[a["version"]]["verdict"] == "accept" and a["version"] in fam["versions"]]
    accepted = standing_accepts[-1]["version"] if standing_accepts else None
    before = standing_accepts[-2]["version"] if len(standing_accepts) > 1 else None
    versions = sorted(fam["versions"].values(), key=lambda v: v.get("published", ""))
    latest = versions[-1]["id"] if versions else None
    return last, accepted, before, latest


def baseline_for(fam):
    """(latest, baseline): the latest version and what it is shown beside: the accepted version,
    or, when the latest is the accepted one, the version accepted before it."""
    _, accepted, before, latest = standing(fam)
    if latest and latest == accepted:
        return latest, before
    return latest, accepted


# ---------------------------------------------------------------------------------------------
# Identity of a version


def source_identity(repo, a, generator):
    commit = git(repo, "rev-parse", "--verify", "--quiet", f"{a['commit']}^{{commit}}") or a["commit"] if a.get("commit") else git(repo, "rev-parse", "HEAD")
    branch = a.get("branch") or git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    src = {"commit": commit, "branch": branch}
    if not a.get("commit"):
        src["dirty"] = bool(git(repo, "status", "--porcelain", "--untracked-files=no"))
    if generator:
        src["generator"] = generator
        path = os.path.join(repo, generator)
        if a.get("generator_sha256"):
            src["generator_sha256"] = a["generator_sha256"]
        elif a.get("commit"):
            r = subprocess.run(["git", "-C", repo, "show", f"{commit}:{generator}"], capture_output=True)
            if r.returncode == 0:
                src["generator_sha256"] = hashlib.sha256(r.stdout).hexdigest()
                src["generator_state"] = "committed"
        elif os.path.exists(path):
            src["generator_sha256"] = G.sha256(path)
            tracked = subprocess.run(["git", "-C", repo, "ls-files", "--error-unmatch", generator], capture_output=True).returncode == 0
            changed = bool(git(repo, "status", "--porcelain", "--", generator))
            src["generator_state"] = "untracked" if not tracked else ("modified" if changed else "committed")
    if a.get("seed") is not None:
        src["seed"] = a["seed"]
    src["params"] = a.get("params") or {}
    return src


def version_id(src, members, date=None):
    h = hashlib.sha256(json.dumps({"g": src.get("generator_sha256"), "s": src.get("seed"), "p": src.get("params"),
                                   "m": [(m["name"], m.get("sha256"), m.get("token_kind"), json.dumps(m.get("recipe"), sort_keys=True)) for m in members]}, sort_keys=True).encode()).hexdigest()
    return f"{(date or today()).replace('-', '')}-{src['commit'][:8]}-{h[:4]}"


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def recipe_entry(repo, name):
    p = os.path.join(repo, "living", "game", "assets", "characters", "recipes.json")
    if not os.path.exists(p):
        return None
    return next((r for r in json.load(open(p))["recipes"] if r["name"] == name), None)


def recipe_file(repo, entry):
    """The file the game loads for a recipe: the animated copy where there is one."""
    if not entry:
        return None
    base = entry["base"]
    anim = os.path.join(repo, "living", "game", "assets", "lookdev", "anim", os.path.basename(base))
    plain = os.path.join(repo, "living", "game", "assets", base)
    return anim if os.path.exists(anim) else (plain if os.path.exists(plain) else None)


def generator_report(path, key):
    if not path or not os.path.exists(path):
        return None
    r = json.load(open(path))
    for holder in (r.get("models"), r):
        if isinstance(holder, dict) and isinstance(holder.get(key), dict):
            return holder[key]
    return None


# ---------------------------------------------------------------------------------------------
# Family files


def ensure_family(repo, families, name, kind=None, title=None, description=None, target=None):
    s = slug(name)
    fam = families.get(name, {}).get("family") or {}
    changed = not fam.get("kind")
    fam = {"schema": SCHEMA, "family": name, **{k: v for k, v in fam.items() if k not in ("schema", "family", "name")}}
    for k, v in (("kind", kind or fam.get("kind") or name.split(":")[0]), ("title", title), ("description", description), ("target", target)):
        if v and fam.get(k) != v:
            fam[k] = v
            changed = True
    fam.setdefault("title", name)
    if changed:
        write_record(repo, f"{s}/family.json", fam)
    families.setdefault(name, {"family": fam, "versions": {}, "decisions": []})["family"] = fam
    return fam


def preset_for(kind):
    return "character" if kind == "character" else ("prop" if kind == "prop" else "building")


# ---------------------------------------------------------------------------------------------
# publish


def parse_member(spec, role):
    name, _, token = spec.partition("=")
    if not token or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name):
        sys.exit(f"board: a model is NAME=PATH or NAME=recipe:RECIPE, NAME in lower case (got {spec!r})")
    return {"name": name, "token": token, "role": role}


def manifest_from_args(a):
    if a.manifest:
        m = json.load(open(a.manifest))
        for k in ("generator", "seed", "note", "track", "maker", "commit", "branch", "generator_sha256"):
            if getattr(a, k, None) is not None:
                m[k] = getattr(a, k)
        if a.param:
            m["params"] = {**m.get("params", {}), **parse_params(a.param)}
        return m
    if not a.family or not a.model:
        sys.exit("board: publish needs --family and at least one --model (or --manifest)")
    members = [parse_member(s, "subject") for s in a.model] + [parse_member(s, "control") for s in a.control or []]
    return {"generator": a.generator, "seed": a.seed, "params": parse_params(a.param), "note": a.note, "track": a.track, "maker": a.maker,
            "commit": a.commit, "branch": a.branch, "generator_sha256": a.generator_sha256,
            "families": [{"family": a.family, "kind": a.kind, "title": a.title, "description": a.description, "target": a.target, "members": members,
                          "report": a.report, "report_keys": dict(kv.split("=", 1) for kv in a.report_key or []), "delivered": a.delivered or []}]}


def publish(a):
    repo = repo_root(a.repo)
    man = manifest_from_args(a)
    families = load_all(repo)
    home = board_home()
    published = []
    for fspec in man["families"]:
        name = fspec["family"]
        s = slug(name)
        fam = ensure_family(repo, families, name, fspec.get("kind"), fspec.get("title"), fspec.get("description"), fspec.get("target"))
        preset_name = fspec.get("preset") or preset_for(fam["kind"])
        preset = C.PRESETS[preset_name]
        merged = {**{k: man.get(k) for k in ("generator", "seed", "commit", "branch", "generator_sha256")}, **{k: v for k, v in fspec.items() if k in ("generator", "seed", "commit", "branch", "generator_sha256") and v is not None}}
        merged["params"] = {**(man.get("params") or {}), **(fspec.get("params") or {})}
        src = source_identity(repo, merged, merged.get("generator"))
        members = []
        for m in fspec["members"]:
            m = dict(m)
            tok = m.pop("token", None) or m.pop("path")
            if tok.startswith("recipe:"):
                entry = recipe_entry(repo, tok.split(":", 1)[1])
                if not entry:
                    sys.exit(f"board: no recipe {tok} in {repo}/living/game/assets/characters/recipes.json")
                path = recipe_file(repo, entry)
                m.update(token_kind="recipe", token=tok, recipe=entry)
            else:
                path = os.path.abspath(tok)
                if not os.path.exists(path):
                    sys.exit(f"board: no model file {tok}")
                m.update(token_kind="file", source_path=os.path.relpath(path, repo) if path.startswith(repo + os.sep) else path)
            m["path"] = path
            if path:
                m["sha256"] = G.sha256(path)
            members.append(m)
        vid = version_id(src, members)
        media_rel = f"media/{s}/{vid}"
        media = os.path.join(home, media_rel)
        if os.path.isdir(media):
            print(f"board: {name} {vid} was published before; photographing it again", file=sys.stderr)
            shutil.rmtree(media)
        os.makedirs(media)
        scratch = os.path.join(home, ".scratch", vid)
        shutil.rmtree(scratch, ignore_errors=True)
        os.makedirs(scratch)
        # Measure every member from its file, and keep file members for re-rendering.
        for m in members:
            if m.get("path"):
                m["stats"] = G.stats(m["path"])
                m["glow"] = m["stats"]["glow"]
            if m["token_kind"] == "file":
                dst = os.path.join(media, "files", f"{m['name']}.glb")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.getsize(m["path"]) <= FILE_LIMIT:
                    shutil.copy2(m["path"], dst)
                    m["file"] = f"files/{m['name']}.glb"
                # The asset view copies files from outside its folder by name; a name of its own
                # keeps two publishes (or two versions in one run) apart.
                view_copy = os.path.join(scratch, "in", f"b{vid[-4:]}{vid[9:13]}-{m['name']}.glb")
                os.makedirs(os.path.dirname(view_copy), exist_ok=True)
                shutil.copy2(m["path"], view_copy)
                m["view_token"] = view_copy
            else:
                m["view_token"] = m["token"]
            key = (fspec.get("report_keys") or {}).get(m["name"]) or os.path.splitext(os.path.basename(m["path"] or m["name"]))[0]
            rep = generator_report(fspec.get("report") or man.get("report"), key) or generator_report(fspec.get("report") or man.get("report"), m["name"])
            if rep:
                m["report"] = rep
        # The renderer: the board's own game for files (it has the board's shots and night), the
        # publishing repo's for recipes (its characters and recipe book).
        renderer_repo = os.path.abspath(a.renderer_repo) if a.renderer_repo else (repo if any(m["token_kind"] == "recipe" for m in members) else TOOL_REPO)
        game = a.game or C.build_game(renderer_repo, jobs=a.jobs)
        renderer = C.renderer_identity(renderer_repo, preset)
        renderer["repo"] = renderer_repo
        print(f"board: photographing {name} {vid} ({len(members)} model(s), renderer {renderer['key']})", file=sys.stderr)
        tokens = [{"name": m["name"], "token": m["view_token"], "glow": m.get("glow")} for m in members]
        shots, clips, views = C.capture(game, renderer_repo, tokens, preset_name, media, os.path.join(scratch, "shots"), clips=False if a.no_clips else (a.clips.split(",") if a.clips else True), only_shots=a.shots and a.shots.split(","))
        for m in members:
            m["shots"] = shots.get(m["name"], [])
            m["clips"] = clips.get(m["name"], [])
            v = views.get(m["name"])
            if v:
                m["view"] = {k: v[k] for k in ("size_m", "triangles", "vertices", "meshes", "materials", "glow", "vertex_colours") if k in v}
        record = {"schema": SCHEMA, "family": name, "id": vid, "published": now_iso(), "track": man.get("track"), "maker": man.get("maker"),
                  "note": fspec.get("note") or man.get("note"), "source": src, "renderer": renderer, "preset": preset_name, "media": media_rel,
                  "members": [{k: v for k, v in m.items() if k not in ("path", "view_token", "glow")} for m in members], "delivered": []}
        keep_delivered(record, media, fspec.get("delivered") or [])
        # The accepted version, photographed again by this renderer where it differs, so the
        # comparison shows the models' change and not the renderer's.
        _, accepted, _, _ = standing(families.get(name, {"decisions": [], "versions": {}}))
        if accepted and accepted != vid and not a.no_rerender:
            rerender_baseline(record, families[name]["versions"][accepted], game, renderer_repo, preset_name, renderer, home, scratch, a)
        write_record(repo, f"{s}/versions/{vid}.json", record)
        families[name]["versions"][vid] = record
        shutil.rmtree(scratch, ignore_errors=True)
        cleanup_view_copies(renderer_repo, members)
        published.append((name, vid))
    build(repo)
    for name, vid in published:
        print(f"published {name} {vid}")
        print(f"  page: {os.path.join(home, 'family', slug(name) + '.html')}")
        print(f"  record: {os.path.join(record_dirs(repo)[0], slug(name), 'versions', vid + '.json')} (commit it with the pass)")
    print(f"board: {os.path.join(home, 'index.html')}")


def cleanup_view_copies(renderer_repo, members):
    for m in members:
        t = m.get("view_token", "")
        if m.get("token_kind") == "file" and t:
            p = os.path.join(renderer_repo, "living", "game", "assets", "view", os.path.basename(t))
            if os.path.exists(p):
                os.remove(p)


def rerender_baseline(record, base, game, renderer_repo, preset_name, renderer, home, scratch, a):
    br = base.get("renderer", {})
    if br.get("key") == renderer["key"] and br.get("preset") == renderer["preset"]:
        return
    names = {m["name"] for m in record["members"]}
    tokens = []
    for m in base.get("members", []):
        f = m.get("file") and os.path.join(home, base["media"], m["file"])
        if m["name"] in names and f and os.path.exists(f):
            t = os.path.join(scratch, "base", f"a{base['id'][-4:]}{base['id'][9:13]}-{m['name']}.glb")
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(f, t)
            tokens.append({"name": m["name"], "token": t, "glow": m.get("stats", {}).get("glow"), "view_token": t, "token_kind": "file"})
    if not tokens:
        return
    rel = f"vs/{base['id']}/render"
    print(f"board: photographing the accepted version {base['id']} again with renderer {renderer['key']} ({len(tokens)} model(s))", file=sys.stderr)
    shots, _, _ = C.capture(game, renderer_repo, tokens, preset_name, os.path.join(home, record["media"], rel), os.path.join(scratch, "base-shots"), clips=False,
                            only_shots=a.shots and a.shots.split(","))
    record["baseline_render"] = {"version": base["id"], "path": rel, "renderer": renderer["key"], "members": {k: v for k, v in shots.items()}}
    cleanup_view_copies(renderer_repo, tokens)


def keep_delivered(record, media, items):
    """Copy a track's own pages, notes or renders into the version's media (delivered/)."""
    for it in items:
        if isinstance(it, str):
            title, _, path = it.partition("=") if "=" in it and not os.path.exists(it) else ("", "", it)
            it = {"title": title or os.path.basename(path.rstrip("/")), "path": path}
        src = os.path.abspath(it["path"])
        if not os.path.exists(src):
            sys.exit(f"board: nothing at {it['path']} to keep")
        dst = os.path.join(media, "delivered", os.path.basename(src.rstrip("/")))
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            entry = "index.html" if os.path.exists(os.path.join(dst, "index.html")) else ""
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            entry = ""
        rel = os.path.relpath(dst, media)
        record["delivered"].append({"title": it.get("title") or os.path.basename(src), "path": rel + ("/" + entry if entry else ""), "from": it["path"]})


# ---------------------------------------------------------------------------------------------
# import: media made elsewhere (a track's delivered page, a Blender render), without the game


def do_import(a):
    repo = repo_root(a.repo)
    families = load_all(repo)
    home = board_home()
    name = a.family
    s = slug(name)
    fam = ensure_family(repo, families, name, a.kind, a.title, a.description, a.target)
    src = source_identity(repo, {"commit": a.commit, "branch": a.branch, "generator_sha256": a.generator_sha256, "seed": a.seed, "params": parse_params(a.param)}, a.generator)
    stats = json.load(open(a.stats)) if a.stats else {}
    stats_keys = dict(kv.split("=", 1) for kv in a.stats_key or [])
    members, claims = [], {}
    for spec in a.member:
        left, _, pattern = spec.partition("=")
        mname, _, role = left.partition(":")
        if "{shot}" not in pattern:
            sys.exit(f"board: an imported member is NAME[:control]=PATTERN with {{shot}} in it (got {spec!r})")
        rx = re.compile("^" + re.escape(pattern).replace(re.escape("{shot}"), "(?P<shot>[A-Za-z0-9_-]+?)") + "$")
        found = sorted(p for p in glob.glob(pattern.replace("{shot}", "*")) if rx.match(p) and not p.endswith("-crop.png") and not any(fnmatch.fnmatch(p, x) for x in a.exclude or []))
        # A file two patterns match (vroid-{shot} and vroid-smith-{shot}) is the more specific one's.
        for p in found:
            shot = rx.match(p).group("shot")
            if p not in claims or len(shot) < len(claims[p][1]):
                claims[p] = (mname, shot)
        m = {"name": mname, "role": role or "subject", "token_kind": "import", "pattern": pattern, "found": found}
        st = stats.get(stats_keys.get(mname, mname))
        if st:
            m["stats"] = st
            m["sha256"] = st.get("sha256") or hashlib.sha256(json.dumps(st, sort_keys=True).encode()).hexdigest()
        members.append(m)
    date = (a.published or today())[:10]
    vid = version_id(src, members, date)
    media_rel = f"media/{s}/{vid}"
    media = os.path.join(home, media_rel)
    shutil.rmtree(media, ignore_errors=True)
    os.makedirs(media)
    from PIL import Image

    for m in members:
        m["shots"] = []
        for p in m.pop("found"):
            owner, shot = claims[p]
            if owner != m["name"] or (a.only_shots and shot not in a.only_shots.split(",")):
                continue
            dst = os.path.join(media, m["name"], shot + ".jpg")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            Image.open(p).convert("RGB").save(dst, quality=92)
            crop = os.path.splitext(p)[0] + "-crop.png"
            if os.path.exists(crop):  # the game camera's middle, enlarged (characters)
                shutil.copy2(crop, dst[:-4] + "-crop.png")
            m["shots"].append(shot)
        m["clips"] = []
        m.pop("pattern")
    for spec in a.clip or []:
        left, _, path = spec.partition("=")
        mname, _, cname = left.partition("/")
        m = next((x for x in members if x["name"] == mname), None)
        if not m:
            sys.exit(f"board: --clip {spec}: no member {mname}")
        dst = os.path.join(media, mname, "clips", os.path.basename(path))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
        m["clips"].append({"name": cname or os.path.splitext(os.path.basename(path))[0], "file": f"clips/{os.path.basename(path)}", "layout": a.clip_layout or ""})
    renderer = {"method": a.method, "commit": a.renderer_commit or "", "key": (a.renderer_commit or "")[:8] or a.method, "preset": C.preset_hash(C.PRESETS[preset_for(fam["kind"])]) if a.same_shots else "", "note": a.renderer_note or ""}
    record = {"schema": SCHEMA, "family": name, "id": vid, "published": a.published or now_iso(), "imported": now_iso(), "track": a.track, "maker": a.maker,
              "note": a.note, "source": src, "renderer": renderer, "preset": preset_for(fam["kind"]) if a.same_shots else "", "media": media_rel, "members": members, "delivered": []}
    keep_delivered(record, media, a.delivered or [])
    write_record(repo, f"{s}/versions/{vid}.json", record)
    families[name]["versions"][vid] = record
    build(repo)
    print(f"imported {name} {vid}: " + ", ".join(f"{m['name']} {len(m['shots'])} shots, {len(m['clips'])} clips" for m in members))


# ---------------------------------------------------------------------------------------------
# decide


def decide(a):
    repo = repo_root(a.repo)
    families = load_all(repo)
    if a.family not in families:
        sys.exit(f"board: no family {a.family}; families: {', '.join(sorted(families))}")
    fam = families[a.family]
    vid = a.version
    if vid == "latest":
        vid = standing(fam)[3]
    matches = [v for v in fam["versions"] if v == vid or v.startswith(vid) or v.endswith(vid)]
    if len(matches) != 1:
        sys.exit(f"board: {a.version} matches {len(matches)} versions of {a.family}: {', '.join(sorted(fam['versions']))}")
    vid = matches[0]
    date = a.date or today()
    d = {"schema": SCHEMA, "family": a.family, "version": vid, "verdict": a.verdict, "date": date, "by": a.by, "words": a.words, "note": a.note,
         "scope": a.scope, "recorded": now_iso(), "recorded_by": a.recorded_by}
    d = {k: v for k, v in d.items() if v not in (None, "")}
    p = write_record(repo, f"{slug(a.family)}/decisions/{date}-{vid}-{a.verdict}.json", d)
    build(repo)
    print(f"recorded: {a.family} {vid} {a.verdict} on {date}\n  {p} (commit it)")


# ---------------------------------------------------------------------------------------------
# status, build, pack


def status(a):
    repo = repo_root(a.repo)
    families = load_all(repo)
    for name in sorted(families):
        if a.family and name != a.family:
            continue
        fam = families[name]
        last, accepted, _, latest = standing(fam)
        st = last.get(latest, {}).get("verdict", "no decision") if latest else "nothing published"
        acc = f"accepted {accepted} ({last[accepted]['date']})" if accepted else "nothing accepted"
        print(f"{name:28} {len(fam['versions'])} version(s); {acc}; latest {latest or '-'}: {st}")


def build(repo=None):
    import page as P

    repo = repo or repo_root()
    families = load_all(repo)
    home = board_home()
    os.makedirs(os.path.join(home, "family"), exist_ok=True)
    P.write_board(home, families, standing, baseline_for)
    return families


def cmd_build(a):
    build(repo_root(a.repo))
    print(os.path.join(board_home(), "index.html"))


def check(a):
    """Every page's links and images resolve inside the board (run it on an unpacked tarball too)."""
    from html.parser import HTMLParser
    from urllib.parse import unquote

    home = os.path.abspath(a.home or board_home())
    pages = [os.path.join(home, "index.html")] + sorted(glob.glob(os.path.join(home, "family", "*.html")))
    missing, n = [], 0

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            nonlocal n
            for k, v in attrs:
                if k in ("src", "href", "data-base", "data-latest") and v and not re.match(r"^(#|[a-z]+:)", v):
                    n += 1
                    target = os.path.normpath(os.path.join(os.path.dirname(self.page), unquote(v.split("#")[0])))
                    if not target.startswith(home) or not os.path.exists(target):
                        missing.append((os.path.relpath(self.page, home), v))

    for pg in pages:
        p = P()
        p.page = pg
        p.feed(open(pg).read())
    for pg, v in missing[:40]:
        print(f"missing: {pg} -> {v}")
    print(f"{len(pages)} pages, {n} links, {len(missing)} missing")
    if missing:
        sys.exit(1)


def pack(a):
    home = board_home()
    build(repo_root(a.repo))
    out = os.path.abspath(os.path.expanduser(a.out or f"~/archive/deliverables/asset-board-{today().replace('-', '')}.tar.gz"))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    def keep(ti):
        rel = ti.name.split("/", 1)[1] if "/" in ti.name else ""
        if rel.startswith(".scratch") or (not a.with_files and "/files/" in "/" + rel):
            return None
        return ti

    with tarfile.open(out, "w:gz") as t:
        t.add(home, arcname="asset-board", filter=keep)
    print(f"{out} ({os.path.getsize(out) >> 20} MiB); open asset-board/index.html")


# ---------------------------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="the repository whose records to read and write (default: the one you are in)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def identity(p):
        p.add_argument("--generator", help="the generator script, relative to the repository")
        p.add_argument("--seed")
        p.add_argument("--param", action="append", help="KEY=VALUE, repeatable (JSON values are parsed)")
        p.add_argument("--commit", help="the source commit, when the models came from another branch")
        p.add_argument("--branch")
        p.add_argument("--generator-sha256", dest="generator_sha256")
        p.add_argument("--note")
        p.add_argument("--track", help="the track that made it, for example kit-1")
        p.add_argument("--maker", help="who made it, for example 'Claude Fable 5.2'")
        p.add_argument("--kind", choices=["building", "prop", "character"])
        p.add_argument("--title")
        p.add_argument("--description")
        p.add_argument("--target", help="the quality target, for example the VRoid control")
        p.add_argument("--delivered", action="append", help="TITLE=PATH or PATH: a page, notes or renders kept with the version")

    p = sub.add_parser("publish", help="photograph a family's models in the game and record the version")
    p.add_argument("--family")
    p.add_argument("--model", action="append", help="NAME=PATH.glb or NAME=recipe:RECIPE, repeatable")
    p.add_argument("--control", action="append", help="NAME=...: a control shown beside it (the quality target), repeatable")
    p.add_argument("--manifest", help="a JSON pass with several families (docs/ASSET_BOARD.md)")
    p.add_argument("--report", help="the generator's own report.json")
    p.add_argument("--report-key", action="append", help="MODEL=KEY in that report, when not the file's stem")
    p.add_argument("--game", help="a built living-game binary (default: build it)")
    p.add_argument("--renderer-repo", help="the repository whose game takes the photographs")
    p.add_argument("--jobs", type=int, default=12)
    p.add_argument("--no-clips", action="store_true")
    p.add_argument("--clips", help="only these clips, e.g. walk-tq,run-side (characters)")
    p.add_argument("--no-rerender", action="store_true", help="do not photograph the accepted version again")
    p.add_argument("--shots", help="only these shots (comma-separated), for a quick look")
    identity(p)
    p.set_defaults(fn=publish)

    p = sub.add_parser("import", help="record a version from media made elsewhere")
    p.add_argument("--family", required=True)
    p.add_argument("--member", action="append", required=True, help="NAME[:control]=PATTERN with {shot}, e.g. man=page/img/ours-{shot}.jpg")
    p.add_argument("--clip", action="append", help="MEMBER[/NAME]=PATH.mp4")
    p.add_argument("--clip-layout", help="what a clip shows, e.g. 'ours | VRoid'")
    p.add_argument("--stats", help="a JSON of file stats by member")
    p.add_argument("--stats-key", action="append", help="MEMBER=KEY in --stats")
    p.add_argument("--method", default="asset-view", help="how the media was rendered: asset-view (the game) or e.g. blender-eevee")
    p.add_argument("--renderer-commit")
    p.add_argument("--renderer-note")
    p.add_argument("--same-shots", action="store_true", help="the media uses the board's preset shots (comparable photograph by photograph)")
    p.add_argument("--only-shots")
    p.add_argument("--exclude", action="append", help="a glob of files no member takes, e.g. '*/vroid-smith-*'")
    p.add_argument("--published", help="when it was made (ISO date or time)")
    identity(p)
    p.set_defaults(fn=do_import)

    p = sub.add_parser("decide", help="record the owner's accept or reject")
    p.add_argument("family")
    p.add_argument("version", help="a version id (or a unique part of one), or latest")
    p.add_argument("verdict", choices=["accept", "reject"])
    p.add_argument("--words", help="the owner's words")
    p.add_argument("--note", help="context: what was compared, what it means")
    p.add_argument("--scope", help="what the accept means, e.g. base (start from it) or bar (good enough)")
    p.add_argument("--date", help="the day of the decision (default today)")
    p.add_argument("--by", default="owner")
    p.add_argument("--recorded-by", dest="recorded_by", default=os.environ.get("ASSET_BOARD_RECORDER", ""))
    p.set_defaults(fn=decide)

    p = sub.add_parser("status", help="each family's accepted and latest versions")
    p.add_argument("family", nargs="?")
    p.set_defaults(fn=status)
    p = sub.add_parser("build", help="write the pages again")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("check", help="every link and image on the pages resolves")
    p.add_argument("home", nargs="?", help="a board folder (default the board's home)")
    p.set_defaults(fn=check)
    p = sub.add_parser("pack", help="a tarball of the board (pages, media, records)")
    p.add_argument("--out")
    p.add_argument("--with-files", action="store_true", help="include the model files kept for re-rendering")
    p.set_defaults(fn=pack)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
