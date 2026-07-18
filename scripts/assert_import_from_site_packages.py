"""斷言 tasks 載自 site-packages。

由 scripts/packaging_smoke_test.sh 在隔離 venv 中呼叫。

**它實際擋住什麼**：「wheel 裝了，但 `tasks` 根本 import 不進來」——例如 packages 設定
錯誤導致 wheel 內只有 metadata、或套件目錄結構壞掉。這種情況下 `portman --version` 可能
仍因 entry point 存在而看似正常，但 import 會炸。

**它不擋什麼（避免 over-claim）**：它*不是*「防止 checkout 遮蔽 site-packages」的保險。
本腳本由 venv 的 python 執行、`sys.path[0]` 是本腳本所在的 `<repo>/scripts`（其下無
`tasks/`），且 smoke test 已清空 PYTHONPATH——checkout 依建構就不可能被 import 到。
路徑斷言在此是**便宜的額外確認**，不是唯一防線。
"""

from __future__ import annotations

import sys


def main() -> None:
    import tasks.local_port_manager.cli as m

    origin = m.__file__ or "<unknown>"
    if "site-packages" not in origin:
        print(
            f"[FAIL] tasks 載自 {origin}，不是 site-packages；"
            "smoke test 可能靠某個 checkout 活著，此驗證不成立",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[OK] tasks 載自 site-packages：{origin}")


if __name__ == "__main__":
    main()
