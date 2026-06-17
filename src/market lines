"""market_lines.py — 盤口線抽取 + 賽後讓分/大小驗證（addon，只讀，不碰模型）。

設計原則（誠實性）：
  • 盤口線來自池子既有 odds_spreads / odds_totals（各 book 中位數＝市場共識），不推測、不捏造。
  • 抽不到線 → 回 None；賽後對應項顯示 N/A。
  • 不寫回任何資料、不碰 score_model / MC / Kelly / prediction_engine。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone


def _median(vals) -> float | None:
    nums = [v for v in vals if isinstance(v, (int, float))]
    return float(statistics.median(nums)) if nums else None


def extract_market(game: dict) -> dict | None:
    """從一場池子 game 抽『市場共識線』。
    回傳 {asian_handicap, over_under, odds_source, timestamp} 或 None（兩者皆無）。
      • asian_handicap = 主隊讓分線（各 book home_point 中位數，負=主隊熱門）
      • over_under     = 大小盤線（各 book line 中位數）
    """
    if not isinstance(game, dict):
        return None
    spreads = game.get("odds_spreads") or []
    totals = game.get("odds_totals") or []
    ah = _median([s.get("home_point") for s in spreads if isinstance(s, dict)])
    ou = _median([t.get("line") for t in totals if isinstance(t, dict)])
    if ah is None and ou is None:
        return None
    return {
        "asian_handicap": ah,
        "over_under": ou,
        "odds_source": "the-odds-api/consensus",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def verify_handicap(market: dict, home_score, away_score):
    """熱門方是否過盤。回傳 (label, hit) 或 None（無線/無比分）。
    hit=True 過盤、False 未過盤、None 走盤或無熱門（和盤）。"""
    if not isinstance(market, dict):
        return None
    ah = market.get("asian_handicap")
    if ah is None or not isinstance(home_score, int) or not isinstance(away_score, int):
        return None
    if ah < 0:          # 主隊熱門（讓分）
        adj = (home_score + ah) - away_score
        side = f"主{ah:+.1f}"
    elif ah > 0:        # 客隊熱門
        adj = (away_score - ah) - home_score
        side = f"客{-ah:+.1f}"
    else:
        return ("和盤", None)
    if adj == 0:
        return (side, None)   # 走盤
    return (side, adj > 0)


def verify_total(market: dict, model_score: dict, home_score, away_score):
    """模型大小偏向是否命中。回傳 (label, hit) 或 None。
    模型偏向＝expected_total vs 盤線；hit=實際大小方向與偏向一致；None=走盤或無偏向。"""
    if not isinstance(market, dict):
        return None
    ou = market.get("over_under")
    if ou is None or not isinstance(home_score, int) or not isinstance(away_score, int):
        return None
    total = home_score + away_score
    if total == ou:
        return (f"線{ou}", None)   # 走盤
    exp = (model_score or {}).get("expected_total")
    if not isinstance(exp, (int, float)) or exp == ou:
        return (f"線{ou}", None)   # 無模型偏向 → 不判命中
    lean_over = exp > ou
    actual_over = total > ou
    return (f"{'大' if lean_over else '小'}（線{ou}）", lean_over == actual_over)
