"""release_gate.py — Production Readiness Gate（最後驗收層）。

只「新增」一層 gate；不改 futures / registry / push / awards 任何邏輯。
目的：production release 不靠感覺，靠數據 gate 控制。

is_production_ready() 檢查 5 件事 → {ready, score(0~100), blockers, warnings}。
所有檢查 guarded：gate 自身絕不可讓 main crash。
runtime 不跑 pytest（由 CI 保證，可注入結果）、不打 API（smoke 用不連網 getter）。
"""
from __future__ import annotations

import os

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# 評分權重（spec ③）
_W_PIPELINE, _W_MARKET, _W_NO_ORPHAN, _W_PYTEST, _W_NOCRASH = 30, 25, 20, 15, 10
_CORE_PUSH = ("run_pregame_push", "run_early_push", "run_postgame_verify")


def _read(name: str) -> str:
    with open(os.path.join(_SRC_DIR, name), encoding="utf-8") as f:
        return f.read()


def _safe_getter(*_a, **_k):   # 不連網：smoke test 用，避免每 tick 打 API
    return None


def _check_pipeline() -> tuple[bool, list[str]]:
    """核心 push 鏈路（pre/early/post）是否「定義且接進 tick」。
    彙整型 addon（每日戰報/獎項）不在此硬性檢查 —— 改由 _check_orphans 以 warning 追蹤，
    避免日後新增/替換 addon 時都要回頭改 gate token。"""
    blockers: list[str] = []
    try:
        sp = _read("sports_prediction.py")
        for fn in _CORE_PUSH:
            if f"def {fn}" not in sp:
                blockers.append(f"push route 缺失：{fn}")
            elif sp.count(fn) < 2:           # 只出現在 def、未被 tick 呼叫 → 未接線
                blockers.append(f"push pipeline 未接線：{fn}")
    except Exception as exc:  # noqa: BLE001
        blockers.append(f"pipeline 檢查失敗：{exc}")
    return (not blockers), blockers


def _check_market_validation() -> tuple[bool, list[str]]:
    """市場驗證層健康度（synthetic self-test；不連網、不依賴今天有無盤）。"""
    try:
        from futures_validation import validate_outright_key
        good = validate_outright_key([{"A": 2.0, "B": 3.0}]) is True
        bad = validate_outright_key([]) is False and validate_outright_key(None) is False
        few = validate_outright_key([{"A": 2.0}]) is False
        return bool(good and bad and few), []
    except Exception as exc:  # noqa: BLE001
        return False, [f"market validation 異常：{exc}"]


def _check_orphans() -> tuple[bool, list[str]]:
    """critical route（awards_push）是否接線；weekly_report 為已知 deferred orphan（warning）。"""
    warnings: list[str] = []
    ok = True
    try:
        sp = _read("sports_prediction.py")
        if "awards_push.run_awards_push" not in sp:
            ok = False
            warnings.append("critical orphan：awards_push 未接 main()")
        if "daily_report.run_daily_report" not in sp:
            warnings.append("每日戰報（daily_report）未接 main()（warning，非阻擋）")
        if "weekly_report" not in sp and "build_weekly_report" not in sp:
            warnings.append("weekly_report 為 orphan（未接 push，已知 deferred，非阻擋）")
    except Exception as exc:  # noqa: BLE001
        ok = False
        warnings.append(f"orphan 檢查失敗：{exc}")
    return ok, warnings


def _check_idempotency() -> tuple[bool, list[str]]:
    """pre/early/post/awards 是否都有 mark_pushed 機制。"""
    warnings: list[str] = []
    try:
        import data_manager as dm
        if not (callable(getattr(dm, "is_pushed", None)) and callable(getattr(dm, "mark_pushed", None))):
            return False, ["data_manager 缺 idempotency 原語（is_pushed/mark_pushed）"]
        sp, ap = _read("sports_prediction.py"), _read("awards_push.py")
        if "mark_pushed" not in sp:
            warnings.append("sports_prediction 未見 mark_pushed")
        for stage in ("pre", "early", "post"):
            if f'"{stage}"' not in sp:
                warnings.append(f"idempotency 未見 stage {stage}")
        if "mark_pushed" not in ap:
            warnings.append("awards_push 未見 mark_pushed")
    except Exception as exc:  # noqa: BLE001
        return False, [f"idempotency 檢查失敗：{exc}"]
    return True, warnings


def _check_no_crash() -> tuple[bool, list[str]]:
    """awards + futures 端到端 smoke（不連網 getter）→ 不可 crash（tick 路徑含 awards）。"""
    try:
        import tournament_futures as tf
        results = tf.build_awards(getter=_safe_getter)
        msg = tf.render_awards(getter=_safe_getter)
        return bool(isinstance(results, list) and isinstance(msg, str)), []
    except Exception as exc:  # noqa: BLE001
        return False, [f"awards/futures smoke crash：{exc}"]


def is_production_ready(*, pytest_passed: bool | None = None) -> dict:
    """回傳 {ready, score, blockers, warnings}。ready=False 當任一硬性 blocker 成立。"""
    blockers: list[str] = []
    warnings: list[str] = []
    score = 0

    pipe_ok, pipe_b = _check_pipeline()
    blockers += pipe_b
    if pipe_ok:
        score += _W_PIPELINE

    mkt_ok, mkt_b = _check_market_validation()
    blockers += mkt_b
    if mkt_ok:
        score += _W_MARKET

    orph_ok, orph_w = _check_orphans()
    warnings += orph_w
    if orph_ok:
        score += _W_NO_ORPHAN
    else:
        blockers.append("critical route orphan")

    idem_ok, idem_w = _check_idempotency()
    warnings += idem_w
    if not idem_ok:
        blockers.append("idempotency 機制不完整")

    if pytest_passed is True:
        score += _W_PYTEST
    elif pytest_passed is False:
        blockers.append("pytest fail")
    else:
        warnings.append("pytest 未於 runtime 驗證（由 CI ci.yml 保證）")

    crash_ok, crash_b = _check_no_crash()
    if crash_ok:
        score += _W_NOCRASH
    else:
        blockers += crash_b
        blockers.append("tick crash risk")

    return {
        "ready": len(blockers) == 0,
        "score": float(score),
        "blockers": blockers,
        "warnings": warnings,
    }
