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
# 已知殘留（設計上的極限，非疏漏）——範圍經實測界定，勿當成「凡壞掉都擋得住」：
#
# 唯一漏網的是「.git 已被整個刪除、且該 worktree 位於主 repo 樹**外**」的情況。
# 此時 git 上下都找不到 repo，該目錄與解壓出來的 zip 在位元層面無法區分，
# 而本 gate 的 fail-open 判準正是「沒有 .git」。要堵住得掃描任意 repo 的 worktree
# admin dir，代價與收益不成比例。
#
# 以下三種都**有**被擋下（曾各自漏過，皆由 mob review 抓出並補上）：
# - .git 是 dangling symlink（-L 測連結本身，-e 會跟隨連結而漏判）
# - $DIR 是壞掉 worktree 的子目錄（往上走訪祖先找 .git）
# - admin dir 被 prune / 主 repo 被搬走（.git 還在 -> 判定為「壞掉」而非「不存在」）
#
# 另有一種不會漏但機制不同：worktree 在主 repo 樹**內**（如本 repo 的
# .claude/worktrees/<name>）且 .git 被刪除時，git 會往上解析到主 repo，
# --git-dir 與 --git-common-dir 相等 -> 走正常放行路徑。此時該目錄事實上
# 已不是 worktree 而只是主 repo 裡的一般目錄，放行不構成本 gate 要防的危害。
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

# CDPATH 必須在**任何 cd 之前**清掉，包括下面那個正規化用的 cd。
# POSIX：cd 的運算元若不以 /、. 或 .. 開頭就會搜尋 CDPATH，命中時還會把目的地印到
# stdout。於是 `DIR=$(cd -- "$DIR" && pwd -P)` 在相對路徑下會 (a) 跑去完全不同的
# 目錄，(b) 取回兩行垃圾。實測（由 mob review 的 silent-failure-hunter 指出）：
# CDPATH 指向 trap 目錄時，DIR='wt' 會讓 gate 去評估 <trap>/wt。
# 那個情況雖然碰巧 fail-closed（垃圾字串讓 git 報錯而不匹配 not-a-repo），
# 但那是意外而非設計，且 [FAIL] 會指名錯的目錄——正是本腳本三度援引 rule 11
# 反對的「誤導訊息」。
export CDPATH=

# 立刻正規化成絕對實體路徑。這不是整潔問題而是正確性問題：
# 下方 _find_broken_git_ancestor 用 `dirname` 逐層往上走，而 `dirname .` 回傳 `.`，
# 相對路徑會讓那個迴圈**永遠跑不到 "/"** -> 無限迴圈，make 整個掛住（比 fail-open
# 更糟：使用者連錯誤訊息都沒有）。實測：`assert_not_worktree.sh . install` 在一個
# 非 git 目錄下 timeout（codex 與 agy 亦各自獨立指出同一點）。
# 呼叫端目前都傳 $(CURDIR)（絕對路徑）走不到，但這是通用工具腳本，不該賭呼叫端。
if ! DIR=$(cd -- "$DIR" && pwd -P); then
  echo "[FAIL] 無法解析目錄的絕對路徑，拒絕安裝：$1" >&2
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
#
# 而且只看 $DIR 自己還不夠：$DIR 可能是壞掉 worktree 的**子目錄**，此時 .git 在
# worktree 根而不在 $DIR。實測（由 mob review 的 codex voice 指出）：prune 掉 admin
# dir 後，gate 對 worktree 根回 exit 1（正確），對子目錄卻回 exit 0（放行）。
# 故要從 $DIR 往上走訪祖先。安全性：本分支只在 git 已宣告「上下都找不到 repo」時
# 才進入，所以此處找到的任何 .git 必然是壞的，而 $DIR 就在它裡面 -> 擋下。
# $1 必須是絕對路徑（上方已正規化）：相對路徑會讓 `dirname .` 永遠回 `.`，迴圈掛死。
# 深度上限是第二道保險：任何讓 dirname 不再收斂的意外（怪異掛載、超深路徑）都不該
# 變成「make 無聲掛住」——那比 fail-open 更難診斷。與 resolve-skill-repo 的 symlink
# 迴圈上限同一個理由。
#
# 回傳碼（呼叫端必須逐一分辨，不可只用 `if !`）：
#   0 = 找到 .git 祖先（印在 stdout）
#   1 = 走到 / 都沒找到
#   2 = 超過深度上限，無法判定
# 本函式**不可用 exit**：它被 `$(...)` 呼叫，那是 subshell，exit 只結束 subshell，
# 腳本會繼續跑並把「無法判定」誤當成「沒找到」而走進 fail-open。此坑由本 PR 自己的
# 突變測試抓到——當時深度上限確實印了 [FAIL] 卻仍 exit 0。
_find_broken_git_ancestor() {
  local d="$1"
  local depth=0
  while :; do
    if [ -e "$d/.git" ] || [ -L "$d/.git" ]; then
      printf '%s\n' "$d"
      return 0
    fi
    [ "$d" = "/" ] && return 1
    depth=$((depth + 1))
    # 上限取 1000：PATH_MAX 在 macOS 是 1024 bytes，每段至少「1 字元 + 分隔符」，
    # 故任何合法路徑最多約 512 段。設 100 會誤擋合法的深路徑（那是 fail-closed，
    # 但仍是回歸）；1000 遠高於任何真實路徑，只在 dirname 真的不收斂時才觸發。
    if [ "$depth" -gt 1000 ]; then
      return 2
    fi
    d=$(dirname -- "$d")
  done
}

