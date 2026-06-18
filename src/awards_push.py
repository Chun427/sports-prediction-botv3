"""awards_push.py — 把 futures 獎項（Champion + GoldenBoot + GoldenGlove）接進推播。

addon layer：不碰 match push / tick 核心（與 worldcup_batch 同類）。
  • 每日最多 1 次：用 flags.json 的 ("awards-YYYYMMDD", "awards") 做 idempotency
    （flags.json 是 commit-back 持久檔，不需新 state、不改 bot.yml）。
  • 全部 N/A → 不推（不洗版）。market 是唯一真相，無資料即 N/A、不捏造。
"""
from __future__ import annotations

import datetime as _dt

import data_manager as dm
import futures_render
import tournament_futures

_STAGE = "awards"
_HEADER = "🏆 World Cup 冠軍與個人獎項（市場隱含）"


def run_awards_push(pusher, *, now=None, getter=None, capabilities=None, builder=None) -> str | None:
    """產生獎項合併推播。回傳已送字串；當日已處理或全 N/A → None（不推）。"""
    now = now or _dt.datetime.utcnow()
    gid = f"awards-{now:%Y%m%d}"
    if dm.is_pushed(gid, _STAGE):                 # 當日已處理 → idempotent
        return None

    build_awards = builder or tournament_futures.build_awards
    results = build_awards(capabilities, getter=getter)
    dm.mark_pushed(gid, _STAGE)                   # 當日標記（避免每 5 分鐘 tick 重抓 API）

    if not any(r.get("available") for r in results):
        return None                               # 全 N/A → 不推

    msg = futures_render.render_awards(results, header=_HEADER)
    pusher(msg)
    return msg
