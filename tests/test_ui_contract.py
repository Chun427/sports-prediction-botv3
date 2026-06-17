"""
test_ui_contract.py — UI 固定契約快照測試。

鎖死三個模板的「section 順序與固定文字」。任何人改動版面（刪段/改序/改標題/
改 emoji）都會讓測試失敗 → 等同 contract enforcement。數值允許變動，結構不允許。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import notifier as nf  # noqa: E402


def _assert_in_order(text, anchors):
    cursor = 0
    for a in anchors:
        idx = text.find(a, cursor)
        assert idx != -1, f"缺少或順序錯誤的 section: {a!r}\n--- 實際輸出 ---\n{text}"
        cursor = idx + len(a)


PREGAME_ANCHORS = [
    "🎯 精算師預測系統", "⚡ 量化預測模型", "📅 台灣時間", "🆚",
    "📐 去Vig真實勝率", "蒙特卡羅模擬勝率",
    "🏆 最可能出現的比分", "🥇", "🥈", "🥉", "4️⃣", "5️⃣",
    "📊 盤口深度分析", "讓分盤口", "總分大小", "獨贏賠率",
    "💰 台灣運彩實戰建議", "🔮【主推】", "💎【次要】", "⭐【備選】",
    "📡 數據來源：AI模型+真實數據+賠率", "⚠️ 請理性投注。",
]

POSTGAME_ANCHORS = [
    "📊 賽後結果", "📅 台灣時間", "vs",
    "預測：", "實際：", "結果：", "方向命中率：",
    "獨贏：", "精準比分：N/A", "讓分：N/A", "大小分：N/A",
    "📊 模型表現", "- EV預測準確性：", "- Edge命中：",
    "📌 預測模式：量化分析",
]

WEEKLY_ANCHORS = [
    "📅 本週預測週報", "總場次：", "已驗證：", "🎯 獨贏命中：",
    "📈 系統自學指標（10 場樣本）", "獨贏命中率：",
    "大小盤命中：N/A", "讓分命中：N/A", "Kelly命中：N/A", "Edge偏差：N/A",
    "各運動命中：", "🏀", "⚾", "⚠️ 數據分析，請理性投注。",
]


def test_pregame_contract_order():
    pred = {
        "sport": "MLB", "home": "Mariners", "away": "Tigers",
        "start_time": "2026-06-07T01:11:00+08:00",
        "fair_prob": {"home": 0.5, "away": 0.5}, "best_odds": {"home": 1.8, "away": 2.1},
        "edge": {"home": -0.03, "away": 0.03},
        "best_pick": {"outcome": "away", "edge": 0.03, "odds": 2.1},
    }
    _assert_in_order(nf.render_pregame_lite(pred), PREGAME_ANCHORS)


def test_postgame_contract_order():
    v = {"pick_outcome": "home", "pick_hit": True, "realized_return": 0.85,
         "winner": "home", "fair_prob_winner": 0.56}
    pred = {"home": "Lakers", "away": "Celtics", "sport": "NBA",
            "start_time": "2026-06-07T10:00:00+08:00"}
    result = {"home_score": 110, "away_score": 100}
    _assert_in_order(nf.render_postgame(v, pred, result), POSTGAME_ANCHORS)


def test_weekly_contract_order():
    report = {"week_range": "06/07–06/13", "total_games": 12, "win_rate": 0.5,
              "sport_breakdown": {"NBA": {"win_rate": 0.6, "games": 5}}}
    _assert_in_order(nf.render_weekly_report(report), WEEKLY_ANCHORS)
