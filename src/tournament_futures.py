"""tournament_futures.py — Tournament Futures 唯一入口（orchestrator）。

所有商業邏輯集中於此（Reviewer Rule 2）：查 registry、決定抓哪個 key、彙整多家、
呼叫去 Vig、排序、決定 available / N/A。renderer 只負責格式化。

依賴方向（Reviewer Rule 3，單向）：
  capability_registry → tournament_futures → futures_fetcher → futures_devig → futures_render
本檔 import 上述模組；上述模組不得反向 import 本檔。
能力一律查 registry（Rule 1），不得出現 `if champion:` 之類寫死分支。
"""
from __future__ import annotations

import capability_registry as registry
import futures_devig
import futures_fetcher
import futures_render

# orchestrator 決定每個能力對應的 outright sport key（Rule 3：由 orchestrator 決定抓哪些）。
# key 未確認/錯誤/當下無賠率 → 最終 render N/A（永不捏造）。WC/NBA/MLB 之後在此擴充即可。
_OUTRIGHT_KEYS: dict[str, str] = {
    "Champion": "soccer_fifa_world_cup_winner",  # 待 API 實測確認
}

_TITLES: dict[str, str] = {
    "Champion": "🏆 冠軍預測",
    "TopGoalscorer": "👟 射手榜",
    "GoldenBoot": "👟 金靴獎",
    "GoldenGlove": "🧤 金手套獎",
}


def _na(capability: str, title: str, reason: str | None) -> dict:
    return {
        "capability": capability, "title": title,
        "available": False, "na_reason": reason,
        "source": None, "overround": None, "ranked": [],
    }


def _consensus_odds(books: list[dict]) -> dict[str, float]:
    """多家 bookmaker 的 {outcome: odds} → 每 outcome 跨家平均 decimal odds（彙整＝商業邏輯）。"""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for b in books:
        for name, price in b.items():
            sums[name] = sums.get(name, 0.0) + price
            counts[name] = counts.get(name, 0) + 1
    return {name: sums[name] / counts[name] for name in sums}


def build(capability: str, *, getter=None) -> dict:
    """產生某能力的 futures 結果（給 renderer 的已備妥 data）。所有判斷都在這裡。"""
    title = _TITLES.get(capability, capability)
    cap = registry.get(capability)
    if cap is None:
        return _na(capability, title, "unknown capability")
    if not cap.supported:                                   # 查 registry，不寫死能力
        return _na(capability, title, cap.reason_if_na)
    key = _OUTRIGHT_KEYS.get(capability)
    if not key:
        return _na(capability, title, "無對應 outright key")

    books = futures_fetcher.fetch(key, getter=getter)       # 只解析
    if not books:
        return _na(capability, title, "目前無 outright 盤口")

    dv = futures_devig.devig(_consensus_odds(books))        # 機率數學（唯一處）
    if not dv:
        return _na(capability, title, "賠率無效")

    ranked = sorted(
        ({"outcome": k, "fair_probability": v} for k, v in dv["fair_probability"].items()),
        key=lambda r: r["fair_probability"], reverse=True,  # 排序＝商業邏輯（不放 renderer）
    )
    return {
        "capability": capability, "title": title,
        "available": True, "na_reason": None,
        "source": cap.source, "overround": dv["overround"],
        "raw_odds": dv["raw_odds"], "implied_probability": dv["implied_probability"],
        "fair_probability": dv["fair_probability"], "ranked": ranked,
    }


def render_text(capability: str, *, getter=None) -> str:
    return futures_render.render_text(build(capability, getter=getter))


def render_json(capability: str, *, getter=None) -> str:
    return futures_render.render_json(build(capability, getter=getter))


# ── 合併獎項推播（Champion + GoldenBoot + GoldenGlove）─────
# orchestrator 決定要哪些能力；每項仍走 registry → fetch → devig → 排序。
# 未確認/無盤口的能力 → build() 回 available=False → render 顯示 N/A（不捏造）。
_AWARD_SET = ["Champion", "GoldenBoot", "GoldenGlove"]


def build_awards(capabilities: list[str] | None = None, *, getter=None) -> list[dict]:
    """產生獎項區塊資料（每能力一個 build() 結果，已備妥給 renderer）。"""
    return [build(c, getter=getter) for c in (capabilities or _AWARD_SET)]


def render_awards(capabilities: list[str] | None = None, *, getter=None,
                  header: str = "🏆 World Cup 冠軍與個人獎項（市場隱含）") -> str:
    return futures_render.render_awards(build_awards(capabilities, getter=getter), header=header)
