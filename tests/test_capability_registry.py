"""capability_registry 測試（runtime-validation 模型：無寫死 supported）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import capability_registry as reg  # noqa: E402


def test_champion_candidate_with_known_key():
    c = reg.get("Champion")
    assert c is not None and c.outright_key == "soccer_fifa_world_cup_winner"
    assert c.source == "odds_api_outrights" and c.permanent_na is None
    assert reg.is_candidate("Champion") is True


def test_goldenboot_goldenglove_permanent_na_no_odds_api_outright_key():
    # 官方證據（the-odds-api.com /sports 清單）：世足 outright 僅 soccer_fifa_world_cup_winner。
    # 金靴／金手套／射手無對應 outright sport key → permanent_na、無候選 key、不空打 API。
    for n in ("GoldenBoot", "GoldenGlove", "TopGoalscorer"):
        assert reg.outright_key(n) is None
        assert reg.permanent_na_of(n)            # 有 permanent_na 理由（非 None）
        assert reg.is_candidate(n) is False


def test_permanent_na_markets():
    for n in ("BallonDor", "BestXI", "MVP"):
        assert "永久 N/A" in (reg.permanent_na_of(n) or "")
        assert reg.is_candidate(n) is False
        assert reg.outright_key(n) is None


def test_waiting_api_no_key():
    for n in ("GroupWinner", "Qualified"):
        assert reg.outright_key(n) is None and reg.permanent_na_of(n) is None
        assert reg.is_candidate(n) is False


def test_unknown_capability():
    assert reg.get("Nope") is None
    assert reg.is_candidate("Nope") is False
    assert reg.outright_key("Nope") is None


def test_candidate_subset():
    names = {c.name for c in reg.candidate_capabilities()}
    assert "Champion" in names
    assert "BallonDor" not in names and "BestXI" not in names and "GroupWinner" not in names
