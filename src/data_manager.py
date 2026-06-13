"""
data_manager.py — 狀態層 (State layer)

唯一負責狀態落盤的模組：flags / pool / history CSV / metrics。

原則：
  • 純 IO，無業務邏輯（業務邏輯與 IO 分離）。
  • 所有 JSON 寫入採 atomic write (temp + os.replace)，
    確保 flags.json 永不半寫毀損 —— 這是整個 idempotent 推播機制的地基。
  • 讀取毀損檔案時，安全降級回 default（Fail-safe：寧可不準，也不能掛掉）。
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime
from typing import Any

import obs
from constants import (
    FLAGS_FILE,
    HISTORY_CSV,
    KEY_STATE_FILE,
    METRICS_FILE,
    POOL_FILE,
    PREDICTIONS_FILE,
    TW_TZ,
    VERIFIED_HISTORY_CSV,
)


# ── 低階 atomic IO ───────────────────────────────────
def _atomic_write(path: str, text: str) -> None:
    """寫入暫存檔後 os.replace，POSIX 上為原子操作，避免半寫毀損。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        obs.error("state.read_failed", path=path, err=str(exc))
        return default


def _write_json(path: str, data: Any) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def _now() -> str:
    return datetime.now(TW_TZ).isoformat(timespec="seconds")


# ── flags.json — idempotency ─────────────────────────
def load_flags() -> dict[str, dict]:
    return _read_json(FLAGS_FILE, {})


def save_flags(flags: dict[str, dict]) -> None:
    _write_json(FLAGS_FILE, flags)


def is_pushed(game_id: str, stage: str) -> bool:
    """查詢某場某階段是否已推播。stage: 'pre' | 'post'。"""
    flags = load_flags()
    return bool(flags.get(game_id, {}).get(stage, False))


def mark_pushed(game_id: str, stage: str) -> None:
    """送出即落盤：標記某場某階段已推播 (idempotent)。"""
    flags = load_flags()
    rec = flags.setdefault(game_id, {})
    rec[stage] = True
    rec["updated_at"] = _now()
    save_flags(flags)
    obs.info("state.mark_pushed", game_id=game_id, stage=stage)


# ── weekly_games.json — Rolling Pool ─────────────────
def load_pool() -> dict[str, Any]:
    return _read_json(POOL_FILE, {"games": [], "updated_at": ""})


def save_pool(games: list[dict], updated_at: str | None = None) -> None:
    # updated_at 預設為現在；排程引擎會傳入「邏輯 tick 時間」以利 slot guard 判定。
    payload = {"games": games, "updated_at": updated_at or _now()}
    _write_json(POOL_FILE, payload)
    obs.info("state.pool_saved", count=len(games))


# ── history.csv — 賽前特徵 + 賽後結果 ────────────────
# 註：採行級 append。呼叫端須保證同一檔案的欄位 schema 一致；
#     變更 schema 由 data 層在建置 Fetch/Processing 時統一定義。
def append_history(row: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(HISTORY_CSV)), exist_ok=True)
    file_exists = os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def read_history() -> list[dict[str, str]]:
    if not os.path.exists(HISTORY_CSV):
        return []
    with open(HISTORY_CSV, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── metrics.json — 自學指標 ──────────────────────────
def load_metrics() -> dict[str, Any]:
    return _read_json(METRICS_FILE, {})


def save_metrics(metrics: dict[str, Any]) -> None:
    _write_json(METRICS_FILE, metrics)


# ── key_state.json — API Key cooldown ────────────────
# 只存「哪個 key slot 在冷卻」（env 名 + cooldown_until），不存金鑰本體。
# 毀損 / 不存在 → 降級為空 dict（視同全部可用）。
def load_key_state() -> dict[str, Any]:
    return _read_json(KEY_STATE_FILE, {})


def save_key_state(state: dict[str, Any]) -> None:
    _write_json(KEY_STATE_FILE, state)


# ── predictions.json — pending prediction snapshot ───
# C-1 truth loop 地基：pre-push 成功時落盤 prediction，賽後 C-4 取回比對。
# 結構：{ game_id: {"prediction": <prediction dict>, "pre_pushed_at": iso} }。
# 毀損 / 不存在 → 降級為空 dict（Fail-safe：寧可缺對照，也不能掛掉）。
def load_predictions() -> dict[str, dict]:
    data = _read_json(PREDICTIONS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_prediction(game_id: str, prediction: dict) -> None:
    """pre-push 成功後落盤該場 snapshot（pending 驗證）。"""
    preds = load_predictions()
    preds[str(game_id)] = {"prediction": prediction, "pre_pushed_at": _now()}
    _write_json(PREDICTIONS_FILE, preds)
    obs.info("state.snapshot_saved", game_id=game_id)


def remove_prediction(game_id: str) -> None:
    """賽後驗證完成後移出 pending（停止再抓 scores）。不存在則無動作。"""
    preds = load_predictions()
    if str(game_id) in preds:
        del preds[str(game_id)]
        _write_json(PREDICTIONS_FILE, preds)
        obs.info("state.snapshot_removed", game_id=game_id)


# ── verified_history.csv — 已驗證賽果（git tracked）──
# C-4 學習資料：固定 schema，append-only。Tournament Engine 未來以此為唯一資料源。
VERIFIED_FIELDS = [
    "verified_at", "game_id", "sport", "winner", "pick_outcome",
    "pick_hit", "moneyline_hit", "realized_return", "fair_prob_winner", "model",
]


def append_verified(record: dict[str, Any]) -> None:
    """append 一筆 verification record（補 verified_at；固定欄位順序，缺值留空）。"""
    row = {k: record.get(k, "") for k in VERIFIED_FIELDS}
    if not row["verified_at"]:
        row["verified_at"] = _now()
    path = VERIFIED_HISTORY_CSV
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VERIFIED_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    obs.info("state.verified_appended", game_id=record.get("game_id"))


def read_verified() -> list[dict[str, str]]:
    if not os.path.exists(VERIFIED_HISTORY_CSV):
        return []
    with open(VERIFIED_HISTORY_CSV, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def verified_count() -> int:
    """已驗證賽事筆數（未來 Tournament Engine 的 verified_count % 4 觸發用）。"""
    return len(read_verified())
