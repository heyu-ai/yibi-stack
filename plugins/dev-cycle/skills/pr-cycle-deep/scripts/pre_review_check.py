#!/usr/bin/env python3
"""pre_review_check.py：pr-cycle-deep Step 1.5 的 pre-review 基線檢查（取代 3 個 Task agent）。

原本 Step 1.5 同時開 3 個 subagent，分別只跑一行指令（`gh pr diff`、`gh pr checks`、
`amplifier-verify.py`）。每個 subagent 都要重新載入整份基底 context（實測 session 第一個
turn 就有 110-165k token），換來的只是三個固定指令的輸出。這支 script 用一次 Bash call 做完，
完整輸出寫進報告檔，stdout 只印幾行摘要，讓主 context 保持精簡。

用法：
  python3 pre_review_check.py --pr 123 [--repo-root /path/to/worktree]

副作用：
  1. 建立 <repo-root>/.pr-review/ 並把 `.pr-review/` 加進 git exclude（與 setup-review-dir.sh
     相同位置，用 `git rev-parse --git-path info/exclude` 解析）
  2. 寫入 <repo-root>/.pr-review/pre-review-check.md（含 amplifier-verify 完整 stdout／stderr）

退出碼：
  0 = 基線取得成功，amplifier 無 MUST／SHOULD finding（CI 失敗或 pending 只是資訊，不在此阻斷）
  1 = amplifier-verify 回報 MUST／SHOULD finding：不要停，讀報告檔把 finding 寫進 final.md
  2 = 致命錯誤（gh 失敗、PR 不存在、amplifier-verify exit 2 或無法執行）：停下並回報 [FAIL]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT = 300
_SCRIPT_DIR = Path(__file__).resolve().parent
_AMPLIFIER = _SCRIPT_DIR / "amplifier-verify.py"
# gh pr checks 在 PR 還沒有任何 check 時的訊息（非零退出、stderr 只有這句）
_NO_CHECKS_MARKER = "no checks reported"


@dataclass
class RunResult:
    """子程序結果；returncode 為 None 代表程式根本沒跑起來（找不到指令或逾時）。"""

    returncode: int | None
    stdout: str
    stderr: str


def run(cmd: list[str], cwd: Path) -> RunResult:
    """執行指令並回傳結果；啟動失敗與逾時都轉成 returncode=None，不往外丟例外。"""
    try:
        proc = subprocess.run(  # nosec B603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
            # gh 的錯誤訊息會在地化，比對 _NO_CHECKS_MARKER 前固定英文
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as e:
        return RunResult(None, "", f"{cmd[0]} 無法執行：{e}")
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def summarize_diff(result: RunResult) -> tuple[str | None, str | None]:
    """解析 `gh pr view --json changedFiles,additions,deletions`；回傳 (摘要, 錯誤)。"""
    if result.returncode != 0:
        return None, f"gh pr view：{result.stderr.strip() or '無輸出'}"
    try:
        data = json.loads(result.stdout)
        files, adds, dels = data["changedFiles"], data["additions"], data["deletions"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, f"gh pr view 輸出無法解析：{result.stdout[:200]!r}"
    return f"{files} files, +{adds}/-{dels} lines", None


def summarize_checks(result: RunResult) -> tuple[str | None, str | None]:
    """解析 `gh pr checks --json name,bucket`；回傳 (摘要, 錯誤)。

    gh 以非零 exit code 表示「有 check 失敗」（1）或「仍在跑」（8），但 stdout 仍是合法 JSON，
    所以先看 stdout 能不能解析，再看 exit code。stdout 不是 JSON 時，只有「還沒有任何 check」
    這一種情況可以放行；其他一律視為工具錯誤（例如 auth 失敗），不可當成「CI 沒問題」。
    """
    try:
        checks = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        checks = None
    if isinstance(checks, list):
        if not checks:
            return "not yet triggered", None
        buckets: dict[str, list[str]] = {}
        for c in checks:
            buckets.setdefault(str(c.get("bucket", "unknown")), []).append(str(c.get("name", "?")))
        parts = [f"{b} {len(names)}" for b, names in sorted(buckets.items())]
        summary = " / ".join(parts)
        failing = buckets.get("fail", []) + buckets.get("cancel", [])
        if failing:
            summary += f" (failing: {', '.join(failing)})"
        return summary, None
    if result.returncode is not None and _NO_CHECKS_MARKER in result.stderr:
        return "not yet triggered", None
    return None, f"gh pr checks：{result.stderr.strip() or '無輸出'}"


def classify_amplifier(result: RunResult) -> tuple[str, int]:
    """把 amplifier-verify.py 的 exit code 對應成 (摘要, 本 script 的 exit code)。"""
    if result.returncode == 0:
        return "OK (exit 0: no spectra change / all TCs traced / TC check skipped)", 0
    if result.returncode == 1:
        return "MUST/SHOULD findings present (exit 1) -- read the report", 1
    if result.returncode == 2:
        return "[FAIL] fatal (exit 2) -- read the report", 2
    return f"[FAIL] amplifier-verify did not run cleanly (exit {result.returncode})", 2


def ensure_review_dir(repo_root: Path) -> Path:
    """建立 .pr-review/ 並加入 git exclude；失敗時 raise RuntimeError。"""
    review_dir = repo_root / ".pr-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    res = run(["git", "rev-parse", "--git-path", "info/exclude"], repo_root)
    if res.returncode != 0:
        raise RuntimeError(f"git rev-parse --git-path info/exclude 失敗：{res.stderr.strip()}")
    exclude = Path(res.stdout.strip())
    if not exclude.is_absolute():
        exclude = repo_root / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = exclude.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if ".pr-review/" not in current.splitlines():
        with exclude.open("a", encoding="utf-8") as fh:
            if current and not current.endswith("\n"):
                fh.write("\n")
            fh.write(".pr-review/\n")
    return review_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pr-cycle-deep Step 1.5 pre-review 基線檢查")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.repo_root is None:
        top = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
        if top.returncode != 0:
            print("[FAIL] 當前目錄不在 git repo 內（請在 PR 的 worktree 執行）", file=sys.stderr)
            return 2
        repo_root = Path(top.stdout.strip())
    else:
        repo_root = args.repo_root.resolve()

    pr = str(args.pr)
    diff_summary, diff_err = summarize_diff(
        run(["gh", "pr", "view", pr, "--json", "changedFiles,additions,deletions"], repo_root)
    )
    checks_summary, checks_err = summarize_checks(
        run(["gh", "pr", "checks", pr, "--json", "name,bucket"], repo_root)
    )
    amp = run([sys.executable, str(_AMPLIFIER), "--pr", pr], repo_root)
    amp_summary, exit_code = classify_amplifier(amp)

    errors = [e for e in (diff_err, checks_err) if e]
    if errors:
        exit_code = 2

    lines = [
        "Pre-review Check",
        f"- Diff: {diff_summary or '[FAIL] ' + str(diff_err)}",
        f"- CI: {checks_summary or '[FAIL] ' + str(checks_err)}",
        f"- Amplifier: {amp_summary}",
    ]
    try:
        review_dir = ensure_review_dir(repo_root)
        report = review_dir / "pre-review-check.md"
        report.write_text(
            "\n".join(lines)
            + "\n\n## amplifier-verify stdout\n\n```text\n"
            + amp.stdout
            + "\n```\n\n## amplifier-verify stderr\n\n```text\n"
            + amp.stderr
            + "\n```\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError) as e:
        print(f"[FAIL] 無法寫入 pre-review 報告：{e}", file=sys.stderr)
        return 2

    print("\n".join(lines))
    print(f"REPORT={report}")
    for e in errors:
        print(f"[FAIL] {e}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
