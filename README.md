# 🎯全自動體育賽事預測系統 sports-prediction-bot

全自動體育賽事預測機器人，透過 GitHub Actions 定期（每 5 分鐘）自動執行：建立賽事池 → 統計／機率模型預測（去Vig + Poisson/常態 + 蒙特卡羅）→ 推播 Telegram → 賽後逐場驗證命中 → 累積賽後驗證紀錄（verified_history）。

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-自動排程-2088FF?logo=github-actions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)

> 狀態：**v0 stable baseline（Production / Observation Mode）**。核心 / 三推播 / 每日戰報 / 賽後驗證 / 漏推對帳 流程皆完成且運行。測試 **251 passed**。賽前/早盤推播以快取為基礎驅動、Pool 刷新失敗安全退回快取、賽後驗證指數退避。工程與維運細節見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/release_notes.md`](docs/release_notes.md)。
> 支援：⚾ MLB · 🏀 NBA · ⚽ FIFA。
> ⚙️ **部署可靠性建議（觸發層）**：GitHub Actions 的 `schedule` 為 best-effort，排程可能延遲或被丟棄。本專案 `bot.yml` 為 single-tick（每 5 分鐘一次乾淨執行）；賽前/早盤推播以**快取驅動 + 刷新失敗退回快取**為基礎，即使某次漏跑或金鑰暫時耗盡，下一個 tick 仍能用快取補推。若要更高送達保證，**可再加一個外部排程器**每 5 分鐘觸發 `workflow_dispatch`。Recommended: optionally add an external scheduler (cron-job.org or Cloudflare Worker) to trigger `workflow_dispatch` every 5 minutes. 推播本身為 idempotent + success-gated（重送不重複、送失敗才重試）。

---

## 📖 這個系統在做什麼？

每 5 分鐘自動跑一次，對「即將開賽」與「剛結束」的賽事做四件事：

1. **建立賽事池**：從 The Odds API 抓未來 48 小時的賽事與盤口，存成本地快取（一天刷新 4 次）。
2. **量化預測**：對盤口去除 vig（莊家抽水）得到公平勝率，再用 Poisson 比分模型 + 蒙特卡羅模擬，推導出比分分布、總進球、投注建議。
3. **分時推播 Telegram**：賽前 12 小時（早盤）與賽前 40 分鐘（最終）各推一次；推播格式固定、重送不重複。
4. **賽後驗證**：比賽結束後抓真實比分，逐場核對「賽前主推方向」是否命中，寫入 `verified_history.csv`，並彙整成每日戰報。

> 核心預測為 **市場去 Vig（market_implied_v1）**：只以真實盤口為輸入，不使用任何捏造的球隊實力/狀態 feature。這是刻意的誠實設計——寧可承認「目前是市場隱含模型」，也不無中生有。

---

## 📱 推播畫面長什麼樣

### ① 賽前推播（12 小時早盤 / 40 分鐘最終，版面相同）

> 下列數字為**版面示意**，實際由當下盤口 + 蒙特卡羅即時算出。

```
🎯 精算師預測系統
🕐 量化預測模型（賽前12小時預測）        ← 40 分鐘版顯示「賽前40分鐘預測」
━━━━━━━━━━━━━━━━
📅 台灣時間 06/26 10:00
⚽️ FIFA
Turkey 🆚 USA
━━━━━━━━━━━━━━━━
📊 勝率分析
去Vig真實勝率
Turkey 24.9% ｜ 平手 23.2% ｜ USA 51.9%

