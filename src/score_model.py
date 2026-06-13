"""
score_model.py — STEP 1：sport-aware 比分模型（PURE，無副作用）

核心誠實原則：
  • λ（預期得分）只能來自「真實市場資料」：totals 線(O/U) + spreads 線(讓分)。
  • 無 totals → 無 λ 來源 → 回 None（呼叫端必須隱藏該 section，不得 fallback 文字）。
  • Poisson 僅用於低分運動（足球進球 / 棒球得分）；NBA 高分近常態 →
    用 margin 常態模型，且「不輸出精準比分」（exact NBA 比分機率無意義 = 假）。

不做：硬編數字、用 h2h 反推 λ（資訊循環 = 假）、對 NBA 套 Poisson 比分。
"""
import math

# 低分運動 → Poisson 有效；NBA → 常態 margin（無精準比分）
POISSON_SPORTS = {"FIFA", "MLB"}
NORMAL_SPORTS = {"NBA"}

# NBA 讓分標準差（經驗值，約 11–13 分）；用於 margin 常態模型
NBA_MARGIN_SIGMA = 12.0


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _median(values: list[float]):
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def consensus_total(odds_totals) -> float | None:
    """各家 O/U 線中位數 = 市場隱含預期總分。無資料 → None。"""
    return _median([r.get("line") for r in (odds_totals or []) if r.get("line") is not None])


def consensus_supremacy(odds_spreads) -> float | None:
    """
    各家主隊讓分中位數 → 主隊預期分差（supremacy）。
    home_point 為負(被看好) → supremacy 正。無資料 → None。
    """
    med = _median([r.get("home_point") for r in (odds_spreads or []) if r.get("home_point") is not None])
    return None if med is None else -med


def split_lambdas(total: float, supremacy: float) -> tuple[float, float]:
    """總分 + 分差 → 主/客預期得分（λ）。λ_home+λ_away=total；λ_home-λ_away=supremacy。"""
    lam_home = max(0.01, (total + supremacy) / 2.0)
    lam_away = max(0.01, (total - supremacy) / 2.0)
    return lam_home, lam_away


def poisson_grid(lam_home: float, lam_away: float, max_goals: int = 12) -> dict:
    """獨立 Poisson 比分網格 {(h,a): prob}，在截斷網格上正規化（Σ=1）。"""
    ph = [_poisson_pmf(h, lam_home) for h in range(max_goals + 1)]
    pa = [_poisson_pmf(a, lam_away) for a in range(max_goals + 1)]
    grid: dict[tuple[int, int], float] = {}
    total = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = ph[h] * pa[a]
            grid[(h, a)] = p
            total += p
    if total > 0:
        for k in grid:
            grid[k] /= total
    return grid


def outcome_probs(grid: dict) -> dict:
    home = draw = away = 0.0
    for (h, a), p in grid.items():
        if h > a:
            home += p
        elif h == a:
            draw += p
        else:
            away += p
    return {"home": round(home, 4), "draw": round(draw, 4), "away": round(away, 4)}


def top_scorelines(grid: dict, n: int = 5) -> list[dict]:
    items = sorted(grid.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return [{"home": h, "away": a, "prob": round(p, 4)} for (h, a), p in items]


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def build_score_model(game: dict) -> dict | None:
    """
    回傳該場的比分模型；資料/運動不支援 → None（呼叫端隱藏 section）。
    需要 totals（λ 來源）；無 totals 一律回 None（不捏造）。
    """
    sport = game.get("sport")
    total = consensus_total(game.get("odds_totals"))
    if total is None:
        return None  # 無 λ 來源 → 無模型
    supremacy = consensus_supremacy(game.get("odds_spreads"))
    if supremacy is None:
        supremacy = 0.0  # 有總分但無讓分 → 視為均勢（仍是真實 total 驅動）

    if sport in POISSON_SPORTS:
        lam_home, lam_away = split_lambdas(total, supremacy)
        grid = poisson_grid(lam_home, lam_away)
        return {
            "type": "poisson",
            "sport": sport,
            "lambda_home": round(lam_home, 3),
            "lambda_away": round(lam_away, 3),
            "expected_total": round(total, 2),
            "supremacy": round(supremacy, 2),
            "outcome_probs": outcome_probs(grid),
            "top_scorelines": top_scorelines(grid, 5),
        }

    if sport in NORMAL_SPORTS:
        # NBA：margin ~ Normal(mean=supremacy, sd=σ)；P(home win)=P(margin>0)
        # 明確不輸出精準比分（NBA exact score 機率無意義）。
        p_home = _normal_cdf(supremacy / NBA_MARGIN_SIGMA)
        return {
            "type": "normal_margin",
            "sport": sport,
            "expected_margin": round(supremacy, 2),
            "expected_total": round(total, 2),
            "sigma": NBA_MARGIN_SIGMA,
            "outcome_probs": {"home": round(p_home, 4), "away": round(1.0 - p_home, 4)},
            # 故意不含 top_scorelines
        }

    return None  # 不支援的運動 → 無模型
