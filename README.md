# 🎯全自動體育賽事預測系統 sports-prediction-bot

全自動體育賽事預測機器人，透過 GitHub Actions 定期（每 5 分鐘）自動執行：建立賽事池 → 統計／機率模型預測（去Vig + Poisson/常態 + 蒙特卡羅）→ 推播 Telegram → 賽後逐場驗證命中 → 累積賽後驗證紀錄（verified_history）。

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-自動排程-2088FF?logo=github-actions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)

> 狀態：**v0 stable baseline（Production / Observation Mode）**。核心 / 三推播 / 每日戰報 / 賽後驗證 / 漏推對帳 流程皆完成且運行。測試 **248 passed**。工程與維運細節見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
> 支援：⚾ MLB · 🏀 NBA · ⚽ FIFA。

> ⚙️ **部署可靠性建議（觸發層）**：GitHub Actions 的 `schedule` 為 best-effort，排程可能延遲或被丟棄。本專案以「每次 run 內部 ~50 分鐘 tick 迴圈」緩解;若要更高的送達保證,**建議再加一個外部排程器**每 5 分鐘觸發 `workflow_dispatch`。Recommended: add an external scheduler (cron-job.org or Cloudflare Worker) to trigger `workflow_dispatch` every 5 minutes for high-reliability delivery. 推播本身已是 idempotent + success-gated（重送不重複、送失敗才重試）,缺的只有觸發層冗餘。

-----

## 🎯 系統定位

> **即時統計 + 機率推論 + 賽後驗證系統。** 本系統不使用機器學習訓練模型（No ML training pipeline），不包含 XGBoost / Neural Network / Deep Learning。
>
> 所有預測基於：
> - 去 Vig 市場機率轉換（Implied Probability）
> - Poisson / 常態分布模型（比分與總分）
> - Monte Carlo 模擬（勝率分布）
> - Edge 計算（期望值差）
> - Truth Gate 賽後驗證（verified_history）
>
> `xgboost` 已保留於 requirements.txt 作為未來實驗性擴展，**目前未啟用且未被任何主流程引用**。

-----

## 📱 推播畫面

### ① 賽前 12 小時（早盤觀察，⚽ FIFA 範例）
```
🎯 精算師預測系統
🕐 量化預測模型（賽前12小時預測）
━━━━━━━━━━━━━━━━
📅 台灣時間 06/22 03:00
⚽️ FIFA
Belgium 🆚 Iran
━━━━━━━━━━━━━━━━
📊 勝率分析
去Vig真實勝率
Belgium 67.0% ｜ 平手 20.5% ｜ Iran 12.5%

蒙特卡羅模擬勝率
Belgium 67.6% ｜ 平手 20.7% ｜ Iran 11.7%
━━━━━━━━━━━━━━━━
🏆 最可能出現的比分
🥇 Belgium 1-0 Iran（15.4%）
🥈 Belgium 2-0 Iran（14.4%）
🥉 Belgium 1-1 Iran（9.6%）
4️⃣ Belgium 2-1 Iran（9.0%）
5️⃣ Belgium 3-0 Iran（9.0%）
━━━━━━━━━━━━━━━━
⚽ 總進球數預測
🥇 2–3球（47%）
🥈 0–1球（29%）
🥉 4–5球（20%）
4️⃣ 6+球（4%）
🎯 最可能：2–3球
📊 平均：2.50球
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → Belgium 勝出
💎【次要】總分大小 → 小分(2.5)
⭐【備選】讓分盤 → Belgium(-1.2)
━━━━━━━━━━━━━━━━
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注
```
> 註：運動 icon＝⚽️ FIFA／⚾️ MLB／🏀 NBA；比分為「主隊先－客隊後」（與隊名列、勝率分析同序）。
> 註：**「⚽ 總進球數預測」與「最可能出現的比分」只會出現在足球（FIFA）推播**；台彩 MLB／NBA 無「正確比分」投注玩法，**棒球（MLB）、籃球（NBA）皆不顯示比分區塊**（僅 獨贏／讓分／大小）。
> 註：**勝率區塊**——足球（FIFA）顯示**三路**（主勝｜平手｜客勝）；棒球（MLB）、籃球（NBA）顯示**兩路**（主勝｜客勝），不顯示平手。

### ② 賽前 40 分鐘（最終投注參考）
版型與 12 小時早盤**逐字相同**，僅標題不同：
```
🕐 量化預測模型（賽前40分鐘預測）
```

