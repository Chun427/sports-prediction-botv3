# 🎯 精算師預測系統 · sports-prediction-bot

以 **GitHub Actions 為核心的賽事分析狀態機**。每 15 分鐘自動執行一次 runtime tick：

> 建立賽事池 → 時間窗判定 → 賽前推播（idempotent）→ 狀態落盤

支援運動：**NBA、MLB、FIFA 世界盃**

> ⚠️ **目前進度**：fetch → pool → 時間窗 → idempotency → Key Pool → cooldown → **市場隱含預測** → **Score Model（Poisson/Normal）** → **Monte Carlo 模擬** → **Output（model-driven render）** 全鏈路已完成。`DRY_RUN=false` + TG secrets 啟用真實推播。Kelly/Risk、result_verifier（moneyline truth loop）已實作。XGBoost 未實作。觸發層建議以外部排程打 `workflow_dispatch`（GitHub schedule 為 best-effort 備援）。

---

## 🧠 Model Architecture（模型架構）

> **UI is not a source of truth. Model outputs are authoritative.**
> Render 層為**純 formatter**：只消費模型輸出、**不生成任何數據**；模型無輸出 → 該 section 隱藏（不 fallback、不捏造）。

分層：**odds → probability → score model → Monte Carlo → render**

| 層 | 模組 | 職責 | 真實來源 |
| --- | --- | --- | --- |
| Odds 抓取 | `data_fetcher` | h2h + totals + spreads（`ODDS_MARKETS="h2h,totals,spreads"`） | The Odds API |
| 機率層 | `prediction_engine` | h2h 去 Vig → `fair_prob` / `edge` / `best_pick` | h2h odds |
| 比分模型 | `score_model` | sport-aware：FIFA/MLB → Poisson（λ from totals+spreads）；NBA → Normal margin（**無精準比分**） | totals（λ）+ spreads（supremacy） |
| 蒙地卡羅 | `monte_carlo_engine` | 由 score_model 的 λ 模擬 → 勝/平/負分布 + 比分分布 | score_model 輸出 |
| Render 層 | `notifier` | 純 formatter，只組裝模型輸出 | 上游模型 |

**不變式（NON-NEGOTIABLE）**
- **λ 只來自市場真實資料**：totals 線 = 預期總分；spreads = 分差（supremacy）。無 totals → 無模型 → render 隱藏 MC/比分 section。
- **Poisson 僅用於低分運動**（足球進球 / 棒球得分）；**NBA 不套 Poisson 比分**（改 Normal margin，只輸出勝率，不產精準比分）。
- **MC 收斂驗證**：Monte Carlo 勝率必須收斂回 score_model 的 analytic 機率（測試強制誤差 < 0.03）。
- **禁止**：硬編數字、用 h2h 反推 λ（資訊循環）、對 NBA 產精準比分、缺模型時填 placeholder 文字。

---

## 🧾 UI Output Contract（固定輸出契約）

> **UI is a fixed output contract. Render layer is NOT allowed to remove or hide sections. Missing data must display `N/A`, not omit.**

- Render 為 **deterministic**：版面、順序、emoji、標題固定，**不得條件式隱藏 section**、不得簡化、不得有替代格式。
- 缺資料時：MC / Score / Odds / Spread / Total 一律顯示 `N/A`（**N/A 是誠實的「無資料」，不是捏造數字**）。
- 三個模板（pregame / postgame / weekly）的 section 順序由 `tests/test_ui_contract.py` 快照鎖定；任何改動版面都會讓測試失敗（= contract enforcement，CI 會擋）。
- 誠實邊界（刻意的 `N/A`，非缺工）：
  - **NBA 無精準比分** → 比分區 `N/A`（統計上不產生 NBA exact score）。
  - **次要/備選建議 `N/A`** → 模型 λ 校準自市場 totals/spreads，與盤口一致 → 無大小/讓分 edge。
  - **postgame 命中分母 = 實際已驗證項數**（目前僅獨贏）→ 不灌成 `/4`；精準比分/讓分/大小分為 `N/A`。
  - **weekly 大小盤/讓分/Kelly/Edge偏差 `N/A`** → 尚未追蹤這些命中率。

