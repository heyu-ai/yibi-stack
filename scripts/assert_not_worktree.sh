#!/usr/bin/env bash
# 斷言指定目錄不是 git worktree，是 worktree 就 [FAIL] 擋下安裝。
#
# 用法：assert_not_worktree.sh <dir> <make-target-name>
# exit 0: 不在 worktree（含「非 git repo」的情況，見下方）
# exit 1: 在 worktree 內，或參數缺漏
#
# 為何需要這個 gate：
# make install 會把 $(CURDIR) 的路徑寫進 ~/.claude/skills/、~/.agents/skills/、
# ~/.agents/bin/ 的 symlink。在 worktree 裡跑，寫進去的就是 worktree 路徑，
# 而 worktree 在分支合併後會被 /clean-merged 刪除，屆時所有 symlink 變成 dangling，
# 全部 skill 失效。
#
# 為何 Makefile 既有的安裝後 gate 擋不住（見 Makefile install target 結尾）：
# 那個 gate 比對 `resolve-skill-repo 的輸出 == $(CURDIR)`。在 worktree 裡兩者
# 本來就相等（resolver 自我定位到 worktree，CURDIR 也是 worktree），故必定通過。
# 它能擋「指向別的 checkout」，擋不住「指向一個即將消失的 checkout」。
#
# 為何不改用 --git-common-dir 自動推導主 repo 路徑（issue #232 的另一個選項）：
# 那會讓使用者以為裝了眼前 worktree 的程式碼，實際裝的是主 repo 的（可能是舊
# commit 或別的分支）——即「安靜地做了別的事」，正是 issue #232 要消滅的問題類型。
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "[FAIL] 用法：assert_not_worktree.sh <dir> <make-target-name>" >&2
  exit 1
fi

DIR="$1"
TARGET="$2"

# 必須清掉繼承來的 git 環境變數：GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR 的優先權
# 高於 `git -C`，被設定時 git 會回報那個 repo 而無視 -C 指定的目錄。
# 對本 gate 而言後果特別嚴重：實測 GIT_DIR=<main>/.git 時，本腳本在 worktree 內
# 會從 exit 1 變成 exit 0，也就是「安靜放行 worktree 安裝」——gate 形同不存在。
# 這不是假想：git hook 執行期間本來就會設 GIT_DIR，而本 repo 大量使用 pre-commit hook。
# 同一 root cause 見 PR #233 對 resolve-skill-repo 的修法。
_GIT="env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE git"

# 非 git repo（例如下載 zip 解壓後安裝）不可能是 worktree，直接放行。
# 這裡刻意 fail-open：擋下合法的非 git 安裝是回歸，而 worktree 這個風險
# 本質上需要 git 才會發生。
if ! GIT_DIR_PATH=$($_GIT -C "$DIR" rev-parse --path-format=absolute --git-dir 2>/dev/null); then
  exit 0
fi
GIT_COMMON_PATH=$($_GIT -C "$DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)

# 主 repo：--git-dir 與 --git-common-dir 相同（都是 <repo>/.git）。
# worktree：--git-dir 是 <main>/.git/worktrees/<name>，--git-common-dir 是 <main>/.git。
# 用相等性判斷，而非比對 ".claude/worktrees" 字串——worktree 可以建在任意路徑。
if [ "$GIT_DIR_PATH" = "$GIT_COMMON_PATH" ]; then
  exit 0
fi

MAIN_REPO=$(dirname "$GIT_COMMON_PATH")
# 不直接印 $DIR：呼叫端可能傳相對路徑（"."），診斷訊息印出來對讀者無意義。
# 讓 git 回報 worktree 的絕對路徑；--show-toplevel 在 worktree 內正是回傳
# worktree 自身路徑（見 rule 15），這裡要的就是它。
WORKTREE_PATH=$($_GIT -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo "$DIR")

echo "  [FAIL] 偵測到目前在 git worktree 內，不可執行 make ${TARGET}：" >&2
echo "         ${WORKTREE_PATH}" >&2
echo "         worktree 會在分支合併後被刪除，屆時 ~/.claude/skills/、~/.agents/" >&2
echo "         的 symlink 會指向不存在的路徑，所有 skill 失效。" >&2
echo "         請改到主 repo 目錄執行：" >&2
echo "           cd ${MAIN_REPO} && make ${TARGET}" >&2
exit 1
