"""Resolve the active model config like living-mind, without evaluating shell code."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def models_path(explicit=None):
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    selected = Path(explicit or os.environ.get('LIVING_MODELS', 'living/configs/models.json'))
    return selected if selected.is_absolute() else ROOT / selected
