#!/usr/bin/env bash
# clean_wt.sh -- 統一的分支／worktree 清理器（取代 clean-gone + clean-merged）。
#
# 用法：
#   bash commands/scripts/clean_wt.sh            # 只報告，不刪（預設）
#   bash commands/scripts/clean_wt.sh --apply    # 實際刪除 SAFE 分類的項目
#   bash commands/scripts/clean_wt.sh --stale-days 30   # 調整 STALE 報告門檻（預設 30）
#
# stdout: 分類報告；stderr: [WARN]/[FAIL] 診斷
# exit 0: 正常（含「無事可做」）；exit 1: 前置條件不足，或 --apply 期間有刪除失敗
#
# ── 為什麼這支腳本存在（合併 clean-gone / clean-merged 的理由）──
# 舊的兩個指令把 bash 直接寫在 markdown 裡，而 agent 讀 command 檔時會「理解意圖後重新
# 生成」bash 而非逐字複製（見 CLAUDE.md 的「slash command bash code block rewritten by
# agent」）。把邏輯收斂成一支被測試覆蓋的腳本，command 檔只留一行呼叫，才能保證每次跑的
# 是同一段、且被 CI 驗證過的邏輯。
#
# ── 判斷分支「內容是否已進 main」的方法（本檔最重要的部分）──
#
# 極性：**預設拒絕**。只有拿到「內容已在 main」的**正面證據**才歸 SAFE；任何證據拿不到、
# 算不出、或工具失敗，一律往 REVIEW 掉（fail closed）。「找不到它未合併的證據」不等於
# 「它已合併」——這兩者的差別就是資料存亡。
#
# 兩個獨立的正面證據，任一成立即 SAFE：
#
#   E1. tip 已是 main 的祖先   -- git merge-base --is-ancestor
#       history 上直接包含，最強的證據。涵蓋 fast-forward 與 merge commit。
#
#   E2. 把分支併回 main 是 no-op -- git merge-tree --write-tree（git >= 2.38）
#       算出「把分支併進 main 會產生的 tree」，若等於 main 現在的 tree，代表分支沒有任何
#       main 沒有的內容。這是關於**內容**的正面證明，與 history 形狀無關，因此 squash
#       merge（單 commit 或多 commit 都可以）、rebase、merge commit 全部涵蓋。
#
#   E3.（輔助）PR 已 MERGED **且 headRefOid == 本地 tip** -- gh
#       只在 E1/E2 都不成立時才問，且**必須綁 tip SHA**。用途是救回 E2 的保守誤判：
#       分支 squash 合併後 main 又動到同一個檔案，merge-tree 會回報 conflict（見下方限制）。
#
# ── 為什麼不用 `git cherry`（前一版用它，已實測會造成資料遺失）──
# git cherry 內部設 revs.max_parents = 1，**merge commit 永遠不會被列出**。因此「內容只
# 存在於 merge commit 裡」（手動衝突解決是最常見的情況）時，git cherry 看不到任何 `+`，
# 讀起來就是「所有 patch 都已在上游」-> SAFE -> 刪除 -> 永久遺失。
# 實測（probe，2026-07-15）：branch 的非 merge commit 全都在上游、唯一內容在 merge commit
# 裡，git cherry 回報 SAFE，merge-tree 回報 NOT-SAFE（正確）。
#
# ── 為什麼不用三點 diff ──
# `git diff main...branch` 從 **merge-base** 算起，而 squash merge 不會讓分支 commit 變成
# main 的祖先，merge-base 因此停在合併前——已經完整合併的分支，三點 diff 仍會顯示全部改動。
# 實測（2026-07-15）：worktree-feat-pin-review-models 的三點 diff 顯示 7 個檔案未合併，但其
# 內容早已由 PR #229 squash 進 main。
#
# ── 已知限制（都是往「留著」的方向，不會誤刪）──
#  - git < 2.38 沒有 `merge-tree --write-tree`：E2 不可用，squash 合併的分支會落到 REVIEW。
#  - 分支 squash 合併後 main 又改到同一個檔案：merge-tree 回報 conflict -> E2 不成立。
#    此時靠 E3（PR MERGED + headRefOid 相符）救回；沒有 gh 就落到 REVIEW。
#  - gh 只抓最近 $GH_PR_LIMIT 個 PR：更舊的 PR 查不到 -> E3 不成立 -> 落到 REVIEW。
#
# ── worktree 佔用與未提交內容 ──
# 分支的「乾淨」不等於它的 worktree 乾淨。分支比對只看 commit，看不到工作目錄裡未提交的
# 檔案。實測（2026-07-15）：worktree-skill-governance-path-c 的分支與 main 零差異，但其
# worktree 存有 33 行未提交的 rule 草稿，只憑分支比對就會被誤判為可安全刪除。
# 因此任何 worktree 只要 `git status --porcelain` 非空，一律標記 BLOCKED，絕不自動刪。
set -uo pipefail

