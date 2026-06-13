"""
prediction_engine.py — Processing layer（MVP 切片：market-implied）

純函式、無 IO（business logic ≠ IO），輸入為 data_fetcher 標準化的 odds_h2h，
輸出 normalized prediction（或 None = 無有效市場）。

本切片只做：多家去 Vig（乘法歸一）→ 市場隱含勝率共識 → 最佳賠率 → Edge(EV)。
不做：Monte Carlo / Kelly / XGBoost。

⚠️ Edge 語意：這是「最佳賠率 vs 多家共識公平機率」的市場價值/比價 edge，
   不是「模型 vs 市場」的預測性 edge（MVP 無模型）。schema 以 model 欄位標記版本。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from constants import EDGE_MIN, MODEL_TAG, TW_TZ

OUTCOMES = ("home", "away", "draw")


def devig_one(book: dict) -> Optional[dict]:
    """單一 bookmaker h2h → 去 Vig 後機率（乘法歸一）。outcome < 2 或無效 → None。"""
    implied = {}
    for key in OUTCOMES:
        price = book.get(key)
        if isinstance(price, (int, float)) and price > 1.0:
            implied[key] = 1.0 / price
    if len(implied) < 2:
        return None
    total = sum(implied.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in implied.items()}


def consensus(books: list[dict]) -> Optional[dict]:
    """多家各自去 Vig 後，對每個 outcome 取平均，再歸一（保險）。無有效家 → None。"""
    devigged = [d for d in (devig_one(b) for b in books) if d]
    if not devigged:
        return None
    keys: set[str] = set()
    for d in devigged:
        keys.update(d)
    fair = {k: sum(d[k] for d in devigged if k in d) / sum(1 for d in devigged if k in d)
            for k in keys}
    total = sum(fair.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in fair.items()}


def best_odds(books: list[dict]) -> dict:
    """各 outcome 跨家最佳（最高）decimal odds。"""
    best: dict[str, float] = {}
    for b in books:
        for key in OUTCOMES:
            price = b.get(key)
            if isinstance(price, (int, float)) and price > 1.0:
                if key not in best or price > best[key]:
                    best[key] = float(price)
    return best


def avg_overround(books: list[dict]) -> Optional[float]:
    """各家抽水（Σ implied − 1）的平均，透明度用。"""
    rounds = []
    for b in books:
        s = sum(1.0 / b[k] for k in OUTCOMES
                if isinstance(b.get(k), (int, float)) and b[k] > 1.0)
        if s > 0:
            rounds.append(s - 1.0)
    return round(sum(rounds) / len(rounds), 4) if rounds else None


def predict(game: dict) -> Optional[dict]:
    """
    game（含 odds_h2h）→ normalized prediction。
    無有效 h2h 市場（odds_h2h 空 / 無法去 Vig）→ 回 None（No Prediction Available）。
    """
    books = game.get("odds_h2h") or []
    fair = consensus(books)
    bests = best_odds(books)
    if not fair or not bests:
        return None

    edge = {k: round(bests[k] * p - 1.0, 4) for k, p in fair.items() if k in bests}
    if not edge:
        return None

    best_k = max(edge, key=edge.get)
    best_pick = (
        {"outcome": best_k, "edge": edge[best_k], "odds": bests[best_k]}
        if edge[best_k] > EDGE_MIN else None
    )

    return {
        "game_id": game.get("id"),
        "sport": game.get("sport"),
        "home": game.get("home"),
        "away": game.get("away"),
        "start_time": game.get("start_time"),
        "market": "h2h",
        "bookmaker_count": len(books),
        "fair_prob": {k: round(v, 4) for k, v in fair.items()},
        "best_odds": bests,
        "edge": edge,
        "best_pick": best_pick,
        "avg_overround": avg_overround(books),
        "model": MODEL_TAG,
        "generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"),
    }
