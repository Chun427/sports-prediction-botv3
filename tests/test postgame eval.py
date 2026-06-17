"""test_postgame_eval.py — 賽果驗收型 UI（render_postgame_eval）。
驗：比分5組對答案、總進球落桶、台彩三項（獨贏可驗／讓分大小誠實 N/A）、NBA 無比分/總進球。
不打網路、不碰核心模型。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import notifier  # noqa: E402


def _fifa_pred(hs_list):
    return {"sport": "FIFA", "home": "Argentina", "away": "Algeria",
            "start_time": "2026-06-17T09:00:00+08:00",
            "model_score": {"type": "poisson", "lambda_home": 1.4, "lambda_away": 1.2,
                            "top_scorelines": hs_list}}


def _v(pick="home", hit=True, winner="home"):
    return {"pick_outcome": pick, "pick_hit": hit, "winner": winner, "verified_at": "2026-06-17"}


def _r(hs, aws):
    return {"id": "g", "completed": True, "home_score": hs, "away_score": aws}


def test_scoreline_hit_counts_exact_match():
    sl = [{"home": 2, "away": 1, "prob": 0.13}, {"home": 1, "away": 0, "prob": 0.11},
          {"home": 2, "away": 0, "prob": 0.10}, {"home": 3, "away": 1, "prob": 0.09},
          {"home": 3, "away": 0, "prob": 0.08}]
    msg = notifier.render_postgame_eval(_v(), _fifa_pred(sl), _r(2, 1))  # 實際 2–1 → 命中第1組
    assert "📊 比賽結果驗證（單場）" in msg
    assert "👉 命中：1 / 5" in msg
    assert "比分命中：1/5" in msg
    # 不得出現舊技術欄位
    assert "蒙特卡羅" not in msg and "Kelly" not in msg and "Edge" not in msg
    assert "命中結果" not in msg  # 累積KPI 移除


def test_scoreline_zero_hits():
    sl = [{"home": 2, "away": 1, "prob": 0.13}, {"home": 1, "away": 0, "prob": 0.11},
          {"home": 2, "away": 0, "prob": 0.10}, {"home": 3, "away": 1, "prob": 0.09},
          {"home": 3, "away": 0, "prob": 0.08}]
    msg = notifier.render_postgame_eval(_v(), _fifa_pred(sl), _r(1, 1))  # 1–1 不在5組
    assert "👉 命中：0 / 5" in msg


def test_total_goals_hit_and_ml():
    sl = [{"home": 2, "away": 1, "prob": 0.13}]
    # λ_total=2.6 → 最可能桶 2–3；實際 2+1=3 → 命中
    msg = notifier.render_postgame_eval(_v(hit=True), _fifa_pred(sl), _r(2, 1))
    assert "實際結果：3 球" in msg
    assert "命中 ✅" in msg
    assert "獨贏（ML）：✅ 命中" in msg
    assert "獨贏命中：✅" in msg


def test_ah_ou_are_honest_na():
    sl = [{"home": 2, "away": 1, "prob": 0.13}]
    msg = notifier.render_postgame_eval(_v(), _fifa_pred(sl), _r(2, 1))  # 無 market
    assert "讓分（AH）：N/A（尚未提供盤口）" in msg
    assert "大小（O/U）：N/A（尚未提供盤口）" in msg
    assert "讓分（AH）：N/A" in msg and "大小（O/U）：N/A" in msg  # 結論段


def test_market_handicap_and_total_verified():
    sl = [{"home": 2, "away": 1, "prob": 0.13}]
    pred = _fifa_pred(sl)
    pred["model_score"]["expected_total"] = 3.2   # 模型偏大
    pred["market"] = {"asian_handicap": -1.5, "over_under": 2.5,
                      "odds_source": "x", "timestamp": "t"}
    # 主 2:1 客 → 讓分 主-1.5 贏1分未過盤 ❌；總3 > 線2.5 且模型偏大 → 大命中 ✅
    msg = notifier.render_postgame_eval(_v(), pred, _r(2, 1))
    assert "讓分（AH）（主-1.5）：❌ 未中" in msg
    assert "大小（O/U）（大（線2.5））：✅ 命中" in msg


def test_nba_no_scoreline_no_total():
    nba = {"sport": "NBA", "home": "Lakers", "away": "Celtics",
           "start_time": "2026-06-17T09:00:00+08:00"}  # 無 model_score
    msg = notifier.render_postgame_eval(_v(hit=False, winner="away"), nba, _r(102, 110))
    # Change 4：非 Poisson → 整段隱藏，不顯示 N/A
    assert "🥅 比分預測" not in msg
    assert "⚽ 總進球數" not in msg
    assert "比分命中" not in msg and "總進球命中" not in msg
    assert "獨贏（ML）：❌ 未中" in msg  # 仍可驗獨贏
