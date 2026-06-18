"""tournament_futures 測試 — 用 fake getter 注入，不打真 API。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tournament_futures as tf  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self.headers = {}
        self.body = body


def _getter_ok(path, params):
    # 一個賽事、一家 bookmaker、三隊 outrights
    return _Resp(200, [{
        "bookmakers": [{
            "markets": [{
                "key": "outrights",
                "outcomes": [
                    {"name": "Spain", "price": 5.0},
                    {"name": "France", "price": 5.5},
                    {"name": "Brazil", "price": 11.0},
                ],
            }],
        }],
    }])


def _getter_empty(path, params):
    return _Resp(200, [])


def _getter_must_not_call(path, params):
    raise AssertionError("不支援的能力不得觸發 fetch")


def test_champion_ranked_desc():
    data = tf.build("Champion", getter=_getter_ok)
    assert data["available"] is True
    probs = [r["fair_probability"] for r in data["ranked"]]
    assert probs == sorted(probs, reverse=True)           # 只驗排序方向＝遞減
    assert {r["outcome"] for r in data["ranked"]} == {"Spain", "France", "Brazil"}
    assert abs(sum(probs) - 1.0) < 1e-9
    assert data["overround"] > 0 and data["source"] == "odds_api_outrights"


def test_champion_na_when_no_odds():
    data = tf.build("Champion", getter=_getter_empty)
    assert data["available"] is False and data["ranked"] == []
    assert "無 outright 盤口" in data["na_reason"]


def test_unsupported_capability_skips_fetch():
    # BallonDor 不支援 → 直接 N/A，且不得呼叫 getter
    data = tf.build("BallonDor", getter=_getter_must_not_call)
    assert data["available"] is False
    assert "永久 N/A" in data["na_reason"]


def test_render_text_and_json_entrypoints():
    txt = tf.render_text("Champion", getter=_getter_ok)
    assert "Spain" in txt and "市場隱含" in txt
    back = json.loads(tf.render_json("Champion", getter=_getter_ok))
    assert back["available"] is True and back["ranked"][0]["outcome"] == "Spain"


def test_build_awards_champion_available_others_na():
    results = tf.build_awards(getter=_getter_ok)
    assert [r["capability"] for r in results] == ["Champion", "GoldenBoot", "GoldenGlove"]
    assert results[0]["available"] is True                  # Champion 有 getter 資料
    assert results[1]["available"] is False                 # GoldenBoot 未支援 → N/A
    assert results[2]["available"] is False                 # GoldenGlove 未支援 → N/A
    txt = tf.render_awards(getter=_getter_ok)
    assert "🏆 冠軍預測" in txt and "Spain" in txt
    assert "（暫無盤口資料）" in txt and "請理性投注" in txt
