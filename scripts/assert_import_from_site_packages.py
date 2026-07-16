"""反證：確認 tasks 載自 site-packages，而非某個 checkout。

由 scripts/packaging_smoke_test.sh 在隔離 venv 中呼叫。

為何需要這一步：smoke test 的宣稱是「wheel 在無 checkout 環境可獨立運作」。若 portman
其實是靠 cwd 上的某個 checkout 活著（例如 CI runner 恰好在 repo 根目錄執行），整個
smoke test 會通過卻毫無資訊量——它會變成一個永遠 PASS 的假閘門。斷言 module 的實際
載入路徑，是唯一能把「真的獨立」與「碰巧可用」區分開的檢查。
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
