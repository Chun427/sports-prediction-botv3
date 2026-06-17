"""audit_engine（V4 Phase 2）測試 — 合成 normalized rows，不依賴實體 CSV/網路。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import audit_engine as ae  # noqa: E402


def _rows():
    # 3 場 FIFA（ML 2 中 1；AH 1 中；ou 兩筆；scoreline 平均）
    return [
        {"sport": "FIFA", "pick_hit": "True", "ah_hit": "True", "ou_hit": "False",
         "total_goals_hit": "True", "scoreline_hit": "1", "realized_return": "0.2"},
        {"sport": "FIFA", "pick_hit": "False", "ah_hit": "", "ou_hit": "True",
         "total_goals_hit": "False", "scoreline_hit": "0", "realized_return": "-0.1"},
        {"sport": "MLB", "pick_hit": "True", "ah_hit": "", "ou_hit": "",
         "total_goals_hit": "", "scoreline_hit": "2", "realized_return": "0.5"},
    ]


def test_build_audit_structure_and_grouping():
    rep = ae.build_audit(_rows())
    assert rep["total"] == 3
    assert set(rep["by_sport"]) == {"FIFA", "MLB"}
    fifa = rep["by_sport"]["FIFA"]
    assert fifa["ml"]["n"] == 2 and fifa["ml"]["hit_rate"] == 0.5
    assert fifa["ah"]["n"] == 1 and fifa["ah"]["hit_rate"] == 1.0   # 空字串不計入
    assert fifa["scoreline_avg_hits"] == 0.5


def test_total_goals_none_excluded_for_mlb():
    rep = ae.build_audit(_rows())
    mlb = rep["by_sport"]["MLB"]
    assert mlb["total_goals"]["hit_rate"] is None   # MLB 無總進球資料 → None（不捏造）
    assert mlb["ml"]["hit_rate"] == 1.0


def test_sample_insufficient_flag():
    rep = ae.build_audit(_rows())
    assert rep["by_sport"]["FIFA"]["sufficient"] is False   # n=2 < 100
    assert "樣本不足" in ae.render_audit(rep)


def test_empty_rows_safe():
    rep = ae.build_audit([])
    assert rep["total"] == 0 and rep["by_sport"] == {}
    assert "尚無驗證資料" in ae.render_audit(rep)


def test_render_no_crash_on_missing_fields():
    # 完全缺欄位的列也不可崩
    rep = ae.build_audit([{"sport": "NBA"}])
    txt = ae.render_audit(rep)
    assert "NBA" in txt and "無資料" in txt
