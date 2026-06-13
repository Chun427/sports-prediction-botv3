"""
data_fetcher.py — Fetch layer

本輪只做：
  • KeyManager           ：Key Pool（KEY1→KEY2）、429/配額耗盡 → cooldown + 切換、自動恢復
  • fetch_upcoming_games ：抓未來 N 小時賽事（用 /events，不計用量配額），UTC→TW，Safe Skip
  • DEBUG_API_SCHEMA     ：沿用 obs.schema_dump（raw + parsed，每 tag 一次，production no-op）

不做：預測、Telegram、AI、Monte Carlo、賠率處理。

依賴注入（便於測試、不打真實 API）：
  • now_fn   : () -> tz-aware datetime（fake clock）
  • transport: (url:str) -> HttpResponse（fake HTTP）
  • cooldown 狀態一律落盤 State 層（data_manager），跨 GitHub Actions run 保留。

Fail-safe（決策2）：兩把 key 都不可用 → raise AllKeysUnavailable（受控例外），
由上層 tick() 捕捉並跳過本輪，不沿用舊快取、不 crash。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlencode

import data_manager as dm
import obs
from constants import (
    KEY_COOLDOWN_MIN,
    ODDS_API_BASE,
    ODDS_KEY_ENVS,
    ODDS_MARKETS,
    ODDS_ODDS_FORMAT,
    ODDS_REGIONS,
    ODDS_SPORT_KEYS,
    POOL_FETCH_HOURS_AHEAD,
    SCORES_DAYS_FROM,
    SUPPORTED_SPORTS,
    TW_TZ,
)


# ── 受控例外 ──────────────────────────────────────────
class FetchError(Exception):
    """Fetch 層受控例外基底。"""


class AllKeysUnavailable(FetchError):
    """所有 API key 都不可用（429 / 配額耗盡 / cooldown 中）。由 tick() 捕捉跳過本輪。"""


# ── HTTP 抽象（可注入 fake）───────────────────────────
@dataclass
class HttpResponse:
    status: int
    headers: dict = field(default_factory=dict)
    body: Any = None


Transport = Callable[[str], HttpResponse]
NowFn = Callable[[], datetime]


def _default_transport(url: str) -> HttpResponse:
    """真實 HTTP（lazy import requests）；測試一律注入 fake，不會走到這裡。"""
    import requests

    resp = requests.get(url, timeout=15)
    try:
        body = resp.json()
    except ValueError:
        body = None
    headers = {k.lower(): v for k, v in resp.headers.items()}
    return HttpResponse(status=resp.status_code, headers=headers, body=body)


def _build_url(path: str, params: dict, key_value: str) -> str:
    query = dict(params)
    query["apiKey"] = key_value
    return f"{ODDS_API_BASE}{path}?{urlencode(query)}"


# ── KeyManager ────────────────────────────────────────
class KeyManager:
    """
    管理 Key Pool：選 key / 標 cooldown / 自動恢復。
    keys: 依優先序的 [(key_id=env名, key_value=金鑰), ...]。
    """

    def __init__(
        self,
        keys: list[tuple[str, str]],
        *,
        now_fn: NowFn | None = None,
        transport: Transport | None = None,
    ):
        self._keys = list(keys)
        self._now = now_fn or (lambda: datetime.now(TW_TZ))
        self._transport = transport or _default_transport

    @classmethod
    def from_env(cls, **kwargs) -> "KeyManager":
        keys = [(env, os.environ[env]) for env in ODDS_KEY_ENVS if os.getenv(env)]
        return cls(keys, **kwargs)

    # 可用性：cooldown_until 為空 或 now >= cooldown_until
    @staticmethod
    def _available(key_id: str, state: dict, now: datetime) -> bool:
        rec = state.get(key_id) or {}
        cu = rec.get("cooldown_until")
        if not cu:
            return True
        try:
            return now >= datetime.fromisoformat(cu)
        except (ValueError, TypeError):
            return True  # state 壞值 → 視為可用，不因毀損卡死

    def _active(self, now: datetime) -> tuple[str, str]:
        state = dm.load_key_state()
        for key_id, key_value in self._keys:
            if self._available(key_id, state, now):
                return key_id, key_value
        raise AllKeysUnavailable("no usable Odds API key (all in cooldown / 429 / quota)")

    def _start_cooldown(self, key_id: str, now: datetime) -> None:
        state = dm.load_key_state()
        rec = state.setdefault(key_id, {})
        rec["cooldown_until"] = (now + timedelta(minutes=KEY_COOLDOWN_MIN)).isoformat(timespec="seconds")
        dm.save_key_state(state)
        obs.warn("key.cooldown", key=key_id, minutes=KEY_COOLDOWN_MIN)

    @staticmethod
    def _is_unavailable(resp: HttpResponse) -> bool:
        """決策1：429 或 配額耗盡（x-requests-remaining<=0 或 401+usage 訊息）視為不可用。"""
        if resp.status == 429:
            return True
        remaining = resp.headers.get("x-requests-remaining")
        if remaining is not None:
            try:
                if float(remaining) <= 0:
                    return True
            except (ValueError, TypeError):
                pass
        if resp.status == 401:
            text = str(resp.body).lower()
            if any(w in text for w in ("usage", "quota", "limit")):
                return True
        return False

    def get(self, path: str, params: dict | None = None) -> HttpResponse:
        """選 active key 發請求；遇 429/配額耗盡 → cooldown + 切換重試；全數耗盡 → AllKeysUnavailable。"""
        params = dict(params or {})
        now = self._now()
        tried: set[str] = set()
        while True:
            key_id, key_value = self._active(now)  # 無可用 key → 直接 raise
            if key_id in tried:
                raise AllKeysUnavailable("all keys exhausted during request")
            tried.add(key_id)
            resp = self._transport(_build_url(path, params, key_value))
            if self._is_unavailable(resp):
                obs.warn("key.unavailable", key=key_id, status=resp.status,
                         remaining=resp.headers.get("x-requests-remaining"))
                self._start_cooldown(key_id, now)
                continue  # 換下一把可用 key
            return resp


# ── fetch_upcoming_games ──────────────────────────────
def _parse_totals(bookmakers: list) -> list[dict]:
    """
    bookmakers[].markets[totals].outcomes[] → 每家一列：
      {"book": <key>, "line": <point|None>, "over": <decimal|None>, "under": <decimal|None>}
    line 為 O/U 數字（over/under 同一條線）。需有 line 才算有效一家。
    """
    rows: list[dict] = []
    for bk in bookmakers or []:
        try:
            market = next((m for m in bk.get("markets", []) if m.get("key") == "totals"), None)
            if not market:
                continue
            row = {"book": bk.get("key", ""), "line": None, "over": None, "under": None}
            for oc in market.get("outcomes", []):
                name = str(oc.get("name", "")).lower()
                price, point = oc.get("price"), oc.get("point")
                if isinstance(point, (int, float)):
                    row["line"] = float(point)
                if isinstance(price, (int, float)) and price > 1.0:
                    if name.startswith("over"):
                        row["over"] = float(price)
                    elif name.startswith("under"):
                        row["under"] = float(price)
            if row["line"] is not None:
                rows.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            obs.warn("fetch.skip_bad_totals", err=str(exc))
            continue
    return rows


def _parse_spreads(bookmakers: list, home: str, away: str) -> list[dict]:
    """
    bookmakers[].markets[spreads].outcomes[] → 每家一列：
      {"book": <key>, "home_point": <float|None>, "away_point": <float|None>}
    home_point 為主隊讓分（負=主隊讓分/被看好）。需有 home_point 才算有效一家。
    """
    rows: list[dict] = []
    for bk in bookmakers or []:
        try:
            market = next((m for m in bk.get("markets", []) if m.get("key") == "spreads"), None)
            if not market:
                continue
            row = {"book": bk.get("key", ""), "home_point": None, "away_point": None}
            for oc in market.get("outcomes", []):
                name, point = oc.get("name", ""), oc.get("point")
                if not isinstance(point, (int, float)):
                    continue
                if name == home:
                    row["home_point"] = float(point)
                elif name == away:
                    row["away_point"] = float(point)
            if row["home_point"] is not None:
                rows.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            obs.warn("fetch.skip_bad_spreads", err=str(exc))
            continue
    return rows


def _parse_h2h(bookmakers: list, home: str, away: str) -> list[dict]:
    """
    bookmakers[].markets[h2h].outcomes[] → 標準化每家一列：
      {"book": <key>, "home": <decimal|None>, "away": <decimal|None>, "draw": <decimal|None>}
    decimal odds 必須 > 1.0；至少要有 home & away 才算有效一家（壞家 Safe Skip）。
    """
    rows: list[dict] = []
    for bk in bookmakers or []:
        try:
            market = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
            if not market:
                continue
            row = {"book": bk.get("key", ""), "home": None, "away": None, "draw": None}
            for oc in market.get("outcomes", []):
                name, price = oc.get("name", ""), oc.get("price")
                if not isinstance(price, (int, float)) or price <= 1.0:
                    continue
                if name == home:
                    row["home"] = float(price)
                elif name == away:
                    row["away"] = float(price)
                else:
                    row["draw"] = float(price)  # "Draw" 或第三方
            if row["home"] is not None and row["away"] is not None:
                rows.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            obs.warn("fetch.skip_bad_bookmaker", err=str(exc))
            continue
    return rows


def _parse_event(ev: dict, sport: str, sport_key: str) -> dict | None:
    """單筆 event → normalized game；缺關鍵欄位 / 壞時間 → Safe Skip（回 None）。"""
    try:
        commence = ev["commence_time"]
        dt_utc = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        start_tw = dt_utc.astimezone(TW_TZ)  # R4：UTC → TW
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        return {
            "id": str(ev["id"]),
            "sport": sport,
            "sport_key": sport_key,
            "home": home,
            "away": away,
            "start_time": start_tw.isoformat(timespec="seconds"),  # 交給時間窗引擎（TW）
            "commence_time_utc": str(commence),
            "odds_h2h": _parse_h2h(ev.get("bookmakers", []), home, away),  # 無賠率時為 []
            "odds_totals": _parse_totals(ev.get("bookmakers", [])),        # STEP0：O/U 線
            "odds_spreads": _parse_spreads(ev.get("bookmakers", []), home, away),  # STEP0：讓分
        }
    except (KeyError, ValueError, TypeError) as exc:
        obs.warn("fetch.skip_bad_event", sport=sport, err=str(exc))
        return None


def fetch_upcoming_games(
    hours_ahead: int = POOL_FETCH_HOURS_AHEAD,
    *,
    key_manager: KeyManager | None = None,
    now_fn: NowFn | None = None,
    sports: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    """
    抓未來 hours_ahead 小時內、尚未開賽的賽事，回傳 normalized game 清單。
    兩把 key 都不可用 → 由 KeyManager 拋 AllKeysUnavailable，向上傳遞（不在此吞）。
    """
    km = key_manager or KeyManager.from_env()
    now = (now_fn or (lambda: datetime.now(TW_TZ)))()
    sports = tuple(sports) if sports is not None else SUPPORTED_SPORTS
    horizon = now + timedelta(hours=hours_ahead)

    games: list[dict] = []
    for sport in sports:
        sport_key = ODDS_SPORT_KEYS.get(sport)
        if not sport_key:
            continue
        resp = km.get(
            f"/sports/{sport_key}/odds",
            {
                "markets": ODDS_MARKETS,
                "regions": ODDS_REGIONS,
                "oddsFormat": ODDS_ODDS_FORMAT,
                "dateFormat": "iso",
            },
        )  # 可能 raise AllKeysUnavailable。成本 = markets × regions = 1 credit/次
        if resp.status != 200:
            obs.error("fetch.bad_status", sport=sport, status=resp.status)
            continue
        raw = resp.body if isinstance(resp.body, list) else []
        if raw:
            obs.schema_dump(f"{sport} raw[0]", raw[0])
        parsed = [g for g in (_parse_event(ev, sport, sport_key) for ev in raw) if g]
        if parsed:
            obs.schema_dump(f"{sport} parsed[0]", parsed[0])
        # 48h 視窗過濾（client-side，robust）；排除已開賽
        for g in parsed:
            start = datetime.fromisoformat(g["start_time"])
            if now <= start <= horizon:
                games.append(g)

    obs.info("fetch.done", count=len(games), hours_ahead=hours_ahead)
    return games


# ── fetch_scores（C-2：賽果抓取，truth loop）──────────
def _parse_score_event(ev: dict, sport: str) -> dict | None:
    """
    單筆 /scores event → normalized result；缺 id → Safe Skip（回 None）。
    scores 為 [{name, score}]（字串分數）；以 home_team/away_team 對映到 home/away。
    未完賽 / 無分數 → home_score/away_score 留 None，completed 照實。
    """
    try:
        gid = str(ev["id"])
    except (KeyError, TypeError):
        obs.warn("scores.skip_bad_event", sport=sport)
        return None
    home_team = ev.get("home_team", "")
    away_team = ev.get("away_team", "")
    home_score = away_score = None
    for s in ev.get("scores") or []:
        try:
            name = s.get("name")
            val = int(float(s.get("score")))
        except (TypeError, ValueError, AttributeError):
            continue  # 壞分數 Safe Skip
        if name == home_team:
            home_score = val
        elif name == away_team:
            away_score = val
    return {
        "id": gid,
        "sport": sport,
        "completed": bool(ev.get("completed", False)),
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "last_update": ev.get("last_update"),
    }


def fetch_scores(
    sport: str,
    event_ids: list[str] | tuple[str, ...],
    *,
    key_manager: KeyManager | None = None,
    now_fn: NowFn | None = None,
    days_from: int = SCORES_DAYS_FROM,
) -> dict[str, dict]:
    """
    抓指定 event_ids 的賽果，回 {id: normalized result}。
    /scores?daysFrom&eventIds&dateFormat=iso，成本 2 credits/次（daysFrom 含完賽）。
    event_ids 空 → 不發請求（省配額）；兩把 key 不可用 → AllKeysUnavailable 上拋（由 tick 跳過 post 路徑）。
    """
    ids = [str(i) for i in event_ids if i]
    if not ids:
        return {}
    sport_key = ODDS_SPORT_KEYS.get(sport)
    if not sport_key:
        return {}

    km = key_manager or KeyManager.from_env(now_fn=now_fn)
    resp = km.get(
        f"/sports/{sport_key}/scores",
        {"daysFrom": days_from, "dateFormat": "iso", "eventIds": ",".join(ids)},
    )  # 可能 raise AllKeysUnavailable
    if resp.status != 200:
        obs.error("scores.bad_status", sport=sport, status=resp.status)
        return {}
    raw = resp.body if isinstance(resp.body, list) else []
    if raw:
        obs.schema_dump(f"{sport} scores raw[0]", raw[0])
    results: dict[str, dict] = {}
    for ev in raw:
        norm = _parse_score_event(ev, sport)
        if norm:
            results[norm["id"]] = norm
    if results:
        obs.schema_dump(f"{sport} scores parsed[0]", next(iter(results.values())))
    obs.info("scores.done", sport=sport, requested=len(ids), returned=len(results))
    return results
