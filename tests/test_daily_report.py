"""daily_report 測試 — 觸發邏輯 + render（不打 API、monkeypatch flags、注入 now/games/verified）。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import daily_report as dr  # noqa: E402
from constants import TW_TZ  # noqa: E402


def _flags(monkeypatch):
    store = set()
    monkeypatch.setattr(dr.dm, "is_pushed", lambda g, s: (g, s) in store)
    monkeypatch.setattr(dr.dm, "mark_pushed", lambda g, s: store.add((g, s)))
    return store


def _now():
    return dt.datetime(2026, 6, 18, 15, 0, tzinfo=TW_TZ)


def test_render_format_per_sport_and_na():
    rows = [
        {"sport": "FIFA", "game_id": "f1", "moneyline_hit": "true", "ah_hit": "true",
         "ou_hit": "false", "scoreline_hit": "true"},
        {"sport": "FIFA", "game_id": "f2", "moneyline_hit": "true", "ah_hit": "false",
         "ou_hit": "true", "scoreline_hit": "false"},
        {"sport": "MLB", "game_id": "m1", "moneyline_hit": "true", "ah_hit": "",
         "ou_hit": "", "scoreline_hit": ""},
    ]
    msg = dr.render_daily(_now(), rows)
    assert "📅 今日戰報 06/18" in msg
    assert "📊 本日總命中 6/9" in msg              # 總計＝各市場加總（比分僅FIFA：3+2+2+2 / ...）
    assert "⚽ 足球（2場）" in msg and "⚾ 棒球（1場）" in msg
    assert "🏀 籃球（0場）" in msg and "無已驗證資料" in msg  # 0場顯示提示
    assert "🎯 整體命中率" in msg
    assert "比分 1/2（50%）" in msg          # 足球有比分段
    assert "大小 0/0（—）" in msg            # MLB 無 OU 資料 → 誠實 N/A，不捏造
    assert "系統統計" in msg


def test_pushes_when_all_verified_and_30min(monkeypatch):
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"}]
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T12:00:00+08:00",
                 "moneyline_hit": "true", "ah_hit": "true", "ou_hit": "", "scoreline_hit": ""}]
    sent = []
    msg = dr.run_daily_report(lambda m: sent.append(m), now=_now(), games=games, verified=verified)
    assert msg and len(sent) == 1 and "今日戰報" in msg


def test_skips_when_a_game_still_pending(monkeypatch):
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"},
             {"id": "g2", "sport": "MLB", "start_time": "2026-06-18T14:00:00+08:00"}]  # 開賽1h、未驗證
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T12:00:00+08:00",
                 "moneyline_hit": "true"}]
    sent = []
    msg = dr.run_daily_report(lambda m: sent.append(m), now=_now(), games=games, verified=verified)
    assert msg is None and sent == []


def test_skips_within_30min_of_last_verify(monkeypatch):
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"}]
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T14:45:00+08:00",
                 "moneyline_hit": "true"}]  # 15 分鐘前
    sent = []
    msg = dr.run_daily_report(lambda m: sent.append(m), now=_now(), games=games, verified=verified)
    assert msg is None


def test_idempotent_once_per_day(monkeypatch):
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"}]
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T12:00:00+08:00",
                 "moneyline_hit": "true"}]
    sent = []
    a = dr.run_daily_report(lambda m: sent.append(m), now=_now(), games=games, verified=verified)
    b = dr.run_daily_report(lambda m: sent.append(m), now=_now(), games=games, verified=verified)
    assert a and b is None and len(sent) == 1


def test_stale_unverified_does_not_block(monkeypatch):
    _flags(monkeypatch)
    now = dt.datetime(2026, 6, 18, 23, 0, tzinfo=TW_TZ)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T08:00:00+08:00"},
             {"id": "g2", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"}]  # 14h前、永遠沒驗證
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T11:00:00+08:00",
                 "moneyline_hit": "true"}]
    sent = []
    msg = dr.run_daily_report(lambda m: sent.append(m), now=now, games=games, verified=verified)
    assert msg and len(sent) == 1     # g2 過期 → 不阻擋 → 仍推 g1


def test_no_today_games(monkeypatch):
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-10T09:00:00+08:00"}]  # 非今日
    msg = dr.run_daily_report(lambda m: None, now=_now(), games=games, verified=[])
    assert msg is None


def test_daily_not_marked_when_send_fails_then_retries(monkeypatch):
    """Never-Miss：daily 送出明確失敗(False) → 不 mark → 下一 tick 可重送，成功才 mark。"""
    store = _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"}]
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T12:00:00+08:00",
                 "moneyline_hit": "true", "ah_hit": "true", "ou_hit": "", "scoreline_hit": ""}]
    # 第一次：送出失敗(False) → 不 mark
    sent = []
    r1 = dr.run_daily_report(lambda m: (sent.append(m), False)[1],
                             now=_now(), games=games, verified=verified)
    assert r1 is None and len(sent) == 1
    assert not any(s == dr._STAGE for (_g, s) in store)  # 未 mark → 可重送
    # 下一 tick：送出成功(True) → mark
    ok_sent = []
    r2 = dr.run_daily_report(lambda m: (ok_sent.append(m), True)[1],
                             now=_now(), games=games, verified=verified)
    assert r2 and len(ok_sent) == 1
    assert any(s == dr._STAGE for (_g, s) in store)  # 成功才 mark


def test_daily_waits_for_not_yet_started_today_game(monkeypatch):
    """完成度：今日尚有未開賽/未驗證的場 → 不可提前送（否則晚場會被 idempotent 永久鎖掉）。"""
    _flags(monkeypatch)
    games = [{"id": "g1", "sport": "MLB", "start_time": "2026-06-18T09:00:00+08:00"},   # 已驗
             {"id": "g2", "sport": "MLB", "start_time": "2026-06-18T20:00:00+08:00"}]   # 今日晚場、未開賽
    verified = [{"game_id": "g1", "sport": "MLB", "verified_at": "2026-06-18T12:00:00+08:00",
                 "moneyline_hit": "true", "ah_hit": "", "ou_hit": "", "scoreline_hit": ""}]
    sent = []
    msg = dr.run_daily_report(lambda m: (sent.append(m), True)[1],
                              now=_now(), games=games, verified=verified)
    assert msg is None and sent == []  # g2 未打完 → 等，不提前送
