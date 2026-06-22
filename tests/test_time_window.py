"""
test_time_window.py — 時間窗引擎 / 賽事池刷新判定 / 賽前推播 idempotency

全部使用 fake clock（直接注入 now）與 fake fetcher / fake pusher，不碰真實 API。

涵蓋拍板要求：
  • 40 分鐘窗口命中
  • 窗口外不推播
  • flags idempotency
  • 每 15 分鐘 tick 覆蓋驗證（含與 hourly 漏窗對照）
  • pool refresh slot guard
  • refresh 與 read cache 分流
另加：fetcher 失敗（兩把 KEY 都 429）fail-safe
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sports_prediction as sp  # noqa: E402
import data_manager as dm  # noqa: E402
from data_fetcher import AllKeysUnavailable  # noqa: E402
from constants import TW_TZ, PREGAME_WINDOW_MIN  # noqa: E402

BASE = datetime(2026, 6, 9, 12, 0, tzinfo=TW_TZ)


def _game(gid: str, start: datetime) -> dict:
    return {"id": gid, "start_time": start.isoformat()}


class FakePusher:
    """記錄被推播的場次；可設定回傳值或拋例外。"""
    def __init__(self, ok: bool = True, boom: bool = False):
        self.ok = ok
        self.boom = boom
        self.calls: list[str] = []

    def __call__(self, game: dict) -> bool:
        if self.boom:
            raise RuntimeError("notifier down")
        self.calls.append(str(game.get("id")))
        return self.ok

    @property
    def count(self) -> int:
        return len(self.calls)


class FakeFetcher:
    """記錄被呼叫次數；回傳固定賽事或拋例外（模擬兩把 KEY 都 429）。"""
    def __init__(self, games=None, boom: bool = False):
        self.games = games or []
        self.boom = boom
        self.calls = 0

    def __call__(self, hours_ahead: int) -> list[dict]:
        self.calls += 1
        if self.boom:
            raise AllKeysUnavailable("both keys 429")
        return list(self.games)


# ── 1. 40 分鐘窗口命中 ───────────────────────────────
def test_window_boundaries():
    assert sp.in_pregame_window(BASE + timedelta(minutes=0), BASE) is True
    assert sp.in_pregame_window(BASE + timedelta(minutes=20), BASE) is True
    assert sp.in_pregame_window(BASE + timedelta(minutes=PREGAME_WINDOW_MIN), BASE) is True
    # 邊界外
    assert sp.in_pregame_window(BASE + timedelta(minutes=41), BASE) is False
    assert sp.in_pregame_window(BASE + timedelta(minutes=40, seconds=1), BASE) is False
    # 已開賽（delta < 0）
    assert sp.in_pregame_window(BASE - timedelta(minutes=1), BASE) is False


def test_window_hit_pushes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pusher = FakePusher()
    start = BASE + timedelta(minutes=30)  # 窗內
    pushed = sp.run_pregame_push(BASE, [_game("g1", start)], pusher)
    assert pushed == ["g1"]
    assert pusher.count == 1
    assert dm.is_pushed("g1", "pre") is True


# ── 2. 窗口外不推播 ──────────────────────────────────
def test_outside_window_no_push(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pusher = FakePusher()
    games = [
        _game("future", BASE + timedelta(minutes=50)),  # 太早
        _game("started", BASE - timedelta(minutes=5)),  # 已開賽
    ]
    pushed = sp.run_pregame_push(BASE, games, pusher)
    assert pushed == []
    assert pusher.count == 0


# ── 3. flags idempotency（同 tick 重複呼叫不重推）─────
def test_idempotency_no_double_push(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pusher = FakePusher()
    start = BASE + timedelta(minutes=30)
    sp.run_pregame_push(BASE, [_game("g1", start)], pusher)
    # 再次呼叫（模擬下一個 tick 仍在窗內）
    sp.run_pregame_push(BASE + timedelta(minutes=15), [_game("g1", start)], pusher)
    assert pusher.count == 1  # 只推一次


def test_push_failure_not_marked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # pusher 回傳 False → 不可標記為已推，下個 tick 可重試
    pusher = FakePusher(ok=False)
    start = BASE + timedelta(minutes=30)
    sp.run_pregame_push(BASE, [_game("g1", start)], pusher)
    assert dm.is_pushed("g1", "pre") is False


def test_pusher_exception_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pusher = FakePusher(boom=True)
    start = BASE + timedelta(minutes=30)
    # 不應拋出
    pushed = sp.run_pregame_push(BASE, [_game("g1", start)], pusher)
    assert pushed == []
    assert dm.is_pushed("g1", "pre") is False


# ── 4. 每 15 分鐘 tick 覆蓋驗證 ──────────────────────
def _sweep(start, gid, step_min, pusher, first=BASE):
    """從 first 掃到 start+1h，每 step_min 一個 tick。"""
    t = first
    last = start + timedelta(hours=1)
    while t <= last:
        sp.run_pregame_push(t, [_game(gid, start)], pusher)
        t += timedelta(minutes=step_min)


def test_15min_tick_always_covers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 不同開賽分鐘偏移，*/15 掃描皆應「剛好推一次」
    for i, offset in enumerate([5, 20, 37, 50, 58, 73, 95]):
        start = BASE + timedelta(minutes=offset)
        pusher = FakePusher()
        _sweep(start, f"g{i}", step_min=15, pusher=pusher)
        assert pusher.count == 1, f"offset={offset} 推了 {pusher.count} 次"


def test_hourly_cron_would_miss(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 對照組：hourly（60 分）會漏掉落在兩 tick 間的 40 分鐘窗
    # 開賽 12:50，窗 12:10–12:50；ticks 12:00 / 13:00 皆在窗外
    start = BASE + timedelta(minutes=50)
    pusher = FakePusher()
    _sweep(start, "miss", step_min=60, pusher=pusher)
    assert pusher.count == 0  # 證明 hourly 會整場漏推 → 故改 */15


# ── 5. pool refresh slot guard ───────────────────────
def test_refresh_slot_guard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = FakeFetcher(games=[_game("g1", BASE + timedelta(hours=2))])
    # 12:00 為刷新時刻、池空 → 應抓取一次
    sp.ensure_pool(BASE, fetcher)
    assert fetcher.calls == 1
    # 同一刷新時段 12:15 / 12:30 / 12:45 → 不得再抓（slot guard）
    for m in (15, 30, 45):
        sp.ensure_pool(BASE + timedelta(minutes=m), fetcher)
    assert fetcher.calls == 1


def test_refresh_new_slot_refetches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = FakeFetcher(games=[_game("g1", BASE + timedelta(hours=2))])
    sp.ensure_pool(BASE, fetcher)                       # 12:00 刷
    sp.ensure_pool(BASE + timedelta(hours=6), fetcher)  # 18:00 新刷新時段 → 再刷
    assert fetcher.calls == 2


# ── 6. refresh 與 read cache 分流 ────────────────────
def test_non_refresh_hour_reads_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 預先放入快取
    dm.save_pool([_game("cached", BASE + timedelta(hours=3))],
                 updated_at=(BASE).isoformat(timespec="seconds"))
    fetcher = FakeFetcher(games=[_game("fresh", BASE)])
    # 13:00 非刷新時刻 → 不抓，回快取
    games = sp.ensure_pool(BASE + timedelta(hours=1), fetcher)
    assert fetcher.calls == 0
    assert [g["id"] for g in games] == ["cached"]


def test_stale_pool_self_heals_on_non_refresh_hour(tmp_path, monkeypatch):
    """漏刷導致池過舊時，非刷新時段的任何 tick 也應 catch-up 補刷（自癒）。"""
    monkeypatch.chdir(tmp_path)
    # 池上次刷新在 8 小時前（超過 POOL_MAX_AGE_HOURS=7）
    dm.save_pool([_game("old", BASE + timedelta(hours=2))],
                 updated_at=(BASE - timedelta(hours=8)).isoformat(timespec="seconds"))
    fetcher = FakeFetcher(games=[_game("fresh", BASE + timedelta(hours=1))])
    # 13:00 非刷新時刻，但池齡 9h > 7h → 補刷
    games = sp.ensure_pool(BASE + timedelta(hours=1), fetcher)
    assert fetcher.calls == 1
    assert [g["id"] for g in games] == ["fresh"]


def test_refresh_hour_fetches_when_due(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = FakeFetcher(games=[_game("fresh", BASE + timedelta(hours=1))])
    games = sp.ensure_pool(BASE, fetcher)  # 12:00 刷新時刻、池空
    assert fetcher.calls == 1
    assert [g["id"] for g in games] == ["fresh"]


# ── 7. 決策2：兩把 KEY 都不可用 → 傳遞例外、不沿用舊快取 ──
def test_refresh_failure_uses_cache_when_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 昨日的舊快取
    dm.save_pool([_game("old", BASE + timedelta(hours=2))],
                 updated_at="2026-06-08T12:00:00+08:00")
    fetcher = FakeFetcher(boom=True)  # 兩把 KEY 都 429 → AllKeysUnavailable
    # 決策2（修正）：刷新失敗但有快取 → 退回沿用快取（不拋例外、不漏推已快取賽事）
    games = sp.ensure_pool(BASE, fetcher)  # 12:00 刷新時刻
    assert fetcher.calls == 1
    assert [g["id"] for g in games] == ["old"]
    # 舊快取「未被覆蓋」（刷新失敗不落盤）
    assert [g["id"] for g in dm.load_pool()["games"]] == ["old"]


def test_tick_skips_when_all_keys_unavailable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetcher = FakeFetcher(boom=True)
    pusher = FakePusher()
    pushed = sp.tick(BASE, fetcher, pusher)  # 12:00 刷新 → fetch raise → tick 捕捉跳過
    assert pushed == []
    assert pusher.count == 0


# ── 整合：tick() 串接 ensure_pool + run_pregame_push ─
def test_tick_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    start = BASE + timedelta(minutes=30)  # 窗內
    fetcher = FakeFetcher(games=[_game("g1", start)])
    pusher = FakePusher()
    pushed = sp.tick(BASE, fetcher, pusher)  # 12:00 刷新 → 抓到 g1 → 推播
    assert pushed == ["g1"]
    assert pusher.count == 1
