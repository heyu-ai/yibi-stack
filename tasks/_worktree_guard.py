"""安裝前的 worktree 守門：確認即將被寫進機器層級設定的 repo 路徑不是 git worktree。

## 為什麼需要它（issue #237）

PR #234 把 `scripts/assert_not_worktree.sh` 接在 7 個 make target 的第一行，但那個
guard 住在 Makefile。繞過 make、直接呼叫 Python module 完全碰不到它——而這不是假想
路徑：`tasks/scheduler/cli.py` 的 `setup` 指令**自己就在教使用者**跑
`uv run python -m tasks.scheduler install`。

危害鏈：在 worktree 裡跑安裝 -> `PROJECT_ROOT`（`tasks/_paths.py` 以 `__file__` 自我
定位）是 worktree 路徑 -> 該路徑被寫進 LaunchAgent plist / `~/.claude/settings.json`
的 hook 指令 -> 分支合併、`/clean-merged` 刪掉 worktree -> 那些機器層級設定指向不存在
的路徑，每 60 秒（或每次 hook 觸發）靜默失敗，使用者不會收到任何通知。

## 為什麼是 subprocess 呼叫 shell script，而不是在 Python 重寫偵測

`assert_not_worktree.sh` 經過 7 輪 mob review、65 個測試，修掉至少 6 個 fail-open：
舊 git 無 `--path-format`、sudo 下的 dubious ownership、dangling `.git` symlink、
`$DIR` 是壞掉 worktree 的子目錄、`$()` subshell 吞 exit code、CDPATH 干擾。在 Python
憑直覺重寫等於把那 6 個坑重踩一次。**偵測維持單一實作**（那支 shell script），本模組
只是薄包裝——這裡沒有任何偵測邏輯，只有「怎麼呼叫」與「失敗時怎麼辦」。

## 為什麼用 `__file__` 定位 script 不是同一個 bug

`PROJECT_ROOT` 自我定位到「執行中的這份 checkout」——而本 guard 要驗的正是這份
checkout。自我定位在這裡剛好命中目標，與 issue #237 的 bug（把自我定位的結果寫進
不會跟著消失的地方）方向相反。
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import NoReturn

from ._paths import PROJECT_ROOT

# 守門腳本相對於 repo 根的固定位置；與 Makefile 的 7 個呼叫點是同一支腳本。
GUARD_SCRIPT = PROJECT_ROOT / "scripts" / "assert_not_worktree.sh"

# 腳本只跑幾個 git 查詢，正常在一秒內結束。逾時代表環境異常（如 git 卡在網路檔案
# 系統），屬於「無法判定」-> fail-closed。
TIMEOUT_SECONDS = 30


def _fail(message: str) -> NoReturn:
    """印出可行動的 [FAIL] 並中止。"""
    print(f"  [FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_not_worktree(command: str, repo_root: Path | None = None) -> None:
    """`repo_root` 是 git worktree、或無法安全判定時，[FAIL] 並 `SystemExit(1)`。

    Args:
        command: 使用者該改到主 repo 執行的**完整指令**（例如
            `uv run python -m tasks.mycelium insight install-hook`）。原樣傳給守門
            腳本，出現在它的 [FAIL] 訊息與 `cd <main> && <command>` 建議裡。腳本
            刻意不補 "make " 前綴，故此處必須傳含程式名的完整指令。
        repo_root: 要檢查的 repo 根；預設為本 checkout 的 `PROJECT_ROOT`。

    這個函式必須在**寫入任何檔案之前**呼叫。寫到一半才擋下來，機器層級設定已經被
    污染了——rule 11 的「guard 是第一個動作」在 Python 這側的對應寫法。
    """
    root = repo_root if repo_root is not None else PROJECT_ROOT

    if not GUARD_SCRIPT.is_file():
        _fail(
            f"找不到 worktree 守門腳本，無法判定是否可安裝，拒絕執行 {command}：\n"
            f"         {GUARD_SCRIPT}\n"
            f"         這份 checkout 可能不完整，請確認 repo 檔案齊全。"
        )

    # 用 `bash <script>` 而非直接 exec：exec bit 若在 checkout / 打包過程遺失，直接
    # exec 會 PermissionError，而經 bash 呼叫不受影響。
    bash = shutil.which("bash")
    if bash is None:
        _fail(f"找不到 bash，無法判定是否在 worktree 內，拒絕執行 {command}")

    # 不 capture：腳本的 [FAIL] 訊息已針對呼叫端的 command 客製（見上方 command 說明），
    # 直接讓它寫到使用者的 stderr，比在此重述一遍更準確也更少走樣。
    try:
        result = subprocess.run(  # nosec B603
            [bash, str(GUARD_SCRIPT), str(root), command],
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _fail(
            f"worktree 守門腳本逾時（超過 {TIMEOUT_SECONDS} 秒），無法判定是否在 "
            f"worktree 內，拒絕執行 {command}"
        )
    except OSError as e:
        _fail(f"無法執行 worktree 守門腳本（{e}），無法判定是否在 worktree 內，拒絕執行 {command}")

    if result.returncode != 0:
        # **不解讀 returncode 的意義**：腳本已把「是 worktree」與「判不出來」（參數缺漏、
        # 目錄不存在、git 呼叫失敗、路徑正規化失敗、暫存檔建不出來）全部歸進非 0，且都
        # 已印出可行動的 [FAIL]。在這裡分辨「哪種非 0 才算真的擋」只會製造新的
        # fail-open——正是 PR #234 反覆修掉的同一個形狀。任何非 0 = 不安全或無法確定。
        raise SystemExit(1)
