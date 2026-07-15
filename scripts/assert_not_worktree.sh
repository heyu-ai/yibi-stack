#!/usr/bin/env bash
# 斷言指定目錄不是 git worktree，是 worktree 就 [FAIL] 擋下安裝。
#
# 用法：assert_not_worktree.sh <dir> <make-target-name>
# exit 0: 確定不在 worktree —— 主 repo，或確定不是 git repo（見下方 fail-open 說明）
# exit 1: 在 worktree 內，**或無法安全判定狀態**
#         （參數缺漏、目錄不存在、git 呼叫失敗、路徑正規化失敗、暫存檔建不出來）
#         此為刻意的 fail-closed：判不出來就不准裝，總比裝到一個注定消失的
#         checkout 上、之後所有 skill 靜默失效好。
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
#
# 已知殘留（設計上的極限，非疏漏）：
# 一個「.git 已被整個刪除、但仍登記在主 repo」的 worktree 會被放行。此時該目錄
# 與解壓出來的 zip 在位元層面無法區分——本 gate 的 fail-open 判準就是「沒有 .git」。
# 要堵住得去掃描任意 repo 的 worktree admin dir，代價與收益不成比例。
# 註：.git 是 dangling symlink 的情況**有**被擋下（-L 測連結本身，見下方）；
# 只有「.git 完全不存在」這一種是真的無從辨識。
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "[FAIL] 用法：assert_not_worktree.sh <dir> <make-target-name>" >&2
  exit 1
fi

DIR="$1"
TARGET="$2"

if [ ! -d "$DIR" ]; then
  echo "[FAIL] 目錄不存在，無法判定是否為 worktree：${DIR}" >&2
  exit 1
fi

# 必須清掉繼承來的 git 環境變數：GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR 的優先權
# 高於 `git -C`，被設定時 git 會回報那個 repo 而無視 -C 指定的目錄。
# 對本 gate 而言後果特別嚴重：實測 GIT_DIR=<main>/.git 時，本腳本在 worktree 內
# 會從 exit 1 變成 exit 0，也就是「安靜放行 worktree 安裝」——gate 形同不存在。
# 這不是假想：git hook 執行期間本來就會設 GIT_DIR，而本 repo 大量使用 pre-commit hook。
# 同一 root cause 見 PR #233 對 resolve-skill-repo 的修法。
#
# LC_ALL=C 是下方「not a git repository」訊息比對的前提：git 會依語系翻譯錯誤訊息，
# 不鎖定語系的話，非英文環境下比對必定落空而誤判成「非預期錯誤」。
# GIT_CEILING_DIRECTORIES / GIT_DISCOVERY_ACROSS_FILESYSTEM 同屬「操控 git 找 repo」
# 的變數，一併清掉。實測（由 mob review 的 silent-failure-hunter 指出）：
# GIT_CEILING_DIRECTORIES=<worktree> 時，從該 worktree 的**子目錄**呼叫會讓 gate
# 回 exit 0。目前 7 個 Makefile 呼叫點都傳 $(CURDIR)（repo 根），走不到這條路徑，
# 但清掉是零成本，且這是最後一個 env 操控的缺口。
_GIT="env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE \
  -u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM LC_ALL=C git"

# CDPATH 必須清掉：下方 _abs_git_path 用 cd 正規化路徑，而 POSIX 規定 cd 的目標
# 若首段不是 . 或 ..（例如 git 回傳的 ".git"），就會去搜尋 CDPATH，命中時還會把
# 目的地印到 stdout，污染 $() 取值。實測（由 mob review 的 silent-failure-hunter
# 指出）：CDPATH 指向一個含 .git 的目錄時，`cd .git && pwd -P` 會回傳兩行。
# 目前尚不足以造成 fail-open，但讓 gate 的正確性依賴「git 剛好回相對還是絕對路徑」
# 是不必要的風險——git 確實會回相對路徑（子目錄下的 --git-common-dir 即為 ../.git）。
export CDPATH=

if ! GIT_ERR=$(mktemp); then
  echo "[FAIL] 無法建立暫存檔，無法判定是否為 worktree，拒絕安裝" >&2
  exit 1
fi
trap 'rm -f "$GIT_ERR"' EXIT

