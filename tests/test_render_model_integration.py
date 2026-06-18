import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import monte_carlo_engine as mc  # noqa: E402
import notifier  # noqa: E402
import score_model as sm  # noqa: E402


def _base_pred():
    return {
        "sport": "FIFA", "home": "Team H", "away": "Team A",
        "start_time": "2026-06-13T03:00:00+08:00",
        "fair_prob": {"home": 0.55, "away": 0.25, "draw": 0.20},
        "best_odds": {"home": 1.8, "away": 4.0, "draw": 3.4},
        "edge": {"home": 0.05, "away": -0.02},
        "best_pick": {"outcome": "home", "edge": 0.05, "odds": 1.8, "prob": 0.55},
        "bookmaker_count": 9,
    }


def _attach(pred, game):
    score = sm.build_score_model(game)
    pred["model_score"] = score
    pred["model_mc"] = mc.run_monte_carlo(score, n=5000, seed=1)
    return pred


def test_model_present_shows_real_mc_and_scores():
    pred = _attach(_base_pred(), {
        "sport": "FIFA",
        "odds_totals": [{"book": "x", "line": 2.7}],
        "odds_spreads": [{"book": "x", "home_point": -0.5}],
    })
    msg = notifier.render_pregame_lite(pred)
    assert "蒙特卡羅模擬勝率" in msg
    assert "最可能出現的比分" in msg
    assert "🥇 Team A" in msg              # 真實比分（非 N/A），客隊先
    assert "🥇 N/A" not in msg


def test_model_absent_shows_na_sections_present():
    pred = _base_pred()
    pred["model_score"] = None
    pred["model_mc"] = None
    msg = notifier.render_pregame_lite(pred)
    # section 仍在，但內容 N/A（不隱藏、不捏造）
    assert "蒙特卡羅模擬勝率" in msg
    assert "Team A N/A" in msg
    assert "🥇 N/A" in msg


def test_nba_has_mc_but_scores_are_na():
    pred = _base_pred()
    pred["sport"] = "NBA"
    _attach(pred, {
        "sport": "NBA",
        "odds_totals": [{"book": "x", "line": 220.5}],
        "odds_spreads": [{"book": "x", "home_point": -6.5}],
    })
    msg = notifier.render_pregame_lite(pred)
    assert "蒙特卡羅模擬勝率" in msg
    assert "🥇 N/A" in msg                  # NBA 不輸出精準比分 → N/A（誠實）
    assert "🥇 Team H" not in msg
