#!/usr/bin/env bash
# clean_wt.sh -- 統一的分支／worktree 清理器（取代 clean-gone + clean-merged）。
#
# 用法：
#   bash commands/scripts/clean_wt.sh                  # 只報告，不刪（預設）
#   bash commands/scripts/clean_wt.sh --apply          # 實際刪除 SAFE 分類的項目
#   bash commands/scripts/clean_wt.sh --stale-days 30  # 調整 STALE 報告門檻（預設 30）
#   bash commands/scripts/clean_wt.sh --base develop   # 改用別的基準分支（預設 main）
#
# stdout: 分類報告；stderr: [WARN]/[FAIL] 診斷
# exit 0: 正常（含「無事可做」）
# exit 1: 前置條件不足，或 --apply 期間有刪除／清理失敗
#
# ── 為什麼這支腳本存在（合併 clean-gone / clean-merged 的理由）──
# 舊的兩個指令把 bash 直接寫在 markdown 裡，而 agent 讀 command 檔時會「理解意圖後重新
# 生成」bash 而非逐字複製（見 CLAUDE.md 的「slash command bash code block rewritten by
# agent」）。把邏輯收斂成一支被測試覆蓋的腳本，command 檔只留一行呼叫，才能保證每次跑的
# 是同一段、且被 CI 驗證過的邏輯。
#
# ══ 判斷分支「內容是否已進 base」的方法 ══
#
# 極性：**預設拒絕**。只有拿到「內容已在 base」的**正面證據**才歸 SAFE；任何證據拿不到、
# 算不出、或工具失敗，一律往 REVIEW 掉（fail closed）。「找不到它未合併的證據」不等於
# 「它已合併」——這兩者的差別就是資料存亡。
#
# 三個獨立的正面證據，任一成立即 SAFE。**三者最終都由本地 git 對 base 快照驗證**：
#
#   E1. tip 已是 base 的祖先   -- git merge-base --is-ancestor
#       history 上直接包含，最強的證據。涵蓋 fast-forward 與 merge commit。
#       對 squash merge 無效：squash 產生全新 commit，與分支原本的 commit 無血緣關係。
#
#   E2. 把分支併回 base 是 no-op -- git merge-tree --write-tree（git >= 2.38）
#       算出「把分支併進 base 會產生的 tree」，若等於 base 的 tree，代表分支沒有任何 base
#       沒有的內容。這是關於**內容**的正面證明，與 history 形狀無關，因此 squash（單／多
#       commit）、rebase、merge commit 全部涵蓋。
#       失效情境：squash 合併後 base 又改到同一個檔案 -> merge-tree 回報 conflict -> 算不出來。
#
#   E3. PR 的 merge commit 仍在 base 的歷史裡 -- gh + git merge-base --is-ancestor
#       只在 E1/E2 都不成立時才問。存在的唯一理由是救回 E2 的 conflict 誤判。
#
# ── E3 的設計：PR 是**線索**，不是**授權** ──
# E3 一度只憑「PR 已 MERGED 且 headRefOid == 本地 tip」就判 SAFE。那是錯的：PR 紀錄講的是
# **過去發生過的事**，不是現在的狀態。base 若被改寫（force push / rebase），squash commit
# 可能已不在歷史裡，內容其實已經不見，而 PR 上仍寫著「已合併」-> 判 SAFE -> 永久遺失。
#
# 現在的 E3 把 PR 降級成**指路的線索**：PR 只負責回答「內容被裝進哪個 commit」（mergeCommit），
# 真正的判定回到本地 git——**那個 commit 還是 base 的祖先嗎？** 是，才算數。
#
# 四個條件全部成立才算 E3（缺一不可）：
#   1. PR state == MERGED
#   2. PR baseRefName == 我們比對的基準分支（合併進別的分支不算數）
#   3. PR headRefOid == 本地 tip（**綁 SHA**：否則只是「有個同名分支合併過」——合併後在本地
#      又 commit 的情況會被誤判為 SAFE，那正是 PR #239 R1 抓到的資料遺失路徑）
#   4. PR mergeCommit 仍是 base 快照的祖先（**現況檢查**：擋掉歷史被改寫的情境）
#
# 實測（PR #239，2026-07-16）E3 的實際收益：本 repo 4 個已合併的分支中，3 個由 E2 判定，
# 1 個（worktree-fix-232-worktree-install-guard / PR #234）因 base 後來改到同一個檔案而使
# merge-tree conflict，只有 E3 能救 -> 約 25%。且此比例會隨時間惡化：分支放愈久，base 動到
# 同檔案的機率愈高——而「放很久的舊合併分支」正是本工具最該處理的對象。
#
# ── 為什麼不用 `git cherry`（前一版用它，已實測會造成資料遺失）──
# git cherry 內部設 revs.max_parents = 1，**merge commit 永遠不會被列出**。因此「內容只
# 存在於 merge commit 裡」（手動衝突解決是最常見的情況）時，git cherry 看不到任何 `+`，
# 讀起來就是「所有 patch 都已在上游」-> SAFE -> 刪除 -> 永久遺失。
# git cherry 另有反方向弱點：多 commit 分支被 squash 後 patch-id 對不上，已合併的分支會被
# 判成未合併。實測：worktree-fix-232-worktree-install-guard 已由 PR #234 squash 合併，
# git cherry 仍回報 8 個「未合併」patch；merge-tree 正確判為 no-op。
#
# ── 為什麼不用三點 diff ──
# `git diff base...branch` 從 **merge-base** 算起，而 squash merge 不會讓分支 commit 變成
# base 的祖先，merge-base 因此停在合併前——已經完整合併的分支，三點 diff 仍會顯示全部改動。
# 實測（2026-07-15）：worktree-feat-pin-review-models 的三點 diff 顯示 7 個檔案未合併，但其
# 內容早已由 PR #229 squash 進 main。
#
# ══ ref 解析：全程用完整 ref（refs/heads/<name>），只在顯示與比對 key 時用短名 ══
# 這不是潔癖，是實測出來的雙重陷阱（PR #239 R2）：
#   - `%(refname:short)` 是**歧義相依**的：存在同名 tag 時它輸出 `heads/feat` 而非 `feat`。
#     但 WT_MAP 的 key 是 `feat`、gh 的 headRefName 也是 `feat` -> 兩邊都比對不到 ->
#     **worktree 髒檢查與 open PR 保護雙雙被跳過**。實測：同一個 repo 只多一個同名 tag，
#     髒 worktree 的分支就從 BLOCKED 變成 SAFE。
#   - 反過來，若用 `%(refname:strip=2)` 拿到純名 `feat` 卻直接餵給 git，`feat` 會解析到
#     **tag**（gitrevisions 把 refs/tags/ 排在 refs/heads/ 之前）-> 用 tag 的 OID 判斷分支。
# 結論：`--format='%(refname:strip=2)'` 拿純名（給 WT_MAP / PR 比對與顯示），所有 git 查詢
# 一律用 `refs/heads/$b`。兩者缺一不可——只修一半會更糟。
#
# ══ worktree 內容保護（分支比對看不到工作目錄）══
#
# 未提交的變更與 untracked 檔案 -> 一律 BLOCKED。
# 實測（2026-07-15）：worktree-skill-governance-path-c 的分支與 main 零差異，但其 worktree
# 存有 33 行未提交的 rule 草稿，只憑分支比對就會被誤判為可安全刪除。
#
# **一律傳 `--untracked-files=all`，覆寫使用者的 `status.showUntrackedFiles` 設定。**
# 設成 `no` 時，連普通的 untracked 檔案都會從 status 消失，而 `git worktree remove` 也不會
# 拒絕——因為兩層問的是同一個被蒙蔽的 status。實測（PR #239）：手寫的 `notes.txt` 完全隱形，
# worktree 被移除，檔案永久消失。這種檔案不是任何東西的副本，也不可重生。
# 因此 `git worktree remove` 也要用 `git -c status.showUntrackedFiles=all` 呼叫，讓 git 自己
# 的那道檢查不會繼承使用者的不安全設定（實測：加了就會正確拒絕）。
#
# ── 為什麼**不**擋 gitignored 檔案（一度擋過，經使用者裁決移除；別再加回來）──
# 三家 mob review（Claude / Codex / agy）都獨立提報「gitignored 檔案會被靜默刪除」為 Critical，
# 理由是 `.env` 不在 git 裡、刪了救不回來。這個推理套用了一般性直覺，但**在本 repo 的 worktree
# 生命週期下不成立**：worktree 裡的 gitignored 內容全是**衍生物**——
#   - `.env` / `.runtime/` / `.claude/settings.local.json`：由 /newjob Step 2b
#     （`newjob-copy-gitignored.sh`）用 `cp` **從主 repo 複製進來**，正本永遠留在主 repo，
#     而本腳本只刪 worktree 與分支，從不碰主 repo。
#     實測（PR #239，只比對變數名與值長度、不讀值）：某 worktree 的 `.env` 與主 repo 的
#     `.env` 變數集合完全相同、值長度也相同 ⇒ 純副本。
#   - `.venv/`、`__pycache__/`、`.mypy_cache/`、`.ruff_cache/`、`.pytest_cache/`：可重生。
#   - `.pr-review/`：本 skill 自己的 review 中間產物，用完即棄。
# ⇒ 刪掉 worktree 的 gitignored 檔案零損失。它們本來就該隨 worktree 一起消失。
#
# 而擋下來的代價是實測過的、且會反噬：本 repo 每個 worktree 都有 37～42 個 gitignored 項目
# （約 95% 是 `__pycache__/` 之類的快取），一旦擋，SAFE 永遠是空的，使用者每次都得加一個
# override 參數，於是它變成反射動作——真正該停下來看的那一次也不會停。守衛因此等於不存在。
# 這正是 Codex 與 agy 都預言的 override habituation。
#
# ══ 已知限制 ══
#
# 往「留著」的方向（不會誤刪）：
#  - git < 2.38 沒有 `merge-tree --write-tree`：E2 不可用 -> 靠 E3 救回；沒有 gh（或 PR 太舊
#    查不到）才落到 REVIEW。
#  - squash 合併後 base 又改到同一個檔案：merge-tree 回報 conflict -> E2 不成立 -> 靠 E3
#    救回；沒有 gh 就落到 REVIEW。
#  - gh 只抓最近 $GH_PR_LIMIT 個 PR：更舊的 PR 查不到 -> E3 不成立 -> 落到 REVIEW。
#    （open PR 保護不受此限：它另外用 `--state open` 查詢，見 gh 閘門。）
#  - `--apply` 需要 gh：無法確認 open PR 就不刪。
#
# **唯一往「刪」的方向的限制**：worktree 的 gitignored 內容不擋。若把**唯一、無備份**的內容
# 放進 worktree 的 gitignored 路徑（不是副本、也非可重生），它會隨 worktree 一起消失。
# 這是本 repo 刻意接受的取捨——worktree 是暫時的工作副本，正本該放主 repo。
# 理由見上方「為什麼**不**擋 gitignored 檔案」。
set -uo pipefail

