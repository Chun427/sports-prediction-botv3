"""near_match_refresh.py — 近賽選擇性盤口刷新（additive / flagged / guarded）。

需求：40 分鐘賽前窗，只對「即將推播的那幾場」重抓最新 odds，再讓現有模型自然重算。
明確不是整池刷新（整池 48h／數百場），而是短窗（2h）只更新目標 game_id 的 odds。

嚴格規格（依監督要求）：
- Feature Flag：ENABLE_NEAR_MATCH_REFRESH，可一鍵關閉，關閉後行為完全等同改動前。
- Near Match Only：只更新傳入的 targets（即將推播場），不碰其他賽事。
- Guard / Fallback：抓取失敗或該場無新盤 → 沿用 pool 原 odds，絕不 raise、絕不中斷推播。
- Logger：逐場記錄 old/new/changed，事後可稽核「40m 到底有沒有抓到新盤」。
- 不碰：prediction_engine / notifier / monte_carlo / score_model / postgame / collector / verified_history。
  本模組只就地更新 game dict 的 odds 欄位；模型由現有 pipeline 重算（不在此處）。
"""
from __future__ import annotations

import obs

# ── Feature Flag（API 快爆時設 False 即整功能關閉，其餘完全不受影響）──
ENABLE_NEAR_MATCH_REFRESH = True

# 近賽短窗（小時）：只抓未來這麼短時間內即將開賽的場 → 量極小，非整池 48h
NEAR_REFRESH_HOURS_AHEAD = 2

_ODDS_FIELDS = ("odds_h2h", "odds_totals", "odds_spreads")


def _h2h_consensus(books) -> tuple:
    """各 book 的 home/away 平均（log 用）；無資料 → (None, None)。"""
    bs = books or []
    def avg(k):
        v = [b.get(k) for b in bs if isinstance(b.get(k), (int, float))]
        return round(sum(v) / len(v), 3) if v else None
    return avg("home"), avg("away")


def _apply(game: dict, fresh: dict) -> None:
    """就地把 fresh 的 odds 欄位覆寫到 game（只動 odds），並記錄 old/new/changed。"""
    old_h, old_a = _h2h_consensus(game.get("odds_h2h"))
    new_h, new_a = _h2h_consensus(fresh.get("odds_h2h"))
    changed = (old_h, old_a) != (new_h, new_a)
    obs.info("near_refresh.applied", game_id=game.get("id"),
             old_home=old_h, new_home=new_h, old_away=old_a, new_away=new_a,
             changed=changed)
    for f in _ODDS_FIELDS:
        if f in fresh:
            game[f] = fresh[f]  # 就地更新（同物件參照，後續 pipeline 自然吃到新 odds）


def refresh(targets: list[dict], fetcher, *, now=None) -> None:
    """對 targets（即將推播場）重抓最新 odds 並就地更新。

    fetcher(hours_ahead) -> list[dict]：沿用 ensure_pool 的同一介面（短窗抓近賽）。
    任何失敗 → 沿用 pool（warn，不 raise）。回傳 None（就地更新 targets）。
    """
    if not ENABLE_NEAR_MATCH_REFRESH or not targets:
        return
    target_ids = {g.get("id") for g in targets if g.get("id")}
    if not target_ids:
        return
    try:
        fresh_list = fetcher(NEAR_REFRESH_HOURS_AHEAD)  # 短窗 → 小量
    except Exception as exc:  # noqa: BLE001 — 刷新失敗不可影響推播
        obs.warn("near_refresh.fetch_failed_use_pool", err=str(exc), n=len(target_ids))
        return  # Fallback：用 pool 原 odds
    fresh_by_id = {g.get("id"): g for g in (fresh_list or [])}
    obs.info("near_refresh.scan", targets=len(target_ids), fresh_returned=len(fresh_by_id))
    for g in targets:
        nf = fresh_by_id.get(g.get("id"))
        if not nf:
            obs.info("near_refresh.no_fresh_use_pool", game_id=g.get("id"))
            continue  # 該場沒回新盤 → 沿用 pool
        try:
            _apply(g, nf)
        except Exception as exc:  # noqa: BLE001 — 單場更新失敗不影響其他場/推播
            obs.warn("near_refresh.apply_failed", game_id=g.get("id"), err=str(exc))
