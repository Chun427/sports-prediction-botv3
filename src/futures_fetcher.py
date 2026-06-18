"""futures_fetcher.py — 抓 outright（futures）盤口。

單一職責（Reviewer Rule 4）：HTTP / Retry / Transport / Parsing。
不算機率、不去 Vig、不排序、不 render。
共用 data_fetcher 的傳輸層（KeyManager：金鑰輪替/cooldown/重試），唯讀 import，不改 data_fetcher。

介面：fetch(key, ...) — 由 orchestrator 決定抓哪個 outright sport key
（World Cup / NBA champion / MLB World Series 皆可共用，Reviewer Rule 3）。
"""
from __future__ import annotations

from data_fetcher import KeyManager  # 唯讀共用傳輸層（不修改 data_fetcher）


def _parse_outrights(resp) -> list[dict] | None:
    """把 outrights 回應解析成「每家 bookmaker 一個 {outcome: decimal_odds}」。

    純解析；狀態非 200 / body 非清單 / 無 outrights 市場 → None（不捏造）。
    """
    if resp is None or getattr(resp, "status", None) != 200:
        return None
    events = resp.body if isinstance(getattr(resp, "body", None), list) else None
    if not events:
        return None
    books: list[dict] = []
    for ev in events:
        for bk in ev.get("bookmakers", []) or []:
            for m in bk.get("markets", []) or []:
                if m.get("key") != "outrights":
                    continue
                odds: dict[str, float] = {}
                for o in m.get("outcomes", []) or []:
                    name, price = o.get("name"), o.get("price")
                    if name and isinstance(price, (int, float)) and not isinstance(price, bool) and price > 1.0:
                        odds[name] = float(price)
                if len(odds) >= 2:
                    books.append(odds)
    return books or None


def fetch(key: str, *, regions: str = "eu", getter=None) -> list[dict] | None:
    """抓某 outright sport key 的 outrights 盤口。

    getter(path, params) -> HttpResponse；預設用 KeyManager.from_env().get（含金鑰輪替）。
    任何傳輸/解析失敗一律回 None（N/A，永不 crash、永不捏造）。
    """
    if not key:
        return None
    get = getter or KeyManager.from_env().get
    try:
        resp = get(
            f"/sports/{key}/odds",
            {"markets": "outrights", "regions": regions, "oddsFormat": "decimal"},
        )
    except Exception:
        return None
    return _parse_outrights(resp)
