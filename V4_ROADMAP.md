# V4 ROADMAP — 規劃（先規劃，不急著寫）

> 原則：全部 **additive overlay**，讀 `data_manager.normalized_verified_view()`，**不碰 Core**（見 RELEASE_NOTES 凍結清單）。
> 每階段都應：有資料才有意義（KPI 需每運動 ≥100 場）、無資料顯示 N/A、不捏造、附測試、CI 全綠。

---

## Phase 1 — 資料層 ✅ completed
- `verified_enrich`（21 欄 truth layer）、`data_manager` 正規化、`normalized_verified_view()`。
- 已上線，作為後續所有 V4 分析的單一資料來源。

## Phase 2 — Audit Engine（下一步）
- 目標：基於 `normalized_verified_view()` 算 KPI baseline（命中率 / 報酬 / 樣本數），分運動。
- 守門：`MIN_SAMPLE`（如 100）以下標「樣本不足」，不下結論。
- 已有 `audit_engine` baseline，本階段補完輸出與（選配）推播/報表。
- 不碰預測；純讀。

## Phase 3 — Calibration（校準）
- 目標：信心 vs 實際命中對照（reliability / Brier / Log Loss）。
- 輸出「模型是否過度自信/低估」，供人判讀。**不自動改模型參數**（避免破壞凍結核心）。

## Phase 4 — Bias Detector（偏差偵測）
- 目標：找系統性偏差（某運動/某盤口/主客場/讓分區間 長期偏一邊）。
- 輸出偏差報告；同樣只「指出」，不自動修正核心。

## Phase 5 — Learning Signal（學習訊號）
- 目標：把 Phase 2–4 的發現整理成「可行動訊號」（例如：某盤口長期負 EV → 建議停用該盤口顯示）。
- 仍是 overlay 決策輔助；任何要改核心行為的，需另立明確任務 + 人為核可。

## Phase 6 — Auto Report（自動報表）
- 目標：把 audit / calibration / bias 整理成定期（週/月/賽季）報表推播。
- 可順便把現有 orphan 的 `weekly_report` 接上 push（需週/賽季 idempotency 狀態）。
- 賽季篩選：2030 世足等新賽事用 sport key / 日期區間「篩選」，不砍歷史、不重算。

---

## 開發紀律（每個 Phase 共通）
- 新模組獨立檔 + 對應 `test_*.py`；不得修改 Core / tick / release_gate 行為。
- 先 Phase A（設計確認）→ Phase B（實作）→ Phase C（雙重驗證：working + 全新 clone）。
- 每次回報：diff summary + 改動檔列表 + pytest 結果。