# 繼承來的 GIT_DIR / GIT_WORK_TREE 會蓋過 `git -C`，讓「這個 worktree 髒不髒」的檢查去問
# 到另一個 repo——髒的 worktree 會被讀成乾淨然後刪掉。git 跑 hook 時就會設 GIT_DIR，而本
# repo 大量使用 pre-commit，所以這不是假想情境。一律清掉，改用 cwd 語意。
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
# CDPATH 有值時 `cd foo` 會印出目的地到 stdout，污染 $(cd ... && pwd -P) 的擷取結果。
export CDPATH=

STALE_DAYS=30
APPLY=0
BASE_BRANCH="main"
GH_PR_LIMIT=800

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --stale-days)
      if [ "$#" -lt 2 ]; then
        echo "[FAIL] --stale-days 需要一個數值" >&2
        exit 1
      fi
      STALE_DAYS="$2"; shift 2 ;;
    --base)
      if [ "$#" -lt 2 ]; then
        echo "[FAIL] --base 需要一個分支名稱" >&2
        exit 1
      fi
      BASE_BRANCH="$2"; shift 2 ;;
    -h|--help)
      echo "用法: clean_wt.sh [--apply] [--stale-days N] [--base BRANCH]"
      exit 0 ;;
    *)
      echo "[FAIL] 未知參數：$1" >&2
      exit 1 ;;
  esac