蒙特卡羅模擬勝率
Turkey 25.2% ｜ 平手 26.4% ｜ USA 48.4%
━━━━━━━━━━━━━━━━
🏆 最可能出現的比分
🥇 Turkey 0-1 USA（12.3%）
🥈 Turkey 1-1 USA（12.3%）
🥉 Turkey 0-2 USA（9.2%）
4️⃣ Turkey 1-2 USA（9.2%）
5️⃣ Turkey 0-0 USA（8.2%）
━━━━━━━━━━━━━━━━
⚽ 總進球數預測                          ← 僅 FIFA 顯示此段
🥇 2–3球（47%）
🥈 0–1球（29%）
🥉 4–5球（20%）
4️⃣ 6+球（4%）
🎯 最可能：2–3球
📊 平均：2.50球
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → USA 勝出
💎【次要】總分大小 → 小分(2.5)
⭐【備選】讓分盤 → USA(-0.5)
━━━━━━━━━━━━━━━━
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注
```

- **去Vig真實勝率**：盤口去抽水後的公平勝率。
- **蒙特卡羅模擬勝率**：Poisson 模型大量模擬後的勝率（與去Vig互為對照）。
- **主推/次要/備選**：主推＝獨贏方向；次要＝大小分；備選＝讓分（誠實顯示市場讓分方向）。

### ② 賽後驗證推播（單場）

> 賽後抓真實比分，核對賽前主推是否命中。

```
📊 比賽結果驗證（單場）
📅 台灣時間 06/26
⚽️ FIFA
Turkey 🆚 USA
📢 比賽結果                              ← 賽後真實最終比分（FIFA/MLB/NBA 通用）
Turkey 1-2 USA
━━━━━━━━━━━━━━━━
📋 比分預測
🎯命中：1/1（100%）
━━━━━━━━━━━━━━━━
💰 台灣運彩投注
🎯命中：…（獨贏/讓分/大小，命中 ✅ / 未中 ❌）
━━━━━━━━━━━━━━━━
📌 單場結論
🎯命中：…
```

### ③ 每日戰報

> 每日彙整當天所有已驗證賽事的命中表現。各市場結果並列（分母可不同）；比分僅統計 FIFA。

```
📅 今日戰報 06/30
━━━━━━━━
📊 本日總命中 25/49（51%）   ← 各市場 numerator/denominator 加總
獨贏 10/16（62%）
讓分  7/16（44%）
大小  5/14（36%）
比分  3/3（100%）            ← 僅 FIFA（MLB/NBA 無正確比分市場）
━━━━━━━━
⚽ 足球（3場）
🎯 整體命中率 7/12（58%）
獨贏 1/3（33%）
讓分 1/3（33%）
大小 2/3（67%）
比分 3/3（100%）
━━━━━━━━
⚾ 棒球（13場）
🎯 整體命中率 18/37（49%）
獨贏 9/13（69%）
讓分 6/13（46%）
大小 3/11（27%）             ← 無比分行（棒球無此市場）
━━━━━━━━
🏀 籃球（0場）
無已驗證資料                 ← 0 場顯式提示
━━━━━━━━
📡 數據來源：系統統計
```

---

## 🧱 架構（資料流）

```
The Odds API
   ↓  fetch_upcoming_games（抓未來 48h；slot guard：TW 0/6/12/18 一天 4 次刷新；其餘讀快取；刷新失敗退回快取）
Pool（weekly_games.json）
   ↓
├─ 12h 早盤推播 run_early_push    （賽前 40〜720 分鐘窗）         ← 快取驅動
├─ 40m 賽前推播 run_pregame_push  （賽前 0〜40 分鐘窗）           ← 快取驅動 +（可選）near_match_refresh
│      ↓ predict() 去 Vig（odds_h2h，market_implied_v1）
│      ↓ build_score_model()（odds_totals→λ；odds_spreads→supremacy；deterministic）
│      ↓ run_monte_carlo()（Poisson 模擬；無 cache）
│      ↓ 比分分布 / 總進球 / 投注建議
│      ↓ notifier render（純輸出，不計算）
└─ Telegram（idempotent：send → 成功才 mark_pushed）
   ↓
賽後逐場驗證 run_postgame_verify（指數退避）→ verified_history.csv
   ↓ postgame_formatter（賽後比分顯示，UI 層）
