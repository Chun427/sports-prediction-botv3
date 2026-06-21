"""awards_push 測試 — idempotency + 全 N/A 不推（不打真 API、monkeypatch flags）。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import awards_push  # noqa: E402


def _patch_flags(monkeypatch):
    store = set()
    monkeypatch.setattr(awards_push.dm, "is_pushed", lambda g, s: (g, s) in store)
    monkeypatch.setattr(awards_push.dm, "mark_pushed", lambda g, s: store.add((g, s)))
    return store


def test_idempotent_once_per_day(monkeypatch):
    _patch_flags(monkeypatch)
    sent = []
    builder = lambda caps, getter=None: [
        {"capability": "Champion", "title": "🏆 冠軍預測", "available": True,
         "ranked": [{"outcome": "Brazil", "fair_probability": 0.3}]}]
    now = datetime.datetime(2026, 6, 18)
    m1 = awards_push.run_awards_push(lambda m: sent.append(m), now=now, builder=builder)
    m2 = awards_push.run_awards_push(lambda m: sent.append(m), now=now, builder=builder)
    assert m1 and len(sent) == 1 and m2 is None      # 同日第二次 → 不重推


def test_all_na_skips_push(monkeypatch):
    _patch_flags(monkeypatch)
    sent = []
    builder = lambda caps, getter=None: [
        {"capability": "Champion", "available": False, "na_reason": "市場不存在"}]
    m = awards_push.run_awards_push(lambda m: sent.append(m),
                                    now=datetime.datetime(2026, 6, 18), builder=builder)
    assert m is None and sent == []                  # 全 N/A → 不推


def test_push_failure_not_marked_then_retries(monkeypatch):
    """Never-Miss：awards 送出明確失敗(False) → 不 mark → 下一 tick 重送，成功才 mark。"""
    store = _patch_flags(monkeypatch)
    builder = lambda caps, getter=None: [
        {"capability": "Champion", "title": "🏆 冠軍預測", "available": True,
         "ranked": [{"outcome": "Brazil", "fair_probability": 0.3}]}]
    now = datetime.datetime(2026, 6, 18)
    sent = []
    m1 = awards_push.run_awards_push(lambda m: (sent.append(m), False)[1], now=now, builder=builder)
    assert m1 is None and len(sent) == 1
    assert ("awards-20260618", "awards") not in store      # 未 mark → 可重送
    ok_sent = []
    m2 = awards_push.run_awards_push(lambda m: (ok_sent.append(m), True)[1], now=now, builder=builder)
    assert m2 and len(ok_sent) == 1
    assert ("awards-20260618", "awards") in store          # 成功才 mark