# 繼承來的 GIT_DIR / GIT_WORK_TREE 會蓋過 `git -C`，讓「這個 worktree 髒不髒」的檢查去問
# 到另一個 repo——髒的 worktree 會被讀成乾淨然後刪掉。git 跑 hook 時就會設 GIT_DIR，而本
# repo 大量使用 pre-commit，所以這不是假想情境。一律清掉，改用 cwd 語意。
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
# CDPATH 有值時 `cd foo` 會印出目的地到 stdout，污染 $(cd ... && pwd -P) 的擷取結果。
export CDPATH=

STALE_DAYS=30
APPLY=0
GH_PR_LIMIT=500

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

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[FAIL] 不在 git repo 內" >&2
  exit 1
fi

# ── 呼叫端脈絡：一定要在 cd 到主 repo **之前**取得 ──
# pr-cycle-fast Step 8 正是在剛合併完的 worktree 裡、同一個 session 內呼叫本腳本，而那個
# worktree 此刻剛好符合 SAFE 條件。若在 cd 之後才算「目前分支」，就只保護到主 repo checkout
# 的分支，呼叫者腳下的 worktree 會被連根移除（實測重現：呼叫者的 cwd 在執行後消失）。
#
# 只需要記分支名就夠：worktree 佔用一個分支時，站在該 worktree 裡的 HEAD 必然就是那個分支，
# 所以「分支相符」與「worktree 路徑相符」在可達的情境下永遠同時成立。detached HEAD 的
# worktree 在 `git worktree list --porcelain` 裡沒有 branch 行，本來就不會成為刪除目標。
# （一版寫過額外的 worktree 路徑比對，經突變測試證實是永遠碰不到的死碼，已移除。）
CALLER_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
[ "$CALLER_BRANCH" = "HEAD" ] && CALLER_BRANCH=""   # detached HEAD：沒有分支要保護