> **推播閘門（truth gate）與 render 分層**：UI 是固定 contract（presentation），但「**一則訊息該不該發**」由 pipeline 的 truth gate 決定（balanced 規則）：**有 +EV 標的(`best_pick`) 或 有可用模型(`score_model`，即 totals 在) 才發；兩者皆無 → skip**（不送全 N/A 空訊息，log `push.skip_no_actionable`）。這讓「訊息發出 = 真訊號」與「版面固定完整」兩個目標並存。

---

## 🧩 系統定位：GitHub Actions 狀態機

| 角色 | 載體 | 職責 |
| --- | --- | --- |
| 驗證層（CI） | `.github/workflows/ci.yml` | push / PR / 手動 → 跑 `pytest -q` |
| Runtime 排程 | `.github/workflows/bot.yml` | `schedule */15` + 手動 → 跑 runtime tick |
| 持久狀態層（repo as DB） | repo 內 JSON | 跨 run 保存狀態，由 bot commit-back |

CI 與 Runtime **完全分離**：CI 只驗證程式碼、不跑 bot；bot 只跑 runtime、不跑測試。

---

## 🗄️ 狀態模型（repo as database）

GitHub Actions runner 是無狀態的（跑完即清空），因此狀態必須 **commit-back** 回 repo 才能跨 run 保留。

| 檔案 | 用途 |
| --- | --- |
| `weekly_games.json` | 賽事池快取（pool cache）+ `updated_at` |
| `flags.json` | 推播 idempotency 追蹤（每場每階段是否已推） |
| `key_state.json` | API Key cooldown 狀態（只存 env 名 + 到期時間，**不存金鑰本體**） |

commit-back 規則：僅當狀態有差異才 commit，commit message 含 `[skip ci] update bot state`，**絕不產生 empty commit**。

---

## ⏰ Runtime 排程

```text
schedule: "*/15 * * * *"   # 每 15 分鐘（UTC；內部轉 TW）

tick()
 → ensure_pool        # 48h 賽事池：刷新時段抓取 /odds（h2h）/ 其餘讀快取（slot guard）
 → run_pregame_push   # 賽前窗 0 ≤ (開賽 - now) ≤ 40 分鐘
 → predict(game)      # 去 Vig → 共識勝率 → Edge；None → [SKIP_NO_PREDICTION] 不推
 → KeyManager         # KEY1/KEY2 + 60 分 cooldown + 429/配額耗盡處理
 → log-only pusher    # [DRY_RUN_PUSH] game_id=xxx would_send=True | fair … best_pick …
 → commit-back state  # flags / weekly_games / key_state
```

**賽事池刷新（每日四次）**：台灣時間 `00:00 / 06:00 / 12:00 / 18:00` 抓取「未來 48 小時」賽事；非刷新時段一律讀本地快取、不重抓。同一刷新小時內以 `updated_at` 做 slot guard，只刷一次。

**為何 `*/15`**：賽前窗寬 40 分鐘 > tick 間隔 15 分鐘 ⇒ 任一場的賽前窗內必含 ≥2 個 tick，數學上不會整場漏窗（取代舊的每小時排程）。

---

## 🔁 Idempotency Flow

```text
tick 落在賽前窗（0–40 分）
        │
        ▼
  is_pushed(game_id,'pre')? ──Yes──► 跳過（不重推）
        │No
        ▼
  log-only pusher → return True
        │
        ▼
  mark_pushed(game_id,'pre')  ← 送出即落盤（atomic write）
        │
        ▼
  commit-back flags.json
```

