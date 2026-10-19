"""Seen tracking by "newest listing" watermark, stored in data/seen.json as {"wttj": ts, "wn": ts}.

Each search records the publish time of the newest job it returned. A listing counts as seen when it was
published at or before the newest one you'd received by the start of your current visit, so jobs stay
"New" for the whole visit in which they first show up.
"""
import json
import os
import threading

PATH = os.environ.get("SEEN_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seen.json")

_lock = threading.Lock()
_newest = None    # newest publish timestamp received per source, updated by every search
_baseline = {}    # snapshot of _newest taken when the page was opened; used for marking


def _load():
    global _newest
    if _newest is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                data = json.load(f)
            _newest = {k: v for k, v in data.items() if isinstance(v, (int, float))}
        except (FileNotFoundError, ValueError, AttributeError):
            _newest = {}
    return _newest


def _save():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_newest, f)
    os.replace(tmp, PATH)


def start_visit():
    """Freeze the current watermarks for marking until the page is opened again."""
    global _baseline
    with _lock:
        _baseline = dict(_load())
        return dict(_baseline)


def baseline(source):
    with _lock:
        return _baseline.get(source)


def record(source, newest_ts):
    """Remember the newest listing a search returned (only ever moves forward)."""
    if not newest_ts:
        return
    with _lock:
        seen = _load()
        if newest_ts > seen.get(source, 0):
            seen[source] = newest_ts
            _save()


def annotate(source, hits):
    """Set seen=True on hits published at or before this visit's watermark."""
    mark = baseline(source)
    for h in hits:
        h["seen"] = bool(mark and h.get("published_ts") and h["published_ts"] <= mark)
    return hits


def clear():
    global _newest, _baseline
    with _lock:
        _newest, _baseline = {}, {}
        _save()
