#!/usr/bin/env python3
"""pictures.py's bundle test (docs/CHARACTERS.md, "Pictures as KTX2"):

    python3 living/tools/characters/pictures_selftest.py IN.tar.gz OUT_DIR

From one char-4 bundle, in one run: a KTX2 bundle twice and a `--pictures png` bundle.

- the PNG bundle's files are the input's, byte for byte, apart from MANIFEST.txt, whose only
  change is the `pictures: png` line;
- the two KTX2 bundles' files are the same (sha256 of every file, every `.ktx2` named);
- both pass `pictures.py check`; the KTX2 bundle's GLBs embed no picture;
- the check fails the KTX2 bundle broken each way it must catch (a thumb missing, an image URI
  that does not resolve, a shadow map in sRGB, a KTX2 a level short, a GLB still embedding its
  picture), with MANIFEST.txt rewritten each time so only the fault is left;
- the sizes: each bundle, and GPU memory per class (KTX2 against RGBA8 without mips).

Writes OUT_DIR/{ktx2-a,ktx2-b,png}.tar.gz and OUT_DIR/selftest.json; exit 1 on any failure.
"""

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pictures  # noqa: E402


def files_of(tgz):
    out = {}
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if m.isfile():
                out[m.name.removeprefix("./")] = t.extractfile(m).read()
    return out


def broken_bundles(tgz, src):
    """The check against a KTX2 bundle broken each way it must catch: {case: caught}."""
    import shutil
    import tempfile
    lk = pictures.ASSETS
    cases = {}

    def thumb_missing(r):
        (r / lk / "pages/types-far.thumb.png").unlink()

    def uri_dangling(r):
        g = r / lk / "styles/overlay/adult-m-a/freckles.glb"
        j, b = pictures.read_glb(g)
        j["images"][0]["uri"] = "nowhere.ktx2"
        pictures.write_glb(g, j, b)

    def wrong_class(r):  # an sRGB picture where the linear shadow map belongs
        shutil.copy(r / lk / "types/adult-f-a.atlas.ktx2", r / lk / "types/adult-f-a.face.ktx2")

    def short_chain(r):  # one level fewer in the header
        f = r / lk / "strands.ktx2"
        b = bytearray(f.read_bytes())
        n = int.from_bytes(b[40:44], "little")
        b[40:44] = (n - 1).to_bytes(4, "little")
        f.write_bytes(bytes(b))

    def still_embedded(r):  # the generator's own GLB back in the bundle
        with tarfile.open(src) as t:
            m = t.getmember(str(lk / "types/adult-f-a.glb"))
            (r / lk / "types/adult-f-a.glb").write_bytes(t.extractfile(m).read())

    for case in [thumb_missing, uri_dangling, wrong_class, short_chain, still_embedded]:
        with tempfile.TemporaryDirectory(dir=str(Path(tgz).parent)) as tmp:
            r = Path(tmp)
            pictures.unpack(tgz, r)
            case(r)
            pictures.write_manifest(r, [h for h in pictures.manifest_parts(r)[0] if h.startswith("pictures:")][0])
            _, _, f = pictures.check(r)
            cases[case.__name__] = bool(f)
    return cases


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    fails = []
    for name, mode in [("ktx2-a", "ktx2"), ("ktx2-b", "ktx2"), ("png", "png")]:
        subprocess.run([sys.executable, str(HERE / "pictures.py"), "bundle", str(src), str(out / f"{name}.tar.gz"), "--pictures", mode], check=True)
    orig, a, b, png = (files_of(p) for p in [src, out / "ktx2-a.tar.gz", out / "ktx2-b.tar.gz", out / "png.tar.gz"])

    # The PNG bundle is the input.
    for n in sorted(set(orig) | set(png)):
        if n == pictures.MANIFEST:
            continue
        if orig.get(n) != png.get(n):
            fails.append(f"png bundle: {n} differs from the input")
    om, pm = orig[pictures.MANIFEST].decode().splitlines(), png[pictures.MANIFEST].decode().splitlines()
    extra = [ln for ln in pm if ln not in om]
    if extra != ["pictures: png"] or [ln for ln in pm if ln != "pictures: png"] != om:
        fails.append(f"png bundle: MANIFEST.txt changed beyond the pictures line: {extra}")

    # The KTX2 bundle twice.
    sha = lambda d: {n: hashlib.sha256(v).hexdigest() for n, v in d.items()}
    sa, sb = sha(a), sha(b)
    if sa != sb:
        fails += [f"ktx2 bundles differ: {n}" for n in sorted(set(sa) | set(sb)) if sa.get(n) != sb.get(n)]
    ktx2 = sorted(n for n in sa if n.endswith(".ktx2"))
    for n, v in a.items():
        if n.endswith(".glb"):
            j = json.loads(v[20:20 + int.from_bytes(v[12:16], "little")])
            if any("bufferView" in im or "mimeType" in im for im in j.get("images", [])):
                fails.append(f"ktx2 bundle: {n} still embeds a picture")
    if "pictures: ktx2-bc7" not in a[pictures.MANIFEST].decode().splitlines():
        fails.append("ktx2 bundle: no 'pictures: ktx2-bc7' line")

    checks = {}
    for name in ["ktx2-a", "png"]:
        r = subprocess.run([sys.executable, str(HERE / "pictures.py"), "check", str(out / f"{name}.tar.gz")], capture_output=True, text=True)
        checks[name] = r.stdout.strip().splitlines()[-1]
        if r.returncode:
            fails.append(f"check {name}: {r.stdout}")
    broken = broken_bundles(out / "ktx2-a.tar.gz", src)
    for name, ok in broken.items():
        if not ok:
            fails.append(f"check passed a bundle with {name}")
    mem = subprocess.run([sys.executable, str(HERE / "pictures.py"), "memory", str(out / "ktx2-a.tar.gz")], check=True, capture_output=True, text=True).stdout
    report = {
        "input": str(src),
        "sizes": {p.name: p.stat().st_size for p in [src, out / "ktx2-a.tar.gz", out / "ktx2-b.tar.gz", out / "png.tar.gz"]},
        "unpacked": {"input": sum(map(len, orig.values())), "ktx2": sum(map(len, a.values())), "png": sum(map(len, png.values()))},
        "ktx2_files": len(ktx2),
        "ktx2_sha256": {n: sa[n] for n in ktx2},
        "ktx2_same_twice": sa == sb,
        "checks": checks,
        "check_catches": broken,
        "memory": json.loads(mem.strip().splitlines()[-1]),
        "fails": fails,
    }
    (out / "selftest.json").write_text(json.dumps(report, indent=1) + "\n")
    print("\n".join(mem.strip().splitlines()[:-1]))
    for k, v in report["sizes"].items():
        print(f"{k:40} {v:>10} bytes")
    print(f"{len(ktx2)} KTX2, the same twice: {sa == sb}; checks: {checks}")
    print(f"check catches: {broken}")
    for f in fails:
        print(f"FAIL {f}")
    print("selftest:", "FAIL" if fails else "ok")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
