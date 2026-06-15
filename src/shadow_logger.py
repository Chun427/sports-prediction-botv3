"""shadow_logger.py — V3.2 影子評估記錄（analysis-only）。

目的：在不影響推播的前提下，並排記錄每場的
  • v1_direction  ：MC argmax 方向（V1 decision layer 來源）
  • v3_best_pick   ：V3 value-edge 的 best_pick（未動，僅讀取）
  • actual_result  ：賽後真實結果（由 postgame 補寫）
供日後 forward 驗證（V1 vs V3）使用。

設計鐵則：
  • append-only CSV；所有寫入皆以 try/except 包裹 → 永不拋例外、永不中斷推播。
  • 不寫入任何 production state（flags/predictions/pool 皆不碰）。
  • 不送 Telegram、不影響 best_pick / Kelly / edge / MC / predict。
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

import obs

SHADOW_CSV = "shadow_eval.csv"
_FIELDS = [
    "ts_utc", "type", "match_id", "sport", "home", "away", "kickoff",
    "v1_direction", "v1_prob", "v3_best_pick", "v3_edge", "actual_result",
]


def _append(row: dict) -> None:
    """寫一列；任何錯誤只記 log，不外拋。"""
    try:
        is_new = not os.path.exists(SHADOW_CSV)
        with open(SHADOW_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in _FIELDS})
    except Exception as exc:  # noqa: BLE001 — shadow 寫入永不影響推播
        obs.warn("shadow.write_failed", err=str(exc))


def log_prediction(game: dict) -> None:
    """推播時記錄一列 predict：v1_direction（MC argmax）+ v3_best_pick（僅讀取）。"""
    try:
        pred = game.get("prediction") or {}
        mc = (pred.get("model_mc") or {}).get("win_prob") or {}
        v1_dir, v1_prob = "", ""
        if mc:
            k = max(mc, key=mc.get)
            v1_dir, v1_prob = k, f"{mc[k]:.4f}"
        bp = pred.get("best_pick") or {}
        edge = pred.get("edge") or {}
        bp_out = bp.get("outcome") if bp else "none"
        _append({
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "type": "predict",
            "match_id": str(game.get("id", "")),
            "sport": pred.get("sport", game.get("sport", "")),
            "home": pred.get("home", game.get("home", "")),
            "away": pred.get("away", game.get("away", "")),
            "kickoff": pred.get("start_time", game.get("start_time", "")),
            "v1_direction": v1_dir,
            "v1_prob": v1_prob,
            "v3_best_pick": bp_out,
            "v3_edge": (edge.get(bp_out) if bp_out in edge else ""),
        })
    except Exception as exc:  # noqa: BLE001
        obs.warn("shadow.log_prediction_failed", err=str(exc))


def log_result(match_id: str, score_result: dict | None = None,
               verify_result: dict | None = None, sport: str = "") -> None:
    """賽後記錄一列 result：actual_result（防禦式從賽果推導 home/away/draw）。"""
    try:
        sr = score_result or {}
        vr = verify_result or {}
        winner = ""
        hs, as_ = sr.get("home_score"), sr.get("away_score")
        if isinstance(hs, (int, float)) and isinstance(as_, (int, float)):
            winner = "home" if hs > as_ else ("away" if as_ > hs else "draw")
        elif vr.get("actual_winner"):
            winner = str(vr.get("actual_winner"))
        _append({
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "type": "result",
            "match_id": str(match_id),
            "sport": sport,
            "actual_result": winner,
        })
    except Exception as exc:  # noqa: BLE001
        obs.warn("shadow.log_result_failed", err=str(exc))
