"""
result_verifier.py — Decision layer（C-3，PURE）

verify(prediction, result) -> record | None

business ≠ IO：純函式、無 IO、deterministic、fully testable。
scope（D-C1 鎖定）：moneyline 命中 + EV 實現 + 單場市場偏差。
不做：spread / totals / exact score / player awards / tournament（未預測，無從驗證）。

輸入：
  • prediction：C-1 snapshot 內的 prediction dict
                （含 game_id / fair_prob{home,away,draw} / best_pick{outcome,edge,odds} / model）
  • result    ：C-2 fetch_scores 的 normalized 結果
                （含 completed / home_score / away_score / id）
"""
from __future__ import annotations


def _winner(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


def verify(prediction: dict, result: dict) -> dict | None:
    """
    比對單場 prediction vs 賽果，回 verification record；尚不可驗 → None。
      • completed=false → None
      • 缺 home/away score → None
    """
    if not result.get("completed"):
        return None
    home_score = result.get("home_score")
    away_score = result.get("away_score")
    if home_score is None or away_score is None:
        return None

    winner = _winner(home_score, away_score)

    # 市場校準：實際結果的市場隱含（去 Vig 共識）勝率，供未來 calibration 聚合。
    fair = prediction.get("fair_prob", {}) or {}
    fair_prob_winner = float(fair.get(winner, 0.0))

    best_pick = prediction.get("best_pick")
    if best_pick:
        pick_outcome = best_pick.get("outcome")
        pick_hit = (pick_outcome == winner)
        moneyline_hit = pick_hit
        # EV 實現（下注 1 unit）：命中 → odds-1；未命中 → -1。
        odds = best_pick.get("odds")
        if isinstance(odds, (int, float)):
            realized_return = (float(odds) - 1.0) if pick_hit else -1.0
        else:
            realized_return = None  # odds 壞值 → 無法計
    else:
        pick_outcome = None
        pick_hit = None
        moneyline_hit = None
        realized_return = None

    return {
        "game_id": str(prediction.get("game_id") or result.get("id", "")),
        "winner": winner,
        "pick_outcome": pick_outcome,
        "pick_hit": pick_hit,
        "moneyline_hit": moneyline_hit,
        "realized_return": realized_return,
        "fair_prob_winner": fair_prob_winner,
        "model": prediction.get("model", ""),
    }
