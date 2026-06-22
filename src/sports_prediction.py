"""
sports_prediction.py — Integration layer

本輪僅實作三件事，全部為「純決策邏輯」＋依賴注入，不接任何真實 API：
  1. 時間窗引擎     in_pregame_window()
  2. 賽事池刷新判定 ensure_pool()  （刷新 vs 讀快取分流 + slot guard）
  3. 賽前推播       run_pregame_push() （idempotency：send → mark）

設計：now / fetcher / pusher 皆由外部注入。
  • now    : tz-aware datetime（fake clock 可注入任意時間）
  • fetcher: Callable[[int hours_ahead], list[game dict]]；真實 Fetch 層後續接上
  • pusher : Callable[[game dict], bool]；真實 Notifier 後續接上

Fail-safe（決策補充）：fetcher 拋例外（含「兩把 KEY 都 429」）時，
不得 crash —— 記錄 error、沿用既有快取、跳過本輪，等下個 cron 週期。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Callable, Iterable

import data_manager as dm
import monte_carlo_engine
import notifier
import obs
import result_verifier
import verified_enrich
import market_lines
import score_model
import shadow_logger
from constants import (
    ENV_ODDS_API_KEY_1,
    ENV_TG_CHAT,
    ENV_TG_ADMIN_CHAT,
    ENV_TG_TOKEN,
    PENDING_STALE_HOURS,
    POOL_FETCH_HOURS_AHEAD,
    POOL_MAX_AGE_HOURS,
    PREGAME_WINDOW_MIN,
    EARLY_WINDOW_MIN,
    REFRESH_HOURS_TW,
    TW_TZ,
    dry_run_enabled,
)
from data_fetcher import AllKeysUnavailable, KeyManager, fetch_scores, fetch_upcoming_games

Fetcher = Callable[[int], list[dict]]
Pusher = Callable[[dict], bool]
Predictor = Callable[[dict], "dict | None"]
ScoresFetcher = Callable[[str, list], dict]
PostPusher = Callable[[str], bool]


# ── 工具 ──────────────────────────────────────────────
def _parse_dt(value) -> datetime:
    """解析為 tz-aware datetime；naive 時視為 TW，確保比較同時區。"""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW_TZ)
    return dt


# ── 1. 時間窗引擎 ─────────────────────────────────────
def in_pregame_window(game_start: datetime, now: datetime) -> bool:
    """賽前唯一規則：0 <= (game_start - now) <= PREGAME_WINDOW_MIN 分鐘。"""
    delta_min = (_parse_dt(game_start) - _parse_dt(now)).total_seconds() / 60.0
    return 0.0 <= delta_min <= PREGAME_WINDOW_MIN


def in_early_window(game_start: datetime, now: datetime) -> bool:
    """早期窗：PREGAME_WINDOW_MIN < (game_start - now) <= EARLY_WINDOW_MIN 分鐘。
    嚴格 > 40，故與 40 分最終窗互不重疊（同一 tick 不會同時觸發 early 與 final）。"""
    delta_min = (_parse_dt(game_start) - _parse_dt(now)).total_seconds() / 60.0
    return PREGAME_WINDOW_MIN < delta_min <= EARLY_WINDOW_MIN


# ── 2. 賽事池刷新判定 ─────────────────────────────────
def is_refresh_slot(now: datetime) -> bool:
    """now（TW）的小時是否落在刷新時刻 {0,6,12,18}。"""
    return _parse_dt(now).astimezone(TW_TZ).hour in REFRESH_HOURS_TW


def already_refreshed_this_slot(pool_updated_at: str, now: datetime) -> bool:
    """池是否已在「當前刷新時段（同日期 + 同小時）」刷過 —— slot guard 核心。"""
    if not pool_updated_at:
        return False
    try:
        last = _parse_dt(pool_updated_at).astimezone(TW_TZ)
    except (ValueError, TypeError):
        return False
    n = _parse_dt(now).astimezone(TW_TZ)
    return last.date() == n.date() and last.hour == n.hour


def ensure_pool(now: datetime, fetcher: Fetcher) -> list[dict]:
    """
    刷新時段且本時段尚未刷 → 抓未來 POOL_FETCH_HOURS_AHEAD 小時賽事並落盤；
    否則一律讀本地快取，不抓。回傳賽事清單。

    updated_at 以「邏輯 tick 時間 now」落盤，確保同一刷新小時內僅刷一次
    （即使 */15 在 12:00/12:15/12:30/12:45 連續觸發）。

    決策2（修正）：刷新失敗（兩把 key 都不可用 → AllKeysUnavailable）時，
    若本地有可用快取 → 退回沿用快取續推（早盤/賽前僅需已快取賠率，
    刷新為一天 4 次，快取至多數小時、用於 12 小時外的早盤完全可接受），
    不再跳過整輪、以免把「已快取、待推」的賽事一起漏掉；
    僅在完全無快取（冷啟動）時才向上傳遞給 tick() 跳過本輪。
    """
    pool = dm.load_pool()
    cached = pool.get("games", [])
    pu = pool.get("updated_at", "")
    age_h = None
    if pu:
        try:
            age_h = round((_parse_dt(now) - _parse_dt(pu)).total_seconds() / 3600.0, 1)
        except (ValueError, TypeError):
            age_h = None

    slot_due = is_refresh_slot(now) and not already_refreshed_this_slot(pu, now)
    # 自癒：漏刷 / 排程丟失 / 冷啟動 → 任何 tick 補刷一次（正常運作不會觸發）
    stale_due = (age_h is None) or (age_h >= POOL_MAX_AGE_HOURS)

    if slot_due or stale_due:
        reason = "slot" if slot_due else "stale"
        try:
            games = fetcher(POOL_FETCH_HOURS_AHEAD)
        except AllKeysUnavailable as exc:
            # 永久修正（根因）：刷新失敗（金鑰全不可用）時，若有可用快取 → 退回快取續推，
            # 不再跳過整個 tick；否則會連已快取、待推的賽事（如 Norway/Senegal 早盤）一起漏掉。
            # 僅在完全無快取（冷啟動）時才向上傳遞跳過。
            if cached:
                obs.warn("pool.refresh_failed_use_cache", err=str(exc),
                         count=len(cached), age_hours=age_h, reason=reason)
                return cached
            raise
        stamp = _parse_dt(now).astimezone(TW_TZ).isoformat(timespec="seconds")
        dm.save_pool(games, updated_at=stamp)
        obs.info("pool.refreshed", count=len(games), hours_ahead=POOL_FETCH_HOURS_AHEAD,
                 reason=reason, prev_age_hours=age_h)
        return games

    obs.info("pool.cache_hit", count=len(cached), updated_at=pu or None, age_hours=age_h)
    return cached


# ── 3. 賽前推播（idempotency）─────────────────────────
def run_pregame_push(
    now: datetime,
    games: Iterable[dict],
    pusher: Pusher,
    predictor: Predictor | None = None,
) -> list[str]:
    """
    對落在賽前窗、且尚未推過的場次推播。
    順序固定 send → 成功才 mark_pushed(gid,'pre')，保證跨 tick idempotency。
    回傳本輪實際推播的 game_id 清單。

    predictor（可選）：predict(game) -> dict|None。
      • dict → 附在 game['prediction']，進入推播流程。
      • None → No Prediction Available：不推、不 mark、輸出 SKIP_NO_PREDICTION，
               不視為錯誤、不影響其他比賽（idempotency 狀態不變）。
    """
    pushed: list[str] = []
    games = list(games)  # OBS：materialize 以利計數（fetcher 本就回 list，行為不變）
    obs.info("pregame.scan", games_count=len(games), window_min=PREGAME_WINDOW_MIN)
    for g in games:
        gid = str(g.get("id", "")).strip()
        if not gid:
            obs.warn("push.skip_no_id", game=g)
            continue
        try:
            start = _parse_dt(g["start_time"])
        except (KeyError, ValueError, TypeError) as exc:
            obs.warn("push.skip_bad_start", game_id=gid, err=str(exc))
            continue

        delta_min = round((_parse_dt(start) - _parse_dt(now)).total_seconds() / 60.0, 1)
        in_win = in_pregame_window(start, now)
        obs.info("pregame.window_check", game_id=gid, delta_min=delta_min,
                 in_window=in_win, window_min=PREGAME_WINDOW_MIN)
        if not in_win:
            continue
        if dm.is_pushed(gid, "pre"):
            obs.info("push.skip_already", game_id=gid)
            continue

        # Processing：無有效預測 → Safe Skip（不推、不 mark）
        if predictor is not None:
            pred = predictor(g)
            obs.info("pregame.predicted", game_id=gid, has_prediction=bool(pred),
                     has_best_pick=bool(pred and pred.get("best_pick")))
            if pred is None:
                print(f"[SKIP_NO_PREDICTION] game_id={gid} reason=no_valid_h2h_market", flush=True)
                obs.info("push.skip_no_prediction", game_id=gid)
                continue
            # STEP1/2：在 pipeline 計算模型（render 只消費，不生成）。
            # 無 totals → score=None → MC=None → renderer 隱藏該 section（不捏造）。
            _score = score_model.build_score_model(g)
            _mc = monte_carlo_engine.run_monte_carlo(_score)
            obs.info("model.built", game_id=gid, has_score_model=bool(_score),
                     has_mc=bool(_mc), model_type=(_score or {}).get("type"))
            pred = {**pred, "model_score": _score, "model_mc": _mc}
            # Truth 閘門（balanced）：有 +EV 標的(best_pick) 或 有可用模型(_score) 才發；
            # 兩者皆無 → skip（不送全 N/A 的空訊息）。renderer 不變，只在此 gate。
            if not pred.get("best_pick") and not _score:
                print(f"[SKIP_NO_ACTIONABLE] game_id={gid} reason=no_edge_no_model", flush=True)
                obs.info("push.skip_no_actionable", game_id=gid,
                         has_best_pick=bool(pred.get("best_pick")), has_model=bool(_score))
                continue
            g = {**g, "prediction": pred}

        try:
            ok = pusher(g)
        except Exception as exc:  # noqa: BLE001 — 推播失敗不可崩
            obs.error("push.failed", game_id=gid, err=str(exc))
            continue

        if ok:
            dm.mark_pushed(gid, "pre")  # send → mark
            # C-1：pre-push 成功且有 prediction → 落盤 snapshot（pending 驗證）。
            # DRY_RUN 也存：在真實送出前即開始累積 truth-loop 對照資料。
            if "prediction" in g:
                try:
                    g["prediction"]["market"] = market_lines.extract_market(g)
                except Exception:  # noqa: BLE001 — 盤口抽取失敗不可中斷推播
                    g["prediction"].setdefault("market", None)
                g["prediction"]["phase"] = "pre_match_40m"  # V4：階段追蹤（純標記）
                dm.save_prediction(gid, g["prediction"])
            shadow_logger.log_prediction(g)  # V3.2 影子記錄（內部 guarded，不影響推播）
            pushed.append(gid)
            obs.info("push.sent", game_id=gid)
        else:
            obs.warn("push.not_sent", game_id=gid)
    return pushed


# ── 早期推播（V3.1 additive：賽前 12h，與 pre 完全獨立）──────
def run_early_push(
    now: datetime,
    games: Iterable[dict],
    pusher: Pusher,
    predictor: Predictor | None = None,
) -> list[str]:
    """早期推播（賽前約 12 小時）。純 additive：不改 run_pregame_push、不改 renderer。
    觸發：in_early_window（40 < delta <= 720）且該場未推過 phase 'early'。
    idempotency：send → mark_pushed(gid,'early')；phase 'early' 與 'pre'/'post' 互不干擾。
    V3.1-fix：early 推播成功後也 dm.save_prediction → 進入賽後驗證池（fallback）；
    若稍後 40m 'pre' 有跑會覆寫成更近賽的快照。解決「40m 窗漏 → 賽後無素材」。
    """
    pushed: list[str] = []
    games = list(games)
    obs.info("early.scan", games_count=len(games), early_window_min=EARLY_WINDOW_MIN)
    for g in games:
        gid = str(g.get("id", "")).strip()
        if not gid:
            continue
        try:
            start = _parse_dt(g["start_time"])
        except (KeyError, ValueError, TypeError) as exc:
            obs.warn("early.skip_bad_start", game_id=gid, err=str(exc))
            continue

        delta_min = round((_parse_dt(start) - _parse_dt(now)).total_seconds() / 60.0, 1)
        in_win = in_early_window(start, now)
        obs.info("early.window_check", game_id=gid, delta_min=delta_min,
                 in_window=in_win, early_window_min=EARLY_WINDOW_MIN)
        if not in_win:
            continue
        if dm.is_pushed(gid, "early"):
            obs.info("early.skip_already", game_id=gid)
            continue

        if predictor is not None:
            pred = predictor(g)
            if pred is None:
                obs.info("early.skip_no_prediction", game_id=gid)
                continue
            _score = score_model.build_score_model(g)
            _mc = monte_carlo_engine.run_monte_carlo(_score)
            pred = {**pred, "model_score": _score, "model_mc": _mc}
            if not pred.get("best_pick") and not _score:
                obs.info("early.skip_no_actionable", game_id=gid)
                continue
            g = {**g, "prediction": pred}

        try:
            ok = pusher(g)
        except Exception as exc:  # noqa: BLE001 — 推播失敗不可崩
            obs.error("early.push_failed", game_id=gid, err=str(exc))
            continue

        if ok:
            dm.mark_pushed(gid, "early")  # send → mark
            # V3.1-fix：early 也落盤 snapshot → 賽後驗證不再依賴 40m 窗命中。
            # idempotent：之後 40m final push 若有跑，會用更新（更近賽）的快照覆寫同一 game_id。
            if "prediction" in g:
                try:
                    g["prediction"]["market"] = market_lines.extract_market(g)
                except Exception:  # noqa: BLE001 — 盤口抽取失敗不可中斷推播
                    g["prediction"].setdefault("market", None)
                g["prediction"]["phase"] = "early_12h"  # V4：階段追蹤（純標記）
                dm.save_prediction(gid, g["prediction"])
            pushed.append(gid)
            obs.info("early.sent", game_id=gid)
        else:
            obs.warn("early.not_sent", game_id=gid)
    return pushed


# ── 賽後驗證（C-4，與 pre 路徑獨立 fail-safe）────────
# 各運動「預估最早完賽時間」（分鐘）：開賽後未達此時長前不抓賽果（賽中 completed 不可能為真）。
# 保守取偏短值，避免延誤抓到提早結束的賽果；達此時間後才每 tick 輪詢直到完賽。
_POSTGAME_MIN_DURATION_MIN = {"MLB": 150, "NBA": 130, "FIFA": 100}

# 賽後輪詢「指數退避」：自 start+min_dur 起，第 n 次輪詢的「額外累積延遲」（分鐘）。
# 例：FIFA 第0次=start+100，第1次=+30→130，第2次=+60→190，第3次=+120→310；
# 超過表尾後每次再 +120。避免卡住的 pending 場每 tick 狂抓 scores、燒 API 配額。
_POSTGAME_BACKOFF_CUM_MIN = [0, 30, 90, 210]


def _postgame_backoff_extra_min(attempts: int) -> int:
    if attempts < len(_POSTGAME_BACKOFF_CUM_MIN):
        return _POSTGAME_BACKOFF_CUM_MIN[attempts]
    return _POSTGAME_BACKOFF_CUM_MIN[-1] + 120 * (attempts - len(_POSTGAME_BACKOFF_CUM_MIN) + 1)


def run_postgame_verify(now: datetime, scores_fetcher: ScoresFetcher,
                        post_pusher: PostPusher, verifier=None) -> list[str]:
    """
    pending snapshots → 抓賽果 → verify → 推賽後 → mark('post') + 封存 verified-history + 移除 pending。
      • 觸發：completed==true 且未驗（D-C3 寬鬆，不卡嚴格 60 分窗）。
      • 過期驅逐（TD11）：start_time 早於 PENDING_STALE_HOURS 仍未驗 → 撈不回賽果，丟棄。
      • scores 抓取 AllKeysUnavailable → 只跳過該運動的 post，pre 不受影響。
    """
    verify = verifier or result_verifier.verify
    preds = dm.load_predictions()
    if not preds:
        return []

    stale_cutoff = now - timedelta(hours=PENDING_STALE_HOURS)
    by_sport: dict[str, list[str]] = {}
    for gid, snap in list(preds.items()):
        pred = snap.get("prediction", {})
        try:
            start = datetime.fromisoformat(pred["start_time"])
        except (KeyError, ValueError, TypeError):
            start = None
        if start is not None and start > now:
            continue  # 尚未開賽 → 不抓
        sport = pred.get("sport")
        # 配額節流 + 指數退避：未到「預估完賽 + 退避延遲」前不抓賽果（賽中/兩次輪詢間 → 不打 API）。
        _min_dur = _POSTGAME_MIN_DURATION_MIN.get(str(sport).upper(), 120)
        _attempts = int(snap.get("post_attempts", 0))
        _earliest_min = _min_dur + _postgame_backoff_extra_min(_attempts)
        if start is not None and now < start + timedelta(minutes=_earliest_min):
            obs.info("postgame.backoff_skip_fetch", game_id=gid, sport=sport,
                     attempts=_attempts, earliest_min=_earliest_min)
            continue
        if start is not None and start < stale_cutoff and not dm.is_pushed(gid, "post"):
            dm.remove_prediction(gid)  # TD11 過期驅逐
            obs.warn("postgame.evict_stale", game_id=gid)
            continue
        if sport:
            by_sport.setdefault(sport, []).append(gid)

    verified: list[str] = []
    for sport, ids in by_sport.items():
        try:
            scores = scores_fetcher(sport, ids)
        except AllKeysUnavailable as exc:
            obs.error("postgame.skip_all_keys_unavailable", sport=sport, err=str(exc))
            continue  # 獨立 fail-safe：只跳此運動 post
        for gid in ids:
            pred = (preds.get(gid) or {}).get("prediction", {})
            r = scores.get(gid)
            if r is None:
                obs.info("postgame.no_result", game_id=gid, sport=sport)  # API 未返回此場賽果 → 等
                dm.bump_post_attempts(gid)  # 退避：拉長下次輪詢間隔
                continue
            if not r.get("completed"):
                obs.info("postgame.not_completed", game_id=gid, sport=sport)  # 尚未完賽 → 等下個 tick
                dm.bump_post_attempts(gid)  # 退避：拉長下次輪詢間隔
                continue
            if dm.is_pushed(gid, "post"):
                dm.remove_prediction(gid)  # idempotent 清理
                continue
            v = verify(pred, r)
            if v is None:
                obs.warn("postgame.verify_none", game_id=gid, sport=sport)  # 完賽但缺分數 → 無法驗證
                continue
            try:
                ok = post_pusher(notifier.render_postgame_eval(v, pred, r))
            except Exception as exc:  # noqa: BLE001 — 推播失敗不可崩
                obs.error("postgame.push_failed", game_id=gid, err=str(exc))
                continue
            if ok:
                dm.mark_pushed(gid, "post")  # send → mark（idempotent）
                try:
                    _enrich = verified_enrich.enrich(pred, r, sport)
                except Exception:  # noqa: BLE001 — 回饋擴充失敗不可影響推播/封存
                    _enrich = {}
                dm.append_verified({**v, "sport": sport, **_enrich})
                dm.remove_prediction(gid)
                shadow_logger.log_result(gid, r, v, sport)  # V3.2 影子結果（guarded）
                verified.append(gid)
                obs.info("postgame.verified", game_id=gid)
    return verified


# ── 單次 cron tick 編排 ───────────────────────────────
def tick(now: datetime, fetcher: Fetcher, pusher: Pusher,
         predictor: Predictor | None = None, *,
         scores_fetcher: ScoresFetcher | None = None,
         post_pusher: PostPusher | None = None,
         early_pusher: Pusher | None = None) -> list[str]:
    """
    確保賽事池 → 賽前推播 →（若配置）賽後驗證。回傳本輪賽前推播的 game_id。

    pre / post 兩條路徑獨立 fail-safe：
      • pre 的 fetcher AllKeysUnavailable → 捕捉、pushed=[]，但仍嘗試 post（post 內部自有跳過）。
      • post 的 scores AllKeysUnavailable → 在 run_postgame_verify 內逐運動跳過，不影響 pre。
    """
    try:
        games = ensure_pool(now, fetcher)
    except AllKeysUnavailable as exc:
        obs.error("tick.skip_all_keys_unavailable", err=str(exc))
        games = None
    pushed = run_pregame_push(now, games, pusher, predictor=predictor) if games is not None else []

    if early_pusher is not None and games is not None:
        run_early_push(now, games, early_pusher, predictor=predictor)

    if scores_fetcher is not None and post_pusher is not None:
        run_postgame_verify(now, scores_fetcher, post_pusher)
    return pushed


# ── TD2：啟動時 secrets fail-fast（config validation）─
def validate_secrets(dry_run: bool) -> None:
    """
    缺必填 secrets → fail-fast（SystemExit 非 0），不可只 log skip。
    ODDS_API_KEY_1 永遠必填；TG_TOKEN/TG_CHAT 僅在 DRY_RUN 關閉時必填。
    註：此為「設定缺失」檢查，與執行期「key 有設但耗盡 → AllKeysUnavailable 跳過」不同。
    """
    missing = []
    if not os.getenv(ENV_ODDS_API_KEY_1):
        missing.append(ENV_ODDS_API_KEY_1)
    if not dry_run:
        for env in (ENV_TG_TOKEN, ENV_TG_CHAT):
            if not os.getenv(env):
                missing.append(env)
    if missing:
        obs.error("config.missing_secrets", missing=missing, dry_run=dry_run)
        raise SystemExit("Missing required secrets: " + ", ".join(missing))


# ── CLI / Runtime entry ───────────────────────────────
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="sports-prediction-bot runtime")
    parser.add_argument("command", nargs="?", default="push", choices=["push"])
    parser.parse_args(argv)

    import prediction_engine

    dry_run = dry_run_enabled()
    validate_secrets(dry_run)  # TD2 fail-fast（在任何 fetch / 網路前）

    # 完整 pipeline：fetch → pool → window → idempotency → predict → output → 賽後驗證
    now = datetime.now(TW_TZ)
    key_manager = KeyManager.from_env(now_fn=lambda: now)

    def fetcher(hours_ahead: int) -> list[dict]:
        return fetch_upcoming_games(hours_ahead, key_manager=key_manager, now_fn=lambda: now)

    def scores_fetcher(sport: str, event_ids: list) -> dict:
        return fetch_scores(sport, event_ids, key_manager=key_manager, now_fn=lambda: now)

    tg = {"token": os.getenv(ENV_TG_TOKEN), "chat": os.getenv(ENV_TG_CHAT)}
    pusher = notifier.make_pusher(dry_run, renderer=notifier.render_pregame_lite, **tg)
    early_pusher = notifier.make_pusher(dry_run, renderer=notifier.render_pregame_early, **tg)
    post_pusher = notifier.make_postgame_pusher(dry_run, **tg)
    pushed = tick(now, fetcher, pusher, predictor=prediction_engine.predict,
                  scores_fetcher=scores_fetcher, post_pusher=post_pusher,
                  early_pusher=early_pusher)
    obs.info("runtime.tick_done", pushed=len(pushed), dry_run=dry_run)

    # ── 每日戰報（addon layer，guarded）取代舊 WorldCup 批次 ──
    # 觸發：當天賽事全驗證完 + 距最近驗證 ≥30 分；每日 idempotent（flags）。
    # 獨立於 match push / tick 核心：只讀 verified_history + weekly_games。
    try:
        import daily_report
        daily_pusher = notifier.make_postgame_pusher(dry_run, **tg)
        daily_report.run_daily_report(daily_pusher, now=now)
    except Exception as exc:  # noqa: BLE001 — addon 不得影響核心
        obs.error("daily_report.error", err=str(exc))

    # ── 冠軍 + 個人獎項 futures 推播（addon layer，guarded，每日 1 次）──
    # 獨立於 match push / tick 核心：build_awards 走 registry→fetch→validate（market 唯一真相）。
    try:
        import awards_push
        aw_pusher = notifier.make_postgame_pusher(dry_run, **tg)
        awards_push.run_awards_push(aw_pusher, now=now)
    except Exception as exc:  # noqa: BLE001 — addon 不得影響核心
        obs.error("awards.error", err=str(exc))

    # ── 漏推對帳告警（Phase1-E；addon, guarded, opt-in）──
    # 偵測「賽前(12h/40m 皆漏) / 賽後(過期未推)」→ 發 admin 告警；每場每類 idempotent。
    # 純讀 state，不改任何推播/驗證邏輯；未設 TG_ADMIN_CHAT → 完全 no-op。
    try:
        admin_chat = os.getenv(ENV_TG_ADMIN_CHAT)
        if admin_chat:
            import push_reconcile
            admin_sender = notifier.make_postgame_pusher(
                dry_run, token=os.getenv(ENV_TG_TOKEN), chat=admin_chat)
            push_reconcile.run_push_reconcile(admin_sender, now=now)
    except Exception as exc:  # noqa: BLE001 — addon 不得影響核心
        obs.error("push_reconcile.error", err=str(exc))

    # ── Production Readiness Gate（唯讀；只報告，不影響核心）──
    try:
        from release_gate import is_production_ready
        status = is_production_ready()
        if not status["ready"]:
            print("[BLOCKED] system not production ready")
            print(status)
    except Exception as exc:  # noqa: BLE001 — gate 不得影響核心
        obs.error("release_gate.error", err=str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
