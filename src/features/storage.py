"""storage.py — append-only feature CSV 儲存（含去重 + 安全寫入）。

原則：
- append-only：同一 (game_pk, team) 已存在則不重複寫（冪等）。
- 零 production import。
"""

from __future__ import annotations

import csv
import os
from . import schema

DEFAULT_PATH = "data/features/mlb_features.csv"


def _existing_keys(path: str) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not os.path.exists(path):
        return keys
    try:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("game_pk", ""), r.get("team", "")))
    except Exception:
        pass
    return keys


def append_rows(rows: list[dict], path: str = DEFAULT_PATH) -> int:
    """append 新列（去重）。回傳實際寫入筆數。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    existing = _existing_keys(path)
    new = [r for r in rows if (r.get("game_pk", ""), r.get("team", "")) not in existing]
    if not new:
        return 0
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in new:
            full = schema.empty_row()
            full.update({k: schema.coerce(v) for k, v in r.items() if k in schema.COLUMNS})
            w.writerow(full)
    return len(new)


def row_count(path: str = DEFAULT_PATH) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, newline="") as f:
        return max(0, sum(1 for _ in f) - 1)