# 把 rev-parse 的輸出正規化成絕對路徑。
#
# 為何不用 --path-format=absolute：該 flag 是 git 2.31（2021）才加入。舊 git 上會回
# fatal，而 fatal 會被 fail-open 分支吃掉，讓整個 gate 靜默失效（PR #234 review 用
# git shim 實測：guard 從 exit 1 變 exit 0）。本 repo 明文在意舊 macOS 工具鏈
# （rule 13 記載 realpath 在 macOS < Ventura 不存在）。
#
# 為何也不能直接比對 raw 輸出（mob review 中 agy 的提案，實測後已由它自己撤回）：
# raw 格式不一致。實測主 repo 「子目錄」下：
#   git -C <main>/scripts rev-parse --git-dir        -> /abs/<main>/.git   （絕對）
#   git -C <main>/scripts rev-parse --git-common-dir -> ../.git            （相對）
# 兩者不等 -> 會誤擋主 repo 的安裝。--path-format 存在的理由正是正規化這件事。
#
# cd+pwd -P 同時滿足兩者：可攜（rule 13 已背書的寫法）且格式無關。
#
# 必須是 `pwd -P`（實體路徑）不能是 `pwd`（邏輯路徑）：git 對這兩個 flag 回傳的
# 路徑分屬不同命名空間。實測 symlink 化的 main repo 子目錄下：
#   git -C <link>/scripts rev-parse --git-dir        -> /private/var/.../real/.git （實體）
#   git -C <link>/scripts rev-parse --git-common-dir -> ../.git                    （相對）
# 相對路徑經邏輯 pwd 正規化會得到 /var/.../link/.git，與前者不等 -> 誤擋主 repo。
# pwd -P 把兩者都解析到實體路徑，比對才有意義。macOS 的 /var -> /private/var
# 就是這種 symlink，故此非理論風險（由 mob review 的 codex voice 指出並實測確認）。
_abs_git_path() {
  local raw
  if ! raw=$($_GIT -C "$1" rev-parse "$2" 2>"$GIT_ERR"); then
    return 1
  fi
  if [ -z "$raw" ]; then
    return 1
  fi
  # raw 為相對路徑時是相對於 $1；絕對路徑時 cd 亦可直接抵達。
  # cd 的錯誤要導進 $GIT_ERR 而非丟掉，且用截斷（>）不用附加（>>）：
  # 此時 GIT_ERR 裝的是「成功的」rev-parse 的 stderr（通常為空，偶爾是無關的 git
  # warning）。丟掉的話呼叫端 `cat "$GIT_ERR"` 印出空白；附加的話那個無關 warning
  # 會被當成錯誤原因呈現。截斷後只留 cd 自己的錯誤（ELOOP、權限、目錄被競態刪除）。
  # cd -- 分隔選項與運算元：路徑以 "-" 開頭時（如 -foo）cd 會當成 flag。
  # $(CURDIR) 一定是絕對路徑不會中招，但這是通用工具腳本，不該賭呼叫端。
  (cd -- "$1" && cd -- "$raw" && pwd -P) 2>"$GIT_ERR" || return 1
}

# fail-open 只允許一種情況：git 明確說「這不是 git repo」**且**該目錄真的沒有 .git。
#
# 不能用「rev-parse 失敗就放行」——那會把 git 版本過舊、dubious ownership
# （sudo make install / repo 屬於他人）、權限不足、git 不在 PATH、$DIR 讀不到
# 全部一併靜默放行，gate 形同不存在。這正是本 PR 要消滅的失敗類型。
#
# 但只比對訊息仍不夠：git 對「真的不是 repo」與「worktree 的 admin dir 不見了」
# 回報同一句話。實測（由 mob review 的 silent-failure-hunter 指出並複現）：
#   rm -rf <main>/.git/worktrees/<name>   （被 prune）      -> fatal: not a git repository: (null)
#   mv <main> <elsewhere>                 （主 repo 搬走）   -> fatal: not a git repository: (null)
# 兩者的 worktree 目錄裡 .git 檔案都還在，明確是 worktree，卻會被訊息比對放行
# ——而且正是「陳舊且注定消失」的目錄，即本 gate 存在的理由本身。
#
# 區分依據：合法的 fail-open 情境（解壓 zip 安裝）**根本沒有 .git 這個項目**。
# .git 存在卻被 git 判定為非 repo = 這個 repo 壞了，不是不存在 -> 擋下。
#
# 必須同時測 -e 與 -L：-e 會**跟隨** symlink，所以 dangling 的 .git symlink
# （連結還在、目標沒了）會讓 `! -e` 為真而走進 fail-open。實測（由 mob review 的
# codex voice 指出）：把真 worktree 的 .git 換成 dangling symlink 後 gate 回 exit 0。
# -L 測的是「連結本身存在」，兩者聯用才等於「這個目錄真的沒有 .git 項目」。
if ! $_GIT -C "$DIR" rev-parse --git-dir >/dev/null 2>"$GIT_ERR"; then
  if grep -qi "not a git repository" "$GIT_ERR" \
    && [ ! -e "$DIR/.git" ] && [ ! -L "$DIR/.git" ]; then
    exit 0
  fi
  echo "[FAIL] git 無法判定 ${DIR} 是否為 worktree，拒絕安裝：" >&2
  cat "$GIT_ERR" >&2
  if [ -e "$DIR/.git" ] || [ -L "$DIR/.git" ]; then
    echo "         （該目錄有 .git 但 git 判定為非 repo，代表這個 repo 壞了而非不存在。" >&2
    echo "           常見成因：worktree 的 admin dir 已被 prune、主 repo 已被搬移或" >&2
    echo "           重新 clone、或該 .git 本身不完整。請確認來源後再安裝。）" >&2
  fi
  exit 1
