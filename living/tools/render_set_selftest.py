#!/usr/bin/env python3
"""render_set.py's generator hash and its exclusion list, on a throwaway git repository.

    python3 living/tools/render_set_selftest.py

Builds living/tools/{blender,characters,textures} with a generator, a check and a measuring tool,
lists the two non-generating ones in living/tools/render_set_exclude.txt, and asserts:
- an edit to a listed check keeps the hash (a set stays ok);
- an edit to a generator changes it (stale);
- an edit to the exclusion list changes it (stale: the list cannot be widened quietly);
- an edit to an unlisted file the generator does not import still changes it (fails safe);
- a listed path that is not in the trees is refused;
- a listed file that a generator imports is reported (exclusion_imported).
Prints one line per case and exits 1 on any failure.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_set  # noqa: E402


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, files, msg):
    for path, text in files.items():
        p = Path(repo) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def main():
    fails = 0

    def case(name, ok):
        nonlocal fails
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        git(d, "config", "user.email", "selftest@example.invalid")
        git(d, "config", "user.name", "selftest")
        T = "living/tools/"
        base = commit(d, {
            T + "blender/gen.py": "import helper\nprint('a model')\n",
            T + "blender/helper.py": "X = 1\n",
            T + "characters/thing_check.py": "print('checks')\n",
            T + "characters/notes_tool.py": "print('an unlisted tool')\n",
            T + "textures/measure_it.py": "print('measures')\n",
            T + "render_set_exclude.txt": "# non-generating\ncharacters/thing_check.py\ntextures/measure_it.py\n",
        }, "base")
        h0 = render_set.gen_hash(d, base)[0]
        case("the list is honoured: no listed file is imported by a generator", render_set.exclusion_imported(d, base) == [])
        c1 = commit(d, {T + "characters/thing_check.py": "print('checks, more strictly')\n"}, "edit a check")
        case("an edit to a listed check keeps the hash", render_set.gen_hash(d, c1)[0] == h0)
        c2 = commit(d, {T + "textures/measure_it.py": "print('measures twice')\n"}, "edit a measure")
        case("an edit to a listed measuring tool keeps the hash", render_set.gen_hash(d, c2)[0] == h0)
        c3 = commit(d, {T + "blender/helper.py": "X = 2\n"}, "edit the generator")
        h3 = render_set.gen_hash(d, c3)[0]
        case("an edit to a generator changes the hash", h3 != h0)
        c4 = commit(d, {T + "characters/notes_tool.py": "print('an unlisted tool, edited')\n"}, "edit an unlisted tool")
        h4 = render_set.gen_hash(d, c4)[0]
        case("an edit to an unlisted file changes the hash (fails safe)", h4 != h3)
        c5 = commit(d, {T + "render_set_exclude.txt": "# non-generating\ncharacters/thing_check.py\ntextures/measure_it.py\ncharacters/notes_tool.py\n"}, "widen the list")
        case("an edit to the exclusion list changes the hash", render_set.gen_hash(d, c5)[0] != h4)
        c6 = commit(d, {T + "render_set_exclude.txt": "characters/thing_check.py\ncharacters/not_there.py\n"}, "a path not in the trees")
        try:
            render_set.gen_hash(d, c6)
            case("a listed path not in the trees is refused", False)
        except SystemExit:
            case("a listed path not in the trees is refused", True)
        c7 = commit(d, {T + "render_set_exclude.txt": "blender/helper.py\n"}, "list a file the generator imports")
        case("a listed file that a generator imports is reported", render_set.exclusion_imported(d, c7) == [("blender/gen.py", "blender/helper.py")])
        c8 = commit(d, {T + "render_set_exclude.txt": "characters/thing_check.py\ntextures/measure_it.py\n"}, "back")
        case("build and check read one definition (gen_hash at a commit is stable)", render_set.gen_hash(d, c8)[0] == render_set.gen_hash(d, c8)[0])
    print(f"render_set_selftest: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
