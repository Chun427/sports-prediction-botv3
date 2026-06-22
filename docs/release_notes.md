# Release Notes — Time Window + API Optimization + Safe Failover

本版三項主要改進:賽前/早盤推播全快取化、Pool 刷新失敗安全退回、賽後驗證指數退避。
皆為 additive patch,未改動任何凍結核心(score_model / monte_carlo_engine / prediction_engine / result_verifier / kelly / market_lines / notifier render / data_fetcher)。

---

## 1. Early Push + Pre-match Push 全快取化
- `run_early_push()`(賽前 12 小時)與 `run_pregame_push()`(賽前 40 分鐘)**只消費 `weekly_games.json` 快取池**,不呼叫 Odds API。
- 預測由 `prediction_engine.predict(game)` 對 snapshot 內已嵌入的賠率做**確定性純計算**(market-implied),推播時不依賴即時 API。
- 結果:Early push、40 分鐘 push 在執行時 **0 次 Odds API 呼叫**。

## 2. Odds API 進入點(澄清)
全系統實際呼叫 Odds API 僅三處:

| 模組 | 用途 | 頻率 |
|---|---|---|
| Pool Refresh(`ensure_pool` → `fetch_upcoming_games`) | 刷新未來賽事 + 賠率 | TW 00/06/12/18,4 次/日(+ stale 自癒) |
| Post-game Scores(`run_postgame_verify` → `fetch_scores`) | 抓最終賽果 | 達「預估完賽 + 退避延遲」才抓 |
| Awards / Futures(`awards_push` → `tournament_futures` → `futures_fetcher`) | **冠軍 outright 市場 de-vig(市場隱含)**;金靴/金手套為 permanent N/A,不抓 | 冠軍 1 次/日(flags 冪等) |

> 註:Awards 目前**僅做冠軍 outright 市場的 de-vig**,**不含任何統計建模或校準**。金靴/金手套因 The Odds API 無對應 outright key,維持誠實 N/A。

不再依賴 Odds API 的路徑:Early push、40 分鐘 push、tick 預測層、render 層、每日戰報、漏推對帳。

## 3. Pool 刷新 Slot Guard + 安全退回
- 刷新僅在 TW 00/06/12/18;同一時段重入由 slot guard 擋下。
- **失敗退回(v8.6 根因修正)**:刷新時 `fetcher()` 因金鑰全不可用拋 `AllKeysUnavailable` 時——
  - 若本地有快取池 → **退回沿用快取續推**(log `pool.refresh_failed_use_cache`),不再跳過整輪;
  - 若完全無快取(冷啟動)→ 才向上傳遞跳過。
- 效果:金鑰暫時耗盡時,早盤/賽前推播仍能用快取賠率正常送出(修正先前「12 小時沒推」的根因)。

## 4. 賽後驗證指數退避
- 自開賽起的輪詢時機(FIFA 例,min_dur=100):**100 → 130 → 190 → 310 → 430 → 550 分**(+30/+60/+120,之後固定 +120)。
- 防止:賽中無謂輪詢、卡住的 pending 場每 tick 狂抓 scores、API 配額爆量。

## 5. State Layer(data_manager)
- 新增 `post_attempts` 欄位 + `bump_post_attempts()`;驅動賽後退避。
- **向下相容**:舊 snapshot 無此欄位 → 讀取預設 0;不覆蓋 `prediction` / `pre_pushed_at`。flags.json / predictions.json schema 無破壞性變更。

## 測試覆蓋
40 分鐘窗、15 分鐘 tick 覆蓋、slot guard、cache fallback、API fail-safe、idempotency、**backoff 排程 + gating**、end-to-end tick。**251 passed**(含本版新增 2 個退避測試)。

## API 用量(估算)
- 較未節流前約降 **60–80%**(估算,實際取決於方案 markets×regions 與當日場數)。
- 執行期大多為 cache-driven;API 僅用於:刷新、最終賽果、冠軍市場。

## 設計保證
推播時點的下注相關計算**不依賴即時 API**,全部 snapshot-driven + 確定性計算。
