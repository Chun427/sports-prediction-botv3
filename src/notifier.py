"""
notifier.py — Output layer（Telegram，DRY_RUN 分流）

business ≠ IO：
  • render_pregame(prediction) -> str   純函式，Output Contract `pregame_v1`（可 golden test）
  • TelegramSender.send(text) -> bool    IO，注入式 transport（預設真實 requests）
  • make_pusher(dry_run, ...)            DRY_RUN=True → log-only；False → Telegram

Fail handling（D5）：send 失敗重試 TG_RETRY 次 → obs.alert（log 層，不再回送 Telegram）
→ 回 False（不 mark_pushed，由 tick + idempotency 控制下個 tick 重試，不在此 loop）。

⚠️ token / chat 永不寫入 log。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from datetime import datetime

import obs
import kelly as _kelly
from constants import (
    PREGAME_TEMPLATE_TAG, POSTGAME_TEMPLATE_TAG, TELEGRAM_API_BASE, TG_RETRY,
    PREGAME_WINDOW_MIN,
)


# ── render（純函式，Output Contract pregame_v1）──────
def _pct(x: float) -> str:
    return f"{x:.1%}"


def render_pregame(p: dict) -> str:
    """market-implied prediction → 賽前模板（plain text）。"""
    home, away = p.get("home", ""), p.get("away", "")
    fair = p.get("fair_prob", {}) or {}
    best = p.get("best_odds", {}) or {}
    pick = p.get("best_pick")

    lines = [
        "🎯 精算師預測系統 — 賽前分析",
        f"{p.get('sport', '')}｜客 {away} vs 主 {home}",
        f"開賽：{p.get('start_time', '')}（台灣時間）",
        "",
        f"📐 市場隱含勝率（去 Vig 共識・{p.get('bookmaker_count', 0)} 家）",
    ]
    if "home" in fair:
        lines.append(f"  主 {home}：{_pct(fair['home'])}")
    if "away" in fair:
        lines.append(f"  客 {away}：{_pct(fair['away'])}")
    if "draw" in fair:
        lines.append(f"  和局：{_pct(fair['draw'])}")
    if p.get("avg_overround") is not None:
        lines.append(f"  平均抽水：{_pct(p['avg_overround'])}")

    lines += ["", "💰 最佳賠率（跨家）"]
    parts = []
    if "home" in best:
        parts.append(f"主 {best['home']}")
    if "away" in best:
        parts.append(f"客 {best['away']}")
    if "draw" in best:
        parts.append(f"和 {best['draw']}")
    lines.append("  " + " ｜ ".join(parts))

    lines += ["", "💎 價值分析（Edge = 最佳賠率 × 共識勝率 − 1）"]
    if pick:
        name = {"home": f"主 {home}", "away": f"客 {away}", "draw": "和局"}.get(
            pick["outcome"], pick["outcome"])
        lines.append(f"  ▶ {name}　edge {pick['edge']:+.1%} @ {pick['odds']}")
    else:
        lines.append("  本場無價值標的（無正 edge）")

    lines += [
        "",
        f"🔖 模型：{p.get('model', PREGAME_TEMPLATE_TAG)}",
        "⚠️ 本訊息為統計分析，非投注建議。請理性使用，僅投入可承受損失之資金。",
    ]
    return "\n".join(lines)


# ── render 賽後（純函式，Output Contract postgame_v1）─
_WINNER_ZH = {"home": "主隊", "away": "客隊", "draw": "和局"}


def render_postgame(verification: dict, prediction: dict, result: dict) -> str:
    """固定 UI contract（postgame）：版面恆定、每 section 必存在。
    本系統目前僅驗證『獨贏(moneyline)』→ 精準比分/讓分/大小分一律 N/A（不捏造）；
    命中分母 = 實際已驗證項數（誠實），不灌成 /4。"""
    home = prediction.get("home", "")
    away = prediction.get("away", "")
    pick = verification.get("pick_outcome")
    hit = verification.get("pick_hit")
    rr = verification.get("realized_return")

    if pick is not None:
        verified_n = 1
        hits = 1 if hit else 0
        ml_result = "✅" if hit else "❌"
        rate = f"{(hits / verified_n) * 100:.0f}%"
        hit_line = f"命中結果：{hits} / {verified_n}（{rate}）"
        edge_eval = "✔ 命中" if hit else "✘ 未中"
    else:
        ml_result = "N/A"
        hit_line = "命中結果：N/A"
        edge_eval = "N/A"
    ev_eval = ("✔ 正向" if rr > 0 else "✘ 負向") if isinstance(rr, (int, float)) else "N/A"
    date_src = prediction.get("start_time", "") or verification.get("verified_at", "")

    out = [
        "📊 賽後結果",
        f"📅 台灣時間 {_fmt_date_tw(date_src)}",
        f"{away} vs {home}",
        "━━━━━━━━━━━━━━━",
        hit_line,
        "━━━━━━━━━━━━━━━",
        f"獨贏：{ml_result}",
        "精準比分：N/A",
        "讓分：N/A",
        "大小分：N/A",
        "────────────────",
        "📊 模型表現",
        f"- EV預測準確性：{ev_eval}",
        f"- Edge命中：{edge_eval}",
        "📊 模型 vs 市場",
        "模型優勢：N/A",
        "市場偏差：N/A",
        "────────────────",
        "📌 預測模式：量化分析",
    ]
    return "\n".join(out)


# ── Telegram sender（IO，注入式 transport）───────────
@dataclass
class TgResponse:
    status: int
    ok: bool


TgTransport = Callable[[str, dict], TgResponse]


def _default_tg_transport(url: str, payload: dict) -> TgResponse:
    """真實 HTTP（lazy import requests）；測試一律注入 fake。"""
    import requests

    r = requests.post(url, json=payload, timeout=15)
    try:
        ok = bool(r.json().get("ok"))
    except (ValueError, AttributeError):
        ok = False
    return TgResponse(status=r.status_code, ok=ok)


class TelegramSender:
    def __init__(self, token: str, chat: str, *,
                 transport: Optional[TgTransport] = None, retry: int = TG_RETRY):
        self._token = token
        self._chat = chat
        self._transport = transport or _default_tg_transport
        self._retry = retry

    def send(self, text: str) -> bool:
        url = f"{TELEGRAM_API_BASE}/bot{self._token}/sendMessage"  # url 不入 log
        payload = {"chat_id": self._chat, "text": text}
        for attempt in range(1, self._retry + 1):
            try:
                resp = self._transport(url, payload)
                if resp.status == 200 and resp.ok:
                    obs.info("notify.sent", attempt=attempt)
                    return True
                obs.warn("notify.retry", attempt=attempt, status=resp.status)
            except Exception as exc:  # noqa: BLE001 — 送出失敗不可崩
                obs.warn("notify.retry", attempt=attempt, err=str(exc))
        obs.alert("notify.failed", attempts=self._retry)  # 不洩漏 token/chat
        return False


# ── pusher 工廠（DRY_RUN 分流）───────────────────────
def log_only_pusher(game: dict) -> bool:
    """DRY_RUN：印 marker + 摘要 + 渲染後模板預覽，不送網路。回 True 觸發 mark_pushed。"""
    gid = str(game.get("id", ""))
    pred = game.get("prediction")
    if pred:
        fp = pred.get("fair_prob", {})
        summary = " ".join(f"{k}={v:.1%}" for k, v in fp.items())
        pick = pred.get("best_pick")
        pick_s = (f" best_pick={pick['outcome']} edge={pick['edge']:+.1%} @{pick['odds']}"
                  if pick else " best_pick=none")
        print(f"[DRY_RUN_PUSH] game_id={gid} would_send=True | {summary}{pick_s}", flush=True)
        print(render_pregame(pred), flush=True)  # 預覽 Output Contract
    else:
        print(f"[DRY_RUN_PUSH] game_id={gid} would_send=True", flush=True)
    obs.info("push.dry_run", game_id=gid, has_prediction=bool(pred))
    return True


def make_pusher(dry_run: bool, *, token: str | None = None, chat: str | None = None,
                transport: Optional[TgTransport] = None,
                renderer: Optional[Callable[[dict], str]] = None) -> Callable[[dict], bool]:
    """回傳 pusher(game)->bool。DRY_RUN → log-only；否則 → Telegram。
    renderer 預設 render_pregame（pregame_v1，向後相容）；可傳 render_pregame_lite 升級畫面。"""
    render = renderer or render_pregame

    if dry_run:
        if render is render_pregame:
            return log_only_pusher  # 預設路徑：行為與既有完全一致
        def log_only_custom(game: dict) -> bool:
            gid = str(game.get("id", ""))
            pred = game.get("prediction")
            print(f"[DRY_RUN_PUSH] game_id={gid} would_send=True", flush=True)
            if pred:
                print(render(pred), flush=True)
            obs.info("push.dry_run", game_id=gid, has_prediction=bool(pred))
            return True
        return log_only_custom

    sender = TelegramSender(token or "", chat or "", transport=transport)

    def telegram_pusher(game: dict) -> bool:
        pred = game.get("prediction")
        if not pred:  # 保險：predictor=None 已在上游 SKIP，理論上不會到這
            obs.warn("notify.no_prediction", game_id=game.get("id"))
            return False
        return sender.send(render(pred))

    return telegram_pusher


def make_postgame_pusher(dry_run: bool, *, token: str | None = None,
                         chat: str | None = None,
                         transport: Optional[TgTransport] = None) -> Callable[[str], bool]:
    """賽後文字級 pusher：DRY_RUN → log-only 印出；否則 → Telegram。回傳 send(text)->bool。"""
    if dry_run:
        def log_only(text: str) -> bool:
            print("[DRY_RUN_PUSH] postgame would_send=True", flush=True)
            print(text, flush=True)
            obs.info("push.dry_run_post")
            return True
        return log_only

    sender = TelegramSender(token or "", chat or "", transport=transport)
    return sender.send


# ── P1 FEATURE 2：每週基本報表渲染（PURE，additive；不影響 pregame/postgame/push flow）──
def render_weekly_report(report: dict) -> str:
    """固定 UI contract（weekly）：版面恆定、每 section 必存在；
    未追蹤的指標（大小盤/讓分/Kelly/Edge偏差）一律 N/A（不捏造）。"""
    def _p(v):
        return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "N/A"

    sb = report.get("sport_breakdown") or {}

    def _sport(code):
        s = sb.get(code)
        return _p(s.get("win_rate")) if s else "N/A"

    games = report.get("total_games", 0)
    out = [
        f"📅 本週預測週報 {report.get('week_range', 'N/A')}",
        "━━━━━━━━━━━━━━━━",
        f"總場次：{games} 場｜已驗證：{games}",
        f"🎯 獨贏命中：{_p(report.get('win_rate'))}",
        "📈 系統自學指標（10 場樣本）",
        "━━━━━━━━━━━━━━━━",
        f"獨贏命中率：{_p(report.get('win_rate'))}",
        "大小盤命中：N/A",
        "讓分命中：N/A",
        "Kelly命中：N/A",
        "Edge偏差：N/A",
        "各運動命中：",
        f"  🏀 {_sport('NBA')}",
        f"  ⚾ {_sport('MLB')}",
        "━━━━━━━━━━━━━━━━",
        "⚠️ 數據分析，請理性投注。",
    ]
    return "\n".join(out)


# ── Stage A：Dream UI Lite 渲染器（Output Contract `pregame_lite_v1`）──────────────
# 原則：只渲染「prediction 真實存在」的資料；MC / Top5 比分 / 讓分 / 大小 / 主推次要
# 在 Stage A 不存在 → 完全不渲染（不留標題、不留 placeholder、不偽造）。
# 「賽前 N 分鐘」動態讀取 PREGAME_WINDOW_MIN，與常數同步（目前 40），不硬編碼。
_DREAM_DIV = "━━━━━━━━━━━━━━━━"
_SPORT_EMOJI = {"NBA": "🏀", "MLB": "⚾", "FIFA": "⚽"}


def _bar10(p: float) -> str:
    filled = max(0, min(10, round(p * 10)))
    return "█" * filled + "░" * (10 - filled)


def _fmt_dt_tw(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except (ValueError, TypeError):
        return str(iso)


def _fmt_date_tw(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%m/%d")
    except (ValueError, TypeError):
        return str(iso) if iso else "N/A"


def _team_label(prediction: dict, key: str) -> str:
    if key == "home":
        return prediction.get("home", "主隊")
    if key == "away":
        return prediction.get("away", "客隊")
    return "和局"


def render_pregame_lite(prediction: dict) -> str:
    """固定 UI contract（pregame）：版面恆定、每 section 必存在；
    有資料給真值、無資料給 N/A（不隱藏 section、不捏造數字）。"""
    fp = prediction.get("fair_prob") or {}
    odds = prediction.get("best_odds") or {}
    edge = prediction.get("edge") or {}
    sport = prediction.get("sport", "")
    home = prediction.get("home", "")
    away = prediction.get("away", "")
    score = prediction.get("model_score") or {}
    mc = (prediction.get("model_mc") or {}).get("win_prob") or {}
    k = _kelly.compute_kelly(prediction)
    kfrac = k["kelly"]["clipped_fraction"]
    risk_zh = {"low": "低", "medium": "中", "high": "高"}.get(k.get("risk_level"), "N/A")

    def _wp(team, val):
        return f"{team}  {_bar10(val)}  {val * 100:.1f}%" if isinstance(val, (int, float)) else f"{team}  N/A"

    def _epct(val):
        return f"{val * 100:+.1f}%" if isinstance(val, (int, float)) else "N/A"

    def _od(val):
        return f"{val}" if isinstance(val, (int, float)) else "N/A"

    total_label = (f"{score['expected_total']:.1f}"
                   if isinstance(score.get("expected_total"), (int, float)) else "N/A")
    spread_label = (f"{home} {(-score['supremacy']):+.1f}"
                    if isinstance(score.get("supremacy"), (int, float)) else "N/A")

    out = [
        "🎯 精算師預測系統",
        f"⚡ 量化預測模型（賽前 {PREGAME_WINDOW_MIN} 分鐘）",
        _DREAM_DIV,
        f"📅 台灣時間 {_fmt_dt_tw(prediction.get('start_time', ''))}",
        f"{_SPORT_EMOJI.get(sport, '🏟')} {sport}",
        f"{away} 🆚 {home}",
        _DREAM_DIV,
        "📐 去Vig真實勝率",
        _wp(away, fp.get("away")),
        _wp(home, fp.get("home")),
        "蒙特卡羅模擬勝率",
        _wp(away, mc.get("away")),
        _wp(home, mc.get("home")),
        _DREAM_DIV,
        "📊 Edge（模型優勢）",
        f"{away} {_epct(edge.get('away'))}",
        f"{home} {_epct(edge.get('home'))}",
        _DREAM_DIV,
        "🏆 最可能出現的比分",
    ]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    tops = score.get("top_scorelines") or []
    for i in range(5):
        if i < len(tops):
            s = tops[i]
            out.append(f"{medals[i]} {home} {s['home']}–{s['away']} {away}（{s['prob'] * 100:.1f}%）")
        else:
            out.append(f"{medals[i]} N/A")

    pick = prediction.get("best_pick")
    main = f"獨贏 → {_team_label(prediction, pick['outcome'])}（@ {pick['odds']}）" if pick else "N/A"
    out += [
        _DREAM_DIV, "📊 盤口深度分析",
        f"讓分盤口     {spread_label}",
        f"總分大小     {total_label}",
        "獨贏賠率",
        f"{away}:{_od(odds.get('away'))}",
        f"{home}:{_od(odds.get('home'))}",
        _DREAM_DIV, "💰 台灣運彩實戰建議",
        f"🔮【主推】{main}",
        "💎【次要】N/A",
        "⭐【備選】N/A",
        _DREAM_DIV, "📊 風控資訊",
        f"- Kelly：{kfrac * 100:.1f}%",
        f"- Risk Level：{risk_zh}",
        _DREAM_DIV,
        "📡 數據來源：AI模型+真實數據+賠率",
        "⚠️ 請理性投注。",
    ]
    return "\n".join(out)
