"""
test_core.py — State / Support 層單元測試

涵蓋 SOP Phase 5 要求：import test / runtime test / error path test。
執行：pytest -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import constants  # noqa: E402
import data_manager as dm  # noqa: E402
import obs  # noqa: E402


# ── import test ──────────────────────────────────────
def test_imports():
    assert constants.SUPPORTED_SPORTS
    assert callable(obs.info)
    assert callable(dm.load_flags)


def test_contract_constants():
    # 輸出契約 / 時間窗參數須符合拍板規格
    assert constants.PREGAME_WINDOW_MIN == 40
    assert constants.POSTGAME_WINDOW_MIN == 60
    assert constants.REFRESH_HOURS_TW == (0, 6, 12, 18)
    # 決策2：統一 48h 抓取視野
    assert constants.POOL_FETCH_HOURS_AHEAD == 48
    # 決策2 / 決策3：退役的常數不應再存在
    assert not hasattr(constants, "POOL_RETENTION_DAYS")
    assert not hasattr(constants, "PREGAME_TOLERANCE_MIN")


# ── flags idempotency ────────────────────────────────
def test_flags_idempotency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert dm.is_pushed("g1", "pre") is False
    dm.mark_pushed("g1", "pre")
    assert dm.is_pushed("g1", "pre") is True
    # 不同 stage 互不影響
    assert dm.is_pushed("g1", "post") is False
    # flags.json 確實落盤且可解析
    data = json.loads((tmp_path / "flags.json").read_text(encoding="utf-8"))
    assert data["g1"]["pre"] is True
    assert "updated_at" in data["g1"]


# ── pool roundtrip ───────────────────────────────────
def test_pool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert dm.load_pool() == {"games": [], "updated_at": ""}
    dm.save_pool([{"id": "g1"}, {"id": "g2"}])
    loaded = dm.load_pool()
    assert len(loaded["games"]) == 2
    assert loaded["updated_at"]


# ── history CSV ──────────────────────────────────────
def test_history_append(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert dm.read_history() == []
    dm.append_history({"game_id": "g1", "win_prob": "0.55"})
    dm.append_history({"game_id": "g2", "win_prob": "0.61"})
    rows = dm.read_history()
    assert len(rows) == 2
    assert rows[0]["game_id"] == "g1"


# ── error path：毀損 JSON 應安全降級為 default ─────────
def test_corrupt_flags_safe_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "flags.json").write_text("{not valid json", encoding="utf-8")
    # 不應拋出例外，回傳空 dict (Fail-safe)
    assert dm.load_flags() == {}


# ── atomic write 不留 .tmp 殘檔 ──────────────────────
def test_atomic_write_no_leftover(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dm.save_flags({"g1": {"pre": True}})
    leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    assert leftovers == []


# ── schema_dump：旗標關閉時為 no-op ──────────────────
def test_schema_dump_noop_when_disabled(monkeypatch, capsys):
    monkeypatch.delenv(constants.ENV_DEBUG_API_SCHEMA, raising=False)
    obs.reset_schema_cache()
    obs.schema_dump("nba raw[0]", {"a": 1})
    assert capsys.readouterr().out == ""


def test_schema_dump_once_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv(constants.ENV_DEBUG_API_SCHEMA, "true")
    obs.reset_schema_cache()
    obs.schema_dump("nba raw[0]", {"a": 1})
    obs.schema_dump("nba raw[0]", {"a": 2})  # 同 tag 第二次應被略過
    out = capsys.readouterr().out
    assert out.count("[schema] nba raw[0]") == 1
