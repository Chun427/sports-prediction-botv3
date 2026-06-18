"""futures_validation 測試。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import futures_validation as v  # noqa: E402


def test_valid_market_true():
    assert v.validate_outright_key([{"A": 2.0, "B": 3.0, "C": 5.0}]) is True


def test_empty_or_none_false():
    assert v.validate_outright_key([]) is False
    assert v.validate_outright_key(None) is False


def test_insufficient_outcomes_false():
    assert v.validate_outright_key([{"A": 2.0}]) is False
