"""
test_postgame.py — C-4 賽後整合（run_postgame_verify + render_postgame + tick）

不打網路：注入 fake scores_fetcher + log-only post_pusher。
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import data_manager as dm  # noqa: E402
import notifier  # noqa: E402
import sports_prediction as sp  # noqa: E402
from data_fetcher import AllKeysUnavailable  # noqa: E402
from constants import TW_TZ  # noqa: E402

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=TW_TZ)


def _snapshot(gid="g1", sport="NBA", started_hours_ago=3):
    start = (NOW - timedelta(hours=started_hours_ago)).isoformat()
    return {"game_id": gid, "sport": sport, "home": "Lakers", "away": "Celtics",
            "start_time": start, "fair_prob": {"home": 0.56, "away": 0.44},
            "best_odds": {"home": 1.85, "away": 2.30},
            "best_pick": {"outcome": "home", "edge": 0.038, "odds": 1.85},
            "model": "market_implied_v1"}


def _result(gid="g1", hs=110, aws=102, completed=True):
    return {"id": gid, "completed": completed, "home_team": "Lakers", "away_team": "Celtics",
            "home_score": hs, "away_score": aws, "last_update": "2026-06-10T03:00:00Z"}


def _log_post():
    return notifier.make_postgame_pusher(True)


# ── render_postgame 契約 ─────────────────────────────
def test_render_postgame_hit(monkeypatch):
    monkeypatch.setattr(notifier._dm, "read_verified", lambda: [])  # 隔離歷史→只計本場
    v = {"game_id": "g1", "winner": "home", "pick_outcome": "home", "pick_hit": True,
         "moneyline_hit": True, "realized_return": 0.85, "fair_prob_winner": 0.56,
         "model": "market_implied_v1"}
    msg = notifier.render_postgame(v, _snapshot(), _result())
    assert "📊 賽後結果" in msg
    assert "Lakers" in msg and "Celtics" in msg
    assert "命中結果：1 / 1（100%）" in msg
    assert "獨贏：✅" in msg
    assert "EV預測準確性：✔ 正向" in msg
    # 未驗證的盤口一律 N/A（不捏造）
    assert "精準比分：N/A" in msg and "讓分：N/A" in msg and "大小分：N/A" in msg
    assert "📌 預測模式：量化分析" in msg


def test_render_postgame_no_pick(monkeypatch):
    monkeypatch.setattr(notifier._dm, "read_verified", lambda: [])  # 隔離歷史
    v = {"game_id": "g1", "winner": "away", "pick_outcome": None, "pick_hit": None,
         "moneyline_hit": None, "realized_return": None, "fair_prob_winner": 0.44,
         "model": "m"}
    msg = notifier.render_postgame(v, _snapshot(), _result(hs=99, aws=105))
    assert "命中結果：N/A" in msg
    assert "獨贏：N/A" in msg


# ── 完整流程：完賽 → verify → push → mark + archive + remove ─
def test_postgame_full_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1"))
    verified = sp.run_postgame_verify(NOW, lambda s, ids: {"g1": _result("g1")}, _log_post())
    assert verified == ["g1"]
    assert dm.is_pushed("g1", "post") is True       # mark('post')
    assert "g1" not in dm.load_predictions()        # pending 移除
    vh = dm.read_verified()                          # verified-history 落盤
    assert len(vh) == 1 and vh[0]["game_id"] == "g1"
    assert vh[0]["sport"] == "NBA" and vh[0]["winner"] == "home"
    assert dm.verified_count() == 1


# ── idempotent：已 post 過 → 不重驗，僅清理 pending ──
def test_postgame_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1"))
    dm.mark_pushed("g1", "post")  # 假設上輪已驗
    verified = sp.run_postgame_verify(NOW, lambda s, ids: {"g1": _result("g1")}, _log_post())
    assert verified == []                            # 不重推
    assert "g1" not in dm.load_predictions()         # 清理 pending
    assert dm.verified_count() == 0                  # 不重複封存


# ── 未完賽 → 不驗、保留 pending ──────────────────────
def test_postgame_not_completed_waits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1"))
    verified = sp.run_postgame_verify(NOW, lambda s, ids: {"g1": _result("g1", completed=False)},
                                      _log_post())
    assert verified == []
    assert "g1" in dm.load_predictions()             # 仍 pending
    assert dm.is_pushed("g1", "post") is False


# ── 尚未開賽 → 不抓 scores ───────────────────────────
def test_postgame_not_started_skips_fetch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1", started_hours_ago=-2))  # 2h 後才開賽

    def fetcher(s, ids):
        raise AssertionError("should not fetch scores for not-started game")

    assert sp.run_postgame_verify(NOW, fetcher, _log_post()) == []
    assert "g1" in dm.load_predictions()


# ── 過期驅逐（TD11）：太舊未驗 → 移除 pending ────────
def test_postgame_stale_eviction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1", started_hours_ago=200))  # 遠超 stale 門檻

    def fetcher(s, ids):
        raise AssertionError("stale game should be evicted before fetch")

    assert sp.run_postgame_verify(NOW, fetcher, _log_post()) == []
    assert "g1" not in dm.load_predictions()         # 驅逐
    assert dm.verified_count() == 0


# ── post 的 scores AllKeysUnavailable → 跳過、pending 保留 ─
def test_postgame_all_keys_unavailable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_prediction("g1", _snapshot("g1"))

    def fetcher(s, ids):
        raise AllKeysUnavailable("down")

    assert sp.run_postgame_verify(NOW, fetcher, _log_post()) == []
    assert "g1" in dm.load_predictions()             # 保留，等下個 tick
    assert dm.is_pushed("g1", "post") is False


# ── tick：pre 與 post 獨立（post 不影響 pre 回傳）───
def test_tick_runs_post_independently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 預埋一筆已完賽 pending，pre 無賽事（fetcher 回 []）
    dm.save_prediction("g1", _snapshot("g1"))

    def odds_fetcher(h):  # 賽前無賽事
        return []

    pushed = sp.tick(NOW, odds_fetcher, notifier.log_only_pusher,
                     scores_fetcher=lambda s, ids: {"g1": _result("g1")},
                     post_pusher=_log_post())
    assert pushed == []                              # pre 無推播
    assert dm.is_pushed("g1", "post") is True        # post 仍完成
    assert dm.verified_count() == 1