fi

if ! GIT_DIR_PATH=$(_abs_git_path "$DIR" --git-dir); then
  echo "[FAIL] 無法解析 git-dir，拒絕安裝：${DIR}" >&2
  cat "$GIT_ERR" >&2
  exit 1
fi

if ! GIT_COMMON_PATH=$(_abs_git_path "$DIR" --git-common-dir); then
  echo "[FAIL] 無法解析 git-common-dir，拒絕安裝：${DIR}" >&2
  cat "$GIT_ERR" >&2
  exit 1
fi

# 主 repo：--git-dir 與 --git-common-dir 正規化後相同（都是 <repo>/.git）。
# worktree：--git-dir 是 <main>/.git/worktrees/<name>，--git-common-dir 是 <main>/.git。
# 用相等性判斷，而非比對 ".claude/worktrees" 字串——worktree 可以建在任意路徑。
if [ "$GIT_DIR_PATH" = "$GIT_COMMON_PATH" ]; then
  exit 0
fi

# 主 repo 路徑取自 git 的權威 metadata：`git worktree list --porcelain` 第一筆
# 必為主 worktree。不用 dirname("$GIT_COMMON_PATH")——common dir 的父目錄不必然是
# 主 work tree（git clone --separate-git-dir / submodule 情境下會指到別處），
# 那會讓 [FAIL] 訊息叫使用者 cd 到一個錯的目錄。
#
# 必須用 `if !` 包住：本腳本是 set -e + pipefail，裸賦值 `X=$(cmd | awk)` 在 cmd
# 失敗時會讓整個腳本當場終止——而此處已確定是 worktree，卻會在印出 [FAIL] 之前
# 就死掉，使用者只看到 make Error 128 而無任何說明，下面的 dirname fallback 也
# 變成永遠碰不到的死碼。實測確認（由 mob review 的 agy voice 指出）。
# awk 不可用 `exit` 提早結束：那會讓 git 在還沒寫完時收到 SIGPIPE，pipefail 於是
# 捕捉到非零，即使 `worktree list` 本身成功也會走進 fallback（訊息品質下降）。
# 改成用旗標只取第一筆，讓 awk 讀完全部輸入（由 mob review 的 codex voice 指出）。
if ! MAIN_REPO=$($_GIT -C "$DIR" worktree list --porcelain 2>/dev/null \
  | awk '/^worktree / && !seen {print substr($0, 10); seen = 1}'); then
  MAIN_REPO=""
fi
# 不直接印 $DIR：呼叫端可能傳相對路徑（"."），診斷訊息印出來對讀者無意義。
# 讓 git 回報 worktree 的絕對路徑；--show-toplevel 在 worktree 內正是回傳
# worktree 自身路徑（見 rule 15），這裡要的就是它。
# fallback 用 printf 不用 echo：$DIR 若以 "-" 開頭（如 -n），echo 會把它當 flag 吃掉。
WORKTREE_PATH=$($_GIT -C "$DIR" rev-parse --show-toplevel 2>/dev/null \
  || printf '%s\n' "$DIR")

# 路徑含空格時，未加引號的 cd 指令複製貼上會失敗；一律用單引號包起來。
# 單引號內的單引號要用 '\'' 收尾再接續（POSIX sh 慣用法）。
_shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

echo "  [FAIL] 偵測到目前在 git worktree 內，不可執行 make ${TARGET}：" >&2
echo "         ${WORKTREE_PATH}" >&2
echo "         worktree 會在分支合併後被刪除，屆時 ~/.claude/skills/、~/.agents/" >&2
echo "         的 symlink 會指向不存在的路徑，所有 skill 失效。" >&2

# 只有在能從 git 權威 metadata 問出主 repo 時才給 cd 建議。
# 問不出來就明說問不出來，不用 dirname("$GIT_COMMON_PATH") 猜——那在
# --separate-git-dir / submodule 佈局下會指到一個不存在或無關的目錄，而
# 「誤導的訊息比簡短的訊息更糟」（rule 11；本點由 mob review 的 codex voice
# 以本 PR 自己寫下的原則反過來檢驗而發現）。
if [ -n "$MAIN_REPO" ]; then
  echo "         請改到主 repo 目錄執行：" >&2
  # install-one / install-force-one 需要 SKILL=<name>，只印 target 名會給出一條
  # 照抄就失敗的指令。呼叫端把完整 make 引數（含 SKILL=）當作 $TARGET 傳進來時，
  # 這裡原樣輸出即可。
  echo "           cd $(_shell_quote "$MAIN_REPO") && make ${TARGET}" >&2
else
  echo "         （無法從 git 問出主 repo 路徑，請自行切到主 repo 目錄後執行" >&2
  echo "           make ${TARGET}）" >&2
fi
exit 1
