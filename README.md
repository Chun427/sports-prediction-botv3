# 🎯全自動體育賽事預測系統 sports-prediction-bot

全自動體育賽事預測機器人。透過 GitHub Actions 定期（每 5 分鐘）自動執行：建立賽事池 → 統計／機率模型預測（去Vig + Poisson/常態 + 蒙特卡羅）→ 推播 Telegram → 賽後逐場驗證命中 → 累積賽後驗證紀錄（verified_history）。

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-自動排程-2088FF?logo=github-actions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)

> 狀態：**Production（已封版，進入 observation mode）**。核心 / 三推播 / 每日戰報 / 驗證流程皆完成且運行。測試 **230 passed**。
> 支援：⚾ MLB · 🏀 NBA · ⚽ FIFA。
> 註：`xgboost` 列於 requirements 但**目前未啟用**（保留為未來擴充），現行預測不依賴它。

-----

## 📱 推播畫面

### ① 賽前 40 分鐘（最終投注參考）
```
🎯 精算師預測系統
🕐 量化預測模型（賽前 40分鐘 預測）
━━━━━━━━━━━━━━━━
📅 台灣時間 06/20 06:41
⚾️ MLB
Detroit Tigers 🆚 Chicago White Sox
━━━━━━━━━━━━━━━━
📊 勝率分析
去Vig真實勝率
Detroit Tigers 64.5% ｜ Chicago White Sox 35.5%

蒙特卡羅模擬勝率
Detroit Tigers 63.2% ｜ Chicago White Sox 24.7%
━━━━━━━━━━━━━━━━
🏆 最可能出現的比分
🥇 Detroit Tigers 4-3 Chicago White Sox（3.8%）
🥈 Detroit Tigers 5-3 Chicago White Sox（3.8%）
🥉 Detroit Tigers 4-4 Chicago White Sox（3.3%）
4️⃣ Detroit Tigers 5-4 Chicago White Sox（3.3%）
5️⃣ Detroit Tigers 4-2 Chicago White Sox（3.2%）
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → Detroit Tigers 勝出
💎【次要】總分大小 → 小分(8.5)
⭐【備選】讓分盤 → Detroit Tigers(-1.5)
━━━━━━━━━━━━━━━━
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注。
```
> 註：運動 icon＝⚽️ FIFA／⚾️ MLB／🏀 NBA；比分為「主隊先－客隊後」（與隊名列、勝率分析同序）。
> 註：**「⚽ 總進球數預測」只會出現在足球（FIFA）推播**；棒球（MLB）不顯示，籃球（NBA）連「最可能出現的比分」整段都不顯示（非 Poisson）。
> 註：**勝率區塊**——足球（FIFA）顯示**三路**（主勝｜平手｜客勝）；棒球（MLB）、籃球（NBA）顯示**兩路**（主勝｜客勝），不顯示平手。

### ② 賽前 12 小時（早盤觀察）
與 40 分鐘版**逐字相同**，僅標題不同：
```
🕐 量化預測模型（賽前 12小時 預測）
```

### ③ 賽後結果（event-driven，逐場）
```
📊 比賽結果驗證（單場）
📅 台灣時間 06/20
⚾️ MLB
Detroit Tigers 🆚 Chicago White Sox
━━━━━━━━━━━━━━━━
🥅 比分預測
🎯命中：1/5 （20%）

🥇 Detroit Tigers 4-3 Chicago White Sox ❌
🥈 Detroit Tigers 5-3 Chicago White Sox ✅
🥉 Detroit Tigers 4-4 Chicago White Sox ❌
4️⃣ Detroit Tigers 5-4 Chicago White Sox ❌
5️⃣ Detroit Tigers 4-2 Chicago White Sox ❌
━━━━━━━━━━━━━━━━
💰 台灣運彩投注
🎯命中：2/3 （67%）
獨贏（ML）：✅
讓分（AH）（主-2.0）：❌
大小（O/U）（線8.5）：✅
━━━━━━━━━━━━━━━━
📌 單場結論
🎯命中：3/4 （75%）
比分命中：1/5
市場命中：2/3
```
> 投注結果用 **✅/❌**（命中→✅、未中或走盤→❌）並標盤口（如 主-2.0 / 線8.5）。
> 比分 5 組僅 Poisson 類（FIFA／MLB）有，**籃球（NBA）整段不顯示**；賽後不再顯示總進球區塊。
> 單場結論：`🎯命中 X/4`＝｛比分(≥1組中算1)＋ML＋AH＋OU｝可用類別命中數（NBA 無比分→/3）；下方另列「比分命中 X/5」「市場命中 X/3」分層真值。沒有盤口資料的投注項目直接略過（不捏造）。