done

case "$STALE_DAYS" in
  ''|*[!0-9]*) echo "[FAIL] --stale-days 必須是非負整數：$STALE_DAYS" >&2; exit 1 ;;
esac
case "$BASE_BRANCH" in
  ''|-*) echo "[FAIL] --base 分支名稱不合法：$BASE_BRANCH" >&2; exit 1 ;;
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
# 一律在主 repo 執行：linked worktree 不能 checkout base，且刪除被佔用的分支會失敗。
# 用 `git worktree list --porcelain` 的第一筆（權威）而非 dirname(--git-common-dir)：
# --separate-git-dir / submodule 下，common dir 的上層不一定是主 work tree。
# 也不用 --path-format=absolute（需 git >= 2.31）。
if ! _wt_raw=$(git worktree list --porcelain 2>&1); then
  echo "[FAIL] 無法列舉 worktree：${_wt_raw}" >&2
  exit 1
fi
MAIN_REPO=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*) MAIN_REPO=${line#worktree }; break ;;
  esac
done <<EOF
$_wt_raw
EOF

if [ -z "$MAIN_REPO" ] || [ ! -d "$MAIN_REPO" ]; then
  echo "[FAIL] 無法確定主 repo 位置" >&2
  exit 1
fi
if ! MAIN_REPO=$(cd "$MAIN_REPO" && pwd -P); then
  echo "[FAIL] 無法解析主 repo 的實體路徑" >&2
  exit 1
fi
if ! cd "$MAIN_REPO"; then
  echo "[FAIL] 無法進入主 repo：$MAIN_REPO" >&2
  exit 1
fi

BASE="origin/$BASE_BRANCH"

HAS_GH=1
if ! command -v gh >/dev/null 2>&1; then
  HAS_GH=0
fi

# fetch --prune 是必要的：沒有它，remote-tracking ref 不會更新，$BASE 停在舊位置，
# 而「分支未合併」與「本地基準過期」看起來一模一樣。舊的 clean-gone 缺這一步。
# FETCH_OK 之後也決定「遠端是否還有這個分支」能不能回答（見 remote_state）。
echo "── 同步 remote 狀態（fetch --prune）──"
FETCH_OK=1
if ! git fetch --prune origin >/dev/null 2>&1; then
  FETCH_OK=0
  if [ "$APPLY" = "1" ]; then
    # 過期的 base 會「證明」其實還沒合併的工作已經合併。--apply 會刪東西，
    # 不可以拿過期的基準當證據。報告模式只是看，降級成 [WARN] 即可。
    echo "[FAIL] git fetch --prune 失敗——--apply 模式下不可用過期的 ${BASE} 當刪除依據" >&2
    echo "       請修好網路／認證後重試，或先不加 --apply 只看報告。" >&2
    exit 1
  fi
  echo "[WARN] git fetch --prune 失敗——以下判斷基於可能過期的 ${BASE}，且遠端狀態未知" >&2
fi

# ── base 快照：分類全程用不可變的 OID，不用會動的符號 ref ──
# `origin/main` 是可變的：另一個行程（別的 session、IDE 的自動 fetch）隨時可能移動它。
# 若 E1/E3 用符號 ref 而 BASE_TREE 用快照，兩者會不一致——更糟的是，force push 之後
# 分類到刪除之間 base 若倒退，可能刪掉「唯一還持有那些內容的 ref」。
# 一次解析成 SHA，全程只用它；刪除前會再驗 base 沒動過（見刪除迴圈）。
BASE_SHA=$(git rev-parse --verify --quiet "${BASE}^{commit}" 2>/dev/null)
if [ -z "$BASE_SHA" ]; then
  echo "[FAIL] 找不到 ${BASE}（可用 --base 指定其他基準分支）" >&2
  exit 1
fi
BASE_TREE=$(git rev-parse --verify --quiet "${BASE_SHA}^{tree}" 2>/dev/null)
if [ -z "$BASE_TREE" ]; then
  echo "[FAIL] 無法取得 $BASE 的 tree" >&2
  exit 1
fi

MAIN_BRANCH_CHECKED_OUT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# E2 需要 `merge-tree --write-tree`（git >= 2.38）。舊 git 會把 --write-tree 當成 rev 而報錯。
# 保留 stderr：探測失敗有很多可能（版本、object DB 損毀、磁碟滿），不可吞掉它再斷言一個
# 從未證實的原因（rule 11：錯誤訊息的提示必須與它所解釋的分支共用同一個判斷式）。
MERGE_TREE_OK=0
if _probe=$(git merge-tree --write-tree "$BASE_SHA" "$BASE_SHA" 2>&1) && [ -n "$_probe" ]; then
  MERGE_TREE_OK=1
else
  echo "[WARN] merge-tree --write-tree 探測失敗——E2 不可用，squash 合併的分支需靠 E3" >&2
  echo "       （需 gh）判定，否則落到 REVIEW。最可能的原因是 git < 2.38，但這裡不臆測；" >&2
  echo "       git 實際回報：${_probe}" >&2
fi

# ── gh 閘門 ──
# gh 有兩個用途，**刻意分成兩次查詢**：
#   1. open PR -> KEEP 政策。用 `--state open`，數量小、不會被 --limit 截斷。
#   2. E3 的線索（mergeCommit）。用 `--state all --limit N`，可能被截斷——但截斷只會讓
#      E3 不成立 -> 落到 REVIEW（安全方向）。
# **不可以合成一次 `--state all` 查詢**：那樣一個比 N 個 PR 更舊的 open PR 會從結果裡消失，
# has_open_pr 讀成「沒有 open PR」-> KEEP 保護無聲失效。那正是本輪要修的 gh 閘門的另一種寫法
# （截斷版），而且完全不會發出警告。
#
# 「gh 不可用」不能被讀成「沒有 open PR」——那正是舊版的錯（實測：gh 掛掉時 open PR 的分支
# 照樣被刪）。與 fetch 閘門同一套推理：--apply 會刪東西，來源不可用就不刪。
OPEN_PR_TSV=""
PR_TSV=""
if [ "$HAS_GH" = "1" ]; then
  if ! OPEN_PR_TSV=$(gh pr list --state open --limit 1000 \
      --json headRefName -q '.[] | [.headRefName] | @tsv' 2>/dev/null); then
    HAS_GH=0
  elif ! PR_TSV=$(gh pr list --state all --limit "$GH_PR_LIMIT" \
      --json headRefName,headRefOid,state,baseRefName,mergeCommit \
      -q '.[] | [.headRefName, .headRefOid, .state, .baseRefName, (.mergeCommit.oid // "")] | @tsv' 2>/dev/null); then
    HAS_GH=0
  fi
fi
if [ "$HAS_GH" != "1" ]; then
  if [ "$APPLY" = "1" ]; then
    echo "[FAIL] gh 不可用（未安裝或查詢失敗）——無法確認哪些分支還有 open PR，" >&2
    echo "       因此不能證明刪除是安全的。--apply 模式下不刪任何東西。" >&2
    echo "       請先修好 gh（gh auth status），或不加 --apply 只看報告。" >&2
    exit 1
  fi
  echo "[WARN] gh 不可用——報告中的 open PR 保護不會生效，KEEP 可能少列" >&2
fi

# 收集被 worktree 佔用的分支 -> 其路徑。`$_wt_raw` 是前面已檢查過 exit status 的輸出。
WT_MAP=$(printf '%s\n' "$_wt_raw" | awk '
  /^worktree /{ path=substr($0, 10) }
  /^branch /   { br=$2; sub("refs/heads/", "", br); print br "\t" path }
')

# 用 ENVIRON 傳分支名，不用 awk -v：-v 會解讀反斜線跳脫。
wt_path_for() {
  br="$1" awk -F'\t' '$1==ENVIRON["br"] {print $2; exit}' <<EOF
$WT_MAP
EOF
}

has_open_pr() {
  [ "$HAS_GH" = "1" ] || return 1
  br="$1" awk -F'\t' '$1==ENVIRON["br"] {found=1} END{exit !found}' <<EOF
$OPEN_PR_TSV
EOF
}

# E3：PR 只是**線索**——它指出內容被裝進哪個 commit；真正的判定是那個 commit 還在不在
# base 的歷史裡。四個條件見檔頭。任何一個查不到／對不上 -> return 1（fail closed）。
# $1 = 分支純名（比對 PR 的 headRefName）、$2 = 已解析的 tip OID（呼叫端解析一次，全程共用）
evidence_pr_merge_commit_still_in_base() {
  local br="$1" tip="$2" mc
  [ "$HAS_GH" = "1" ] || return 1
  [ -n "$tip" ] || return 1

  mc=$(tip="$tip" base_branch="$BASE_BRANCH" awk -F'\t' '
    $2==ENVIRON["tip"] && $3=="MERGED" && $4==ENVIRON["base_branch"] && $5!="" {print $5; exit}' <<EOF
$PR_TSV
EOF
  )
  [ -n "$mc" ] || return 1

  # 條件 4：現況檢查。mergeCommit 必須存在於本地物件庫，且是 base 快照的祖先。
  git rev-parse --verify --quiet "${mc}^{commit}" >/dev/null 2>&1 || return 1
  git merge-base --is-ancestor "$mc" "$BASE_SHA" 2>/dev/null
}

# E1 / E2 都吃**已解析的 tip OID**，不吃分支名：分類期間分支可能前進，若證據查的是名字、
# CAS 記的是另一次解析的結果，就會發生「證據證明舊 tip 安全、卻刪掉新 tip」（Codex R2 C1）。
evidence_is_ancestor() {
  git merge-base --is-ancestor "$1" "$BASE_SHA" 2>/dev/null
}

evidence_merge_is_noop() {
  local tip="$1" mt
  [ "$MERGE_TREE_OK" = "1" ] || return 1
  mt=$(git merge-tree --write-tree "$BASE_SHA" "$tip" 2>/dev/null) || return 1
  # 乾淨合併時輸出就是單行 OID（實測：含 rename detection 也只有一行）；有衝突時 exit 非 0。
  # 不檢查長度：sha1 是 40 位、sha256 是 64 位，寫死 40 會在 sha256 repo 靜默廢掉 E2。
  case "$mt" in
    "" | *[!0-9a-f]*) return 1 ;;
  esac
  [ "$mt" = "$BASE_TREE" ]
}

# 遠端是否還有這個分支：三態 PRESENT / ABSENT / UNKNOWN。
# 不用 `git ls-remote --heads origin "$b"`：它對 ref 名稱做**尾部比對**，本地 `bar` 會被遠端
# 的 `refs/heads/feature/bar` 命中而回報「遠端仍在」——正好在刪除一個不可救回的分支之前
# 給出相反的保證（實測）。fetch 成功後 remote-tracking ref 就是答案，且免費、離線、精確。
remote_state() {
  [ "$FETCH_OK" = "1" ] || { echo UNKNOWN; return; }
  if git rev-parse --verify --quiet "refs/remotes/origin/$1" >/dev/null 2>&1; then
    echo PRESENT
  else
    echo ABSENT
  fi
}

remote_note_for() {
  case "$(remote_state "$1")" in
    PRESENT) echo "遠端仍在，可救回" ;;
    ABSENT)  echo "僅本地" ;;
    *)       echo "遠端狀態未知（fetch 失敗）" ;;
  esac
}

