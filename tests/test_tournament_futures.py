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
    # 任何 key 都回同一份 outrights（模擬「市場存在」）
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


def _getter_by_key(path, params):
    # 只有冠軍 key 有市場；其餘（goalscorer/goalkeeper）回空 → 模擬「API 沒有該盤」
    if "world_cup_winner" in path:
        return _getter_ok(path, params)
    return _Resp(200, [])


def _getter_must_not_call(path, params):
    raise AssertionError("永久 N/A 的能力不得觸發 fetch")


def test_champion_ranked_desc():
    data = tf.build("Champion", getter=_getter_ok)
    assert data["available"] is True
    probs = [r["fair_probability"] for r in data["ranked"]]
    assert probs == sorted(probs, reverse=True)
    assert {r["outcome"] for r in data["ranked"]} == {"Spain", "France", "Brazil"}
    assert abs(sum(probs) - 1.0) < 1e-9
    assert data["overround"] > 0 and data["source"] == "odds_api_outrights"


def test_champion_na_when_no_market():
    data = tf.build("Champion", getter=_getter_empty)
    assert data["available"] is False and data["ranked"] == []
    assert "市場不存在" in data["na_reason"]


def test_permanent_na_skips_fetch():
    # BallonDor 永久 N/A → 直接 N/A，且不得呼叫 getter
    data = tf.build("BallonDor", getter=_getter_must_not_call)
    assert data["available"] is False and "永久 N/A" in data["na_reason"]


def test_champion_available_when_market_exists():
    # Champion（官方有效 key soccer_fifa_world_cup_winner）：市場存在（getter 回盤）→ runtime 驗證 → available
    data = tf.build("Champion", getter=_getter_ok)
    assert data["available"] is True


def test_goldenboot_goldenglove_permanent_na_regardless_of_market():
    # 官方無金靴/金手套 outright key → permanent_na 在 fetch 前就擋；即使 getter 回盤也永久 N/A
    for n in ("GoldenBoot", "GoldenGlove"):
        data = tf.build(n, getter=_getter_ok)
        assert data["available"] is False


def test_render_text_and_json_entrypoints():
    txt = tf.render_text("Champion", getter=_getter_ok)
    assert "Spain" in txt and "市場隱含" in txt
    back = json.loads(tf.render_json("Champion", getter=_getter_ok))
    assert back["available"] is True and back["ranked"][0]["outcome"] == "Spain"


def test_build_awards_runtime_validation():
    # 冠軍盤存在、射手/門將盤不存在 → 只有冠軍 available（runtime 驗證，不寫死）
    results = tf.build_awards(getter=_getter_by_key)
    assert [r["capability"] for r in results] == ["Champion", "GoldenBoot", "GoldenGlove"]
    assert results[0]["available"] is True
    assert results[1]["available"] is False
    assert results[2]["available"] is False
    txt = tf.render_awards(getter=_getter_by_key)
    assert "🏆 冠軍預測" in txt and "Spain" in txt
    assert "（暫無盤口資料）" in txt and "請理性投注" in txt
