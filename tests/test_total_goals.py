"""total_goals display helper 測試。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import total_goals as tg  # noqa: E402


def test_buckets_sum_to_one_and_mean():
    score = {"lambda_home": 1.4, "lambda_away": 1.2}  # λ_total = 2.6
    g = tg.goal_buckets(score)
    assert g is not None
    total = sum(p for _, p in g["buckets"])
    assert abs(total - 1.0) < 1e-6           # 分布總和 ≈ 1
    assert abs(g["mean"] - 2.6) < 1e-9        # 平均 = λ_home + λ_away
    assert g["most_likely"] in {"0–1", "2–3", "4–5", "6+"}


def test_nba_no_lambda_returns_none():
    assert tg.goal_buckets({"expected_total": 220.5}) is None   # 無 lambda
    assert tg.goal_buckets({}) is None
    assert tg.goal_buckets(None) is None


def test_render_block_present_and_empty():
    block = tg.render_total_goals_block({"lambda_home": 1.5, "lambda_away": 1.1})
    assert any("總進球數預測" in ln for ln in block)
    assert any("平均" in ln for ln in block)
    assert tg.render_total_goals_block({}) == []                # 不適用 → 空
