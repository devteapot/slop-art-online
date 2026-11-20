#!/usr/bin/env python3
"""What fills a world's commitlog: its bytes by table, by reducer input and by framing, read
offline from the replica's segments (SpacetimeDB 2.14.1's log format, `v2.14.1` `a0bf6be`).

    python3 living/tools/clog_read.py --replica 4000001 --schema schema.json [--container sg-stdb]
        [--segments all|last:N|0,1073741824] [--out bytes.json]

The format (crates/commitlog: segment.rs, commit.rs, payload/txdata.rs):
- a segment is a 10-byte header (`(ds)^2`, version 1, crc32c) and commits;
- a commit is min_tx_offset u64, epoch u64, n u16, len u32, then `len` bytes of n records, then a
  crc32c u32 (26 bytes of framing);
- a record (a transaction) is a flags byte, then the reducer's inputs (u32 length, u8 name length,
  name, BSATN args), its outputs (u8 length, text), and its mutations: a varint count of insert ops
  (u32 table id, varint row count, BSATN rows), the same for deletes, and truncated table ids.
Rows are not length-prefixed, so each table's row type is needed to step over them. `--schema` is
what clog_watch.py saves at the run's start: `spacetime describe --json` (the typespace and the
tables) and `st_table` (ids to names). A few system tables are known here; a record touching any
other table is counted whole as `undecoded` (the commit's length still frames it), as are the
publish's schema commits. Segments 2.14.1 has compressed (zstd, after a snapshot) are read through
`zstd -dc`.

Prints (and with `--out` writes) bytes per table (insert and delete rows, with their op headers),
per reducer (inputs), framing and undecoded, ranked, and the total checked against the files.
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict

CLOG = "/home/spacetime/.local/share/spacetime/data/replicas/{}/clog"
ZSTD_MAGIC = bytes.fromhex("28b52ffd")


# ---- BSATN sizes -------------------------------------------------------------------------------

FIXED = {"Bool": 1, "U8": 1, "I8": 1, "U16": 2, "I16": 2, "U32": 4, "I32": 4, "F32": 4, "U64": 8, "I64": 8, "F64": 8,
         "U128": 16, "I128": 16, "U256": 32, "I256": 32}


def kind(t):
    """An AlgebraicType in `spacetime describe --json` form: ({"U64": []} or {"Ref": 3} ...) -> (tag, body)."""
    if isinstance(t, dict) and len(t) == 1:
        return next(iter(t.items()))
    raise ValueError(f"type {t!r}")


def elements(body):
    return body["elements"] if isinstance(body, dict) else body


def variants(body):
    return body["variants"] if isinstance(body, dict) else body


def compile_type(t, types, memo):
    """A row type as either an int (fixed size) or a function (buf, pos) -> new pos."""
    tag, body = kind(t)
    if tag in FIXED:
        return FIXED[tag]
    if tag == "Ref":
        if body not in memo:
            memo[body] = None  # recursion guard
            memo[body] = compile_type(types[body], types, memo)
        r = memo[body]
        if r is None:
            raise ValueError("recursive type")
        return r
    if tag == "String":
        return lambda b, p: p + 4 + int.from_bytes(b[p:p + 4], "little")
    if tag == "Array":
        el = compile_type(body, types, memo)
        if isinstance(el, int):
            return lambda b, p, s=el: p + 4 + s * int.from_bytes(b[p:p + 4], "little")

        def arr(b, p, f=el):
            n = int.from_bytes(b[p:p + 4], "little")
            p += 4
            for _ in range(n):
                p = f(b, p)
            return p
        return arr
    if tag == "Product":
        parts = [compile_type(e["algebraic_type"], types, memo) for e in elements(body)]
        if all(isinstance(x, int) for x in parts):
            return sum(parts)
        fixed_run = []
        steps = []
        for x in parts:
            if isinstance(x, int):
                fixed_run.append(x)
            else:
                if fixed_run:
                    steps.append(sum(fixed_run))
                    fixed_run = []
                steps.append(x)
        if fixed_run:
            steps.append(sum(fixed_run))

        def prod(b, p, steps=steps):
            for s in steps:
                p = p + s if isinstance(s, int) else s(b, p)
            return p
        return prod
    if tag == "Sum":
        vs = [compile_type(v["algebraic_type"], types, memo) for v in variants(body)]
        if all(isinstance(x, int) for x in vs) and len(set(vs)) <= 1:
            return 1 + (vs[0] if vs else 0)

        def sm(b, p, vs=vs):
            v = vs[b[p]]
            return p + 1 + v if isinstance(v, int) else v(b, p + 1)
        return sm
    raise ValueError(f"unknown type tag {tag}")


def string_t():
    return {"String": []}


# The system tables a running world writes (crates/datastore/src/system_tables.rs).
SYSTEM = {
    3: ("st_sequence", {"Product": {"elements": [{"algebraic_type": t} for t in
                                                 [{"U32": []}, string_t(), {"U32": []}, {"U16": []}] + [{"I128": []}] * 5]}}),
    7: ("st_client", {"Product": {"elements": [{"algebraic_type": {"U256": []}}, {"algebraic_type": {"U128": []}}]}}),
    11: ("st_connection_credentials", {"Product": {"elements": [{"algebraic_type": {"U128": []}}, {"algebraic_type": string_t()}]}}),
    15: ("st_view_sub", {"Product": {"elements": [{"algebraic_type": t} for t in
                                                 [{"U32": []}, {"U64": []}, {"U256": []}, {"U64": []}, {"Bool": []}, {"I64": []}]]}}),
    16: ("st_view_arg", {"Product": {"elements": [{"algebraic_type": {"U64": []}}, {"algebraic_type": {"Array": {"U8": []}}}]}}),
}


def load_schema(path):
    """Table id -> (name, sizer) from clog_watch.py's schema file."""
    s = json.load(open(path))
    desc = s["describe"]
    if "sections" in desc:  # RawModuleDefV10 (2.14.1's `describe --json`)
        sec = {k: v for x in desc["sections"] for k, v in x.items()}
        types, tables = sec["Typespace"]["types"], sec["Tables"]
    else:  # V9
        types, tables = desc["typespace"]["types"], desc["tables"]
    by_name = {}
    for t in tables:
        name = t.get("source_name") or t.get("name")
        by_name[name] = t["product_type_ref"]
    memo = {}
    out = {}
    for row in s["st_table"]:
        tid, name = int(row["table_id"]), row["table_name"]
        if name in by_name:
            out[tid] = (name, compile_type({"Ref": by_name[name]}, types, memo))
    for tid, (name, t) in SYSTEM.items():
        out[tid] = (name, compile_type(t, [], {}))
    return out


