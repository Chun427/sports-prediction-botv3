"""Phase1-E：push_reconcile 漏推對帳 overlay 測試。

純邏輯（detect_missed）+ 入口（run_push_reconcile）；以 fake flag store 隔離檔案狀態。
驗證：Never-Miss 偵測正確、idempotent（不重複告警）、送失敗不 mark（下一 tick 會再試）。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import data_manager as dm  # noqa: E402
import push_reconcile as pr  # noqa: E402
from constants import TW_TZ, PENDING_STALE_HOURS  # noqa: E402


@pytest.fixture
def flags(monkeypatch):
    """以記憶體 set 取代 flags 檔案，測 idempotency。"""
    store: set[tuple[str, str]] = set()
    monkeypatch.setattr(dm, "is_pushed", lambda gid, stage: (gid, stage) in store)
    monkeypatch.setattr(dm, "mark_pushed", lambda gid, stage: store.add((gid, stage)))
    return store


NOW = datetime(2026, 6, 20, 12, 0, tzinfo=TW_TZ)


def _game(gid, start, **kw):
    g = {"id": gid, "start_time": start.isoformat(), "home": "A", "away": "B", "sport": "MLB"}
    g.update(kw)
    return g


def test_pregame_missed_detected(flags):
    # 開賽已過、early/pre 皆未推 → 賽前漏推
    g = _game("g1", NOW - timedelta(minutes=10))
    missed = pr.detect_missed(NOW, [g])
    assert ("g1", "pregame", g) in missed


def test_pregame_not_missed_if_pushed(flags):
    g = _game("g1", NOW - timedelta(minutes=10))
    dm.mark_pushed("g1", "pre")  # 有成功推過 40m
    assert pr.detect_missed(NOW, [g]) == []


def test_pregame_not_missed_if_early_pushed(flags):
    g = _game("g1", NOW - timedelta(minutes=10))
    dm.mark_pushed("g1", "early")  # 12h 有推過
    assert pr.detect_missed(NOW, [g]) == []


def test_future_game_not_missed(flags):
    g = _game("g1", NOW + timedelta(hours=5))  # 還沒開賽
    assert pr.detect_missed(NOW, [g]) == []


def test_postgame_missed_when_stale(flags):
    start = NOW - timedelta(hours=PENDING_STALE_HOURS + 1)
    g = _game("g2", start)
    missed = pr.detect_missed(NOW, [g])
    assert ("g2", "postgame", g) in missed


def test_postgame_not_missed_if_post_pushed(flags):
    start = NOW - timedelta(hours=PENDING_STALE_HOURS + 1)
    g = _game("g2", start)
    dm.mark_pushed("g2", "post")
    # 開賽久遠也會觸發 pregame 漏推，但 postgame 這類不應出現
    phases = [p for (_gid, p, _g) in pr.detect_missed(NOW, [g])]
    assert "postgame" not in phases


def test_run_sends_and_marks(flags):
    g = _game("g1", NOW - timedelta(minutes=10))
    sent: list[str] = []

    def sender(text):
        sent.append(text)
        return True

    alerted = pr.run_push_reconcile(sender, now=NOW, games=[g])
    assert ("g1", "pregame") in alerted
    assert len(sent) == 1 and "漏推告警" in sent[0]
    assert dm.is_pushed("g1", "alert-pregame")  # 已 mark


def test_run_idempotent_no_double_alert(flags):
    g = _game("g1", NOW - timedelta(minutes=10))
    sender = lambda text: True  # noqa: E731
    pr.run_push_reconcile(sender, now=NOW, games=[g])
    # 第二次：已 mark alert-pregame → 不再回報、不再送
    sent2: list[str] = []
    alerted2 = pr.run_push_reconcile(lambda t: sent2.append(t) or True, now=NOW, games=[g])
    assert alerted2 == []
    assert sent2 == []


def test_run_failed_send_does_not_mark(flags):
    g = _game("g1", NOW - timedelta(minutes=10))

    def bad_sender(text):
        return False  # 送出失敗

    alerted = pr.run_push_reconcile(bad_sender, now=NOW, games=[g])
    assert alerted == []
    assert not dm.is_pushed("g1", "alert-pregame")  # 未 mark → 下一 tick 會再試


def test_run_sender_exception_caught(flags):
    g = _game("g1", NOW - timedelta(minutes=10))

    def boom(text):
        raise RuntimeError("telegram down")

    # 不可崩；回傳空、未 mark
    alerted = pr.run_push_reconcile(boom, now=NOW, games=[g])
    assert alerted == []
    assert not dm.is_pushed("g1", "alert-pregame")


def test_bad_game_skipped(flags):
    bad = {"id": "", "start_time": NOW.isoformat()}  # 無 id
    bad2 = {"id": "x", "start_time": "not-a-date"}    # 壞時間
    assert pr.detect_missed(NOW, [bad, bad2]) == []
