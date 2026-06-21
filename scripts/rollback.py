"""rollback.py — 安全快照 / 還原工具（狀態檔層級）。

用途：在套用任何 enhancement 前先 snapshot；若出事可一鍵還原「狀態檔」。

範圍（重要）：本工具只處理 commit-back 的「狀態檔」：
    weekly_games.json / predictions.json / verified_history.csv /
    flags.json / key_state.json
「程式碼」回滾請用 git（見下方），本工具刻意不做 git reset / checkout，
避免在非技術操作下誤刪 commit。

用法：
    python scripts/rollback.py snapshot         # 建立 snapshot/state_<UTC>.zip
    python scripts/rollback.py list             # 列出可用快照
    python scripts/rollback.py restore <zip>    # 從指定快照還原狀態檔（還原前會自動再備份一次）

程式碼回滾（用 git，不用本工具）：
    git log --oneline                      # 找最後一個穩定 commit
    git checkout <commit> -- src/          # 只還原程式碼
    # 或安全地反轉某個壞 commit（保留歷史）：
    git revert <bad_commit>
"""
from __future__ import annotations

import datetime
import glob
import os
import sys
import zipfile

_STATE_FILES = [
    "weekly_games.json",
    "predictions.json",
    "verified_history.csv",
    "flags.json",
    "key_state.json",
]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SNAP_DIR = os.path.join(_ROOT, "snapshot")


def _present() -> list[str]:
    return [f for f in _STATE_FILES if os.path.exists(os.path.join(_ROOT, f))]


def snapshot() -> str:
    os.makedirs(_SNAP_DIR, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(_SNAP_DIR, f"state_{ts}.zip")
    present = _present()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in present:
            z.write(os.path.join(_ROOT, f), f)
    print(f"[snapshot] 已建立 {os.path.relpath(path, _ROOT)}")
    print(f"[snapshot] 內含狀態檔：{present}")
    missing = [f for f in _STATE_FILES if f not in present]
    if missing:
        print(f"[snapshot] （略過不存在的檔：{missing}）")
    return path


def list_snapshots() -> list[str]:
    snaps = sorted(glob.glob(os.path.join(_SNAP_DIR, "state_*.zip")))
    if not snaps:
        print("[list] 尚無快照（先執行 snapshot）")
    for s in snaps:
        size = os.path.getsize(s)
        print(f"  {os.path.basename(s)}  ({size} bytes)")
    return snaps


def restore(zip_name: str) -> None:
    zip_path = zip_name if os.path.isabs(zip_name) else os.path.join(_SNAP_DIR, zip_name)
    if not os.path.exists(zip_path):
        print(f"[restore] 找不到快照：{zip_path}")
        print("[restore] 可用快照：")
        list_snapshots()
        return
    # 還原前先自動備份當前狀態（雙保險，避免還原後反悔無路）
    print("[restore] 還原前先備份目前狀態 ...")
    snapshot()
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        z.extractall(_ROOT)
    print(f"[restore] 已從 {os.path.basename(zip_path)} 還原：{names}")
    print("[restore] 完成。請 git add/commit 還原後的狀態檔以持久化（commit-back）。")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "snapshot":
        snapshot()
    elif cmd == "list":
        list_snapshots()
    elif cmd == "restore" and len(sys.argv) >= 3:
        restore(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
