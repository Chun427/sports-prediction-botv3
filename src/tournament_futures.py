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
import obs
from futures_validation import validate_outright_key

# orchestrator 決定每個能力對應的 outright sport key（Rule 3：由 orchestrator 決定抓哪些）。
# key 未確認/錯誤/當下無賠率 → 最終 render N/A（永不捏造）。WC/NBA/MLB 之後在此擴充即可。
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
    """產生某能力的 futures 結果（給 renderer 的已備妥 data）。所有判斷都在這裡。

    可用與否＝runtime 市場驗證：registry 提供候選 key → fetch → validate_outright_key。
    不再依賴寫死的 supported 旗標（market 是唯一真相）。
    """
    title = _TITLES.get(capability, capability)
    cap = registry.get(capability)
    if cap is None:
        obs.warn("awards.build.na", capability=capability, layer="capability_registry",
                 reason="unknown capability（registry 無此能力）")
        return _na(capability, title, "unknown capability")
    if cap.permanent_na:                                    # 市場根本不存在 → 不 fetch
        obs.info("awards.build.na", capability=capability, layer="capability_registry",
                 market_key=cap.outright_key, reason=f"permanent_na：{cap.permanent_na}")
        return _na(capability, title, cap.permanent_na)
    key = cap.outright_key                                  # key 來自 registry（單一真相）
    if not key:
        obs.warn("awards.build.na", capability=capability, layer="capability_registry",
                 reason="無對應 outright key（registry 未設定 market key）")
        return _na(capability, title, "無對應 outright key（待 API）")

    books = futures_fetcher.fetch(key, getter=getter)       # 只解析
    _n_books = len(books or [])
    if not validate_outright_key(books):                    # ← runtime 驗證市場是否真的存在
        # 區分：odds source 沒回東西 vs 回了但市場無效/解析不出
        _layer = "odds_source（getter 未回傳任何盤口）" if _n_books == 0 else "parser/market（有回應但市場無效或解析失敗）"
        obs.warn("awards.build.na", capability=capability, layer=_layer,
                 market_key=key, n_books=_n_books, reason="市場不存在或無有效盤口")
        return _na(capability, title, "市場不存在或無有效盤口")

    dv = futures_devig.devig(_consensus_odds(books))        # 機率數學（唯一處）
    if not dv:
        obs.warn("awards.build.na", capability=capability, layer="futures/devig",
                 market_key=key, n_books=_n_books, reason="賠率無效（devig 失敗）")
        return _na(capability, title, "賠率無效")

    obs.info("awards.build.ok", capability=capability, market_key=key, n_books=_n_books,
             overround=dv["overround"])

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
