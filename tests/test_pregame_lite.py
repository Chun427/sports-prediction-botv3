"""
test_pregame_lite.py — 固定 UI contract（pregame）。

驗證：版面恆定、每 section 必存在；有資料給真值、無資料給 N/A（不隱藏、不捏造）；
分鐘數動態綁定 PREGAME_WINDOW_MIN；make_pusher 可接 renderer。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import notifier as nf  # noqa: E402
from notifier import TgResponse  # noqa: E402
from constants import PREGAME_WINDOW_MIN  # noqa: E402

PRED_2WAY = {
    "game_id": "g1", "sport": "MLB", "home": "Mariners", "away": "Tigers",
    "start_time": "2026-06-07T01:11:00+08:00", "market": "h2h", "bookmaker_count": 6,
    "fair_prob": {"home": 0.50, "away": 0.50},
    "best_odds": {"home": 1.80, "away": 2.10},
    "edge": {"home": -0.033, "away": 0.033},
    "best_pick": {"outcome": "away", "edge": 0.033, "odds": 2.10},
    "avg_overround": 0.04, "model": "market_implied_v1", "generated_at": "x",
}
PRED_NO_PICK = {**PRED_2WAY, "best_pick": None}
PRED_FIFA = {**PRED_2WAY, "sport": "FIFA"}  # 比分（正確比分）為 FIFA-only，比分相關契約用此


def test_window_minutes_is_dynamic_not_hardcoded():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert f"賽前{PREGAME_WINDOW_MIN}分鐘" in out
    assert "賽前30分鐘" not in out


def test_all_fixed_sections_present():
    out = nf.render_pregame_lite(PRED_FIFA)  # 含比分的完整契約 → FIFA
    for header in [
        "🎯 精算師預測系統", "🕐 量化預測模型", "去Vig真實勝率", "蒙特卡羅模擬勝率",
        "🏆 最可能出現的比分", "💰 台灣運彩實戰建議",
        "🔮【主推】", "💎【次要】", "⭐【備選】",
        "📡 數據來源：AI模型+真實數據+賠率", "⚠️ 請理性投注",
    ]:
        assert header in out, f"缺少固定 section: {header}"


def test_mlb_nba_no_scoreline_section():
    """台彩 MLB/NBA 無正確比分投注 → 賽前推播不顯示比分區塊。"""
    for sport in ("MLB", "NBA"):
        out = nf.render_pregame_lite({**PRED_2WAY, "sport": sport})
        assert "🏆 最可能出現的比分" not in out, f"{sport} 不應顯示比分"


def test_devig_real_values():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "Mariners" in out and "Tigers" in out
    assert "50.0%" in out
    assert "█" not in out and "░" not in out   # 已移除進度條（②：純「隊伍 X%」）


def test_edge_not_displayed():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "📊 Edge" not in out and "模型優勢" not in out


def test_handicap_block_removed():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "📊 盤口深度分析" not in out
    assert "獨贏賠率" not in out


def test_missing_model_shows_na_not_fabricated():
    out = nf.render_pregame_lite(PRED_FIFA)  # 比分區塊為 FIFA-only
    assert "蒙特卡羅模擬勝率" in out
    assert "Tigers N/A" in out and "Mariners N/A" in out
    assert "🥇 N/A" in out
    assert "📊 盤口深度分析" not in out


def test_best_pick_main_real():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "🔮【主推】獨贏 → Tigers" in out


def test_no_pick_main_is_na():
    out = nf.render_pregame_lite(PRED_NO_PICK)
    assert "🔮【主推】N/A" in out


def test_secondary_alt_are_na():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "💎【次要】N/A" in out
    assert "⭐【備選】N/A" in out


def test_kelly_and_risk_not_displayed():
    out = nf.render_pregame_lite(PRED_2WAY)
    assert "Kelly：" not in out and "Risk Level：" not in out
    assert "📊 Edge" not in out


def test_make_pusher_real_uses_renderer():
    sent = {}

    def fake(url, payload):
        sent["text"] = payload["text"]
        return TgResponse(200, True)

    pusher = nf.make_pusher(False, token="T", chat="C", transport=fake,
                            renderer=nf.render_pregame_lite)
    assert pusher({"id": "g1", "prediction": PRED_2WAY}) is True
    assert "量化預測模型" in sent["text"]
    assert "📡 數據來源" in sent["text"]


def test_make_pusher_dry_run_previews(capsys):
    pusher = nf.make_pusher(True, renderer=nf.render_pregame_lite)
    assert pusher({"id": "g1", "prediction": PRED_2WAY}) is True
    out = capsys.readouterr().out
    assert "[DRY_RUN_PUSH] game_id=g1 would_send=True" in out
    assert "量化預測模型" in out
