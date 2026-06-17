"""worldcup_batch.py — FIFA 世界盃批次彙整（addon layer）。

設計原則（不破壞 RC 架構）：
  • 只讀 verified_history.csv（賽後已寫入的真實結果），不重算任何預測。
  • 每累積 BATCH_SIZE(=4) 場「已驗證的 FIFA 賽事」推一次批次摘要。
  • 冪等：worldcup_state.json 記錄已批次處理的場數；同一批不重推。
  • FIFA-only：非 FIFA 一律忽略。
  • 不碰 tick 核心 / Kelly / MC / Edge / match push / postgame pipeline。
  • 誠實：只用 verified_history 內實際存在的欄位（sport / pick_hit /
    realized_return / fair_prob_winner / game_id）。verified_history 不含 edge
    與隊名 → 不顯示 edge；隊名僅在該場仍於 weekly_games 池中時補上，否則顯示 game_id。
"""
from __future__ import annotations

import datetime

import data_manager as dm
import obs

_STATE = "worldcup_state.json"
_POOL = "weekly_games.json"
BATCH_SIZE = 4
_DIV = "━━━━━━━━━━━━━━━━"
_TW = datetime.timezone(datetime.timedelta(hours=8))


def _isnum(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _is_hit(r: dict) -> bool:
    return str(r.get("pick_hit", "")).strip().lower() == "true"


def _fifa_verified() -> list[dict]:
    """verified_history 內 sport=FIFA 的列，維持寫入順序。"""
    return [r for r in dm.read_verified() if (r.get("sport") or "").upper() == "FIFA"]


def _enrich_name(gid: str) -> str:
    """若該場仍在 weekly_games 池中則補隊名，否則回 game_id 前 8 碼（誠實，不捏造）。"""
    try:
        pool = dm._read_json(_POOL, {"games": []}).get("games", [])
        for g in pool:
            if g.get("id") == gid:
                return f"客 {g.get('away', '?')} vs 主 {g.get('home', '?')}"
    except Exception:
        pass
    return gid[:8] if gid else "N/A"


def render_worldcup_batch(batch: list[dict], batch_index: int) -> str:
    hits = sum(1 for r in batch if _is_hit(r))
    rets = [float(r["realized_return"]) for r in batch if _isnum(r.get("realized_return"))]
    avg_ret = (sum(rets) / len(rets)) if rets else None
    upsets = sum(1 for r in batch
                 if _isnum(r.get("fair_prob_winner")) and float(r["fair_prob_winner"]) < 0.5)

    lines = [
        "🏆 FIFA 世界盃戰況（批次彙整）",
        f"📦 第 {batch_index} 批（每 {BATCH_SIZE} 場已驗證）",
        _DIV,
    ]
    for r in batch:
        mark = "✔" if _is_hit(r) else "❌"
        lines.append(f"{_enrich_name(r.get('game_id', ''))} {mark}")
    lines += [
        _DIV,
        f"📊 本批次命中：{hits} / {len(batch)}",
        (f"📈 平均報酬：{avg_ret * 100:+.1f}%" if avg_ret is not None else "📈 平均報酬：N/A"),
        f"🎲 冷門場數（賽前真實勝率<50%一方獲勝）：{upsets} / {len(batch)}",
        _DIV,
        "📌 資料來源：verified_history（賽後驗證真實結果）",
    ]
    return "\n".join(lines)


def run_worldcup_batch(pusher) -> bool:
    """檢查是否湊滿新的一批 FIFA 已驗證賽事；若有則推一批並更新狀態。

    pusher: callable(str) -> bool（建議用 notifier.make_pusher(..., renderer=lambda m: m)）。
    回傳 True 表示有推出一批；False 表示尚未湊滿或推播失敗（失敗不更新狀態，下次補）。
    一次最多推一批，避免一次性洗版；多批 backlog 由後續 tick 逐批補齊（冪等）。
    """
    rows = _fifa_verified()
    done = len(rows)
    state = dm._read_json(_STATE, {"batched_count": 0, "last_batch_sent": None})
    already = int(state.get("batched_count", 0))

    if done // BATCH_SIZE <= already // BATCH_SIZE:
        obs.info("worldcup.no_new_batch", fifa_verified=done, batched=already)
        return False

    start = (already // BATCH_SIZE) * BATCH_SIZE
    batch = rows[start:start + BATCH_SIZE]
    batch_index = start // BATCH_SIZE + 1

    msg = render_worldcup_batch(batch, batch_index)
    ok = bool(pusher(msg))
    if ok:
        state["batched_count"] = start + BATCH_SIZE
        state["last_batch_sent"] = datetime.datetime.now(_TW).isoformat()
        dm._write_json(_STATE, state)
        obs.info("worldcup.batch_sent", batch_index=batch_index, batched=state["batched_count"])
        return True
    obs.info("worldcup.push_failed", batch_index=batch_index)
    return False
