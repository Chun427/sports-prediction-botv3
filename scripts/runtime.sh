#!/usr/bin/env bash
# ============================================================================
# V0.1 Scheduler Reliability Upgrade — runtime watchdog
# ----------------------------------------------------------------------------
# 職責（只做基礎設施，不碰任何 business logic）：
#   在「單一 workflow run」內，可靠、節流地重複執行既有 tick
#   （python src/sports_prediction.py push），並安全地 checkpoint 狀態。
#
# 不修改：predict / Monte Carlo / Kelly / Score Model / Odds 邏輯 / 推播內容。
# 不增加 API：tick 內部的 pool(slot guard)/scores(backoff)/awards(每日冪等)
#             三層 gate 仍生效，迴圈多跑不等於多打 API。
#
# 設計重點：
#   1. runtime watchdog ：單次觸發 → 內部 ~50 分鐘、每 5 分鐘一 tick。
#   2. safe shutdown     ：捕捉 SIGTERM/SIGINT → 收尾 commit → 乾淨退出
#                          （避免「推播已送、flag 未落盤」→ 下次重送）。
#   3. commit debounce   ：idempotency 關鍵檔(flags/predictions)變更→立即提交；
#                          其餘(pool/key_state/verified)節流批次，降低 commit 數。
#   4. push safe         ：commit 後 pull --rebase --autostash 再 push，
#                          避免與手動上傳 race；失敗只延後重試，不破壞狀態。
#   5. recovery          ：狀態存在 git，下一個 run checkout 即自動恢復；
#                          已推過的場由 is_pushed 擋住、已開賽的場由 window
#                          擋住 → 自動「不補送賽前推」，只恢復 scheduler 狀態。
# ============================================================================
set -uo pipefail

LOOP_SECONDS="${LOOP_SECONDS:-3000}"        # 單 run 內部覆蓋時長（~50 分）
TICK_INTERVAL="${TICK_INTERVAL:-300}"       # tick 間隔（5 分）
COMMIT_DEBOUNCE="${COMMIT_DEBOUNCE:-900}"   # 非關鍵變更批次間隔（~15 分）

STATE_FILES=(flags.json weekly_games.json predictions.json key_state.json verified_history.csv)
CRITICAL_FILES=(flags.json predictions.json)   # 與推播冪等直接相關 → 立即落盤

STOP=0
on_term() { STOP=1; }                       # safe shutdown 旗標
trap on_term TERM INT

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"level\":\"INFO\",\"src\":\"runtime\",\"msg\":\"$1\"}"; }

git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

LAST_COMMIT=0

stage_state() {   # 只 stage 存在的檔；不存在的略過（避免整批 git add 失敗）
  local f
  for f in "${STATE_FILES[@]}"; do
    [ -f "$f" ] && git add -- "$f" 2>/dev/null || true
  done
}

commit_push() {   # $1 = reason
  stage_state
  if git diff --staged --quiet; then return 0; fi
  git commit -q -m "[skip ci] state checkpoint (${1})" || return 0
  git pull --rebase --autostash -q || true   # rebase-safe：先納入他人/手動變更
  if git push -q; then
    LAST_COMMIT=$SECONDS
  else
    log "push.deferred reason=${1} (retry next checkpoint)"
  fi
}

has_critical_change() {
  stage_state
  git diff --staged --quiet && return 1
  local changed; changed="$(git diff --staged --name-only)"
  local f
  for f in "${CRITICAL_FILES[@]}"; do
    printf '%s\n' "$changed" | grep -qx "$f" && return 0
  done
  return 1
}

# --- startup recovery checkpoint（觀測用；不補送推播）-------------------------
log "runtime.start loop=${LOOP_SECONDS}s tick=${TICK_INTERVAL}s debounce=${COMMIT_DEBOUNCE}s"
if [ -f flags.json ]; then
  log "recovery.state_loaded flags=present (idempotency+window 自動防重送/防補送)"
else
  log "recovery.cold_start no_flags_yet"
fi

END=$((SECONDS + LOOP_SECONDS))
while :; do
  python src/sports_prediction.py push || true   # 既有 tick；失敗不終止迴圈

  # commit 策略：關鍵檔變更立即落盤；非關鍵變更節流批次
  if has_critical_change; then
    commit_push "push"
  elif ! git diff --staged --quiet; then
    if [ $((SECONDS - LAST_COMMIT)) -ge "$COMMIT_DEBOUNCE" ]; then
      commit_push "debounce"
    fi
    # 否則保留 staged，待 debounce / shutdown / loop-end 一次提交
  fi

  if [ "$STOP" = 1 ]; then
    commit_push "safe-shutdown"; log "runtime.safe_shutdown committed_pending=ok"; break
  fi
  if [ "$SECONDS" -ge "$END" ]; then
    commit_push "loop-end"; log "runtime.loop_end"; break
  fi

  # 可被 SIGTERM 立即中斷的睡眠（拆短睡，及時 safe shutdown）
  slept=0
  while [ "$slept" -lt "$TICK_INTERVAL" ] && [ "$STOP" = 0 ]; do
    sleep 5; slept=$((slept + 5))
  done
done

log "runtime.exit clean"
