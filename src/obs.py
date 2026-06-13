"""
obs.py — 結構化 Log (Support layer)

純觀測層：只負責輸出結構化 log，不含業務邏輯、不做任何狀態落盤。
其他層透過 info/warn/error/alert/schema_dump 輸出單行 JSON，
方便在 GitHub Actions log 中以欄位追蹤。

註：alert() 只負責「標記」需要外部告警的事件；
    實際送 Telegram Alert 由 notifier 層處理（業務邏輯與 IO 分離）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from constants import TW_TZ, debug_schema_enabled


def _now_iso() -> str:
    return datetime.now(TW_TZ).isoformat(timespec="seconds")


def event(level: str, msg: str, **fields: Any) -> None:
    """輸出單行結構化 log。ERROR / ALERT 走 stderr，其餘走 stdout。"""
    record: dict[str, Any] = {"ts": _now_iso(), "level": level.upper(), "msg": msg}
    if fields:
        record.update(fields)
    line = json.dumps(record, ensure_ascii=False, default=str)
    stream = sys.stderr if level.upper() in ("ERROR", "ALERT") else sys.stdout
    print(line, file=stream, flush=True)


def info(msg: str, **fields: Any) -> None:
    event("INFO", msg, **fields)


def warn(msg: str, **fields: Any) -> None:
    event("WARN", msg, **fields)


def error(msg: str, **fields: Any) -> None:
    event("ERROR", msg, **fields)


def alert(msg: str, **fields: Any) -> None:
    """需要外部告警的事件（實際送 Telegram Alert 由 notifier 處理）。"""
    event("ALERT", msg, **fields)


# 每類 schema 僅輸出一次，避免洗版 (見 README DEBUG_API_SCHEMA)
_schema_seen: set[str] = set()


def schema_dump(tag: str, sample: Any) -> None:
    """
    DEBUG_API_SCHEMA=true 時，每個 tag 僅輸出一筆樣本。

    範例：
        obs.schema_dump("nba raw[0]", raw_payload[0])
        obs.schema_dump("nba parsed[0]", parsed[0])
    輸出：[schema] nba raw[0] {...}
    不影響 production（旗標關閉時為 no-op）。
    """
    if not debug_schema_enabled():
        return
    if tag in _schema_seen:
        return
    _schema_seen.add(tag)
    try:
        body = json.dumps(sample, ensure_ascii=False, default=str)[:2000]
    except (TypeError, ValueError):
        body = repr(sample)[:2000]
    print(f"[schema] {tag} {body}", file=sys.stdout, flush=True)


def reset_schema_cache() -> None:
    """測試用：清空 schema 去重快取。"""
    _schema_seen.clear()
