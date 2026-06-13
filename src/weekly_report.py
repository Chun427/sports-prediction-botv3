"""
weekly_report.py — P1 FEATURE 2：每週基本績效報表（PURE，additive-only）

只讀現有 verified_history.csv（不新增 DB / 不改 schema / 不改 verifier）。
空資料 → 安全 fallback。

⚠️ 誠實註記：verified_history 目前「未儲存 edge」欄位，故無法計算 avg_edge。
   本報表以 avg_realized_return（EV 實現）與 market_calibration（實際贏家的
   平均市場隱含勝率）取代。待 P2 擴充 verified_history 後才談 avg_edge。
"""
from __future__ import annotations

from typing import Optional

import data_manager as dm


def _to_bool(v) -> Optional[bool]:
    s = str(v).strip()
    if s == "True":
        return True
    if s == "False":
        return False
    return None


def _to_float(v) -> Optional[float]:
    try:
        s = str(v).strip()
        return float(s) if s != "" else None
    except (TypeError, ValueError):
        return None


def _rate(flags: list) -> float:
    valid = [b for b in flags if b is not None]
    if not valid:
        return 0.0
    return round(sum(1 for b in valid if b) / len(valid), 4)


def _mean(vals: list) -> float:
    valid = [x for x in vals if x is not None]
    if not valid:
        return 0.0
    return round(sum(valid) / len(valid), 4)


def _empty_report(week_range: str) -> dict:
    return {
        "week_range": week_range or "N/A",
        "total_games": 0,
        "win_rate": 0.0,
        "avg_realized_return": 0.0,
        "market_calibration": 0.0,
        "ev_trend": 0.0,
        "sport_breakdown": {},
        "notes": "no verified data",
    }


def build_weekly_report(rows: Optional[list] = None, *, week_range: Optional[str] = None) -> dict:
    """
    rows：verified_history 列（list[dict]）。None → 自 data_manager.read_verified() 讀取。
    回傳純 report dict（不觸發任何推播）。
    """
    if rows is None:
        rows = dm.read_verified()

    total = len(rows)
    if total == 0:
        return _empty_report(week_range)

    win_rate = _rate([_to_bool(r.get("moneyline_hit")) for r in rows])
    avg_rr = _mean([_to_float(r.get("realized_return")) for r in rows])
    market_cal = _mean([_to_float(r.get("fair_prob_winner")) for r in rows])

    by_sport: dict = {}
    for r in rows:
        by_sport.setdefault(r.get("sport") or "?", []).append(r)
    sport_breakdown = {
        sport: {
            "games": len(rs),
            "win_rate": _rate([_to_bool(x.get("moneyline_hit")) for x in rs]),
            "avg_realized_return": _mean([_to_float(x.get("realized_return")) for x in rs]),
        }
        for sport, rs in by_sport.items()
    }

    if not week_range:
        dates = sorted(str(r.get("verified_at", ""))[:10] for r in rows if r.get("verified_at"))
        week_range = f"{dates[0]} ~ {dates[-1]}" if dates else "N/A"

    return {
        "week_range": week_range,
        "total_games": total,
        "win_rate": win_rate,
        "avg_realized_return": avg_rr,
        "market_calibration": market_cal,
        "ev_trend": avg_rr,           # 以平均 EV 實現作為趨勢基準（單期）
        "sport_breakdown": sport_breakdown,
        "notes": "avg_edge 不在 verified_history（P1 未擴充 schema），故以 EV/校準替代",
    }