# worktree 內容檢查。設定全域 WT_DIRTY（未提交／untracked 的條目數；非 0 -> BLOCKED）。
# 讀不到狀態、或問到的不是這個 worktree 時 return 1 -> 呼叫端判 BLOCKED
# （缺少證據，不是「沒有問題」）。
#
# **toplevel 驗證是必要的，不是防禦性程式設計**（實測，PR #239 R2）：
# production 的 worktree 是**巢狀**在 repo 內（`.claude/worktrees/<name>`）且被 gitignore。
# 當 worktree 的 `.git` 連結檔不見時（admin dir 被 prune、主 repo 搬家／重新 clone），
# `git -C <wt> status` **不會失敗**——它往上走到主 repo，而主 repo 認為整個目錄是 ignored，
# 於是回傳 **rc=0 且輸出為空** -> WT_DIRTY=0 -> 閘門判定「乾淨」。問錯了 repo，卻拿到一個
# 看起來很乾淨的答案。實測：worktree 裡有 notes.txt，只要 rm 掉它的 .git，分類就從 BLOCKED
# 變成 SAFE。
WT_DIRTY=0
inspect_worktree() {
  local wt="$1" dirty_out top top_real wt_real
  WT_DIRTY=0

  top=$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null) || return 1
  [ -n "$top" ] || return 1
  top_real=$(cd "$top" 2>/dev/null && pwd -P) || return 1
  wt_real=$(cd "$wt" 2>/dev/null && pwd -P) || return 1
  # 問到的不是這個 worktree（往上走到主 repo 了）-> 沒有證據，不是乾淨
  [ "$top_real" = "$wt_real" ] || return 1

  if ! dirty_out=$(git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null); then
    return 1
  fi
  if [ -n "$dirty_out" ]; then
    WT_DIRTY=$(printf '%s\n' "$dirty_out" | grep -c .)
  fi
  return 0
}

