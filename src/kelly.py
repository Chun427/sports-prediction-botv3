"""
kelly.py — P1 FEATURE 1：Kelly + Risk 引擎（PURE，additive-only）

把現有 prediction 的 best_pick（fair_prob + odds）轉成 Kelly 下注比例與風險等級。
不修改 prediction_engine、不改 snapshot / verified_history schema。
本模組為獨立純函式；是否接進主鏈由上層決定（本輪不接，保 113 不動）。

Kelly:  f* = (b·p − q) / b   其中 b = odds − 1, p = 勝率, q = 1 − p
Safety: f ≤ 0 → 0；cap 0.25；odds ≤ 1.01 → 0（無可下注空間）。
Risk:   clipped < 0.02 → low；0.02–0.06 → medium；> 0.06 → high。
"""
from __future__ import annotations

KELLY_CAP = 0.25
ODDS_FLOOR = 1.01


def kelly_fraction(prob: float, decimal_odds: float) -> float:
    """原始 Kelly 比例（可為負；未 clip / 未 cap）。odds ≤ 1.01 → 0。"""
    b = decimal_odds - 1.0
    if b <= (ODDS_FLOOR - 1.0):
        return 0.0
    q = 1.0 - prob
    return (b * prob - q) / b


def clip_fraction(raw: float) -> float:
    """套用 safety：負值 → 0；上限 cap 0.25。"""
    if raw <= 0.0:
        return 0.0
    return min(raw, KELLY_CAP)


def classify_risk(clipped: float) -> str:
    if clipped < 0.02:
        return "low"
    if clipped <= 0.06:
        return "medium"
    return "high"


def compute_kelly(prediction: dict) -> dict:
    """
    由 prediction 的 best_pick + fair_prob 算出 kelly/risk_level（additive 欄位）。
    無 best_pick / 缺勝率 → fraction 0、risk low。
    回傳：{"kelly": {"fraction": float, "clipped_fraction": float}, "risk_level": str}
    """
    pick = prediction.get("best_pick")
    if not pick:
        return {"kelly": {"fraction": 0.0, "clipped_fraction": 0.0}, "risk_level": "low"}

    outcome = pick.get("outcome")
    odds = pick.get("odds")
    prob = (prediction.get("fair_prob") or {}).get(outcome)
    if prob is None or not isinstance(odds, (int, float)):
        return {"kelly": {"fraction": 0.0, "clipped_fraction": 0.0}, "risk_level": "low"}

    raw = round(kelly_fraction(prob, float(odds)), 4)
    clipped = round(clip_fraction(raw), 4)
    return {
        "kelly": {"fraction": raw, "clipped_fraction": clipped},
        "risk_level": classify_risk(clipped),
    }


def attach(prediction: dict) -> dict:
    """回傳「prediction + kelly/risk_level」的新 dict（不變動原 dict，純 additive）。"""
    return {**prediction, **compute_kelly(prediction)}
