"""daily_report.py — 每日戰報（取代舊 WorldCup 批次）。

addon layer：不碰 match push / tick 核心（與舊 worldcup_batch 同類，guarded 呼叫）。

觸發＝「最後一場 +30 分」近似版：
  • 當天（台灣日期）所有「已開賽且非過期」的賽事都已驗證，
  • 且距最近一次驗證 ≥ 30 分鐘，
  • 每日只推一次（flags：daily-YYYYMMDD）。
  （無法事先得知哪場是最後一場，故以「全驗證完 + 靜置 30 分」近似；逾 12h 仍未驗證視為過期，
    避免單場卡住整日不推。）

內容：本日總命中（獨贏/讓分/大小）＋ 各球類（🎯整體命中率＋各盤口；比分僅足球）。
誠實：純讀 verified_history + weekly_games；無有效盤口顯示「—」，不捏造。
"""
from __future__ import annotations

import datetime as _dt

import data_manager as dm
import obs
from constants import TW_TZ

_STAGE = "daily"
_DIV = "━━━━━━━━"
_WAIT_MIN = 30        # 最近一次驗證後需靜置（分）
_STALE_HOURS = 12     # 開賽逾此時數仍未驗證 → 視為過期，不再等待
_DEADLINE_TW = (23, 35)  # （保留：舊常數，已不作為主要保險）
_SAFETY_TW = (23, 30)    # 同日最後保險：TW 此刻後仍未送 → 強制送已驗證真實場（搭配跨午夜補送）
_SPORT_ORDER = ["FIFA", "MLB", "NBA"]
_SPORT_LABEL = {"FIFA": "⚽ 足球", "MLB": "⚾ 棒球", "NBA": "🏀 籃球"}
_FOOTER = "📡 數據來源：系統統計"


