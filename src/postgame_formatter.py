"""postgame_formatter.py — 賽後 UI 增強層（UI layer，與 notifier 核心 render 解耦）。

職責：在已 render 好的「比賽結果驗證（單場）」字串中，插入一行『真實賽後比分』。
資料來源：只取 result dict 的 home_score / away_score（scores API 真實值）。
誠實原則：任一為非整數（未完賽 / 無分數）→ 不插入，原樣返回（不捏造）。
通用：FIFA / MLB / NBA 全運動適用（任何有最終比分的賽事皆顯示）。

明確不做：
- 不 import / 不修改 notifier、prediction_engine、market_lines、kelly 等核心。
- 不碰讓分盤 / AH / O/U / ML 邏輯、不重算任何模型數值、不改 verified_history 結構。
"""
from __future__ import annotations


def _score_line(prediction: dict, result: dict) -> str | None:
    """組『📢 比賽結果 + 比分』兩行；無真實比分 → None（不捏造）。

    隊序沿用 render_postgame_eval 的標題 `{home} 🆚 {away}`：主隊比分在前。
    """
    if not isinstance(result, dict) or not isinstance(prediction, dict):
        return None
    hs = result.get("home_score")
    aws = result.get("away_score")
    if not (isinstance(hs, int) and isinstance(aws, int)):
        return None
    home = prediction.get("home") or result.get("home_team") or ""
    away = prediction.get("away") or result.get("away_team") or ""
    return f"📢 比賽結果\n{home} {hs}-{aws} {away}"


def enhance(rendered: str, prediction: dict, result: dict) -> str:
    """在已 render 的賽後字串插入真實比分行。

    插入點：標題對戰行（含 🆚）之後；找不到則置於最前。
    無真實比分 → 原樣返回（完全不動）。
    """
    if not isinstance(rendered, str):
        return rendered
    line = _score_line(prediction, result)
    if not line:
        return rendered
    out: list[str] = []
    inserted = False
    for ln in rendered.split("\n"):
        out.append(ln)
        if not inserted and "🆚" in ln:
            out.append(line)
            inserted = True
    if not inserted:
        return line + "\n" + rendered
    return "\n".join(out)