# ── 解析主 repo ──
# 一律在主 repo 執行：linked worktree 不能 checkout main，且 branch -D 對被佔用的分支會失敗。
# 用 `git worktree list --porcelain` 的第一筆（權威）而非 dirname(--git-common-dir)：
# --separate-git-dir / submodule 下，common dir 的上層不一定是主 work tree。
# 也不用 --path-format=absolute（需 git >= 2.31）。
MAIN_REPO=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*) MAIN_REPO=${line#worktree }; break ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null)

if [ -z "$MAIN_REPO" ] || [ ! -d "$MAIN_REPO" ]; then
  echo "[FAIL] 無法確定主 repo 位置（git worktree list 失敗）" >&2
  exit 1
fi
MAIN_REPO=$(cd "$MAIN_REPO" && pwd -P) || exit 1
cd "$MAIN_REPO" || exit 1

BASE_BRANCH="main"
BASE="origin/$BASE_BRANCH"

HAS_GH=1
if ! command -v gh >/dev/null 2>&1; then
  HAS_GH=0
  echo "[WARN] gh 不存在——E3（PR 證據）不可用，只靠 git 證據判斷" >&2
fi

# fetch --prune 是必要的：沒有它，remote-tracking ref 不會更新，origin/main 停在舊位置，
# 而「分支未合併」與「本地 origin/main 過期」看起來一模一樣。舊的 clean-gone 缺這一步。
echo "── 同步 remote 狀態（fetch --prune）──"
if ! git fetch --prune origin >/dev/null 2>&1; then
  if [ "$APPLY" = "1" ]; then
    # 過期的 origin/main 會「證明」其實還沒合併的工作已經合併。--apply 會刪東西，
    # 不可以拿過期的基準當證據。報告模式只是看，降級成 [WARN] 即可。
    echo "[FAIL] git fetch --prune 失敗——--apply 模式下不可用過期的 $BASE 當刪除依據" >&2
    echo "       請修好網路／認證後重試，或先不加 --apply 只看報告。" >&2
    exit 1
  fi
  echo "[WARN] git fetch --prune 失敗——以下判斷基於可能過期的 $BASE" >&2
fi

if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "[FAIL] 找不到 $BASE" >&2
  exit 1
fi
BASE_TREE=$(git rev-parse "$BASE^{tree}" 2>/dev/null)
if [ -z "$BASE_TREE" ]; then
  echo "[FAIL] 無法取得 $BASE 的 tree" >&2
  exit 1
fi

MAIN_BRANCH_CHECKED_OUT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# E2 需要 `merge-tree --write-tree`（git >= 2.38）。舊 git 會把 --write-tree 當成 rev 而報錯，
# 探測失敗即視為 E2 不可用——不可用就是拿不到證據，往 REVIEW 掉，不是「安全」。
MERGE_TREE_OK=0
if _probe=$(git merge-tree --write-tree "$BASE" "$BASE" 2>/dev/null) && [ -n "$_probe" ]; then
  MERGE_TREE_OK=1
else
  echo "[WARN] 此 git 不支援 merge-tree --write-tree（需 >= 2.38）——E2 不可用，" >&2
  echo "       squash 合併的分支會落到 REVIEW 而非 SAFE（安全方向）" >&2
fi

# ── 批次抓 PR（一次 network call，不在迴圈裡逐一查）──
# TSV: headRefName \t headRefOid \t state \t baseRefName
PR_TSV=""
if [ "$HAS_GH" = "1" ]; then
  if ! PR_TSV=$(gh pr list --state all --limit "$GH_PR_LIMIT" \
      --json headRefName,headRefOid,state,baseRefName \
      -q '.[] | [.headRefName, .headRefOid, .state, .baseRefName] | @tsv' 2>/dev/null); then
    HAS_GH=0
    PR_TSV=""
    echo "[WARN] gh pr list 失敗——E3（PR 證據）不可用，只靠 git 證據判斷" >&2
  fi
fi

# 收集被 worktree 佔用的分支 -> 其路徑
WT_MAP=$(git worktree list --porcelain 2>/dev/null | awk '
  /^worktree /{ path=substr($0, 10) }
  /^branch /   { br=$2; sub("refs/heads/", "", br); print br "\t" path }
')

# 用 ENVIRON 傳分支名，不用 awk -v：-v 會解讀反斜線跳脫，含 `\` 的分支名會被改寫。
wt_path_for() {
  br="$1" awk -F'\t' '$1==ENVIRON["br"] {print $2; exit}' <<EOF
$WT_MAP
EOF
}

has_open_pr() {
  [ "$HAS_GH" = "1" ] || return 1
  br="$1" awk -F'\t' '$1==ENVIRON["br"] && $3=="OPEN" {found=1} END{exit !found}' <<EOF
$PR_TSV
EOF
}

# E3：存在一個 PR，state=MERGED、base 是我們比對的基準分支、且 headRefOid == 本地 tip。
# 綁 SHA 是重點：`--head <name>` 只回答「有沒有一個同名 head-ref 的 PR 被合併過」，不回答
# 「這個本地分支現在的內容有沒有被合併」。本 repo 的標準流程是 squash + --delete-branch，
# 遠端分支被刪、本地還在；此時在本地再 commit（未開新 PR），PR 狀態仍是 MERGED ->
# 舊版判為 SAFE -> 分支只在本地 -> git branch -D -> 永久遺失。
evidence_pr_merged() {
  local b="$1" tip
  [ "$HAS_GH" = "1" ] || return 1
  tip=$(git rev-parse --verify --quiet "$b" 2>/dev/null) || return 1
  [ -n "$tip" ] || return 1
  tip="$tip" base_branch="$BASE_BRANCH" awk -F'\t' '
    $2==ENVIRON["tip"] && $3=="MERGED" && $4==ENVIRON["base_branch"] {found=1}
    END{exit !found}' <<EOF
$PR_TSV
EOF
}

evidence_is_ancestor() {
  git merge-base --is-ancestor "$1" "$BASE" 2>/dev/null
}

# E2：把分支併回 base 是否為 no-op。exit != 0（衝突或錯誤）一律 return 1（fail closed）。
evidence_merge_is_noop() {
  local b="$1" mt
  [ "$MERGE_TREE_OK" = "1" ] || return 1
  mt=$(git merge-tree --write-tree "$BASE" "$b" 2>/dev/null) || return 1
  # 乾淨合併時輸出就是單行 tree OID；有衝突時 exit 非 0（已於上一行擋掉）。
  # 非 40 位 hex（含多行輸出）一律不採信。
  case "$mt" in
    "" | *[!0-9a-f]*) return 1 ;;
  esac
  [ "${#mt}" -eq 40 ] || return 1
  [ "$mt" = "$BASE_TREE" ]
}

SAFE_BRANCHES=()
SAFE_LINES=""
BLOCKED=""
KEEP=""
REVIEW=""

now_epoch=$(date +%s)

# process substitution（非 pipeline）：迴圈必須留在目前的 shell，否則陣列與計數在 subshell
# 裡累積完就被丟掉。
while IFS= read -r b; do
  [ -z "$b" ] && continue
  [ "$b" = "$BASE_BRANCH" ] && continue

  if [ "$b" = "$MAIN_BRANCH_CHECKED_OUT" ]; then
    KEEP="$KEEP\n  $b  (主 repo 目前 checkout 的分支)"
    continue
  fi

  if [ -n "$CALLER_BRANCH" ] && [ "$b" = "$CALLER_BRANCH" ]; then
    KEEP="$KEEP\n  $b  (呼叫端所在分支)"
    continue
  fi

  wt_path=$(wt_path_for "$b")

  # 工作目錄未提交內容 -> 一律 BLOCKED（分支比對看不到這個）
  if [ -n "$wt_path" ] && [ -d "$wt_path" ]; then
    if ! dirty=$(git -C "$wt_path" status --porcelain 2>/dev/null); then
      BLOCKED="$BLOCKED\n  $b  (無法讀取 worktree 狀態：$wt_path)"
      continue
    fi
    if [ -n "$dirty" ]; then
      n=$(printf '%s\n' "$dirty" | wc -l | tr -d ' ')
      BLOCKED="$BLOCKED\n  $b  ($n 個未提交變更於 $wt_path)"
      continue
    fi
  fi

  if has_open_pr "$b"; then
    KEEP="$KEEP\n  $b  (open PR)"
    continue
  fi

  reason=""
  if evidence_is_ancestor "$b"; then
    reason="tip 已是 $BASE 的祖先"
  elif evidence_merge_is_noop "$b"; then
    reason="併回 $BASE 為 no-op（merge-tree 內容比對）"
  elif evidence_pr_merged "$b"; then
    reason="PR 已 MERGED 且 headRefOid == 本地 tip"
  fi

  if [ -n "$reason" ]; then
    remote_note="僅本地"
    if git ls-remote --heads --exit-code origin "$b" >/dev/null 2>&1; then
      remote_note="遠端仍在，可救回"
    fi
    SAFE_BRANCHES+=("$b")
    SAFE_LINES="$SAFE_LINES\n  $b  [$reason; $remote_note]"
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
    REVIEW="$REVIEW\n  $b  (${age}d 未更新, $ahead 個獨有 commit) [STALE]"
  else
    REVIEW="$REVIEW\n  $b  (${age}d, $ahead 個獨有 commit)"
  fi
done < <(git branch --format='%(refname:short)')

echo ""
echo "══ SAFE：可刪除（已證實內容在 ${BASE}）══"
[ -n "$SAFE_LINES" ] && printf '%b\n' "$SAFE_LINES" || echo "  (無)"
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

if [ "${#SAFE_BRANCHES[@]}" -eq 0 ]; then
  echo ""
  echo "[OK] 沒有可安全刪除的分支"
  exit 0
fi

# ── Port 登記清理 ──
# worktree 建立時（/newjob Step 2c）會用 branch name 當 project key 登記 host port。
# 刪分支卻不 release，登記就永久洩漏——下一個 worktree 會被推去用更高的 port，無限累積。
# 這個工具只存在於本 repo，因此先確認 module 在再呼叫；不在就安靜跳過（別的 repo 沒有它）。
PM_AVAILABLE=0
if [ -d "$MAIN_REPO/tasks/local_port_manager" ] && command -v uv >/dev/null 2>&1; then
  PM_AVAILABLE=1
fi

release_ports() {
  local b="$1" out svc
  [ "$PM_AVAILABLE" = "1" ] || return 0
  if ! out=$(uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager list -p "$b" 2>/dev/null); then
    echo "  [WARN] 讀取 port registry 失敗，略過 port 清理：${b}（登記可能需手動清）" >&2
    return 0
  fi
  # list 輸出是「表頭 + 分隔線 + 每行一筆」；無資料時只印一行提示，NR>2 自然為空。
  svc=$(printf '%s\n' "$out" | awk 'NR>2 {print $2}')
  [ -z "$svc" ] && return 0
  while IFS= read -r s; do
    [ -z "$s" ] && continue
    if uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager release "$b" "$s" >/dev/null 2>&1; then
      echo "  [OK] port 登記已釋放：$b/$s"
    else
      echo "  [WARN] port 釋放失敗：$b/${s}（登記需手動清）" >&2
    fi
  done <<EOF
$svc
EOF
}

echo ""
echo "── 執行刪除（僅 SAFE 清單）──"
FAILED=0
for b in ${SAFE_BRANCHES[@]+"${SAFE_BRANCHES[@]}"}; do
  wt_path=$(wt_path_for "$b")
  if [ -n "$wt_path" ]; then
    if git worktree remove "$wt_path" >/dev/null 2>&1; then
      echo "  [OK] worktree 已移除：$wt_path"
    else
      echo "  [WARN] worktree 移除失敗，略過分支：${b}（可能被 lock 或有殘留檔案）" >&2
      FAILED=1
      continue
    fi
  fi
  release_ports "$b"
  if git branch -D "$b" >/dev/null 2>&1; then
    echo "  [OK] 分支已刪除：$b"
  else
    echo "  [FAIL] 分支刪除失敗：$b" >&2
    FAILED=1
  fi
done

git worktree prune
echo ""
echo "剩餘分支："
git branch --format='  %(refname:short)'

if [ "$FAILED" != "0" ]; then
  echo ""
  echo "[FAIL] 有項目刪除失敗（見上方 [WARN]/[FAIL]）" >&2
  exit 1
fi
echo ""
echo "[OK] 完成"
