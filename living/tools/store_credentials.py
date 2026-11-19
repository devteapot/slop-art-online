"""Find credential values in packed store payloads without returning the values."""
import bz2
import gzip
import io
import lzma
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


FIELD = rb'(?:["\x27]|\\["\x27])?\s*[:=]\s*'
VALUE = rb'''(?:"(?P<quoted>(?:[^"\\\r\n]|\\.)*)"|'(?P<single>[^'\r\n]*)'|(?:\\")?(?P<value>[^\s"'\\,;}\]<>]+|<redacted>))'''
RULES = (
    ("JWT", re.compile(rb'\b(?P<value>eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)')),
    ("authorization", re.compile(rb'(?i)\bauthorization' + FIELD +
                                 rb'(?:\\?["\x27])?(?:basic|bearer|digest|token)[ \t]+' + VALUE)),
    ("authorization", re.compile(rb'(?i)\bauthorization' + FIELD + VALUE)),
    ("bearer", re.compile(rb'''(?i)\bbearer[ \t]+(?P<value>[A-Za-z0-9._~+/=-]+)''')),
    ("Neo4j URI credential", re.compile(
        rb'''(?i)\b(?:neo4j|bolt)(?:\+s(?:sc)?)?://(?P<value>[^/\s@"'<>]+)@''')),
    ("Neo4j credential field", re.compile(rb'(?i)\b(?:NEO4J_PASSWORD|NEO4J_AUTH)' + FIELD + VALUE)),
    ("project API key", re.compile(
        rb'(?i)\b(?:MISTRAL|CARGO_NPC|TYPESAFE)_API_KEY' + FIELD + VALUE)),
    ("SpacetimeDB CLI token", re.compile(rb'(?i)\bauth token is[ \t]+' + VALUE)),
    ("token argument", re.compile(rb'(?i)(?:[?#&]token=|--(?:auth-)?token[= \t]+)' + VALUE)),
    ("player or bystander token field", re.compile(
        rb'(?i)(?<![\w-])(?:token2|(?:player|bystander)[_-]?(?:auth[_-]?)?token)' + FIELD + VALUE)),
    ("credential field", re.compile(
        rb'(?i)(?<![\w-])(?:token(?!2)|auth[_-]?token|identity[_-]?token|access[_-]?token|'
        rb'refresh[_-]?token|password|passwd|(?:x-)?api[_-]?key)' + FIELD + VALUE)),
    ("provider token", re.compile(
        rb'\b(?P<value>hf_[A-Za-z0-9]{30,}|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}|'
        rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')),
)
PLACEHOLDERS = {b'<redacted>', b'[redacted]', b'redacted', b'null', b'none', b'true', b'false', b'example', b'""', b"''"}

# Fast literal checks avoid running every regular expression over large binary assets.
TRIGGERS = (
    (b"eyj",), (b"authorization",), (b"authorization",), (b"bearer",),
    (b"neo4j", b"bolt"), (b"neo4j_",), (b"_api_key",), (b"auth token is",),
    (b"token",), (b"token",), (b"token", b"password", b"passwd", b"api"),
    (b"hf_", b"sk-", b"gh", b"github_pat_"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    offset: int
    kind: str
    role: str

    def __str__(self):
        return f"{self.path} @ byte {self.offset}: {self.kind} ({self.role})"


def _matches(data):
    matches = {}
    lower = data.lower()
    for (kind, pattern), triggers in zip(RULES, TRIGGERS):
        if not any(trigger in lower for trigger in triggers):
            continue
        for match in pattern.finditer(data):
            group = next(key for key, value in match.groupdict().items() if value is not None)
            value = match[group].strip()
            if (not value or value.lower() in PLACEHOLDERS or value.startswith((b'$', b'[redacted:', b'<redacted:'))
                    or value.strip(b'*') == b''):
                continue
            if kind == "bearer" and len(value) < 8 and value.isalpha() and not match[0].startswith(b"Bearer"):
                continue  # prose such as "bearer of" and placeholders in headers
            if group == "value" and (value.lower() in (b'bearer', b'basic', b'digest', b'token')
                                     or value.startswith((b'{', b'['))):
                continue
            start, end = match.span(group)
            matches.setdefault((start, end), []).append(kind)
    return matches


def safe_label(label):
    data = label.encode("utf-8", errors="surrogateescape")
    intervals = []
    for start, end in sorted(_matches(data)):
        if intervals and start < intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else:
            intervals.append((start, end))
    for start, end in reversed(intervals):
        data = data[:start] + b"<redacted>" + data[end:]
    return data.decode("utf-8", errors="backslashreplace").replace("\n", "\\n").replace("\r", "\\r")


class Scanner:
    def __init__(self, extract_to=None):
        self.extract_to = extract_to
        self.findings = []
        self.files = 0
        self.bytes = 0

    def scan(self, path, label):
        path = Path(path)
        label = self._name(label)
        if path.is_symlink() or not path.is_file():
            raise ValueError("expected a regular file")
        with path.open("rb") as source:
            self._scan(source, label, 0)

    def _name(self, label):
        safe = safe_label(label)
        if safe != label and _matches(label.encode("utf-8", errors="surrogateescape")):
            self.findings.append(Finding(safe, 0, "credential in path", "other"))
        return safe

    def _scan(self, source, label, depth):
        if depth > 20:
            raise ValueError("archive nesting exceeds 20 levels")
        with io.BufferedReader(source) as stream:
            self._scan_stream(stream, label, depth)

    def _scan_stream(self, stream, label, depth):
        head = stream.peek(512)[:512]
        name = label.lower()
        if head.startswith(b'\x28\xb5\x2f\xfd') or name.endswith((".zst", ".zstd", ".tzst")):
            with tempfile.TemporaryFile(dir=self.extract_to) as compressed:
                shutil.copyfileobj(stream, compressed)
                compressed.seek(0)
                with subprocess.Popen(["zstd", "-dc"], stdin=compressed, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL) as process:
                    try:
                        self._scan(process.stdout, label + "!decoded", depth + 1)
                    finally:
                        process.stdout.close()
                    if process.wait():
                        raise ValueError("invalid zstd stream")
        elif head.startswith(b'\x1f\x8b') or name.endswith((".gz", ".tgz")):
            with gzip.GzipFile(fileobj=stream) as decoded:
                self._scan(decoded, label + "!decoded", depth + 1)
        elif head.startswith(b'BZh') or name.endswith((".bz2", ".tbz2")):
            with bz2.BZ2File(stream) as decoded:
                self._scan(decoded, label + "!decoded", depth + 1)
        elif head.startswith(b'\xfd7zXZ\x00') or name.endswith((".xz", ".txz")):
            with lzma.LZMAFile(stream) as decoded:
                self._scan(decoded, label + "!decoded", depth + 1)
        elif (head[257:262] == b'ustar' or name.endswith(".tar")
              or name.endswith((".tar.gz!decoded", ".tgz!decoded", ".tar.zst!decoded", ".tzst!decoded",
                                ".tar.xz!decoded", ".txz!decoded", ".tar.bz2!decoded", ".tbz2!decoded"))):
            with tarfile.open(fileobj=stream, mode="r|") as archive:
                self._members(self._tar_members(archive, label.removesuffix("!decoded")),
                              label.removesuffix("!decoded"), depth)
            # Read through the compression footer even when tar reaches its end marker first.
            while stream.read(65536):
                pass
        elif head.startswith((b'PK\x03\x04', b'PK\x05\x06')) or name.endswith(".zip"):
            with tempfile.TemporaryFile(dir=self.extract_to) as seekable:
                shutil.copyfileobj(stream, seekable)
                with zipfile.ZipFile(seekable) as archive:
                    self._members(((m.filename, archive.open(m)) for m in archive.infolist()
                                   if not m.is_dir() and not stat.S_ISLNK(m.external_attr >> 16)), label, depth)
        else:
            self._content(stream.read(), label)

    def _tar_members(self, archive, label):
        for member in archive:
            if member.isfile():
                yield member.name, archive.extractfile(member)
            else:
                self._name(f"{label}!{member.name}")
                if member.linkname:
                    self._name(f"{label}!{member.name}!link={member.linkname}")

    def _members(self, members, label, depth):
        directory = Path(tempfile.mkdtemp(dir=self.extract_to)) if self.extract_to is not None else None
        for index, (name, member) in enumerate(members):
            inner = self._name(f"{label}!{name}")
            with member:
                if directory is None:
                    self._scan(member, inner, depth + 1)
                else:
                    # Archive names never become extraction paths.
                    path = directory / str(index)
                    with path.open("xb") as dest:
                        shutil.copyfileobj(member, dest)
                    with path.open("rb") as source:
                        self._scan(source, inner, depth + 1)

    def _content(self, data, label):
        self.files += 1
        self.bytes += len(data)
        matches = _matches(data)
        if not matches and data.strip() and label.lower().endswith((".token", "/hf_token", "/bystander_token",
                                                                    "/player_token", "/auth_token")):
            matches[(0, len(data))] = ["credential file"]
        for (start, end), kinds in sorted(matches.items()):
            left = data.rfind(b"\n", 0, start) + 1
            right = data.find(b"\n", end)
            context = data[left:right if right != -1 else len(data)].lower()
            if "SpacetimeDB CLI token" in kinds or (b"login" in context and b"--token" in context):
                role = "scratch-server token" if "actions.jsonl" in label or "verify-" in label else "SpacetimeDB CLI token"
            elif ("player or bystander token field" in kinds or
                  (("credential field" in kinds or "JWT" in kinds)
                   and ((b'"identity"' in context or rb'\"identity\"' in context) or label.endswith(("state.json", "-players.json"))))):
                role = "player or bystander credential"
            else:
                role = "other or unknown"
            self.findings.append(Finding(label, start, " / ".join(kinds), role))