窗內會有 2–3 個 tick，靠 `flags.json` 去重；順序固定 **送出 → 成功才標記**（較安全的失敗方向是「最多重推一次」，而非靜默漏推）。

---

## 🔑 Key Pool & Cooldown

| 規則 | 行為 |
| --- | --- |
| 預設 | 優先使用 `ODDS_API_KEY_1` |
| KEY1 遇 **429** 或 **配額耗盡** | 標記 60 分鐘 cooldown，切換 `ODDS_API_KEY_2` |
| 配額耗盡判定 | HTTP 429 ／ `x-requests-remaining ≤ 0` ／ 401 + usage/quota 訊息 |
| cooldown 恢復 | 每次呼叫前以 `now ≥ cooldown_until` 重算；到期即自動恢復、KEY1 重回優先（無人工介入） |
| 兩把都不可用 | `raise AllKeysUnavailable` → `tick()` 捕捉 → 跳過本輪 |

cooldown 狀態存於 `key_state.json`，跨 run 由 commit-back 持久化。

---

## 📈 Processing（market-implied，MVP 切片）

從 The Odds API `/odds` 端點抓 **h2h moneyline**（`markets=h2h`、`regions=us`、`oddsFormat=decimal`），由 `prediction_engine` 產生市場隱含預測：

| 步驟 | 方法 |
| --- | --- |
| 去 Vig | 乘法歸一（multiplicative）：`implied_i = 1/odds_i`，`fair_i = implied_i / Σ implied` |
| 共識 | 多家各自去 Vig 後，每個 outcome 取平均（2-way 或 3-way 皆適用） |
| 最佳賠率 | 各 outcome 跨家最高 decimal odds |
| **Edge (EV)** | `best_odds × fair_prob − 1`；`best_pick` = 最大且 > 0 者 |

> ⚠️ **Edge 語意**：這是「最佳賠率 vs 多家共識公平機率」的**市場價值/比價** edge，**不是**「模型 vs 市場」的預測性 edge（MVP 尚無模型）。prediction schema 以 `model="market_implied_v1"` 標記版本；未來把共識機率換成 Monte Carlo/XGB 模型機率，同一公式即升級為預測性 edge。

**No Prediction Available 規則**：`predict(game)` 回 `None`（無有效 h2h 市場）時 → **不推播、不 `mark_pushed`、idempotency 狀態不變**，輸出 `[SKIP_NO_PREDICTION] game_id=… reason=no_valid_h2h_market`，視為正常 Safe Skip（非錯誤、不影響其他比賽）。

**配額成本**：`h2h × us = 1 credit/次`，一次呼叫回該運動所有賽事 → `3 運動 × 4 刷新 = 12 credits/天 ≈ 360/月`（免費 500/月內；KEY2 第二帳號可再翻倍餘裕）。

**賽果抓取（C-2，truth loop）**：`fetch_scores(sport, event_ids)` 打 `/scores?daysFrom=1&eventIds=<batch>&dateFormat=iso`，成本 **2 credits/次**（daysFrom 含完賽）。用 `eventIds` 批次只撈我們預測過的 pending（與 `/odds` 同一套 32 字元 id），回 `{id: {completed, home/away_score, last_update, ...}}`；`event_ids` 空則不發請求。兩把 key 不可用 → `AllKeysUnavailable` 上拋,由 tick 跳過 post 路徑。

---

## 📤 Output（Telegram Notifier，DRY_RUN 分流）`notifier` 維持 business ≠ IO：`render_pregame()`（純函式，Output Contract）與 `TelegramSender.send()`（注入式 IO）分離。

**DRY_RUN 分流**

| 模式 | 行為 | 必填 secrets |
| --- | --- | --- |
| `DRY_RUN=true`（預設） | 渲染模板並輸出到 log，**不送 Telegram** | `ODDS_API_KEY_1` |
| `DRY_RUN=false` | 真實 Telegram 推播 | `ODDS_API_KEY_1` + `TG_TOKEN` + `TG_CHAT` |

