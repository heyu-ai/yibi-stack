#!/usr/bin/env python3
"""agy_print_timeout.py：pr-cycle-deep 三支 agy 腳本共用的 print-timeout 預算與偵測（issue #443）。

agy 自 1.1.28 起，`--print-timeout` 到期時**回傳已產出的片段並 exit 0**（changelog 1.1.28 原文：
"returns the partial output it has and exits successfully with a warning on stderr, instead of
failing with a timeout error"）。以 agy 1.2.4 實測複驗：exit 0，stderr 印出
`[agy] print timeout after 40s with turn in progress; returning partial output`。
對 mob review 而言，這代表半截的 R1／R2 會被當成一份完整的 voice 計入 consensus——
R2 格式的第一個 heading 就是 `## Cross-review verdict`，agy_validate.py 的 verdict 子字串
檢查會直接放行。

實測另一個形狀：卡在 429 RESOURCE_EXHAUSTED 退避重試時逾時，stdout 是 0 bytes，而 429 只寫進
agy log、stderr 完全沒有。舊腳本此時回報「輸出空白」或「JSON 萃取失敗」，看不出真正原因。

子命令：
  budget  讀 AGY_PRINT_TIMEOUT_SECS（未設或空字串用預設 480），必須是 1..570 的純數字；
          通過時把值印到 stdout，否則 [FAIL] 並 exit 2。
  check   以兩個獨立訊號判定逾時：stderr 標記，或實際耗時 > 預算（標記是呈現層，措辭會隨版本
          改）。逾時時把半截輸出改名成 `<stem>.timeout-partial<suffix>`（0600），讓下游聚合
          讀不到，並 exit 1。

退出碼（check）：0 未逾時；1 逾時（輸出已隔離）；2 參數或 IO 錯誤（無法判定，不可當成未逾時）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ENV_VAR = "AGY_PRINT_TIMEOUT_SECS"
BUDGET_DEFAULT_SECS = 480
# 上界 570 而非 599：預算計的是 agy 內部時間，牆鐘還要加上 language server 啟動（實測 40 秒預算
# 牆鐘 41 秒）。Claude Code Bash tool 上限 600 秒，貼著它設會讓 harness 先砍掉整支腳本，
# 所有 [FAIL] 診斷都印不出來。與 agy-review／agy-consult 的上下界一致。
BUDGET_MAX_SECS = 570
_MARKER = "print timeout after"
_QUOTA_TOKEN = "RESOURCE_EXHAUSTED"


def resolve_budget(raw: str | None) -> int:
    """驗證並回傳時間預算秒數；不合法時 raise ValueError。

    只接受純 ASCII 數字：`int()` 會接受 `+5`、前後空白與底線分隔，這些都不是使用者該傳的形狀。
    """
    if raw is None or raw == "":
        return BUDGET_DEFAULT_SECS
    if not (raw.isascii() and raw.isdigit()):
        raise ValueError(f"{ENV_VAR} 必須是整數秒（收到：{raw!r}），例如 {BUDGET_DEFAULT_SECS}")
    value = int(raw)
    if not 1 <= value <= BUDGET_MAX_SECS:
        raise ValueError(
            f"{ENV_VAR} 必須介於 1 與 {BUDGET_MAX_SECS} 之間（收到：{raw}）。"
            "上界留了 30 秒餘裕給 agy 啟動；貼著 600 會讓 Claude Code Bash tool 先砍掉腳本，"
            "0 則會讓耗時判定對每次執行都成立。"
        )
    return value


def detect_print_timeout(stderr_text: str, *, elapsed_secs: int, budget_secs: int) -> str | None:
    """回傳逾時理由；未逾時回傳 None。

    耗時用嚴格大於：bash 的 SECONDS 是整數，剛好在預算邊界完成的正常回答不應被誤判。
    """
    if _MARKER in stderr_text:
        return "agy 在 stderr 印出 print timeout 標記"
    if elapsed_secs > budget_secs:
        return "實際耗時超過預算（agy 未印出標記，故為疑似 timeout）"
    return None


def quarantine_partial(raw: Path) -> Path | None:
    """把半截輸出改名移開並設為 0600；原檔不存在時回傳 None。"""
    if not raw.exists():
        return None
    target = raw.with_name(f"{raw.stem}.timeout-partial{raw.suffix}")
    os.replace(raw, target)
    target.chmod(0o600)
    return target


def last_quota_line(agy_log_text: str) -> str | None:
    """回傳 agy log 中最後一筆 429 RESOURCE_EXHAUSTED 重試行。"""
    hits = [line for line in agy_log_text.splitlines() if _QUOTA_TOKEN in line]
    return hits[-1] if hits else None


def _cmd_budget() -> int:
    try:
        print(resolve_budget(os.environ.get(ENV_VAR)))
    except ValueError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    label = args.label
    try:
        stderr_text = args.stderr_log.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(
            f"[FAIL] {label}：無法讀取 agy stderr log（{e}），無法確認輸出是否因 timeout 而不完整",
            file=sys.stderr,
        )
        return 2

    reason = detect_print_timeout(
        stderr_text, elapsed_secs=args.elapsed_secs, budget_secs=args.budget_secs
    )
    if reason is None:
        return 0

    try:
        moved = quarantine_partial(args.raw)
    except OSError as e:
        print(
            f"[FAIL] {label}：偵測到 timeout（{reason}），但無法移開半截輸出 {args.raw}（{e}）。"
            "該檔內容不完整，不可計入 mob consensus。",
            file=sys.stderr,
        )
        return 2

    kept = f"已移到 {moved}" if moved is not None else "沒有產出任何輸出"
    print(
        f"[FAIL] {label}：agy 在 {args.budget_secs} 秒預算內沒有完成"
        f"（實際 {args.elapsed_secs} 秒）：{reason}。"
        f"agy 此時仍 exit 0，輸出可能只是半截，已不計入 mob consensus；{kept}。",
        file=sys.stderr,
    )
    if args.agy_log is not None:
        try:
            quota = last_quota_line(args.agy_log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            quota = None  # log 不存在只代表少一條線索，主因已由上方 [FAIL] 說明
        if quota is not None:
            print(
                f"[INFO] agy log 有 429 {_QUOTA_TOKEN} 重試紀錄（常是逾時主因），最後一筆：{quota}",
                file=sys.stderr,
            )
    print(
        f"       可用 {ENV_VAR} 調整預算（1-{BUDGET_MAX_SECS}）；agy log：{args.agy_log}",
        file=sys.stderr,
    )
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="agy print-timeout 預算與偵測（issue #443）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("budget", help=f"驗證並印出 {ENV_VAR}")
    check = sub.add_parser("check", help="判定 agy 是否因 print timeout 回傳半截輸出")
    check.add_argument("--raw", type=Path, required=True, help="agy stdout 輸出檔")
    check.add_argument("--stderr-log", type=Path, required=True, help="agy stderr 落地檔")
    check.add_argument("--agy-log", type=Path, default=None, help="agy --log-file 路徑")
    check.add_argument("--elapsed-secs", type=int, required=True)
    check.add_argument("--budget-secs", type=int, required=True)
    check.add_argument("--label", default="agy")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "budget":
        return _cmd_budget()
    return _cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
