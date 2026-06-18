"""capability_registry 測試。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import capability_registry as reg  # noqa: E402


def test_champion_supported():
    c = reg.get("Champion")
    assert c is not None and c.supported is True
    assert c.source == "odds_api_outrights" and c.reason_if_na is None
    assert reg.is_supported("Champion") is True


def test_ballondor_permanently_na():
    c = reg.get("BallonDor")
    assert c is not None and c.supported is False
    assert reg.is_supported("BallonDor") is False
    assert "永久 N/A" in (reg.reason_if_na("BallonDor") or "")


def test_default_unconfirmed_are_false():
    for name in ("GroupWinner", "Qualified", "TopGoalscorer", "GoldenBoot"):
        assert reg.is_supported(name) is False
        assert reg.reason_if_na(name)  # 有原因字串


def test_unknown_capability():
    assert reg.get("Nope") is None
    assert reg.is_supported("Nope") is False
    assert reg.reason_if_na("Nope") == "unknown capability"


def test_supported_subset():
    names = {c.name for c in reg.supported_capabilities()}
    assert "Champion" in names and "BallonDor" not in names


def test_goldenglove_registered_unsupported():
    c = reg.get("GoldenGlove")
    assert c is not None and c.supported is False
    assert reg.reason_if_na("GoldenGlove")