**Fail-fast（TD2）**：啟動時檢查必填 secrets，缺則**直接非 0 退出**（不再以 graceful skip 取代設定錯誤）。此與執行期「key 有設但 429/cooldown 耗盡 → AllKeysUnavailable 跳過」不同。

**送出失敗處理**：retry 3 次 → `obs.alert`（log 層告警）→ 回 False（不 `mark_pushed`，由下個 tick 經 idempotency 重試，不在 call 內 loop）。

### Output Contract `pregame_v1`

```text
🎯 精算師預測系統 — 賽前分析
NBA｜客 Celtics vs 主 Lakers
開賽：2026-06-11T10:30:00+08:00（台灣時間）

📐 市場隱含勝率（去 Vig 共識・5 家）
  主 Lakers：56.1%
  客 Celtics：43.9%
  平均抽水：4.5%

💰 最佳賠率（跨家）
  主 1.85 ｜ 客 2.3

💎 價值分析（Edge = 最佳賠率 × 共識勝率 − 1）
  ▶ 主 Lakers　edge +3.8% @ 1.85

🔖 模型：market_implied_v1
⚠️ 本訊息為統計分析，非投注建議。請理性使用，僅投入可承受損失之資金。
```

`v1` 僅含 market-implied 欄位；🎲 蒙地卡羅勝率、💰 Kelly、📋 Top5 比分為**預留擴充段**（B 完成時插入，不動 v1 既有欄位）。

---

## 🔁 Decision（Truth Loop，建置中）

讓系統從「會預測」變成「可評估」。三段已完成、一段待做：

- **C-1 snapshot（✅）**：pre-push 成功落盤 `predictions.json`（by game_id，git tracked，DRY_RUN 也存）。
- **C-2 fetch_scores（✅）**：`/scores?daysFrom&eventIds` 批次抓賽果（與 /odds 同一套 id）。
- **C-3 result_verifier（✅，純函式）**：`verify(prediction, result)` → moneyline 命中 + EV 實現 + 單場市場偏差（`fair_prob_winner`）。不做 spread/totals/exact-score（未預測）。
- **C-4 賽後整合（✅）**：`run_postgame_verify` 在 tick 中與 pre 路徑**獨立 fail-safe**——抓賽果 → verify → `render_postgame`（postgame_v1，DRY_RUN 分流）→ `mark_pushed('post')` → 封存 `verified_history.csv`（git tracked）→ 移除 pending。觸發採「completed 且未驗」（D-C3 寬鬆）；過期 pending 依 `PENDING_STALE_HOURS` 驅逐（TD11）。

Truth loop 完整：`predict → render_pregame → snapshot → fetch_scores → verify → render_postgame → verified-history`。

---

## 🛡️ Fail-safe Matrix

> 原則：寧可不準（甚至跳過一次），也不能掛掉。

| 情境 | 降級行為 |
| --- | --- |
| KEY1 429 / 配額耗盡 | cooldown 60 分 + 切 KEY2 |
| 兩把 Key 都不可用 | `AllKeysUnavailable` → tick 跳過本輪 |
| `key_state.json` 毀損 | 降級為「全部可用」 |
| 壞 event record | Safe Skip（跳過該筆，不影響其餘） |
| 賽事池刷新失敗 | 不覆蓋快取、不續推、跳過本輪 |
| pusher 失敗（回 False） | 不標記，下個 tick 重試 |
| 非刷新時段 | 讀快取、不抓 |
| 必填 Secrets 缺失 | **Fail Fast（非 0 退出）** |
| Telegram 送出失敗 | retry 3 次 → obs.alert → 回 False（下個 tick 重試） |
| 無有效 h2h 市場（predict→None） | Safe Skip：不推、不 mark、[SKIP_NO_PREDICTION] |

---

## ⚙️ Workflow

**Trigger matrix**