### ⚾ MLB 賽前範例（無比分）
```
🎯 精算師預測系統
🕐 量化預測模型（賽前40分鐘預測）
━━━━━━━━━━━━━━━━
📅 台灣時間 06/22 08:00
⚾️ MLB
Detroit Tigers 🆚 Chicago White Sox
━━━━━━━━━━━━━━━━
📊 勝率分析
去Vig真實勝率
Detroit Tigers 63.2% ｜ Chicago White Sox 24.7%

蒙特卡羅模擬勝率
Detroit Tigers 63.2% ｜ Chicago White Sox 24.7%
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → Detroit Tigers 勝出
💎【次要】總分大小 → 小分(7.8)
⭐【備選】讓分盤 → Detroit Tigers(-1.2)
━━━━━━━━━━━━━━━━
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注
```

### 🏀 NBA 賽前範例（無比分）
```
🎯 精算師預測系統
🕐 量化預測模型（賽前40分鐘預測）
━━━━━━━━━━━━━━━━
📅 台灣時間 06/22 08:00
🏀 NBA
Boston Celtics 🆚 Miami Heat
━━━━━━━━━━━━━━━━
📊 勝率分析
去Vig真實勝率
Boston Celtics 68.1% ｜ Miami Heat 31.9%

蒙特卡羅模擬勝率
Boston Celtics 68.1% ｜ Miami Heat 31.9%
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → Boston Celtics 勝出
💎【次要】總分大小 → 大分(221.5)
⭐【備選】讓分盤 → Boston Celtics(-5.5)
━━━━━━━━━━━━━━━━
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注
```
> 註：**MLB／NBA 為兩路勝率（無平手）**，**無「最可能出現的比分」、無「總進球數預測」、無比分區塊**；僅 獨贏（ML）／大小（O/U）／讓分（AH）。比分相關區塊只有 ⚽ FIFA 才有。

### ③ 賽後結果（event-driven，逐場）
```
📊 比賽結果驗證（單場）
📅 台灣時間 06/21
⚽️ FIFA
Tunisia 🆚 Japan
━━━━━━━━━━━━━━━━
📋 比分預測
🎯命中：0/1（0%）
🥇 Tunisia 0-1 Japan ❌
🥈 Tunisia 0-2 Japan ❌
🥉 Tunisia 1-1 Japan ❌
4️⃣ Tunisia 1-2 Japan ❌
5️⃣ Tunisia 0-0 Japan ❌
━━━━━━━━━━━━━━━━
💰 台灣運彩投注
🎯命中：2/3（67%）
獨贏（ML）：✅ Japan 勝出
大小（O/U）：❌ 小分（2.5）
讓分（AH）：✅ Japan（客-1.0）
━━━━━━━━━━━━━━━━
📌 單場結論
🎯命中：2/4（50%）
比分命中：0/1（0%）
盤口命中：2/3（67%）
```
> 投注結果用 **✅/❌**（命中→✅、未中或走盤→❌），並標推薦內容（ML 推哪隊／OU 大小＋線／AH 哪隊＋讓分）。
> **比分命中以「中／沒中」二元計**：5 組任一中 → 1/1，否則 0/1（不再計 X/5）。
> 比分區塊**僅足球（FIFA）有**（台彩有正確比分玩法）；**棒球（MLB）、籃球（NBA）整段不顯示**；賽後不顯示總進球區塊。
> 單場結論：FIFA 為 `🎯命中 X/4`＝｛比分(二元,1類)＋ML＋AH＋OU｝；**MLB／NBA 無正確比分玩法 → `X/3`**（僅 ML＋AH＋OU，不顯示比分區塊、不列「比分命中」）。比分命中僅 FIFA 另列「X/1」；盤口命中列「X/3」。無盤口的投注項目直接略過（不捏造）。

### ④ 每日戰報
```
📅 今日戰報 06/18
━━━━━━━━
🎯 本日總命中
獨贏 6/8（75%）
讓分 3/8（38%）
大小 5/8（63%）
比分 1/3（33%）
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
   ├─ daily_report             （當天全驗證 + 30分 → 每日戰報；worldcup_batch 已 dormant）
   └─ push_reconcile           （漏推對帳 → admin 告警；opt-in，TG_ADMIN_CHAT 未設則 no-op）
        ↓
commit-back 狀態檔（[skip ci] update bot state）
```

**核心設計：State + Idempotency + Full Scan**（非 Queue / Event Bus）。

**推播可靠性（Never-Miss）**：六種推播（early / pregame / postgame / daily / awards / reconcile）全部 **success-gated**——送出成功才 `mark`，失敗不 mark、下一個 tick 自動重送至成功（partial failure 逐場隔離）。賽後驗證為 **event-driven**（賽果 `completed` 當下那個 tick 即推，**非固定 30 分鐘**）。漏推原因可由 obs log 診斷（`postgame.no_result` / `not_completed` / `verify_none` / `evict_stale`）；超過 recovery boundary 仍漏 → `push_reconcile` 發 admin 告警。不重複：`is_pushed` flags + concurrency 序列化。詳見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

-----

## 🔄 預測流程