### ④ 每日戰報（取代舊 WorldCup 批次）
```
📅 今日戰報 06/18
━━━━━━━━
🎯 本日總命中
獨贏 6/8（75%）
讓分 3/8（38%）
大小 5/8（63%）
━━━━━━━━
⚽ 足球（3場）
🎯 整體命中率 6/12（50%）
獨贏 2/3（67%）
讓分 1/3（33%）
大小 2/3（67%）
比分 1/3（33%）
━━━━━━━━
⚾ 棒球（4場）
🎯 整體命中率 7/12（58%）
獨贏 3/4（75%）
讓分 2/4（50%）
大小 2/4（50%）
━━━━━━━━
🏀 籃球（1場）
🎯 整體命中率 2/3（67%）
獨贏 1/1（100%）
讓分 0/1（0%）
大小 1/1（100%）
━━━━━━━━
📡 數據來源：系統統計
```
> 觸發＝「最後一場 +30 分」近似版：當天（台灣日期）所有「已開賽且非過期（<12h）」的賽事都驗證完、且距最近一次驗證 ≥30 分，才推；每日 idempotent（flags：`daily-YYYYMMDD`）。內容只統計「今天」；各球類先看 🎯整體命中率，再看各盤口（比分僅足球）。無有效盤口顯示「—」（不捏造）。
> **🎯整體命中率＝該球類「所有盤口」（ML+AH+OU，足球另含比分）命中數加總 ÷ 總盤口數，不是「場次命中率」。** 例：ML 3/5、AH 2/5、OU 4/5 → 整體 9/15（60%）。
> 舊的「WorldCup 每 4 場批次」已由本每日戰報取代（`main()` 不再呼叫 `worldcup_batch`）；`worldcup_batch.py` 保留為 dormant，可日後一併清除。

-----

## 🏗 架構總覽

```
External Scheduler (cron-job.org / Cloudflare)   ← 主觸發（準時）
        +
GitHub Actions schedule (*/5)                     ← 備援觸發
        ↓
.github/workflows/bot.yml → python src/sports_prediction.py push
        ↓
tick()                          ← 每次執行全掃描、冪等補齊（非單次觸發）
   ├─ ensure_pool              （48h 賽事池，快取）
   ├─ run_early_push           （賽前 12h 窗）
   ├─ run_pregame_push         （賽前 40m 窗）
   └─ run_postgame_verify      （event-driven：賽果 completed 即逐場推）
        ↓
main() 之後（guarded addon）
   └─ daily_report             （當天全驗證 + 30分 → 每日戰報；worldcup_batch 已 dormant）
        ↓
commit-back 狀態檔（[skip ci] update bot state）
```

**核心設計：State + Idempotency + Full Scan**（非 Queue / Event Bus）。

-----

## 🔄 預測流程

```
建立賽事池 → 去Vig → Poisson/常態 比分模型 → 蒙特卡羅 → Edge → Truth Gate → Render → Telegram → save_prediction →（賽後）逐場 Verify → Postgame Push
```

| 段別 | 觸發 | 標題 |
|---|---|---|
| Early 早推 | 賽前 12h（`EARLY_WINDOW_MIN=720`） | 🕐 賽前 12小時 預測 |
| Pregame 最終 | 賽前 40m（`PREGAME_WINDOW_MIN=40`） | ⚡ 賽前 40 分鐘 |
| Postgame 賽後 | 賽果 `completed=true`（逐場即時） | 📊 賽後結果 |

賽前兩推成功皆 `save_prediction` 落盤 → 賽後驗證不依賴 40m 窄窗命中。

-----

## 🧩 Overlay 層（addon，不碰核心）

- **⚽ 總進球數（單場）**：只讀既有 `lambda_home/away`，Poisson(λ_total) 分桶，依機率排序顯示。**僅足球（FIFA）顯示**；棒球（MLB）、籃球（NBA）不顯示（總進球分布僅對足球有意義）。不改 score_model/MC/Edge。
- **📅 每日戰報**（取代舊 WorldCup 批次）：當天賽事全驗證完 + 距最近驗證 ≥30 分，推一則「本日總命中＋各球類命中率」；只讀 verified_history + weekly_games；每日冪等（flags `daily-YYYYMMDD`）；掛 `main()` tick 之後，不碰逐場賽後。`worldcup_batch.py` 已 dormant（`main()` 不再呼叫）。
- **📊 Audit Engine（V4 Phase 2 · 可觀測層）**：唯讀 KPI 報表（依運動/盤口分組命中率、平均報酬、樣本不足警示）；只讀 `normalized_verified_view()`，**不碰核心、不寫狀態、不進推播路徑**。