SAFE_BRANCHES=()
SAFE_TIPS=()
SAFE_LINES=()
BLOCKED_LINES=()
KEEP_LINES=()
REVIEW_LINES=()

now_epoch=$(date +%s)

# `%(refname:strip=2)` 拿**純名**（`feat`，不是歧義相依的 `heads/feat`）：WT_MAP 與 gh 的
# headRefName 都是純名，比對 key 必須一致。所有 git 查詢則一律用 `refs/heads/$b`。見檔頭。
# 檢查真正那一次呼叫的 exit status，不要用另一個引數不同的探測來代答（實測：
# `for-each-ref --format='%(bogus)'` rc=128，而無 --format 的同名呼叫 rc=0）。
if ! BRANCHES=$(git for-each-ref --format='%(refname:strip=2)' refs/heads/ 2>&1); then
  echo "[FAIL] 無法列舉分支：${BRANCHES}" >&2
  exit 1
fi

while IFS= read -r b; do
  [ -z "$b" ] && continue
  [ "$b" = "$BASE_BRANCH" ] && continue

  if [ "$b" = "$MAIN_BRANCH_CHECKED_OUT" ]; then
    KEEP_LINES+=("  $b  (主 repo 目前 checkout 的分支)")
    continue
  fi

  if [ -n "$CALLER_BRANCH" ] && [ "$b" = "$CALLER_BRANCH" ]; then
    KEEP_LINES+=("  $b  (呼叫端所在分支)")
    continue
  fi

  wt_path=$(wt_path_for "$b")

  if [ -n "$wt_path" ]; then
    # 已註冊但路徑不存在（被搬走／未掛載／被 rm -rf）-> 缺少證據。
    # 註（突變測試界定，避免誇大）：這一段**不是**安全防線——拿掉它，`git -C <不存在的路徑>`
    # 會 exit 128，inspect_worktree 隨即 return 1，呼叫端一樣判 BLOCKED（實測：突變後測試仍
    # 全綠 = equivalent mutant）。它的作用只有一個：把「路徑不見了」與「路徑在但狀態壞掉」
    # 分成兩則不同的訊息。真正 fail-closed 的是 inspect_worktree。
    if [ ! -d "$wt_path" ]; then
      BLOCKED_LINES+=("  $b  (worktree 已註冊但路徑不存在，無法確認未提交內容：$wt_path)")
      continue
    fi
    if ! inspect_worktree "$wt_path"; then
      BLOCKED_LINES+=("  $b  (無法讀取 worktree 狀態，或它已不是有效的 worktree：$wt_path)")
      continue
    fi
    if [ "$WT_DIRTY" != "0" ]; then
      BLOCKED_LINES+=("  $b  ($WT_DIRTY 個未提交／untracked 變更於 $wt_path)")
      continue
    fi
  fi

  if has_open_pr "$b"; then
    KEEP_LINES+=("  $b  (open PR)")
    continue
  fi

  # tip 只解析**這一次**，之後 E1/E2/E3 與 CAS 全部共用它。
  # 若證據查名字、CAS 另外再解析一次，中間分支前進就會「證明舊 tip 安全、卻刪掉新 tip」。
  tip=$(git rev-parse --verify --quiet "refs/heads/$b" 2>/dev/null)
  if [ -z "$tip" ]; then
    REVIEW_LINES+=("  $b  (無法解析 tip，略過)")
    continue
  fi

  reason=""
  if evidence_is_ancestor "$tip"; then
    reason="tip 已是 $BASE 的祖先"
  elif evidence_merge_is_noop "$tip"; then
    reason="併回 $BASE 為 no-op（merge-tree 內容比對）"
  elif evidence_pr_merge_commit_still_in_base "$b" "$tip"; then
    reason="PR 的 merge commit 仍在 $BASE 的歷史中（tip SHA 相符）"
  fi

  if [ -n "$reason" ]; then
    note=$(remote_note_for "$b")
    SAFE_BRANCHES+=("$b")
    SAFE_TIPS+=("$tip")
    SAFE_LINES+=("  $b  [$reason; $note]")
    continue
  fi

  # 無證據 -> 只報告。附上年齡供人工判斷，但年齡本身不是刪除依據。
  last=$(git log -1 --format='%ct' "refs/heads/$b" 2>/dev/null)
  age="?"
  if [ -n "$last" ]; then
    age=$(( (now_epoch - last) / 86400 ))
  fi
  if ! ahead=$(git rev-list --count "${BASE_SHA}..refs/heads/$b" 2>/dev/null) || [ -z "$ahead" ]; then
    ahead="?"
  fi
  if [ "$age" != "?" ] && [ "$age" -ge "$STALE_DAYS" ]; then
    REVIEW_LINES+=("  $b  (${age}d 未更新, ${ahead} 個獨有 commit) [STALE]")
  else
    REVIEW_LINES+=("  $b  (${age}d, ${ahead} 個獨有 commit)")
  fi
