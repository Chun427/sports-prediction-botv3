"""mlb_statsapi.py — 官方 MLB Stats API 來源（免 key）。

原則：有網路就抓；任何失敗 → 回 NA 欄位，絕不 raise、絕不捏造。fetch 可注入（offline 測試）。
授權注意：MLB Stats API 官方資料不得用於商業用途；個人/研究可。
"""

from __future__ import annotations

from typing import Callable
from .. import schema

BASE = "https://statsapi.mlb.com/api/v1"


def _default_fetch(url: str, params: dict) -> dict | None:
    try:
        import urllib.request, urllib.parse, json
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "feature-collector"})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fetch_team_context(team: str, game_date: str, *, fetch: Callable = _default_fetch) -> dict[str, str]:
    """回傳該隊在該日的可得情境欄位（先發名、球場）。取不到一律 NA。"""
    out: dict[str, str] = {}
    data = fetch(f"{BASE}/schedule", {"sportId": 1, "date": game_date, "hydrate": "probablePitcher,venue"})
    if not isinstance(data, dict):
        return {"source_mlb_statsapi": "FAIL"}
    try:
        sp_name = park = schema.NA
        for d in data.get("dates", []):
            for g in d.get("games", []):
                teams = g.get("teams", {})
                for side in ("home", "away"):
                    t = teams.get(side, {})
                    if team and team.lower() in str(t.get("team", {}).get("name", "")).lower():
                        pp = t.get("probablePitcher", {})
                        sp_name = schema.coerce(pp.get("fullName"))
                        park = schema.coerce(g.get("venue", {}).get("name"))
        out["sp_name"] = sp_name
        out["park"] = park
        out["source_mlb_statsapi"] = "OK" if sp_name != schema.NA else "PARTIAL"
    except Exception:
        out["source_mlb_statsapi"] = "FAIL"
    return out
