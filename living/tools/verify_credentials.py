"""Credential handling shared by the verification and performance harnesses."""
import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

REDACTED = "<redacted>"
CREDENTIAL_TEXT = re.compile(
    r'(?P<prefix>\bBearer[ \t]+|\bauth token is[ \t]+|[#?&]token=)'
    r'[^\s"\\\x27,;&]+|\beyJ[\w-]+\.[\w-]+\.[\w-]+',
    re.IGNORECASE | re.ASCII,
)
CREDENTIAL_FIELD = re.compile(
    r'("(?:token\d*|access_token|refresh_token|authorization|password|api_key)"\s*:\s*)'
    r'"(?:[^"\\]|\\.)*"',
    re.IGNORECASE,
)


def redact(text, secrets=()):
    for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = CREDENTIAL_FIELD.sub(r'\1"<redacted>"', text)
    return CREDENTIAL_TEXT.sub(lambda match: (match["prefix"] or "") + REDACTED, text)


def private_dir(root):
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    checkout = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    directory = state / "slop-art-online" / "verify" / checkout
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def write_private(path, text):
    """Atomically replace private state with a file created at mode 0600."""
    stream = NamedTemporaryFile(mode="w", dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
