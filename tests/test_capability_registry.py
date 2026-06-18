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


def test_goldenboot_goldenglove_have_candidate_keys_not_hardcoded_na():
    # 不再寫死 False；有候選 key、非永久 N/A → 由 runtime 驗證決定
    for n in ("GoldenBoot", "GoldenGlove", "TopGoalscorer"):
        assert reg.outright_key(n)
        assert reg.permanent_na_of(n) is None
        assert reg.is_candidate(n) is True


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