每日戰報 run_daily_report（Never-Miss 三層）
漏推對帳 run_push_reconcile（補核未推/漏推）
```

### 三個推播時點

| 時點 | 窗口 | 進入點 | 用途 |
|---|---|---|---|
| 早盤 | 賽前 40〜720 分（≤12h） | `run_early_push` | 方向性提示 |
| 最終 | 賽前 0〜40 分 | `run_pregame_push` | 最終預測（可選近賽刷新） |
| 賽後 | 完賽後 | `run_postgame_verify` | 真實比分驗證命中 |

> early 窗 `>40`、final 窗 `≤40`，**互不重疊**，同一 tick 不會同時觸發。

---

## 🆕 主要功能（皆 additive / 可 rollback / 可 flag 關閉）

- **近賽選擇性刷新（near_match_refresh）**：40 分鐘賽前窗，**只對「即將推播的那幾場」**重抓 2h 短窗最新盤口，再讓既有模型自然重算。
  > 啟用時 40m 推播**會**為近賽場呼叫一次 Odds API（短窗、量小、失敗自動退回快取）。設 `ENABLE_NEAR_MATCH_REFRESH=False` 即關閉，回到「推播時點純讀快取、不呼叫 API」。
- **賽後比分顯示（postgame_formatter）**：賽後加入真實最終比分（FIFA/MLB/NBA 通用，無比分不捏造）；notifier 核心格式不動。
- **每日戰報 Never-Miss**：主路徑（當日全部驗證完 + 靜置 30 分）→ 同日 23:30 保險 → 跨午夜補送。
- **FIFA 冠軍/個人獎項**：目前**停用**（`AWARDS_ENABLED=False`，可逆）；FIFA 單場賽事預測不受影響。

## 🧩 主要模組

| 模組 | 職責 | 備註 |
|---|---|---|
| `ensure_pool` | 賽事池 slot 刷新 / 讀快取 / 失敗退回 | 一天 4 次刷新，抓 48h |
| `prediction_engine.predict` | 市場去 Vig（market_implied_v1） | 凍結 |
| `score_model` / `monte_carlo_engine` | Poisson 比分 + 蒙特卡羅 | deterministic / 無 cache |
| `near_match_refresh` | 40m 近賽選擇性刷新 | flag / guarded / 只動目標場 |
| `notifier` | 三推播 render（純輸出） | 凍結格式 |
| `postgame_formatter` | 賽後比分 UI 層 | 不碰 notifier 核心 |
| `daily_report` | 每日戰報（Never-Miss） | — |
| `push_reconcile` | 漏推對帳 | — |
| `awards`（futures） | FIFA 冠軍/個人獎項 | **停用中（可逆）** |

## 🔒 設計原則（鐵律）

- **只用真實資料**：盤口 / verified_history / 真實 API 回應；任何取不到的值留 NA，**不捏造**。
- **核心凍結**：`predict`（market_implied_v1）、score_model、monte_carlo、notifier 格式不隨意更動。
- **Additive / Rollback / Flag**：新增功能皆獨立、可移除、可關閉，不影響既有流程。
- **idempotent 推播**：同場同階段只推一次；送失敗才重試。

## 🛡️ 資料治理（Data Integrity）

`verified_history.csv` 是**唯一真實來源（single source of truth）**，所有命中率 / 戰報 / 稽核皆依此。為避免「跨運動 schema 污染」，遵守以下規則：

- **跨運動隔離（Sport Isolation）**：`scoreline_hit`、`total_goals_hit` **僅 FIFA 有意義**。MLB/NBA 雖然 Poisson 也會產生 top_scorelines，但台彩無棒球/籃球的正確比分市場 → 這些欄位在非 FIFA 一律寫入 `None`（見 `verified_enrich._scoreline_hit` 的 `is_fifa` gate），避免污染下游 `daily_report` 顯示與 `audit_engine` 統計。
- **None-safe 聚合**：缺值一律 `None`，**永不當成 0**、永不回填歷史空缺。`audit_engine._avg` 會跳過 `None`，故非 FIFA 的比分不會稀釋全體指標。
- **特徵純度（Feature Purity）**：每個指標需「可獨立解讀、跨運動安全、重跑可重現」。未來任何運動擴充（NBA 進階數據、MLB props…）都不得污染 FIFA schema。
- **顯示層 vs 來源層**：`daily_report` 的 FIFA-only 過濾是顯示層防火牆；真正的源頭乾淨由 `verified_enrich` 保證。兩層都守。

## 🔭 觀察 / 待累積（Roadmap）

- **MLB 模型**：目前為 market-implied（無 feature 模型）。待 `verified_history` 累積 **300–500 場**後再評估離線特徵建模（投手 ERA/FIP、牛棚、打線…）；**唯有離線回測勝過現行模型才考慮上線，且版本化、不覆蓋**。
- **每日戰報**：Never-Miss 已部署，待實際 `daily-YYYYMMDD` flag 確認首次送出。
- **near_match_refresh**：上線後可由 `near_refresh.scan` / `near_refresh.applied` log 觀察刷新頻率與盤口漂移。

## 🧪 測試

```bash
pytest -q        # 251 passed
```
release_gate 通過。

## ↩️ Rollback 快速參考

| 想關掉的功能 | 做法 |
|---|---|
| 近賽刷新 | `ENABLE_NEAR_MATCH_REFRESH=False` |
| FIFA 冠軍/個人獎項 | `AWARDS_ENABLED=True` 可恢復（目前 False＝停用） |
| 其他 addon | 移除對應檔 + 還原呼叫點 |

## ⚠️ 免責聲明

本專案為統計／機率分析的技術專案，所有輸出僅為數據分析，**非投注建議**。請理性使用，僅投入可承受損失之資金。
