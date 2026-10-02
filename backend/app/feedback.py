"""Feedback captured from testers during a UAT round.

Deliberately NOT per-session. Tester state is isolated so two people do not disturb
each other's work; feedback is the opposite — it is the output of the round and the
whole team must see it. It is keyed by who said it, not hidden from them.

Durability is the weak point and is stated rather than papered over: entries live in
memory and are appended to a JSONL file. On Cloud Run that file lives on an instance
whose disk does not survive a new revision, so the round must export before
redeploying. Somewhere durable — GCS, Firestore or straight into ClickUp — is the
next step and the seam for it is `sink()` below.
"""
import json
import os
import uuid
from pathlib import Path

# Free text with a hard ceiling. A tester pasting a whole screen of logs is useful;
# an unbounded field is a denial-of-service and a storage problem.
MAX_COMMENT = 4000

RATINGS = ("blocked", "confusing", "works", "idea")

_entries = []
_path = Path(os.environ.get("FEEDBACK_PATH", "/tmp/volt-uat-feedback.jsonl"))


def reset():
    """Test seam."""
    _entries.clear()


def sink(entry):
    """Append to the JSONL file. A failure here must never lose the entry from
    memory or fail the request — a tester who typed a paragraph should not be told
    to type it again because a disk was read-only."""
    try:
        with _path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def add(payload, tester, at):
    """Returns (entry, error_code)."""
    payload = payload or {}
    comment = str(payload.get("comment") or "").strip()
    rating = payload.get("rating") or None
    screen = str(payload.get("screen") or "").strip() or None

    # A rating alone says something ("this task is blocked"); a comment alone says
    # more. One of the two must be present, or the entry carries no information.
    if not comment and not rating:
        return None, "empty"
    if rating is not None and rating not in RATINGS:
        return None, "rating_unknown"
    if len(comment) > MAX_COMMENT:
        return None, "comment_too_long"

    entry = {
        "id": "fb-" + uuid.uuid4().hex[:12],
        "at": at,
        "tester": tester,
        "screen": screen,
        "task_id": payload.get("task_id") or None,
        "rating": rating,
        "comment": comment or None,
        # Context the tester should not have to describe. Which language and theme
        # they were in matters: "the number is cut off" is a different bug in Thai.
        "lang": payload.get("lang") or None,
        "theme": payload.get("theme") or None,
        "path": payload.get("path") or None,
        "durable": False,
    }
    entry["durable"] = sink(entry)
    _entries.append(entry)
    return entry, None


def entries():
    return list(_entries)


def summary():
    by_rating = {}
    by_screen = {}
    for entry in _entries:
        if entry["rating"]:
            by_rating[entry["rating"]] = by_rating.get(entry["rating"], 0) + 1
        if entry["screen"]:
            by_screen[entry["screen"]] = by_screen.get(entry["screen"], 0) + 1
    return {
        "total": len(_entries),
        "by_rating": by_rating,
        "by_screen": by_screen,
        "testers": sorted({e["tester"] for e in _entries if e["tester"]}),
        "file": str(_path),
        # If this is ever false, a redeploy loses everything not yet exported.
        "all_written_to_disk": all(e["durable"] for e in _entries) if _entries else True,
    }
