# 🎯 精算師預測系統（sports-prediction-bot）

一個**會自動推播到 Telegram 的 AI 賽事預測系統**。
它每 15 分鐘自動巡一次即將開打的比賽；當某場比賽進入「開賽前 40 分鐘」時，
系統會即時算出勝率、模擬比分、下注優勢，並把一張「預測卡」推播到你的 Telegram。

支援賽事：⚾ MLB、🏀 NBA、⚽ FIFA 世界盃。

---

## 這個系統幫你做什麼？

每當有比賽接近開打，它會自動：

1. 抓取多家博彩公司的賠率（獨贏、大小分、讓分）。
2. 去除博彩抽水，還原「真實勝率」。
3. 用統計模型（Poisson / 常態）+ 蒙特卡羅模擬，算出勝率分布與最可能比分。
4. 計算「下注優勢（Edge）」與「凱利建議下注比例」。
5. 只有在「有真正值得下注的訊號」時，才把預測卡推到你的 Telegram。

> 它不是亂猜，也不會無中生有：沒有資料的欄位一律標 `N/A`，不捏造數字。

---

## 推播畫面

    🎯 精算師預測系統
    ⚡ 量化預測模型（賽前 40 分鐘）
    ━━━━━━━━━━━━━━━━
    📅 台灣時間 06/14 09:10
    ⚾ MLB
    Giants 🆚 Dodgers
    ━━━━━━━━━━━━━━━━
    📐 去Vig真實勝率
    Giants  ████░░░░░░  42.0%
    Dodgers ██████░░░░  58.0%
    蒙特卡羅模擬勝率
    Giants  ██░░░░░░░░  24.7%
    Dodgers ██████░░░░  63.0%
    ━━━━━━━━━━━━━━━━
    📊 Edge（模型優勢）
    Giants -2.0%
    Dodgers +3.0%
    ━━━━━━━━━━━━━━━━
    🏆 最可能出現的比分
    🥇 Dodgers 4–3 Giants（3.8%）
    🥈 Dodgers 5–3 Giants（3.8%）
    🥉 Dodgers 4–4 Giants（3.3%）
    4️⃣ Dodgers 5–4 Giants（3.3%）
    5️⃣ Dodgers 4–2 Giants（3.2%）
    ━━━━━━━━━━━━━━━━
    📊 盤口深度分析
    讓分盤口     Dodgers -1.5
    總分大小     8.5
    獨贏賠率
    Giants:2.3
    Dodgers:1.72
    ━━━━━━━━━━━━━━━━
    💰 台灣運彩實戰建議
    🔮【主推】獨贏 → Dodgers（@ 1.72）
    💎【次要】N/A
    ⭐【備選】N/A
    ━━━━━━━━━━━━━━━━
    📊 風控資訊
    - Kelly：0.0%
    - Risk Level：低
    ━━━━━━━━━━━━━━━━
    📡 數據來源：AI模型+真實數據+賠率
    ⚠️ 請理性投注。

---

## 我需要設定什麼？

在 GitHub → Settings → Secrets and variables → Actions 加入：

| 名稱 | 用途 | 必填 |
| --- | --- | --- |
| `ODDS_API_KEY_1` | 賠率資料來源（The Odds API）金鑰 | 是 |
| `ODDS_API_KEY_2` | 第二把金鑰（備援，可不填） | 否 |
| `TG_TOKEN` | 你的 Telegram 機器人 token | 是 |
| `TG_CHAT` | 要推播的 Telegram 頻道 / 對話 id | 是 |

設定完成後系統會自動每 15 分鐘執行，不需要你手動操作。

---

## 開 / 關真實推播（DRY_RUN）

在 `.github/workflows/bot.yml` 裡：

- `DRY_RUN: "false"` → **真的推播到 Telegram**（正式運行）。
- `DRY_RUN: "true"` → **只寫 log、不送 Telegram**（測試管線用）。

---

## 常見問題

| 你看到的狀況 | 為什麼 | 怎麼辦 |
| --- | --- | --- |
| Actions 綠燈但 Telegram 沒收到 | 當下沒有比賽在「賽前 40 分鐘」內，或沒有值得下注的訊號（系統會合法地不推） | 等有比賽接近開打；或在某場開賽前約 30 分鐘手動 Run 一次 |
| 完全沒抓到比賽 | Odds API 金鑰沒設，或當月額度用完 | 檢查 `ODDS_API_KEY_1` 與 API 額度 |
| 想先測試但不想真的發訊息 | — | 把 `DRY_RUN` 設成 `"true"` |

---

## 運作原理（給想了解的人）

    抓賠率 → 還原真實勝率 → 比分模型 → 蒙特卡羅模擬 → 訊號判斷 → 產生推播卡 → 送 Telegram → 存檔

- **比分模型**：足球 / 棒球用 Poisson（低分賽事適用）；籃球用常態分布（不硬產精準比分）。
- **蒙特卡羅**：用模型參數模擬大量場次，得到勝率與比分分布。
- **訊號判斷（truth gate）**：只有「有正期望值標的，或有可用模型」時才推播，避免洗版。
- **資料即真相**：缺資料就顯示 `N/A`，永不捏造。

---

## 技術備註（維運用）

- 架構：GitHub Actions 狀態機；repo 內 JSON 當資料庫（runtime 自動 commit-back）。
- CI：`ci.yml` 跑 `pytest`（目前 171 passed）。
- Runtime：`bot.yml`，每 15 分鐘 + 可手動觸發。
- 模組：`data_fetcher` / `prediction_engine` / `score_model` / `monte_carlo_engine` / `notifier`（render）/ `sports_prediction`（主流程）。

> ⚠️ 本系統為統計分析工具，所有輸出僅供參考，不構成投注建議。請理性投注。
