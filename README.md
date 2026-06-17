# 🎯全自動體育賽事預測系統sports-prediction-bot

全自動體育賽事預測機器人。透過 GitHub Actions 定期（每 5 分鐘）自動執行：建立賽事池 → 統計／機率模型預測（去Vig + Poisson/常態 + 蒙特卡羅）→ 推播 Telegram → 賽後逐場驗證命中 → 累積賽後驗證紀錄（verified_history）。

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-自動排程-2088FF?logo=github-actions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)

> 狀態：**Release Candidate**（核心完成；overlay bundle 待合併 + scheduler 待上線 → Production Ready）。測試 **178 passed**。
> 支援：⚾ MLB · 🏀 NBA · ⚽ FIFA。
> 註：`xgboost` 列於 requirements 但**目前未啟用**（保留為未來擴充），現行預測不依賴它。

-----

## 📱 推播畫面（全部）

### ① 賽前 40 分鐘（最終投注參考）

```
🎯 精算師預測系統
⚡ 量化預測模型（賽前 40 分鐘）
━━━━━━━━━━━━━━━━
📅 台灣時間 06/17 08:11
⚾ MLB
Detroit Tigers 🆚 Houston Astros
━━━━━━━━━━━━━━━━
📐 去Vig真實勝率
Detroit Tigers  ████░░░░░░  39.3%
Houston Astros  ██████░░░░  60.7%
蒙特卡羅模擬勝率
Detroit Tigers  ██░░░░░░░░  24.4%
Houston Astros  ██████░░░░  63.1%
━━━━━━━━━━━━━━━━
📊 Edge（模型優勢）
Detroit Tigers -2.5%
Houston Astros -2.3%
━━━━━━━━━━━━━━━━
🏆 最可能出現的比分
🥇 Houston Astros 4–3 Detroit Tigers（3.8%）
🥈 Houston Astros 5–3 Detroit Tigers（3.8%）
🥉 Houston Astros 4–4 Detroit Tigers（3.3%）
4️⃣ Houston Astros 5–4 Detroit Tigers（3.3%）
5️⃣ Houston Astros 4–2 Detroit Tigers（3.2%）
━━━━━━━━━━━━━━━━
📊 盤口深度分析
讓分盤口     Houston Astros -1.5
總分大小     8.5
獨贏賠率
Detroit Tigers:2.48
Houston Astros:1.61
━━━━━━━━━━━━━━━━
💰 台灣運彩實戰建議
🔮【主推】獨贏盤 → Houston Astros 勝出
💎【次要】總分大小 → 小分(8.5)
⭐【備選】讓分盤 → Houston Astros(-1.5)
📡 數據來源：AI模型+真實數據+賠率
⚠️ 請理性投注。
```

> 註：**「⚽ 總進球數預測」只會出現在足球（FIFA）推播**；棒球（MLB）、籃球（NBA）不顯示（如上方 MLB 範例即無此區塊）。

### ② 賽前 12 小時（早盤觀察）

與 40 分鐘版**逐字相同**，僅標題不同：

```
🕐 量化預測模型（賽前 12小時預測）
```

### ③ 賽後結果（event-driven，逐場）

```
📊 賽後結果
📅 台灣時間 06/17
Detroit Tigers vs Houston Astros
━━━━━━━━━━━━━━━
預測：Houston Astros 勝出
實際：Houston Astros 勝出
結果：✅ 命中
━━━━━━━━━━━━━━━
命中結果：1 / 1（100%）
方向命中率：1 / 1（100%）
━━━━━━━━━━━━━━━
獨贏：✅
精準比分：N/A
讓分：N/A
大小分：N/A
────────────────
📊 模型表現
- EV預測準確性：✔ 正向
- Edge命中：✔ 命中
────────────────
📌 預測模式：量化分析
```

> 驗證的是「賽前主推方向」（MC argmax，與賽前 🔮主推同源）。未命中 → `結果：❌ 未命中`。精準比分／讓分／大小分目前一律 N/A（未獨立驗證，不捏造）。

### ④ FIFA 世界盃批次彙整（每 4 場已驗證 FIFA）