# ---- the log ---------------------------------------------------------------------------------------

def varint(b, p):
    r = shift = 0
    while True:
        x = b[p]
        p += 1
        r |= (x & 0x7F) << shift
        if x < 0x80:
            return r, p
        shift += 7


class Undecoded(Exception):
    pass


def records(b, n, schema, acc):
    """Attribute one commit's records (bytes `b`) to `acc`; raises Undecoded on an unknown table."""
    p = 0
    for _ in range(n):
        flags = b[p]
        p += 1
        acc["framing", "flags"] += 1
        if flags & 0x80:
            ln = int.from_bytes(b[p:p + 4], "little")
            name = b[p + 5:p + 5 + b[p + 4]].decode()
            acc["inputs", name] += 4 + ln
            acc["calls", name] += 1
            p += 4 + ln
        if flags & 0x40:
            acc["outputs", "text"] += 1 + b[p]
            p += 1 + b[p]
        if flags & 0x20:
            for side in ("ins", "del"):
                q = p
                nops, p = varint(b, p)
                acc["framing", "op counts"] += p - q
                for _ in range(nops):
                    tid = int.from_bytes(b[p:p + 4], "little")
                    q = p
                    m, p = varint(b, p + 4)
                    if tid not in schema:
                        raise Undecoded(tid)
                    name, f = schema[tid]
                    start = q
                    if isinstance(f, int):
                        p += f * m
                    else:
                        for _ in range(m):
                            p = f(b, p)
                    acc[side, name] += p - start
                    acc[side + " rows", name] += m
            q = p
            nt, p = varint(b, p)
            p += 4 * nt
            acc["framing", "truncates"] += p - q
    if p != len(b):
        raise Undecoded(f"record length {p} != {len(b)}")


def segment_stream(container, replica, name):
    path = f"{CLOG.format(replica)}/{name}"
    head = subprocess.run(["docker", "exec", container, "head", "-c", "4", path], capture_output=True).stdout
    cmd = ["docker", "exec", container, "cat", path]
    cat = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=1 << 20)
    if head == ZSTD_MAGIC:
        z = subprocess.Popen(["zstd", "-dc", "-q"], stdin=cat.stdout, stdout=subprocess.PIPE, bufsize=1 << 20)
        cat.stdout.close()
        return z, head == ZSTD_MAGIC, [cat, z]
    return cat, False, [cat]


def read_exact(f, n):
    out = f.read(n)
    while len(out) < n:
        more = f.read(n - len(out))
        if not more:
            break
        out += more
    return out


