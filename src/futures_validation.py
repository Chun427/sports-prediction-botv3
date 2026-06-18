"""futures_validation.py — runtime 驗證「outright 市場是否真實存在」。

market 是唯一真相：不靠寫死的 supported，靠 bookmaker 回應判斷。
單一職責：只判斷有效性。不抓 API、不去 Vig、不排序、不 render。

validate_outright_key(books) — books 為 futures_fetcher.fetch() 解析後的結果
  （list[dict]，每家 bookmaker 一個 {outcome: decimal_odds}）。
  有效市場 = 至少一家 bookmaker、且該家至少 2 個有效 outcome。
  空 / None / 不足 → False（市場不存在 → 上層標 N/A，不捏造）。
"""
from __future__ import annotations


def validate_outright_key(books: list[dict] | None) -> bool:
    if not books:
        return False
    return any(isinstance(b, dict) and len(b) >= 2 for b in books)