done <<EOF
$BRANCHES
EOF

# printf '%s\n'（不是 '%b'）：'%b' 會解讀內容裡的跳脫序列，worktree 路徑含 `\` 時會把一行
# 拆成兩行。分支名不受影響（git check-ref-format 拒絕 `\`），但路徑會。
print_section() {
  local title="$1"; shift
  echo ""
  echo "$title"
  if [ "$#" -eq 0 ]; then
    echo "  (無)"
  else
    printf '%s\n' "$@"
  fi
}

print_section "══ SAFE：可刪除（已證實內容在 ${BASE}）══" ${SAFE_LINES[@]+"${SAFE_LINES[@]}"}
print_section "══ KEEP：保留 ══" ${KEEP_LINES[@]+"${KEEP_LINES[@]}"}
print_section "══ BLOCKED：有無法確認或未提交的內容，不自動處理 ══" ${BLOCKED_LINES[@]+"${BLOCKED_LINES[@]}"}
print_section "══ REVIEW：無證據顯示內容已進 ${BASE}，需人工判斷 ══" ${REVIEW_LINES[@]+"${REVIEW_LINES[@]}"}

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
PM_AVAILABLE=0
if [ -d "$MAIN_REPO/tasks/local_port_manager" ]; then
  # 這個 module 只存在於本 repo；不在就安靜跳過（別的 repo 沒有它，是正常狀態）。
  # 但 module 在而 uv 不在，是**錯誤狀態**，不可用同一個沉默處理掉：
  # fail-open 必須逐一列出它寬恕的條件（rule 11）。
  if command -v uv >/dev/null 2>&1; then
    PM_AVAILABLE=1
  else
    echo "[WARN] uv 不存在——port 登記無法釋放，將永久洩漏，需手動 release" >&2
  fi
