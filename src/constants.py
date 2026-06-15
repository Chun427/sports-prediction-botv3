"""
constants.py — 系統常數與不可變契約 (Support layer)

本檔僅定義常數與設定，不含任何業務邏輯或 IO。
所有「輸出契約」「時間窗參數」「賽事池保留天數」集中於此，
其餘模組一律從這裡 import，禁止散落 magic number。

⚠️ 輸出契約 / 時間窗參數視為 immutable，修改前必須回到 PLANNING 階段評估影響。
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

# ── 時區 ──────────────────────────────────────────────
TW_TZ = ZoneInfo("Asia/Taipei")

# ── 支援運動 ──────────────────────────────────────────
SPORT_NBA = "NBA"
SPORT_MLB = "MLB"
SPORT_FIFA = "FIFA"
SUPPORTED_SPORTS = (SPORT_NBA, SPORT_MLB, SPORT_FIFA)

# ── 賽事池抓取視野 (Phase 1 Rolling Pool) ────────────
# 決策2：取消各運動差異化視野，NBA / MLB / FIFA 一律抓「未來 48 小時」賽事。
# 目標：降低 API 用量、長期穩定、不追求提前數日預測。
POOL_FETCH_HOURS_AHEAD = 48

# Rolling Pool 重新整理時刻 (台灣時間, 24h 制)
REFRESH_HOURS_TW = (0, 6, 12, 18)
# 自癒門檻：池齡超過此值（任何 tick，不限刷新時段）即補刷。
# 設在 6h 正常刷新間隔之上 → 正常運作不會多刷；僅在「漏刷/排程丟失」時觸發 catch-up。
POOL_MAX_AGE_HOURS = 7

# ── 時間窗引擎 (Phase 3) — 唯一合法推播入口 ──────────
# 決策3：退役 10 分鐘容錯。cron 改 */15 後 15 < 40，覆蓋已足夠。
# 賽前唯一規則：0 <= (game_start - now) <= PREGAME_WINDOW_MIN 分鐘
PREGAME_WINDOW_MIN = 40
# 早期推播窗：賽前 12 小時（與 40 分最終窗互不重疊：early 觸發 40 < delta <= 720）
EARLY_WINDOW_MIN = 720
# 賽後：完賽後 <= POSTGAME_WINDOW_MIN 分鐘
POSTGAME_WINDOW_MIN = 60

# ── 狀態檔路徑 ────────────────────────────────────────
FLAGS_FILE = "flags.json"          # idempotency 旗標
POOL_FILE = "weekly_games.json"    # Rolling Pool
KEY_STATE_FILE = "key_state.json"  # API Key cooldown 狀態（不存金鑰本體）
PREDICTIONS_FILE = "predictions.json"  # C-1 pending prediction snapshot（git tracked）
VERIFIED_HISTORY_CSV = "verified_history.csv"  # C-4 已驗證賽果（git tracked，學習資料）
HISTORY_CSV = "data/history.csv"   # 賽前特徵 + 賽後結果
METRICS_FILE = "data/metrics.json"  # 自學指標

# ── Odds API ──────────────────────────────────────────
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
# /events 端點：回傳賽事 id / 隊伍 / 開賽時間，不含賠率、不計用量配額。
# 本輪只建賽事池，故用 /events；賠率抓取留待 Processing 層。
ODDS_SPORT_KEYS = {
    SPORT_NBA: "basketball_nba",
    SPORT_MLB: "baseball_mlb",
    SPORT_FIFA: "soccer_fifa_world_cup",
}
# API Key cooldown（決策3：429 與配額耗盡統一 60 分鐘）
KEY_COOLDOWN_MIN = 60

# Odds 抓取參數（成本 = markets × regions credits；h2h × us = 1 credit/次）
ODDS_MARKETS = "h2h,totals,spreads"
ODDS_REGIONS = "us"
ODDS_ODDS_FORMAT = "decimal"

# /scores 抓取參數（C-2）：帶 daysFrom（1~3）→ 回完賽結果，成本 2 credits/次。
# 以 eventIds 批次篩選只撈我們預測過的場 → 一次涵蓋該運動所有 pending。
SCORES_DAYS_FROM = 1

# ── Processing（market-implied MVP）──────────────────
MODEL_TAG = "market_implied_v1"   # prediction schema 版本標記
EDGE_MIN = 0.0                     # best_pick 門檻：edge 須 > EDGE_MIN 才算 value

# ── Output（Telegram，DRY_RUN 分流）──────────────────
ENV_DRY_RUN = "DRY_RUN"
TELEGRAM_API_BASE = "https://api.telegram.org"
TG_RETRY = 3                       # 送出失敗重試次數
PREGAME_TEMPLATE_TAG = "pregame_v1"  # Output Contract 版本
POSTGAME_TEMPLATE_TAG = "postgame_v1"  # 賽後 Output Contract 版本
# pending 過期驅逐（C-4 / TD11）：start_time 早於此時數仍未驗證 → 視為撈不回賽果，丟棄。
# 與 /scores 的 daysFrom 覆蓋範圍對齊（24*daysFrom + 緩衝）。
PENDING_STALE_HOURS = 24 * SCORES_DAYS_FROM + 12


def dry_run_enabled() -> bool:
    """DRY_RUN 分流：預設安全（未設定 → True，不送 Telegram）。"""
    return os.getenv(ENV_DRY_RUN, "true").strip().lower() not in ("0", "false", "no")

# ── 環境變數名稱 ──────────────────────────────────────
# 決策4：移除單把 ODDS_API_KEY，改為 Key Pool（不留相容層）。
ENV_ODDS_API_KEY_1 = "ODDS_API_KEY_1"
ENV_ODDS_API_KEY_2 = "ODDS_API_KEY_2"
# Key Pool 優先序（KEY1 → KEY2）
ODDS_KEY_ENVS = (ENV_ODDS_API_KEY_1, ENV_ODDS_API_KEY_2)

ENV_TG_TOKEN = "TG_TOKEN"
ENV_TG_CHAT = "TG_CHAT"
ENV_DEBUG_API_SCHEMA = "DEBUG_API_SCHEMA"

# 缺少任一即 Fail Fast (見 README Fail-safe 表)。
# KEY1 為主、必填；KEY2 為備援、建議填（缺時 Key Pool 退化為單把）。
REQUIRED_SECRETS = (ENV_ODDS_API_KEY_1, ENV_TG_TOKEN, ENV_TG_CHAT)


def debug_schema_enabled() -> bool:
    """DEBUG_API_SCHEMA 是否開啟。"""
    return os.getenv(ENV_DEBUG_API_SCHEMA, "").strip().lower() in ("1", "true", "yes")