```
建立賽事池 → 去Vig → Poisson/常態 比分模型 → 蒙特卡羅 → Edge → Truth Gate → Render → Telegram → save_prediction →（賽後）逐場 Verify → Postgame Push
```

| 段別 | 觸發 | 標題 |
|---|---|---|
| Early 早推 | 賽前 12h（`EARLY_WINDOW_MIN=720`） | 🕐 賽前12小時預測 |
| Pregame 最終 | 賽前 40m（`PREGAME_WINDOW_MIN=40`） | ⚡ 賽前 40 分鐘 |
| Postgame 賽後 | 賽果 `completed=true`（逐場即時） | 📊 賽後結果 |

賽前兩推成功皆 `save_prediction` 落盤 → 賽後驗證不依賴 40m 窄窗命中。

> ⚙️ 註：上述時間窗、刷新時點、過期門檻等**運行參數**皆定義於 `src/constants.py`（如 `EARLY_WINDOW_MIN` / `PREGAME_WINDOW_MIN` / `POSTGAME_WINDOW_MIN` / `REFRESH_HOURS_TW`），文件數值為當前預設、可依部署調整。**All values are runtime-config driven and may vary per deployment.**（測試數等 repo 事實不在此列。）

-----

## 🧩 Overlay 層（addon，不碰核心）

- **⚽ 總進球數（單場）**：只讀既有 `lambda_home/away`，Poisson(λ_total) 分桶，依機率排序顯示。**僅足球（FIFA）顯示**；棒球（MLB）、籃球（NBA）不顯示（總進球分布僅對足球有意義）。不改 score_model/MC/Edge。
- **📅 每日戰報：當天賽事全驗證完 + 距最近驗證 ≥30 分，推一則「本日總命中＋各球類命中率」；只讀 verified_history + weekly_games；每日冪等（flags `daily-YYYYMMDD`）；掛 `main()` tick 之後，不碰逐場賽後。`worldcup_batch.py` 已 dormant（`main()` 不再呼叫）。
- **📊 Audit Engine（Phase 2 · 可觀測層）**：唯讀 KPI 報表（依運動/盤口分組命中率、平均報酬、樣本不足警示）；只讀 `normalized_verified_view()`，**不碰核心、不寫狀態、不進推播路徑**。

-----

## 🧠 回饋觀測層（Feedback / Observability）

執行核心（本專案版本 **V0**）已凍結；其上**加一層唯讀的資料回饋與觀測**，不碰任何核心模型：

- **Phase 1 — 資料合約層（truth）**：`verified_history.csv` 擴充為 **21 欄完整回饋事件**（ML / AH / OU / 比分 / 總進球 / 信心 / Edge / 預期vs實際總分 / phase…），由 `verified_enrich.py` 在賽後驗證時補寫（additive、缺值留空、不 backfill）。`normalized_verified_view()` 為分析**唯一入口**（統一 schema、缺值＝None）。
- **Phase 2 — 智能/觀測層（analysis）**：`audit_engine.py` 為 baseline KPI；`bias_detector / calibration_tracker / learning_signal` 為設計就緒、**待資料累積（每運動 ≥100 場）才實作**。
- **治理**：所有分析只讀不改；任何模型調整需 Audit→回測→人工確認（詳見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)）。

-----

## 📂 狀態檔（repo as DB）

| 檔案 | 功能 |
|---|---|
| `weekly_games.json` | 48h 賽事池 + 三盤口賠率快取 |
| `flags.json` | 推播狀態（每場 early / pre / post） |
| `predictions.json` | 預測快照（賽後驗證唯一素材來源） |
| `verified_history.csv` | 賽後完整回饋紀錄（**21 欄 truth layer**；分析經 `normalized_verified_view()`） |
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
- 不建立球員資料模型推估個人獎項；目前僅顯示市場隱含機率，若無盤口則 N/A，不生成任何預測。
- 不生成未驗證機率模型（缺資料一律 N/A，永不捏造）。
- 不修改核心：score_model / monte_carlo / prediction_engine / kelly / Edge / Risk / result_verifier（含 `main_direction`）。新功能一律 additive overlay。

-----

## 🧪 測試 & 部署

- `pytest -q` → **248 passed**；CI 必須全綠才可 merge。
- **Secrets**：`ODDS_API_KEY_1`(必)、`ODDS_API_KEY_2`、`TG_TOKEN`(必)、`TG_CHAT`(必)、`TG_ADMIN_CHAT`(選；設了才啟用漏推告警，未設則 no-op)；`bot.yml` 須 `DRY_RUN: "false"`（未設預設 true＝只 log）。
- **Deployment status**：All overlay modules have been merged into the production branch. Refer to Git history for implementation details.

-----

## ⚠️ 免責聲明

本系統為統計模型分析工具，輸出為方向參考，**非投注獲利保證、非 +EV 投注建議**。請理性評估、自負盈虧，並遵守所在地區法律。
