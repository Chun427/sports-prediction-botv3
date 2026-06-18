"""capability_registry.py — 系統能力的唯一事實來源（Rule 1）。

任何地方都不得寫死能力（禁止 `if champion:` / `if golden_boot:`）；一律查此 registry。
supported 預設保守 False（未經 API 實測不誇稱）；確認有資料後才改 True。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    supported: bool
    source: str | None        # 資料來源描述（例：odds_api_outrights）
    reason_if_na: str | None   # 不支援原因（supported=False 時填）


_REGISTRY: dict[str, Capability] = {
    "Champion":      Capability("Champion", True, "odds_api_outrights", None),
    "GroupWinner":   Capability("GroupWinner", False, None, "待 API 實測確認"),
    "Qualified":     Capability("Qualified", False, None, "待 API 實測確認"),
    "TopGoalscorer": Capability("TopGoalscorer", False, None, "Odds API 未確認提供，待 key 實測"),
    "GoldenBoot":    Capability("GoldenBoot", False, None, "同 TopGoalscorer outright，待實測"),
    "BallonDor":     Capability("BallonDor", False, None, "Odds API 不涵蓋此獎項 → 永久 N/A"),
}


def get(name: str) -> Capability | None:
    return _REGISTRY.get(name)


def is_supported(name: str) -> bool:
    c = _REGISTRY.get(name)
    return bool(c and c.supported)


def source_of(name: str) -> str | None:
    c = _REGISTRY.get(name)
    return c.source if c else None


def reason_if_na(name: str) -> str | None:
    c = _REGISTRY.get(name)
    if c is None:
        return "unknown capability"
    return c.reason_if_na


def all_capabilities() -> list[Capability]:
    return list(_REGISTRY.values())


def supported_capabilities() -> list[Capability]:
    return [c for c in _REGISTRY.values() if c.supported]
