"""verified_enrich.py — V4 Phase 1：賽後回饋資料擴充（additive、純讀、不碰核心）。

在 run_postgame_verify 把一筆 verification record 補上完整回饋欄位，
供未來 audit / calibration / benchmark 使用。

設計原則（對齊 V4 設計文件 §1、§11）：
  • 純讀：只讀 prediction / result / market_lines / total_goals，不改任何核心模組。
  • 逐欄 guard：算不出就填 None，永不 crash、永不捏造（safe by default）。
  • 不 backfill：舊資料維持空白，只有新賽果才逐步填。
  • analytics 不被 schema bias 汙染：total_goals_hit / scoreline_hit 僅在「有意義」時給值，
    否則 None（例如非 FIFA 無總進球桶、MLB/NBA 無 top_scorelines）。
"""
from __future__ import annotations

import market_lines
import result_verifier
import total_goals


def _hit_of(t):
    """verify_handicap / verify_total 回 (label, hit) 或 None → 取 hit。"""
    if isinstance(t, (tuple, list)) and len(t) >= 2:
        return t[1]
    return None


def _safe(fn):
    """任何欄位計算失敗一律回 None（回饋層永不可崩）。"""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def enrich(prediction: dict, result: dict, sport: str) -> dict:
    """回傳 V4 新增欄位 dict；與既有 VERIFIED_FIELDS 併用。"""
    pred = prediction or {}
    res = result or {}
    ms = pred.get("model_score") or {}
    mc = (pred.get("model_mc") or {}).get("win_prob") or {}
    fair = pred.get("fair_prob") or {}
    edge = pred.get("edge") or {}
    market = pred.get("market")
    is_fifa = str(sport).upper() == "FIFA"

    hs = res.get("home_score")
    aws = res.get("away_score")
    has_score = hs is not None and aws is not None
    actual_total = (hs + aws) if has_score else None

    direction = _safe(lambda: result_verifier.main_direction(pred))

    def _scoreline_hit():
        # 正確比分僅 FIFA 有意義（MLB/NBA 雖有 Poisson top_scorelines，但無台彩比分市場）→ 非 FIFA 一律 None。
        # 比照 _total_goals_hit 的 is_fifa gate，避免 cross-sport schema 污染 verified_history。
        # NOTE: scoreline_hit is intentionally FIFA-scoped to avoid cross-sport contamination.
        # All non-FIFA values must remain None to preserve feature-space purity for downstream
        # consumers (daily_report display, audit_engine aggregation, future ML features).
        if not is_fifa:
            return None
        tops = ms.get("top_scorelines")
        if not tops or not has_score:
            return None
        return sum(1 for s in tops if s.get("home") == hs and s.get("away") == aws)

    def _total_goals_hit():
        if not is_fifa or not has_score:
            return None  # 僅 FIFA 有總進球桶；非足球 → None（避免 schema bias）
        gb = total_goals.goal_buckets(ms)
        if not gb or not gb.get("most_likely"):
            return None
        return total_goals.bucket_label_of_total(actual_total) == gb["most_likely"]

    def _ou_recommended_hit():
        # 對齊「賽前 O/U 推薦」(notifier)：大分 if expected_total > market_total else 小分（平手/無→小分）；
        # 以真實盤線 over_under 結算（actual_total vs 線）。走盤(等於線)→None。
        # 刻意不改凍結的 market_lines.verify_total（其 exp==line 即判「無偏向」回 None，導致 ou_hit 長期空白）。
        if not isinstance(market, dict) or not has_score:
            return None
        ou = market.get("over_under")
        et = ms.get("expected_total")
        if ou is None or not isinstance(et, (int, float)):
            return None
        if actual_total == ou:
            return None  # 走盤
        lean_over = et > ms.get("market_total", et)   # 同賽前規則：平手/小於＝小分
        actual_over = actual_total > ou
        return lean_over == actual_over

    return {
        # --- 市場命中 ---
        "ah_hit": _safe(lambda: _hit_of(market_lines.verify_handicap(market, hs, aws))) if has_score else None,
        "ou_hit": _safe(_ou_recommended_hit),
        # --- 比分品質 ---
        "scoreline_hit": _safe(_scoreline_hit),
        "total_goals_hit": _safe(_total_goals_hit),
        # --- 模型診斷 ---
        "edge": _safe(lambda: edge.get(direction)),
        "confidence": _safe(lambda: mc.get(direction)),
        "model_winprob": _safe(lambda: mc.get(direction)),
        "devig_winprob": _safe(lambda: fair.get(direction)),
        # --- 總分校準 ---
        "expected_total": _safe(lambda: ms.get("expected_total")),
        "actual_total": actual_total,
        # --- 階段追蹤（early_12h / pre_match_40m；未記錄則 None）---
        "phase": pred.get("phase"),
    }
