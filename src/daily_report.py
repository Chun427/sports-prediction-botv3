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
_SPORT_ORDER = ["FIFA", "MLB", "NBA"]
_SPORT_LABEL = {"FIFA": "⚽ 足球", "MLB": "⚾ 棒球", "NBA": "🏀 籃球"}
_FOOTER = "📡 數據來源：系統統計"


def _parse(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _istrue(v) -> bool:
    return str(v).strip().lower() == "true"


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
    out = [
        f"📅 今日戰報 {date_str}", _DIV, "🎯 本日總命中",
        _line("獨贏", *_rate(today_rows, "moneyline_hit")),
        _line("讓分", *_rate(today_rows, "ah_hit")),
        _line("大小", *_rate(today_rows, "ou_hit")),
    ]
    by_sport: dict[str, list] = {}
    for r in today_rows:
        by_sport.setdefault((r.get("sport") or "").upper(), []).append(r)

    for sp in _SPORT_ORDER:
        rows = by_sport.get(sp)
        if not rows:
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


def run_daily_report(pusher, *, now=None, games=None, verified=None) -> str | None:
    """觸發判定 + 推播。回傳已送字串；條件未滿足／當日已推 → None。"""
    now = now or _dt.datetime.now(TW_TZ)
    today = now.astimezone(TW_TZ).date()
    gid = f"daily-{today:%Y%m%d}"
    if dm.is_pushed(gid, _STAGE):
        return None

    if games is None:
        games = dm._read_json("weekly_games.json", {"games": []}).get("games", [])
    if verified is None:
        verified = dm.read_verified()

    today_games = [g for g in games
                   if (_parse(g.get("start_time")) and
                       _parse(g.get("start_time")).astimezone(TW_TZ).date() == today)]
    if not today_games:
        return None

    today_ids = {g.get("id") for g in today_games}
    verified_ids = {r.get("game_id") for r in verified}

    # 仍有「已開賽、未驗證、非過期」的場次 → 還沒打完，等
    for g in today_games:
        st = _parse(g.get("start_time"))
        if not st:
            continue
        if st <= now and g.get("id") not in verified_ids and (now - st) <= _dt.timedelta(hours=_STALE_HOURS):
            obs.info("daily.skip_pending", game_id=g.get("id"), sport=g.get("sport"))
            return None

    today_rows = [r for r in verified if r.get("game_id") in today_ids]
    if not today_rows:
        return None

    # 距最近一次驗證需 ≥ 30 分
    last = None
    for r in today_rows:
        d = _parse(r.get("verified_at"))
        if d and (last is None or d > last):
            last = d
    if last is not None and (now - last) < _dt.timedelta(minutes=_WAIT_MIN):
        obs.info("daily.skip_wait30", last_verified=last.isoformat())
        return None

    msg = render_daily(now, today_rows)
    pusher(msg)
    dm.mark_pushed(gid, _STAGE)
    obs.info("daily.sent", date=gid, games=len(today_rows))
    return msg