def read_segment(container, replica, name, schema, acc, per_seg, base=0, rng=None):
    """Read one segment; with `rng` (A, B), count only the commits that start at a cumulative log
    byte (`base` + position in this segment) in [A, B)."""
    proc, compressed, procs = segment_stream(container, replica, name)
    f = proc.stdout
    seg = defaultdict(int)
    hdr = read_exact(f, 10)
    inr = lambda pos: rng is None or rng[0] <= pos < rng[1]
    if inr(base):
        seg["framing", "segment header"] += len(hdr)
    total = len(hdr)
    counted_bytes = len(hdr) if inr(base) else 0
    commits = 0
    first = last = None
    while True:
        h = read_exact(f, 22)
        if len(h) < 22:
            if h:
                seg["framing", "partial tail"] += len(h)
                total += len(h)
            break
        off = int.from_bytes(h[0:8], "little")
        n = int.from_bytes(h[16:18], "little")
        ln = int.from_bytes(h[18:22], "little")
        if n == 0 and ln == 0 and off == 0 and commits:
            # Preallocated zeroes past the durable end.
            seg["framing", "zero tail"] += 22
            total += 22
            rest = f.read()
            seg["framing", "zero tail"] += len(rest)
            total += len(rest)
            break
        pos = base + total
        body = read_exact(f, ln + 4)
        total += 22 + len(body)
        if not inr(pos):
            continue
        counted_bytes += 22 + len(body)
        seg["framing", "commit"] += 26
        if first is None:
            first = off
        last = off + max(n, 1) - 1
        commits += 1
        try:
            local = defaultdict(int)
            records(body[:ln], n, schema, local)
            for k, v in local.items():
                seg[k] += v
        except (Undecoded, IndexError, UnicodeDecodeError) as e:
            seg["undecoded", str(e).split(" ")[0] if not isinstance(e, Undecoded) else f"table {e.args[0]}"] += ln
    for p in procs:
        p.wait()
    for k, v in seg.items():
        acc[k] += v
    per_seg[name] = {"bytes_decompressed": total, "bytes_counted": counted_bytes, "compressed_on_disk": compressed,
                     "commits_counted": commits, "tx_offsets_counted": [first, last]}
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replica", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--container", default="sg-stdb")
    ap.add_argument("--segments", default="all", help="all, last:N, or a comma list of segment start offsets")
    ap.add_argument("--byte-range", help="A,B: count only commits starting at cumulative (decompressed) log bytes in [A, B), as battle_viewers.py --clog's log_bytes record a window")
    ap.add_argument("--out")
    a = ap.parse_args()
    rng = tuple(int(x) for x in a.byte_range.split(",")) if a.byte_range else None
    schema = load_schema(a.schema)
    ls = subprocess.run(["docker", "exec", a.container, "ls", CLOG.format(a.replica)], capture_output=True, text=True, check=True).stdout.split()
    segs = sorted(x for x in ls if x.endswith(".stdb.log"))
    if a.segments.startswith("last:"):
        segs = segs[-int(a.segments[5:]):]
    elif a.segments != "all":
        want = {int(x) for x in a.segments.split(",")}
        segs = [s for s in segs if int(s.split(".")[0]) in want]
    acc = defaultdict(int)
    per_seg = {}
    total = 0
    for s in segs:
        total += read_segment(a.container, a.replica, s, schema, acc, per_seg, total, rng)
        print(f"{s}: {per_seg[s]}", file=sys.stderr)
    counted = sum(v for (k, _), v in acc.items() if k not in ("calls", "ins rows", "del rows"))
    by_table = defaultdict(lambda: {"ins": 0, "del": 0, "ins_rows": 0, "del_rows": 0})
    other = {}
    for (k, name), v in acc.items():
        if k in ("ins", "del"):
            by_table[name][k] += v
        elif k in ("ins rows", "del rows"):
            by_table[name][k.replace(" ", "_")] += v
        else:
            other[f"{k}: {name}"] = v
    tables = sorted(({"table": t, "bytes": d["ins"] + d["del"], **d} for t, d in by_table.items()), key=lambda r: -r["bytes"])
    in_range = sum(v["bytes_counted"] for v in per_seg.values())
    res = {"replica": a.replica, "byte_range": rng, "segments": per_seg, "bytes_decompressed": total, "bytes_in_range": in_range, "bytes_counted": counted,
           "tables": tables, "other": dict(sorted(other.items(), key=lambda kv: -kv[1]))}
    print(f"total {total:,} bytes decompressed, in range {in_range:,}, attributed {counted:,}")
    total = in_range or 1
    for r in tables[:30]:
        print(f"  {r['table']:32s} {r['bytes']:>14,} B {100 * r['bytes'] / total:5.1f}%  rows ins {r['ins_rows']:>11,} del {r['del_rows']:>11,}")
    for k, v in list(res["other"].items())[:15]:
        print(f"  {k:32s} {v:>14,}   {100 * v / total:5.1f}%" if not k.startswith("calls") else f"  {k:32s} {v:>14,} calls")
    if a.out:
        open(a.out, "w").write(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
