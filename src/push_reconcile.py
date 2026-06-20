"""push_reconcile — Never-Miss 漏推對帳（additive, opt-in overlay）。

掃描 weekly_games 池，偵測「推播窗已關但未成功」的場 → 發 admin 告警。

設計邊界（嚴格遵守 V3 治理）：
  • 純讀 state（weekly_games + flags）；不改任何推播 / 預測 / 驗證邏輯。
  • 不碰 Core 的 score_model / monte_carlo / notifier renderer / tick 推播鏈。
  • idempotent：每場每類只告警一次（flags：alert-<phase>）。
  • opt-in：未設 TG_ADMIN_CHAT → main() 不會呼叫本模組（完全 no-op）。

偵測的兩類高訊號漏推：
  • pregame：開賽已過，但 12h('early') 與 40m('pre') 皆未成功推 → 使用者賽前完全沒收到。
  • postgame：開賽逾 PENDING_STALE_HOURS 仍未推賽後驗證('post') → 漏驗。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import data_manager as dm
import obs
from constants import TW_TZ, PENDING_STALE_HOURS


def _parse(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(str(dt_str))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW_TZ)
    return dt.astimezone(TW_TZ)


def detect_missed(now: datetime, games: list[dict]) -> list[tuple[str, str, dict]]:
    """純函式（易測，無副作用）：回傳 [(game_id, phase, game)]。

    phase ∈ {'pregame', 'postgame'}；已告警過（flags alert-<phase>）的不重複回傳。
    """
    now = now.astimezone(TW_TZ)
    out: list[tuple[str, str, dict]] = []
    for g in games:
        gid = str(g.get("id", "")).strip()
        if not gid:
            continue
        try:
            start = _parse(g["start_time"])
        except (KeyError, ValueError, TypeError):
            continue
        delta_min = (start - now).total_seconds() / 60.0

        # 賽前完全漏推：開賽已過，且 early/pre 皆未成功 mark
        if (delta_min <= 0
                and not dm.is_pushed(gid, "pre")
                and not dm.is_pushed(gid, "early")
                and not dm.is_pushed(gid, "alert-pregame")):
            out.append((gid, "pregame", g))

        # 賽後漏驗：開賽逾 stale 門檻仍未成功推 post
        if (start < now - timedelta(hours=PENDING_STALE_HOURS)
                and not dm.is_pushed(gid, "post")
                and not dm.is_pushed(gid, "alert-postgame")):
            out.append((gid, "postgame", g))
    return out


_LABEL = {
    "pregame": "賽前推播漏送（12h／40m 皆未成功）",
    "postgame": "賽後驗證漏送（已過期未推）",
}


def render_alert(game_id: str, phase: str, game: dict) -> str:
    """固定格式的 admin 告警訊息（純文字）。"""
    return (
        "🚨 漏推告警（Admin）\n"
        f"類型：{_LABEL.get(phase, phase)}\n"
        f"賽事：{game.get('home', '?')} 🆚 {game.get('away', '?')}"
        f"（{game.get('sport', '?')}）\n"
        f"開賽：{game.get('start_time', '?')}\n"
        f"game_id：{game_id}"
    )


def _read_pool() -> list[dict]:
    data = dm._read_json("weekly_games.json", {"games": []})
    return data.get("games", []) if isinstance(data, dict) else []


def run_push_reconcile(
    alert_sender: Callable[[str], bool],
    *,
    now: datetime | None = None,
    games: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """addon 入口：偵測漏推 → 發 admin 告警（idempotent）。

    成功送出才 mark（alert-<phase>），確保「重試到成功、且不重複洗版」。
    回傳已成功告警的 (game_id, phase) 列表。
    """
    now = now or datetime.now(TW_TZ)
    if games is None:
        games = _read_pool()
    obs.info("reconcile.scan", games_count=len(games))

    alerted: list[tuple[str, str]] = []
    for gid, phase, g in detect_missed(now, games):
        try:
            ok = alert_sender(render_alert(gid, phase, g))
        except Exception as exc:  # noqa: BLE001 — 告警失敗不可崩；下一 tick 再試
            obs.error("reconcile.alert_failed", game_id=gid, phase=phase, err=str(exc))
            continue
        if ok:
            dm.mark_pushed(gid, f"alert-{phase}")  # send → mark（idempotent）
            obs.warn("reconcile.missed_push", game_id=gid, phase=phase)
            alerted.append((gid, phase))
    return alerted
