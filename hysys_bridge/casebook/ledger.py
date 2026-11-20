"""Append-only result ledger (JSON lines): one row per case, package and run, so drift shows when the backend or the packages change."""
from __future__ import annotations
import datetime, json, os, subprocess

DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "ledger.jsonl")


def _commit():
    try: return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, cwd=os.path.dirname(__file__)).stdout.strip() or None
    except Exception: return None


def append(rows: list[dict], path: str | None = None) -> int:
    path = path or DEFAULT
    stamp = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "git": _commit()}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as f:
        for r in rows: f.write(json.dumps({**stamp, **r}, sort_keys=True) + "\n")
    return len(rows)


def read(path: str | None = None) -> list[dict]:
    path = path or DEFAULT
    if not os.path.exists(path): return []
    with open(path) as f: return [json.loads(l) for l in f if l.strip()]
