# V3 Architecture & Production Operations

> 本文件為 V3 的**工程／維運**說明（pipeline、idempotency、fail-safe、cron、部署）。
> 使用者畫面與推播格式請見 `README.md`。本文件以 GitHub HEAD 實際程式碼為準。

## System Overview

V3 是一套 **rule-based probabilistic sports prediction system**：去 Vig（賠率正規化）→ Poisson／常態分布 → Monte Carlo 模擬 → Edge 計算 → 賽後真值驗證（Truth Gate）。**不使用任何 ML 訓練模型**。執行模型為 **GitHub Actions cron 週期觸發**，每次執行一個 `tick`，完成「建立賽事池 → 預測 → 推播 → 賽後驗證 → 每日戰報」並把狀態 commit 回 repo。

支援運動：FIFA（足球）、MLB（棒球）、NBA（籃球），以**單一 Core + 條件分流（Conditional Strategy Router）**處理運動差異，非三套獨立 Core。

## Architecture Diagram（文字版）

```
GitHub Actions (cron */5, concurrency-serialized)
        |
   main() -> validate_secrets -> tick(now)
        |
        |-- ensure_pool（weekly_games 滾動池；refresh slot 0/6/12/18）
        |       AllKeysUnavailable -> raise（不吞，下一 tick 重試）
        |-- run_pregame_push   (pre,  0-40 分)
        |-- run_early_push     (early,40-720 分)   成功才 mark；失敗->下一 tick 補
        |-- run_postgame_verify(post, completed)
        |
   addon overlays（guarded，不污染 core）
        |-- daily_report   （每日戰報）
        |-- awards_push    （FIFA-only 獎項；見 Known Limitations）
        |-- push_reconcile （漏推對帳 -> admin 告警，opt-in）
        |
   commit-back（flags / predictions / verified_history，[skip ci]）
```

## Pipeline Flow

- **Early push（賽前 12h）**：`40 < (start - now) <= 720` 分。每 tick 掃池，未成功推就送；**送成功才 mark_pushed(early)**，失敗不 mark -> 下一 tick 重送，直到成功或離開窗（交棒 40m）。
- **Pregame push（賽前 40m）**：`0 <= (start - now) <= 40` 分。同上，重送至 kickoff。
- **Postgame verify（賽後）**：pending 預測賽果 `completed==true` 且未驗 -> 驗證 -> render_postgame_eval -> 送 -> **成功才 mark_pushed(post)**。event-driven，重試至成功或開賽逾 PENDING_STALE_HOURS 驅逐。
- **Daily report（每日戰報）**：當日每場皆 settled（已驗證 OR 開賽逾 12h 過期）且距最後一次驗證靜置 >=30 分、當日未推 -> 送；**成功才 mark**（失敗下一 tick 重送）。daily-YYYYMMDD 冪等。
- **Reconcile overlay**：偵測「賽前 12h/40m 皆漏」「賽後過期未推」-> 發 admin 告警（opt-in，TG_ADMIN_CHAT 未設則 no-op）。最後一道保險，僅在 recovery boundary 後觸發、每場每類只告警一次。

## Data Model

- **weekly_games.json**：滾動賽事池。每 6 小時（TW 0/6/12/18）刷新；含 id/sport/home/away/start_time/賠率。
- **predictions.json**：賽前推播時寫入的預測快照（供賽後驗證對照）。
- **verified_history.csv**：賽後真值（Truth Gate）。每場驗證後追加 ML/AH/OU 命中（**比分命中 scoreline_hit 僅 FIFA**；台彩 MLB/NBA 無正確比分玩法 → None）與 verified_at。每日戰報與長期統計唯一來源。
- **flags.json / key_state.json**：冪等旗標與 API key 狀態。

資料流：weekly_games -> predictions（賽前）-> verified_history（賽後），以 game_id 串接，commit-back 持久化。

## Idempotency Design

- 每場每階段 is_pushed(game_id, stage) / mark_pushed(game_id, stage)。
- Stage 獨立、無 cross-phase collision：pre / early / post / alert-pregame / alert-postgame；每日為 daily-YYYYMMDD。
- **成功才 mark**（pre/early/post/daily/alert 皆然）-> 「重試到成功」內建。
- commit-back 持久化 flags，跨 tick 一致。

## Fail-safe Strategy

- **API key 全不可用**：ensure_pool 觸發 AllKeysUnavailable -> raise 不吞 -> 該 tick 失敗，下一 tick 重試（不用髒資料推播）。
- **賽後賽果抓取失敗**：只跳過該運動的 post，pre/early 不受影響。
- **Telegram 送出失敗**（timeout/500/network）：except -> obs.error -> 不 mark -> continue -> 下一 tick 重送。
- **partial failure**：單場例外不影響其他場。
- **addon 例外**：daily/awards/reconcile 皆 try/except 包裹，不影響 core tick。

## API Key Pool Mechanism

KeyManager 管理多把 Odds API key（ODDS_API_KEY_1 必、_2 選）。額度耗盡／失效自動切換；全部不可用 -> AllKeysUnavailable。狀態持久化於 key_state.json。

## Cron Schedule Design

- **執行**：cron "*/5 * * * *"（每 5 分鐘一個 tick）。
- **Concurrency**：group bot-runtime-<ref>、cancel-in-progress: false -> 同分支序列化、新 run 排隊不重疊 -> 配合冪等旗標，不會 double-push / commit 衝突。
- **Refresh slot**：池在 TW 0/6/12/18 刷新。
- **Commit-back**：[skip ci] 提交狀態檔，避免 CI 迴圈。

## Known Limitations

1. **GitHub 排程 best-effort**：高負載時 cron 可能延遲或整段跳過。app 層補推依賴 tick 有跑；整段沒跑無法自動補。建議外部 uptime-cron 冗餘觸發 workflow_dispatch（infra，非 code）。
2. **Awards push 目前無法送達**（FIFA-only 附加層）：aw_pusher 用 make_pusher(renderer=lambda m:m) 但傳字串 -> 送出時 AttributeError（被 try/except 接住）；且 mark_pushed 在 send 之前 -> 先標記、後失敗、永不重送。core pipeline 不受影響，但 awards 在修正前不會實際推播。列為非阻擋已知問題。
3. **40m 窗較窄**（約 8 個 tick）：高頻漏跑時較脆弱，仰賴外部冗餘觸發。
4. **無獨立分運動進階模型**：MLB/NBA 與 FIFA 共用市場+Poisson/常態路徑；進階校正屬未來 additive。
5. **無 ML**：樣本不足，刻意不導入。

## Production Deployment Notes

- **Secrets**：ODDS_API_KEY_1（必）、ODDS_API_KEY_2（選）、TG_TOKEN（必）、TG_CHAT（必）、TG_ADMIN_CHAT（選；設了才啟用漏推告警）。
- bot.yml 須 DRY_RUN: "false"（未設預設 true＝只 log 不送）。
- CI：ci.yml 跑 pytest -q（須全綠才可 merge）。
- 新功能一律 additive overlay；不改凍結核心邏輯；每次變更跑六道 QA gate。