# 提示訊息必須與 fail-open 判準共用同一個前提（git 確實說了「不是 repo」），
# 不能只看「有沒有 .git」。否則任何其他 git 失敗（dubious ownership、git 不在
# PATH）發生在一個有 .git 的目錄時，都會印出「這個 repo 壞了、admin dir 被 prune、
# 主 repo 被搬移」——實測在**健康的主 repo** 上會照印，全部是假的（由 mob review
# 的 silent-failure-hunter 指出）。這與本腳本援引 rule 11 移除 dirname fallback 是
# 同一條原則：那個 fallback 指出可能錯的「目錄」，這個提示指出可能錯的「原因」。
if ! $_GIT -C "$DIR" rev-parse --git-dir >/dev/null 2>"$GIT_ERR"; then
  if grep -qi "not a git repository" "$GIT_ERR"; then
    WALK_RC=0
    BROKEN_AT=$(_find_broken_git_ancestor "$DIR") || WALK_RC=$?
    if [ "$WALK_RC" -eq 0 ]; then
      echo "[FAIL] git 無法判定 ${DIR} 是否為 worktree，拒絕安裝：" >&2
      cat "$GIT_ERR" >&2
      echo "         （${BROKEN_AT} 有 .git 但 git 判定為非 repo，代表這個 repo 壞了" >&2
      echo "           而非不存在。常見成因：worktree 的 admin dir 已被 prune、主 repo" >&2
      echo "           已被搬移或重新 clone、或該 .git 本身不完整。請確認來源後再安裝。）" >&2
      exit 1
    fi
    if [ "$WALK_RC" -ne 1 ]; then
      # rc=2：超過深度上限，無法判定 -> fail-closed（不可當成「沒找到」而放行）
      echo "[FAIL] 祖先目錄走訪超過上限，無法判定是否為 worktree，拒絕安裝：${DIR}" >&2
      exit 1
    fi
    # git 說沒有 repo，且一路到 / 都找不到 .git -> 真的不是 git repo（解壓 zip）-> 放行
    exit 0
  fi
  # 其他 git 失敗：擋下，但不猜原因——只把 git 自己的訊息透出來。
  echo "[FAIL] git 無法判定 ${DIR} 是否為 worktree，拒絕安裝：" >&2
  cat "$GIT_ERR" >&2
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
  # 相等不代表安全：worktree 的 .git 檔被刪除、而該 worktree 又位於主 repo 樹內
  # （本 repo 的 .claude/worktrees/<name> 正是如此）時，git 會往上解析到主 repo，
  # 兩者於是相等 -> 放行。但實測該 worktree **仍登記在主 repo**（git worktree list
  # 標記為 prunable），所以「它已經只是一般目錄」的推論並不成立（由 mob review 的
  # codex voice 指出）。
  #
  # 註（實測界定，避免誇大）：本 repo 目前沒有任何工具會刪除該目錄——
  # `git worktree prune` 只移除 admin entry 不動目錄，/clean-merged 與 /clean-gone
  # 也沒有刪 worktree 目錄的邏輯。故危害鏈未閉合。但與其用文字論證它安全，
  # 不如直接問 git：只要這個路徑仍登記為 linked worktree 就擋下。
  if REGISTERED=$($_GIT -C "$DIR" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{print substr($0, 10)}'); then
    _main_seen=0
    while IFS= read -r wt; do
      [ -z "$wt" ] && continue
      # 第一筆必為主 worktree，跳過；其餘皆為 linked worktree。
      if [ "$_main_seen" -eq 0 ]; then
        _main_seen=1
        continue
      fi
      wt_abs=$(cd -- "$wt" 2>/dev/null && pwd -P) || continue
      if [ "$DIR" = "$wt_abs" ]; then
        echo "  [FAIL] ${DIR} 仍登記為 git worktree（其 .git 已遺失），不可執行 make ${TARGET}：" >&2
        echo "         git 會把它解析成主 repo，但 git worktree list 仍將它列為 worktree。" >&2
        echo "         在此安裝會把全域 symlink 指向一個狀態不明的目錄。" >&2
        echo "         請先在主 repo 執行 git worktree prune 或移除此目錄後再安裝。" >&2
        exit 1
      fi
    done <<EOF
$REGISTERED
EOF
  fi
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