| Workflow | push(main) | pull_request(main) | workflow_dispatch | schedule `*/15` |
| --- | --- | --- | --- | --- |
| `ci.yml` | ✓ pytest（忽略狀態檔） | ✓ pytest | ✓ | ✗ |
| `bot.yml` | ✗ | ✗ | ✓ | ✓ runtime tick |

`ci.yml` 對 `flags.json` / `weekly_games.json` / `key_state.json` 設 `paths-ignore`，避免 bot 的狀態 commit 觸發 CI。

**Secret matrix**

| Secret | ci.yml | bot.yml | 必填 |
| --- | --- | --- | --- |
| `ODDS_API_KEY_1` | ✗ | ✓ | ✓（缺則 fail-fast） |
| `ODDS_API_KEY_2` | ✗ | ✓ | 建議 |
| `TG_TOKEN` / `TG_CHAT` | ✗ | 僅 `DRY_RUN=false` | DRY_RUN 關時必填 |
| `DRY_RUN` | ✗ | ✓（預設 true） | ✗ |
| `DEBUG_API_SCHEMA` | ✗ | 選 | ✗ |

CI 全程使用 fake，不需任何 secret。

---

## 🔐 環境變數

| 變數 | 必填 | 說明 |
| --- | --- | --- |
| `ODDS_API_KEY_1` | ✅ | The Odds API 主金鑰 |
| `ODDS_API_KEY_2` | ⬜（建議） | 備援金鑰；缺時 Key Pool 退化為單把 |
| `DEBUG_API_SCHEMA` | ⬜ | `true` 時輸出 API schema 樣本（raw/parsed 各一次），production no-op |

> Telegram 相關變數待 Output 層完成後再加入。

GitHub Secrets 設定路徑：`Settings → Secrets and variables → Actions`，新增 `ODDS_API_KEY_1`（與選用的 `ODDS_API_KEY_2`）。

---

## 📁 專案結構

```text
sports-prediction-bot/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── flags.json              # 狀態：idempotency
├── weekly_games.json       # 狀態：賽事池快取
├── key_state.json          # 狀態：Key cooldown
├── .github/workflows/
│   ├── ci.yml              # CI only
│   └── bot.yml             # runtime only
├── src/
│   ├── constants.py        # 不可變契約 / 常數
│   ├── obs.py              # 結構化 log + schema_dump
│   ├── data_manager.py     # State 層（atomic JSON / CSV）
│   ├── data_fetcher.py     # Fetch 層（KeyManager + fetch_upcoming_games /odds）
│   ├── prediction_engine.py# Processing 層（去 Vig / 共識 / Edge，market-implied）
│   ├── notifier.py         # Output 層（render_pregame + TelegramSender + DRY_RUN）
│   └── sports_prediction.py# Integration（時間窗引擎 + runtime entry + validate_secrets）
└── tests/
    ├── test_core.py
    ├── test_time_window.py
    ├── test_data_fetcher.py
    ├── test_prediction_engine.py
    ├── test_notifier.py
    └── test_runtime.py
```

---

## 🚀 安裝與執行

```bash
git clone <repo-url>
cd sports-prediction-bot
pip install -r requirements.txt

# 初始化狀態檔（首次）
echo '{}'                          > flags.json
echo '{"games":[],"updated_at":""}' > weekly_games.json
echo '{}'                          > key_state.json

# 本機執行測試（全程 fake，不打真實 API）
pytest -q

# runtime tick（dry-run；真實 fetch 需有效 ODDS_API_KEY_1/2 與外網）
ODDS_API_KEY_1=xxx python src/sports_prediction.py push
```

---

## ⚠️ Disclaimer

本系統為數據分析與學習用途。所有輸出皆為統計模型結果，不構成任何投注建議或獲利保證。模型再精準，也無法消除莊家抽水（vig）、市場波動、傷兵資訊延遲與運動賽事的隨機性。請理性使用，並僅投入可承受損失的資金。
