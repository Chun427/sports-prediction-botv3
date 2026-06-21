# RELEASE NOTES — V0 Final（Production Baseline）

> 狀態：**Production Baseline / Freeze**。此版本為穩定基準線；之後回饋觀測層開發一律 **additive overlay**，不得修改下列 Core。
> 測試：**230 passed**　|　Release Gate：**ready=true / score=100**

---

## ✅ 本版本完成的功能

### 預測核心（Core，凍結）
- 賽事池 `ensure_pool`：Odds API 抓取 h2h / totals / spreads（KeyManager 金鑰輪替）。
- 去 Vig → 雙變量獨立 Poisson 比分模型（λ 由市場勝率校準）→ 蒙地卡羅模擬。
- 總進球：Poisson(λ_total) 分桶（0–1 / 2–3 / 4–5 / 6+）。
- 盤口驗證 `market_lines`：讓分 / 大小（過盤 / 未過 / 走盤）。
- 賽後驗證 `result_verifier` + `verified_enrich`（21 欄 truth layer）。

### 推播（4 條鏈路）
- **賽前 12h**（`render_pregame_early`）：勝率分析（主→平→客 橫排）+ Top5 比分 +（足球）總進球 + 運彩建議。
- **賽前 40m**（`render_pregame_lite`）：同上，標題不同。
- **賽後單場**（`render_postgame_eval`）：比分 Top5 + 總進球 + 投注 ✅/❌（標盤口）+ 單場結論。即時（賽果驗證後逐場推）。
- **每日戰報**（`daily_report`）：本日總命中 + 各球類 🎯整體命中率 + 各盤口；觸發＝當天賽事全驗證 + 距最近驗證 ≥30 分；每日 idempotent（flags `daily-YYYYMMDD`）。取代舊 WorldCup 批次。

### Overlay（Addon，可擴充）
- **Futures 層**：`capability_registry → tournament_futures → futures_fetcher → futures_devig → futures_render`，加 runtime `futures_validation`（市場是唯一真相，無盤即 N/A）。
- **獎項推播** `awards_push`：冠軍 + 金靴 + 金手套（市場隱含；無盤 N/A，不捏造）。
- **Release Gate** `release_gate`：production readiness 數據化（pipeline / market validation / orphan / pytest / no-crash）。

### 工程
- CI（`ci.yml`）跑 pytest；`bot.yml` cron `*/5` + workflow_dispatch 跑 `python src/sports_prediction.py push`。
- 狀態以 commit-back 持久化：`flags.json`、`weekly_games.json`、`predictions.json`、`verified_history.csv`、`key_state.json`。

---

## ⚠️ 已知限制（Known Limitations）

1. **獎項目前多為 N/A**：冠軍/金靴/金手套需 Odds API outright 盤確認（待你的 key 實測）；金手套幾乎永久 N/A。
2. **每日戰報的「大小 O/U」累積 = N/A**：`verified_history.ou_hit` 欄目前未由賽後驗證寫入（資料缺口，非顯示 bug）。
3. **每日戰報觸發為近似**：無法事先得知「最後一場」，採「全驗證 + 靜置 30 分 + 12h 過期跳過」近似。
4. **樣本不足**：命中率/KPI 在每運動 ≥100 場前不具統計代表性，僅供方向參考。
5. **MLB 蒙地卡羅勝率偶不總和 100%**（MC 層既有現象，未列入本次修改）。
6. **`.gitignore` 失效**：內容誤存為根目錄 `download` 檔 → `.env` 未被忽略（housekeeping，建議改名）。
7. **無法於離線/CI 驗證的事項**：GitHub Actions 實際排程、Telegram 真實送達、Secrets、`DRY_RUN=false` — 需 production 環境確認（見 PRODUCTION_CHECKLIST）。

---

## 🚫 Deferred（刻意不做 / 永久不做）

- **錦標賽 bracket 模擬 / 冠軍機率模擬**：永久不做（無賽程結構 → 會造假）。
- **Elo / xG / 球員 impact / Best XI / MVP 模型**：永久不做（系統無球員層級資料 → 會造假）。market 是唯一真相。
- **週報 / 賽季累積報**：`weekly_report` 已寫但未接 push（orphan）；留待回饋觀測層報表。
- **獎項 push 真實上線**：待 Odds API outright 盤確認後再接（極小 additive）。
- **清理項（不急）**：dormant `worldcup_batch.py` + 其測試、誤放的 `tests/futures_validation.py`、`tests/test postgame eval.py`、dead 常數、`download`→`.gitignore`。

---

## 🔒 凍結清單（不得修改，只能 additive）

`prediction_engine`、`score_model`、`monte_carlo_engine`、`total_goals`、`market_lines`、`result_verifier`、`kelly`、`data_fetcher`、`tick()`、`bot.yml`、`ci.yml`、`release_gate`（已穩定）。

---

## 🧭 後續方向（詳見 ROADMAP.md）
Audit Engine → Calibration → Bias Detector → Learning Signal → Auto Report。全部 additive，讀 `normalized_verified_view()`，不碰 Core。