```
🏆 FIFA 世界盃戰況（批次彙整）
📦 第 1 批（每 4 場已驗證）
━━━━━━━━━━━━━━━━
f1 ✔
f2 ❌
f3 ✔
f4 ❌
━━━━━━━━━━━━━━━━
📊 本批次命中：2 / 4
📈 平均報酬：-21.3%
🎲 冷門場數（賽前真實勝率<50%一方獲勝）：2 / 4
━━━━━━━━━━━━━━━━
📌 資料來源：verified_history（賽後驗證真實結果）
```

> 仍在賽事池中的場會補上隊名，否則顯示 game_id（資料中無隊名時不捏造）。

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
   └─ worldcup_batch           （每 4 場 FIFA 已驗證 → 批次彙整）
        ↓
commit-back 狀態檔（[skip ci] update bot state）
```

**核心設計：State + Idempotency + Full Scan**（非 Queue / Event Bus）。

-----

## 🔄 預測流程

```
建立賽事池 → 去Vig → Poisson/常態 比分模型 → 蒙特卡羅 → Edge → Truth Gate → Render → Telegram → save_prediction →（賽後）逐場 Verify → Postgame Push
```

|段別         |觸發                             |標題         |
|-----------|-------------------------------|-----------|
|Early 早推   |賽前 12h（`EARLY_WINDOW_MIN=720`） |🕐 賽前 12小時預測|
|Pregame 最終 |賽前 40m（`PREGAME_WINDOW_MIN=40`）|⚡ 賽前 40 分鐘 |
|Postgame 賽後|賽果 `completed=true`（逐場即時）      |📊 賽後結果     |

賽前兩推成功皆 `save_prediction` 落盤 → 賽後驗證不依賴 40m 窄窗命中。

-----

## 🧩 Overlay 層（addon，不碰核心）

- **⚽ 總進球數（單場）**：只讀既有 `lambda_home/away`，Poisson(λ_total) 分桶，依機率排序顯示。**僅足球（FIFA）顯示**；棒球（MLB）、籃球（NBA）不顯示（總進球分布僅對足球有意義）。不改 score_model/MC/Edge。
- **🌍 WorldCup Batch**：每 4 場已驗證 FIFA 推一則彙整（命中率/平均報酬/冷門數）；只讀 verified_history；冪等（`worldcup_state.json`）；掛 `main()` tick 之後，不碰逐場賽後。

-----

## 📂 狀態檔（repo as DB）

|檔案                    |功能                         |
|----------------------|---------------------------|
|`weekly_games.json`   |48h 賽事池 + 三盤口賠率快取          |
|`flags.json`          |推播狀態（每場 early / pre / post）|
|`predictions.json`    |預測快照（賽後驗證唯一素材來源）           |
|`verified_history.csv`|賽後驗證紀錄（累積命中率）              |
|`key_state.json`      |Odds API 金鑰輪替 / cooldown   |
|`worldcup_state.json` |WorldCup batch 已處理場數（冪等）   |

-----

## 🛡️ Recovery（為什麼不會漏）

1. **tick 全掃描**：每次掃全部賽事，補齊「在窗內、未推」的場。
1. **冪等**：`is_pushed(gid, phase)` 防重複（重複 tick ≠ 重複推播）。
1. **scheduler 失敗自癒**：某次沒跑，下次 tick 補齊。
1. **賽後保底**：early 成功即落盤 → 不依賴 40m 窄窗。

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

- `pytest -q` → **178 passed**；CI 必須全綠才可 merge。
- **Secrets**：`ODDS_API_KEY_1`(必)、`ODDS_API_KEY_2`、`TG_TOKEN`(必)、`TG_CHAT`(必)；`bot.yml` 須 `DRY_RUN: "false"`（未設預設 true＝只 log）。
- **Overlay bundle**（新分支 + PR，CI 綠才 merge）：
  `src/notifier.py`(覆蓋)、`src/sports_prediction.py`(覆蓋)、`src/total_goals.py`(新)、`src/worldcup_batch.py`(新)、`tests/test_total_goals.py`(新)、`tests/test_worldcup_batch.py`(新)、`tests/test_postgame.py`(保留)。

-----

## ⚠️ 免責聲明

本系統為統計模型分析工具，輸出為方向參考，**非投注獲利保證、非 +EV 投注建議**。請理性評估、自負盈虧，並遵守所在地區法律。