-----

## 🧠 V4 資料回饋層（Feedback / Observability）

V3 是執行層、已凍結；V4 在其上**加一層唯讀的資料回饋與觀測**，不碰任何核心模型：

- **Phase 1 — 資料合約層（truth）**：`verified_history.csv` 擴充為 **21 欄完整回饋事件**（ML / AH / OU / 比分 / 總進球 / 信心 / Edge / 預期vs實際總分 / phase…），由 `verified_enrich.py` 在賽後驗證時補寫（additive、缺值留空、不 backfill）。`normalized_verified_view()` 為分析**唯一入口**（統一 schema、缺值＝None）。
- **Phase 2 — 智能/觀測層（analysis）**：`audit_engine.py` 為 baseline KPI；`bias_detector / calibration_tracker / learning_signal` 為設計就緒、**待資料累積（每運動 ≥100 場）才實作**。
- **治理**：所有分析只讀不改；任何模型調整需 Audit→回測→人工確認（詳見 `V4_FEEDBACK_DESIGN.md`、`V4_PHASE2_ARCHITECTURE.md`）。

-----

## 📂 狀態檔（repo as DB）

| 檔案 | 功能 |
|---|---|
| `weekly_games.json` | 48h 賽事池 + 三盤口賠率快取 |
| `flags.json` | 推播狀態（每場 early / pre / post） |
| `predictions.json` | 預測快照（賽後驗證唯一素材來源） |
| `verified_history.csv` | 賽後完整回饋紀錄（**V4：21 欄 truth layer**；分析經 `normalized_verified_view()`） |
| `key_state.json` | Odds API 金鑰輪替 / cooldown |
| `worldcup_state.json` | （已停用）舊 WorldCup batch 狀態；每日戰報改用 flags `daily-YYYYMMDD` |

-----

## 🛡️ Recovery（為什麼不會漏）

1. **tick 全掃描**：每次掃全部賽事，補齊「在窗內、未推」的場。
2. **冪等**：`is_pushed(gid, phase)` 防重複（重複 tick ≠ 重複推播）。
3. **scheduler 失敗自癒**：某次沒跑，下次 tick 補齊。
4. **賽後保底**：early 成功即落盤 → 不依賴 40m 窄窗。

> 可靠性瓶頸不在邏輯（已是冪等狀態機），而在「tick 是否被準時執行」→ 由 scheduler 解決。

-----

## ⚙️ GitHub Actions / Scheduler

- `bot.yml`：`schedule: */5` + `workflow_dispatch`；跑 `python src/sports_prediction.py push`，結束 commit-back 狀態檔。
- **外部 scheduler（核心）**：cron-job.org / Cloudflare 每 5 分鐘 POST
  `.../actions/workflows/bot.yml/dispatches`（用檔名 `bot.yml`，body `{"ref":"main"}`，PAT 只給該 repo Actions:write）。
- 公開 repo Actions 分鐘免費；賽程池快取不增賠率 API 用量；但有 pending 場時每 tick 會打**賽果 API** → `*/5` 為延遲與額度平衡點。

-----

## 🚫 設計邊界（已封板）

- 不使用 webhook（Odds API 僅 polling）。
- 不做 bracket / 冠軍模擬（無賽程結構，避免造假機率）。
- 不做個人獎項（金球/金靴/金手套，無球員資料源）。
- 不生成未驗證機率模型（缺資料一律 N/A，永不捏造）。
- 不修改核心：score_model / monte_carlo / prediction_engine / kelly / Edge / Risk / result_verifier（含 `main_direction`）。新功能一律 additive overlay。

-----

## 🧪 測試 & 部署

- `pytest -q` → **230 passed**；CI 必須全綠才可 merge。
- **Secrets**：`ODDS_API_KEY_1`(必)、`ODDS_API_KEY_2`、`TG_TOKEN`(必)、`TG_CHAT`(必)；`bot.yml` 須 `DRY_RUN: "false"`（未設預設 true＝只 log）。
- **Overlay bundle**（新分支 + PR，CI 綠才 merge）：
  `src/notifier.py`(覆蓋)、`src/sports_prediction.py`(覆蓋)、`src/total_goals.py`(新)、`src/worldcup_batch.py`(新)、`tests/test_total_goals.py`(新)、`tests/test_worldcup_batch.py`(新)、`tests/test_postgame.py`(保留)。

-----

## ⚠️ 免責聲明

本系統為統計模型分析工具，輸出為方向參考，**非投注獲利保證、非 +EV 投注建議**。請理性評估、自負盈虧，並遵守所在地區法律。
