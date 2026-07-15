#!/usr/bin/env bash
# clean_wt.sh -- 統一的分支／worktree 清理器（取代 clean-gone + clean-merged）。
#
# 用法：
#   bash commands/scripts/clean_wt.sh            # 只報告，不刪（預設）
#   bash commands/scripts/clean_wt.sh --apply    # 實際刪除 SAFE 分類的項目
#   bash commands/scripts/clean_wt.sh --stale-days 30   # 調整 STALE 報告門檻（預設 30）
#
# stdout: 分類報告；stderr: [WARN]/[FAIL] 診斷
# exit 0: 正常（含「無事可做」）；exit 1: 前置條件不足
#
# ── 為什麼這支腳本存在（合併 clean-gone / clean-merged 的理由）──
# 舊的兩個指令把 bash 直接寫在 markdown 裡，而 agent 讀 command 檔時會「理解意圖後重新
# 生成」bash 而非逐字複製，於是每次執行的實際指令都可能不同（見 CLAUDE.md 的
# 「slash command bash code block rewritten by agent」）。把邏輯收斂成一支被測試覆蓋的
# 腳本，command 檔只留一行呼叫，才能保證每次跑的是同一段、且被 CI 驗證過的邏輯。
#
# ── 判斷分支「是否還有價值」的方法（本檔最重要的部分）──
# 不可只用 `git diff main...branch`（三點 diff）判斷內容是否已進 main。三點 diff 是從
# **merge-base** 算起，而 squash merge 不會把分支 commit 變成 main 的祖先，merge-base
# 因此停在合併前——已經完整合併的分支，三點 diff 仍會顯示全部改動，看起來像「還沒進 main」。
# 實測（2026-07-15）：worktree-feat-pin-review-models 的三點 diff 顯示 7 個檔案未合併，
# 但其內容早已由 PR #229 squash 進 main；真相是 `git rebase` 逐一 cherry-pick 時發現改動
# 已在上游而全部跳過，分支被清空。
#
# 本腳本改用三個**各自獨立**的證據，任一成立才算「內容已在 main」：
#   1. PR 狀態（gh，權威）      -- MERGED 即可刪
#   2. tip 是 main 的祖先        -- git merge-base --is-ancestor（fast-forward / merge commit）
#   3. 所有 patch 都在上游       -- git cherry（patch-id 比對，可涵蓋單 commit 的 squash）
# 三者皆不成立 → 歸為 REVIEW/STALE，只報告不刪。寧可留著也不猜。
#
# 已知限制（刻意不猜）：多 commit 分支被 squash 成一個 commit 時，git cherry 的 patch-id
# 對不上（上游是一個大 patch，分支是多個小 patch），會落到 REVIEW。這是安全方向的誤判。
#
# ── worktree 佔用與未提交內容 ──
# 分支的「乾淨」不等於它的 worktree 乾淨。分支比對只看 commit，看不到工作目錄裡未提交的
# 檔案。實測（2026-07-15）：worktree-skill-governance-path-c 的分支與 main 零差異，但其
# worktree 存有 33 行未提交的 rule 草稿，只憑分支比對就會被誤判為可安全刪除。
# 因此任何 worktree 只要 `git status --porcelain` 非空，一律標記 BLOCKED，絕不自動刪。
set -uo pipefail

STALE_DAYS=30
APPLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --stale-days)
      if [ "$#" -lt 2 ]; then
        echo "[FAIL] --stale-days 需要一個數值" >&2
        exit 1
      fi
      STALE_DAYS="$2"; shift 2 ;;
    -h|--help)
      echo "用法: clean_wt.sh [--apply] [--stale-days N]"
      exit 0 ;;
    *)
      echo "[FAIL] 未知參數：$1" >&2
      exit 1 ;;
  esac
done

case "$STALE_DAYS" in
  ''|*[!0-9]*) echo "[FAIL] --stale-days 必須是非負整數：$STALE_DAYS" >&2; exit 1 ;;
esac

if ! command -v git >/dev/null 2>&1; then
  echo "[FAIL] git 不存在" >&2
  exit 1
fi

# 一律在主 repo 執行：linked worktree 不能 checkout main，且 branch -D 對被佔用的分支會失敗。
_gcd=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
if [ -z "$_gcd" ]; then
  echo "[FAIL] 不在 git repo 內" >&2
  exit 1
fi
MAIN_REPO=$(dirname "$_gcd")
cd "$MAIN_REPO" || exit 1

HAS_GH=1
if ! command -v gh >/dev/null 2>&1; then
  HAS_GH=0
  echo "[WARN] gh 不存在——無法讀取 PR 狀態，已合併的分支只能靠 git 證據判斷" >&2
fi

# --prune 是必要的：沒有它，remote-tracking ref 不會更新，[gone] 標記永遠不會出現，
# 於是「沒有 gone 分支」與「還沒 prune」看起來一模一樣。舊的 clean-gone 缺這一步。
echo "── 同步 remote 狀態（fetch --prune）──"
if ! git fetch --prune origin >/dev/null 2>&1; then
  echo "[WARN] git fetch --prune 失敗——[gone] 偵測可能不準確" >&2
fi

BASE="origin/main"
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "[FAIL] 找不到 $BASE" >&2
  exit 1
fi

CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# 收集被 worktree 佔用的分支 -> 其路徑
WT_MAP=$(git worktree list --porcelain 2>/dev/null | awk '
  /^worktree /{ path=substr($0, 10) }
  /^branch /   { br=$2; sub("refs/heads/", "", br); print br "\t" path }
')

SAFE=""      # 可安全刪除
BLOCKED=""   # 有未提交內容或其他阻礙
KEEP=""      # open PR / 目前分支
REVIEW=""    # 證據不足，需人工判斷

now_epoch=$(date +%s)

for b in $(git branch --format='%(refname:short)' | grep -v '^main$'); do
  [ -z "$b" ] && continue

  if [ "$b" = "$CURRENT" ]; then
    KEEP="$KEEP\n  $b  (目前所在分支)"
    continue
  fi

  wt_path=$(printf '%s\n' "$WT_MAP" | awk -F'\t' -v br="$b" '$1==br {print $2; exit}')

  # 工作目錄未提交內容 -> 一律 BLOCKED（分支比對看不到這個）
  if [ -n "$wt_path" ] && [ -d "$wt_path" ]; then
    dirty=$(git -C "$wt_path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$dirty" != "0" ]; then
      BLOCKED="$BLOCKED\n  $b  ($dirty 個未提交變更於 $wt_path)"
      continue
    fi
  fi

  pr_state=""
  if [ "$HAS_GH" = "1" ]; then
    pr_state=$(gh pr list --head "$b" --state all --json state -q '.[0].state' 2>/dev/null)
  fi

  if [ "$pr_state" = "OPEN" ]; then
    KEEP="$KEEP\n  $b  (open PR)"
    continue
  fi

  # 證據 1：PR 已 MERGED（權威）
  reason=""
  if [ "$pr_state" = "MERGED" ]; then
    reason="PR MERGED"
  # 證據 2：tip 已是 main 的祖先
  elif git merge-base --is-ancestor "$b" "$BASE" 2>/dev/null; then
    reason="tip 已是 $BASE 的祖先"
  # 證據 3：所有 patch 都已在上游（patch-id 比對，非三點 diff）
  elif [ -z "$(git cherry "$BASE" "$b" 2>/dev/null | grep '^+' || true)" ]; then
    reason="所有 patch 已在上游（git cherry）"
  fi

  if [ -n "$reason" ]; then
    remote_note="僅本地"
    if git ls-remote --heads --exit-code origin "$b" >/dev/null 2>&1; then
      remote_note="遠端仍在，可救回"
    fi
    SAFE="$SAFE\n  $b  [$reason; $remote_note]"
    continue
  fi

  # 無證據 -> 只報告。附上年齡供人工判斷，但年齡本身不是刪除依據。
  last=$(git log -1 --format='%ct' "$b" 2>/dev/null)
  age="?"
  if [ -n "$last" ]; then
    age=$(( (now_epoch - last) / 86400 ))
  fi
  ahead=$(git rev-list --count "$BASE..$b" 2>/dev/null)
  if [ "$age" != "?" ] && [ "$age" -ge "$STALE_DAYS" ]; then
    REVIEW="$REVIEW\n  $b  (${age}d 未更新, $ahead 個獨有 commit, 無 PR) [STALE]"
  else
    REVIEW="$REVIEW\n  $b  (${age}d, $ahead 個獨有 commit, 無 PR)"
  fi
done

echo ""
echo "══ SAFE：可刪除（內容確認已在 ${BASE}）══"
[ -n "$SAFE" ] && printf '%b\n' "$SAFE" || echo "  (無)"
echo ""
echo "══ KEEP：保留 ══"
[ -n "$KEEP" ] && printf '%b\n' "$KEEP" || echo "  (無)"
echo ""
echo "══ BLOCKED：有未提交內容，不自動處理 ══"
[ -n "$BLOCKED" ] && printf '%b\n' "$BLOCKED" || echo "  (無)"
echo ""
echo "══ REVIEW：無證據顯示內容已進 ${BASE}，需人工判斷 ══"
[ -n "$REVIEW" ] && printf '%b\n' "$REVIEW" || echo "  (無)"

if [ "$APPLY" != "1" ]; then
  echo ""
  echo "（預設只報告。確認 SAFE 清單無誤後，加 --apply 實際刪除。）"
  exit 0
fi

if [ -z "$SAFE" ]; then
  echo ""
  echo "[OK] 沒有可安全刪除的分支"
  exit 0
fi

echo ""
echo "── 執行刪除（僅 SAFE 清單）──"
printf '%b\n' "$SAFE" | while read -r b _rest; do
  [ -z "$b" ] && continue
  wt_path=$(printf '%s\n' "$WT_MAP" | awk -F'\t' -v br="$b" '$1==br {print $2; exit}')
  if [ -n "$wt_path" ]; then
    if git worktree remove "$wt_path" >/dev/null 2>&1; then
      echo "  [OK] worktree 已移除：$wt_path"
    else
      echo "  [WARN] worktree 移除失敗，略過分支：$b" >&2
      continue
    fi
  fi
  if git branch -D "$b" >/dev/null 2>&1; then
    echo "  [OK] 分支已刪除：$b"
  else
    echo "  [FAIL] 分支刪除失敗：$b" >&2
  fi
done

git worktree prune
echo ""
echo "[OK] 完成。剩餘分支："
git branch --format='  %(refname:short)'
