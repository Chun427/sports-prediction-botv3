"""schema.py — MLB feature 蒐集的欄位定義（單一真相）。

原則：
- 欄位先定義齊全，蒐集分批上線；任何取不到的欄位一律 NA（不捏造）。
- 此模組純資料定義，零外部依賴、零 production import。
"""

from __future__ import annotations

NA = "NA"

# 欄位順序即 CSV 欄位順序（append-only 必須穩定，不得隨意重排）
COLUMNS: list[str] = [
    # --- 識別 ---
    "collected_at", "game_date", "game_pk", "team", "opponent", "home_away",
    # --- 先發投手 ---
    "sp_name", "sp_era", "sp_fip", "sp_xfip", "sp_whip", "sp_k_pct", "sp_bb_pct",
    "sp_hardhit_pct", "sp_barrel_pct",
    # --- 牛棚 ---
    "bp_era_season", "bp_era_7d", "bp_era_15d", "bp_innings_3d",
    # --- 打線 ---
    "bat_ops", "bat_wrc_plus", "bat_iso", "bat_babip", "bat_ops_last10", "bat_ops_last30",
    # --- 情境 ---
    "park", "rest_days", "weather_temp_c", "weather_wind_kph", "umpire",
    # --- 盤口（多為付費，先留欄位）---
    "open_ml", "closing_ml", "line_movement",
    # --- 結果對齊（與 verified_history 連結）---
    "actual_winner", "actual_total",
    # --- 蒐集診斷（哪些來源成功/失敗）---
    "source_status",
]


def empty_row() -> dict[str, str]:
    """產生一列全 NA 的列（保證每欄都有值，永不留空、永不假值）。"""
    return {c: NA for c in COLUMNS}


def coerce(value) -> str:
    """把任意值轉成 CSV 安全字串；None/空 → NA。"""
    if value is None:
        return NA
    s = str(value).strip()
    return s if s else NA
