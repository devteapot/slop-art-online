"""Read mind journals with their system prompts in place.

Since 2026-11-10 the mind service stores each distinct system prompt once, beside the journal
files (`<journal>/system/<hash>.txt`), and an entry's system message names that file:
`{"role": "system", "content_ref": "system/<hash>.txt"}` (llm.rs `system_by_ref`). Older
entries carry the prompt inline. `restore` puts the text back as `content`, so readers see
the exact messages that were sent either way.
"""
import os

_texts = {}


def restore(entry, journal_dir):
    """Fill in each referenced system prompt of a journal entry (in place; returns it).
    `journal_dir` is the directory holding the entry's `.jsonl` file."""
    request = entry.get("request") if isinstance(entry, dict) else None
    messages = request.get("messages") if isinstance(request, dict) else None
    for m in messages or []:
        ref = m.get("content_ref") if isinstance(m, dict) else None
        if not ref or "content" in m:
            continue
        path = os.path.join(str(journal_dir), ref)
        if path not in _texts:
            try:
                with open(path, encoding="utf-8") as f:
                    _texts[path] = f.read()
            except OSError:
                _texts[path] = None
        if _texts[path] is not None:
            m["content"] = _texts[path]
    return entry