fi

release_ports() {
  local b="$1" out svc
  [ "$PM_AVAILABLE" = "1" ] || return 0
  if ! out=$(uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager list -p "$b" 2>/dev/null); then
    echo "  [WARN] 讀取 port registry 失敗，略過 port 清理：${b}（登記可能需手動清）" >&2
    return 1
  fi
  # list 輸出是「表頭 + 分隔線 + 每行一筆」；無資料時只印一行提示，NR>2 自然為空。
  svc=$(printf '%s\n' "$out" | awk 'NR>2 {print $2}')
  [ -z "$svc" ] && return 0
  local rc=0
  while IFS= read -r s; do
    [ -z "$s" ] && continue
    if uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager release "$b" "$s" >/dev/null 2>&1; then
      echo "  [OK] port 登記已釋放：$b/$s"
    else
      echo "  [WARN] port 釋放失敗：$b/${s}（登記需手動清）" >&2
      rc=1
    fi
  done <<EOF
$svc
EOF
  return "$rc"
}

echo ""
echo "── 執行刪除（僅 SAFE 清單）──"
FAILED=0
i=0
for b in ${SAFE_BRANCHES[@]+"${SAFE_BRANCHES[@]}"}; do
  expected_tip="${SAFE_TIPS[$i]}"
  i=$((i + 1))

  # ── 破壞任何東西**之前**先驗證所有前提 ──
  # 順序是刻意的（Codex R2 I1）：舊版先移除 worktree、再釋放 port、最後才 CAS。若 ref 在
  # 這期間動了，CAS 正確地拒絕刪除分支——但 worktree 與 port 登記已經沒了，使用者拿到一個
  # 「刪除被拒絕」的訊息，卻已經失去它的工作目錄。所有檢查都要在第一個破壞性動作之前做完。

  # base 不能在分類後移動：另一個行程的 fetch（尤其 force push 後）會讓分類依據失效。
  now_base=$(git rev-parse --verify --quiet "${BASE}^{commit}" 2>/dev/null)
  if [ "$now_base" != "$BASE_SHA" ]; then
    echo "  [FAIL] ${BASE} 在分類後變動，全部中止（請重跑）" >&2
    FAILED=1
    break
  fi

  # ref 不能在分類後前進。CAS 最終會再擋一次（那是原子的），這裡先擋是為了不在
  # 「注定要中止」的情況下先把 worktree 砍掉。
  now_tip=$(git rev-parse --verify --quiet "refs/heads/$b" 2>/dev/null)
  if [ "$now_tip" != "$expected_tip" ]; then
    echo "  [WARN] 分支在分類後變動，略過：${b}" >&2
    echo "         分類時=${expected_tip}；現在=${now_tip:-不存在}" >&2
    FAILED=1
    continue
  fi

  wt_path=$(wt_path_for "$b")
  if [ -n "$wt_path" ] && [ -d "$wt_path" ]; then
    # 刪除前立即重掃：分類到刪除之間有窗口，期間可能有人在那個 worktree 裡動了檔案。
    if ! inspect_worktree "$wt_path"; then
      echo "  [WARN] 刪除前重掃失敗，略過分支：${b}" >&2
      FAILED=1
      continue
    fi
    if [ "$WT_DIRTY" != "0" ]; then
      echo "  [WARN] worktree 在分類後出現未提交變更，略過分支：${b}" >&2
      FAILED=1
      continue
    fi
  fi

  # ── 開始破壞 ──
  if [ -n "$wt_path" ]; then
    # `-c status.showUntrackedFiles=all`：git worktree remove 自己也會做一次 untracked 檢查，
    # 那是我們閘門之外的第二道防線——但它會繼承使用者的 status.showUntrackedFiles=no 而失效
    # （實測：檔案被刪）。加上這個覆寫，它才會正確拒絕。
    # 不加 --force：讓 git 的檢查真的能擋。gitignored 檔案不會讓它拒絕（實測），那正是我們
    # 要的——它們本來就該隨 worktree 消失。
    if git -c status.showUntrackedFiles=all worktree remove "$wt_path" >/dev/null 2>&1; then
      echo "  [OK] worktree 已移除：$wt_path"
    else
      echo "  [WARN] worktree 移除失敗，略過分支：${b}（可能被 lock、有未提交內容或殘留檔案）" >&2
      FAILED=1
      continue
    fi
  fi

  # compare-and-swap 刪除：ref 若在此刻仍與分類時相同才刪，否則 git 拒絕。
  # `git branch -D` 只認名字、不驗 SHA，會把併發寫入的 commit 一併刪掉（實測）。
  #
  # 注意 update-ref 與 branch -D 的一個**重要差異**（實測，PR #239 R2）：branch -D 會拒絕
  # 刪除「被 worktree 佔用」的分支，update-ref -d **不會**。上面已經先移除了 worktree，
  # 所以到這裡不該還有佔用；但若 WT_MAP 因故沒抓到某個 worktree，這道 git 內建保護就不在了。
  # 因此保留下面的佔用檢查——它補上 update-ref 沒有的那一層。
  still_occupied=$(wt_path_for "$b")
  if [ -n "$still_occupied" ] && [ -d "$still_occupied" ]; then
    echo "  [WARN] 分支仍被 worktree 佔用，不刪除 ref：${b}（${still_occupied}）" >&2
    FAILED=1
    continue
  fi
  if git update-ref -d "refs/heads/$b" "$expected_tip" 2>/dev/null; then
    echo "  [OK] 分支已刪除：$b"
    # port 登記只在刪除成功後才釋放：若刪除被拒，分支還在，它的 port 登記也該留著。
    if ! release_ports "$b"; then
      FAILED=1
    fi
  else
    echo "  [FAIL] 分支刪除失敗（ref 已變動或刪除被拒）：$b" >&2
    FAILED=1
  fi
done

# 不呼叫 `git worktree prune`（agy R2 實測）：它會把「路徑不見」的 worktree 從登記中移除，
# 而那正是我們判 BLOCKED 的依據——下一次執行時該分支就沒有 worktree，直接繞過 BLOCKED 檢查
# 而可能被刪。等於本腳本自己解除自己的守衛（延遲一輪才發作）。
# `git worktree remove` 已經會清掉它自己成功移除的那些登記；使用者手動 rm -rf 的殘留，
# 由使用者自己 prune。

echo ""
echo "剩餘分支："
git for-each-ref --format='  %(refname:strip=2)' refs/heads/

if [ "$FAILED" != "0" ]; then
  echo ""
  echo "[FAIL] 有項目刪除或清理失敗（見上方 [WARN]/[FAIL]）" >&2
  exit 1
fi
echo ""
echo "[OK] 完成"