def _parse(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _istrue(v) -> bool:
    # 同時支援 True/False 與 1/0 兩種編碼（scoreline_hit 用 1/0，其餘用 True/False）
    return str(v).strip().lower() in ("true", "1")


def _has(v) -> bool:
    return str(v).strip().lower() not in ("", "none")


def _rate(rows: list[dict], col: str) -> tuple[int, int]:
    vals = [r.get(col) for r in rows if _has(r.get(col))]
    return sum(1 for v in vals if _istrue(v)), len(vals)


def _line(label: str, hit: int, tot: int) -> str:
    pct = f"（{round(hit / tot * 100)}%）" if tot else "（—）"
    return f"{label} {hit}/{tot}{pct}"


def render_daily(now, today_rows: list[dict]) -> str:
    """today_rows = 當天已驗證的 verified_history 列（dict）。"""
    date_str = now.astimezone(TW_TZ).strftime("%m/%d")
    # 本日總命中：各市場結果並列；比分僅 FIFA（MLB/NBA 無正確比分市場）。
    # 📊 總計 = 所有市場 numerator/denominator 加總（各市場分母可不同，比分分母僅 FIFA）。
    _ml = _rate(today_rows, "moneyline_hit")
    _ah = _rate(today_rows, "ah_hit")
    _ou = _rate(today_rows, "ou_hit")
    _fifa_rows = [r for r in today_rows if (r.get("sport") or "").upper() == "FIFA"]
    _sc_all = _rate(_fifa_rows, "scoreline_hit")
    _tot_h = _ml[0] + _ah[0] + _ou[0] + _sc_all[0]
    _tot_n = _ml[1] + _ah[1] + _ou[1] + _sc_all[1]
    out = [
        f"📅 今日戰報 {date_str}", _DIV,
        _line("📊 本日總命中", _tot_h, _tot_n),
        _line("獨贏", *_ml),
        _line("讓分", *_ah),
        _line("大小", *_ou),
    ]
    if _sc_all[1] > 0:                              # 當天有 FIFA 比分資料才顯示
        out.append(_line("比分", *_sc_all))
    by_sport: dict[str, list] = {}
    for r in today_rows:
        by_sport.setdefault((r.get("sport") or "").upper(), []).append(r)

    for sp in _SPORT_ORDER:
        rows = by_sport.get(sp)
        if not rows:
            out += [_DIV, f"{_SPORT_LABEL[sp]}（0場）", "無已驗證資料"]
            continue
        ml, ah, ou, sc = (_rate(rows, "moneyline_hit"), _rate(rows, "ah_hit"),
                          _rate(rows, "ou_hit"), _rate(rows, "scoreline_hit"))
        parts = [ml, ah, ou] + ([sc] if sp == "FIFA" else [])   # 整體＝各盤口加總（足球含比分）
        oh, ot = sum(h for h, _ in parts), sum(t for _, t in parts)
        out += [_DIV, f"{_SPORT_LABEL[sp]}（{len(rows)}場）",
                _line("🎯 整體命中率", oh, ot),
                _line("獨贏", *ml), _line("讓分", *ah), _line("大小", *ou)]
        if sp == "FIFA":
            out.append(_line("比分", *sc))

    out += [_DIV, _FOOTER]
    return "\n".join(out)


def _try_send_day(day, now, games, verified, pusher, *, allow_force):
    """嘗試送某一天的戰報（單一真實來源邏輯）。回傳 msg 或 None。

    all_settled（當日每場皆已驗證或逾 12h 過期）→ 主路徑（+30 分靜置）送。
    未 all_settled 時：allow_force=True → 用「目前已驗證的真實場」強制送；否則等。
    只送 verified_history 真實場，無資料不送（不捏造）。冪等：當日已送 → 不重送。
    """
    gid = f"daily-{day:%Y%m%d}"
    if dm.is_pushed(gid, _STAGE):
        return None
    # ── 真實來源 = verified_history（永久），依「驗證時間的 TW 日期」取當天真實場。
    #    不再用 weekly_games 的 game_id 反查（那是 48h 滾動快取，舊日期會滾掉→補送失效）。──
    day_rows = [r for r in verified
                if (_parse(r.get("verified_at")) and
                    _parse(r.get("verified_at")).astimezone(TW_TZ).date() == day)]
    # day_games 僅用於「今日是否全部打完」判定（仍在池內的當日場）；昨日多半已滾出 → 視為已 settled。
    day_games = [g for g in games
                 if (_parse(g.get("start_time")) and
                     _parse(g.get("start_time")).astimezone(TW_TZ).date() == day)]
    if not day_rows and not day_games:
        return None  # 該日完全無資料（無真實場可送，也無候選）
    verified_ids = {r.get("game_id") for r in verified}

    # all_settled = 每場皆「已驗證」或「開賽逾 12h（過期）」；無 day_games（已滾出池）→ 預設 True
    all_settled = True
    for g in day_games:
        st = _parse(g.get("start_time"))
        if not st:
            continue
        stale = (now - st) > _dt.timedelta(hours=_STALE_HOURS)
        if g.get("id") not in verified_ids and not stale:
            all_settled = False
            break

    if all_settled:
        # ── 主路徑：最後一場完成 → 靜置 30 分 → 送 ──
        if not day_rows:
            return None
        last = None
        for r in day_rows:
            d = _parse(r.get("verified_at"))
            if d and (last is None or d > last):
                last = d
        if last is not None and (now - last) < _dt.timedelta(minutes=_WAIT_MIN):
            obs.info("daily.skip_wait30", date=gid, last_verified=last.isoformat())
            return None
    else:
        # ── 尚未全部完成 ──
        if not allow_force:
            obs.info("daily.skip_pending", date=gid)
            return None
        if not day_rows:
            obs.info("daily.force_no_data", date=gid)
            return None
        obs.info("daily.force_send", date=gid, verified_games=len(day_rows))

    msg = render_daily(now, day_rows)
    if pusher(msg) is False:  # 送出失敗 → 不 mark → 下一 tick 重送（Never-Miss）
        obs.warn("daily.push_failed", date=gid)
        return None
    dm.mark_pushed(gid, _STAGE)
    obs.info("daily.sent", date=gid, games=len(day_rows))
    return msg


def run_daily_report(pusher, *, now=None, games=None, verified=None) -> str | None:
    """每日戰報觸發。Never-Miss 三層：

    1. 主路徑：當日最後一場完成 + 靜置 30 分 → 送（最適時間，不靠固定時刻）。
    2. 同日保險：TW 23:30 後仍未送 → 強制送當日已驗證真實場（極端情況最後一道）。
    3. 跨午夜補送：隔日 tick 發現昨日未送且有已驗證場 → 補送昨日完整結果（真正 never-miss，
       不依賴狹窄時間窗，免疫 GitHub Actions tick 抖動）。
    """
    now = now or _dt.datetime.now(TW_TZ)
    if games is None:
        games = dm._read_json("weekly_games.json", {"games": []}).get("games", [])
    if verified is None:
        verified = dm.read_verified()

    tw_now = now.astimezone(TW_TZ)
    today = tw_now.date()
    yesterday = today - _dt.timedelta(days=1)
    past_safety = (tw_now.hour, tw_now.minute) >= _SAFETY_TW

    # 今日：主路徑（all_settled+30分），或 23:30 後同日保險強制送
    sent = _try_send_day(today, now, games, verified, pusher, allow_force=past_safety)
    if sent:
        return sent
    # 跨午夜補送：昨日若還沒送（同日窗口被 tick 抖動錯過）→ 用昨日完整已驗證結果補送
    return _try_send_day(yesterday, now, games, verified, pusher, allow_force=True)
