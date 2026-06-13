"""
monte_carlo_engine.py — STEP 2：Monte Carlo 模擬（PURE，無副作用）

輸入必須是 score_model 的真實輸出（λ 來自 totals/spreads）。
不接受任何硬編/UI 來源。score_model 為 None → 本層回 None。

設計：
  • Poisson 運動：抽 home/away 得分 ~ Poisson(λ) → 勝/平/負分布 + 比分分布。
  • Normal 運動（NBA）：抽 margin ~ Normal → 勝負分布（不產精準比分）。
  • 提供 seed 以利可重現的收斂/變異驗證；MC 結果應收斂回 score_model 的 analytic 機率。
"""
import math
import random


def _poisson_sample(lam: float, rng: random.Random) -> int:
    """Knuth Poisson 抽樣。"""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def simulate_poisson(lam_home: float, lam_away: float, n: int = 20000, seed=None) -> dict:
    rng = random.Random(seed)
    home_w = draw = away_w = 0
    score_counts: dict[tuple[int, int], int] = {}
    for _ in range(n):
        h = _poisson_sample(lam_home, rng)
        a = _poisson_sample(lam_away, rng)
        if h > a:
            home_w += 1
        elif h == a:
            draw += 1
        else:
            away_w += 1
        score_counts[(h, a)] = score_counts.get((h, a), 0) + 1
    top = sorted(score_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "n": n,
        "win_prob": {
            "home": round(home_w / n, 4),
            "draw": round(draw / n, 4),
            "away": round(away_w / n, 4),
        },
        "top_scorelines": [
            {"home": h, "away": a, "prob": round(c / n, 4)} for (h, a), c in top
        ],
    }


def simulate_normal_margin(mean: float, sigma: float, n: int = 20000, seed=None) -> dict:
    rng = random.Random(seed)
    home_w = 0
    for _ in range(n):
        if rng.gauss(mean, sigma) > 0:
            home_w += 1
    return {
        "n": n,
        "win_prob": {"home": round(home_w / n, 4), "away": round(1.0 - home_w / n, 4)},
        # NBA：故意不產精準比分
    }


def run_monte_carlo(score_model: dict | None, n: int = 20000, seed=None) -> dict | None:
    """依 score_model 類型分派；None → None（不捏造）。"""
    if not score_model:
        return None
    t = score_model.get("type")
    if t == "poisson":
        return simulate_poisson(score_model["lambda_home"], score_model["lambda_away"], n, seed)
    if t == "normal_margin":
        return simulate_normal_margin(score_model["expected_margin"], score_model["sigma"], n, seed)
    return None
