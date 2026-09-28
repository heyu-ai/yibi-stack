#!/usr/bin/env python3
"""加總所有 open PR 對同一個檔案的行數增減，檢查合併後是否超過行數上限。

每個 PR 的 CI 只拿自己的 base 驗證行數上限（例如 pr-cycle-deep/SKILL.md 與
test_convergence_contract.py 的 `LINE_BUDGET`），看不到「多個 PR 都 merge 後」的總和。
2026-09-28 的實例：main 上 SKILL.md 1340 行剛好等於 budget，#494／#495／#474 三個 PR
並行修改；協調者只讀 main 上的 budget，誤判 #474 需要精簡，實際上 #474 的 branch
早已把 budget 調高到 1355。

本 script 做兩種檢查：

1. 單獨 merge：main 行數 + 該 PR 的淨增減 <= 該 PR merge 後生效的 budget
   （PR 有改 budget 檔時用它 branch 上的值；沒改時 branch 上的只是舊 base 殘值，用 main 的）
2. 全部 merge：main 行數 + 所有 PR 淨增減總和 <= main 與各 PR budget 中的最大值
   （調高 budget 的 PR 一旦 merge，它的 budget 就會落到 main 上）

已知限制：`gh pr list` 的 additions/deletions 是相對於各 PR 自己的 merge base，
不是目前的 main；PR 落後 main 很多時，淨增減可能與 rebase 後不同。結果是協調用的估算，
不是 gate 判決。

Exit code：0 = 都在上限內；1 = 至少一項超出；2 = 無法取得資料（gh 失敗、檔案不存在、
找不到 budget 常數）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass

DEFAULT_FILE = "plugins/dev-cycle/skills/pr-cycle-deep/SKILL.md"
DEFAULT_BUDGET_FILE = (
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py"
)
DEFAULT_BUDGET_VAR = "LINE_BUDGET"


@dataclass(frozen=True)
class PrDelta:
    """單一 open PR 對目標檔的淨增減，與它 merge 後生效的 budget。"""

    number: int
    head_ref: str
    delta: int
    budget: int


@dataclass(frozen=True)
class Report:
    """檢查結果；`violations` 為空代表都在上限內。"""

    main_lines: int
    main_budget: int
    prs: tuple[PrDelta, ...]
    combined_lines: int
    combined_budget: int
    violations: tuple[str, ...]


def parse_budget(text: str, var: str) -> int | None:
    """從 Python 原始碼找出頂層 `VAR = <int>`；找不到回傳 None。"""
    match = re.search(rf"^{re.escape(var)}\s*(?::\s*int\s*)?=\s*(\d+)\s*(?:#.*)?$", text, re.M)
    return int(match.group(1)) if match else None


def file_delta(files: list[dict[str, object]], path: str) -> int | None:
    """回傳 PR 對 `path` 的 additions - deletions；PR 沒改這個檔案時回傳 None。"""
    for entry in files:
        if entry.get("path") == path:
            additions = entry.get("additions")
            deletions = entry.get("deletions")
            if not isinstance(additions, int) or not isinstance(deletions, int):
                raise ValueError(f"PR 檔案資料缺少 additions/deletions：{entry!r}")
            return additions - deletions
    return None


def evaluate(main_lines: int, main_budget: int, prs: list[PrDelta]) -> Report:
    """計算單獨 merge 與全部 merge 兩種情境，列出超出上限的項目。"""
    violations: list[str] = []
    for pr in prs:
        standalone = main_lines + pr.delta
        if standalone > pr.budget:
            violations.append(
                f"#{pr.number} 單獨 merge 後 {standalone} 行，超過 merge 後生效的 budget {pr.budget}"
            )
    combined_lines = main_lines + sum(pr.delta for pr in prs)
    combined_budget = max([main_budget, *(pr.budget for pr in prs)])
    if combined_lines > combined_budget:
        violations.append(
            f"全部 merge 後 {combined_lines} 行，超過可能的最大 budget {combined_budget}"
        )
    return Report(
        main_lines=main_lines,
        main_budget=main_budget,
        prs=tuple(prs),
        combined_lines=combined_lines,
        combined_budget=combined_budget,
        violations=tuple(violations),
    )


def _run_gh(args: list[str]) -> str:
    try:
        proc = subprocess.run(  # nosec B603
            ["gh", *args], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"無法執行 gh {' '.join(args)}：{e}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} 失敗（exit {proc.returncode}）：{proc.stderr.strip()}"
        )
    return proc.stdout


def fetch_file(path: str, ref: str) -> str:
    """用 GitHub API 讀取指定 ref 上的檔案原文（不動本機 git refs）。"""
    return _run_gh(
        [
            "api",
            "-H",
            "Accept: application/vnd.github.raw",
            f"repos/{{owner}}/{{repo}}/contents/{path}?ref={ref}",
        ]
    )


def fetch_open_prs() -> list[dict[str, object]]:
    """回傳所有 open PR 的 number、headRefName、files。"""
    out = _run_gh(
        ["pr", "list", "--state", "open", "--limit", "100", "--json", "number,headRefName,files"]
    )
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"gh pr list 回傳的不是 JSON：{out[:200]!r}") from e
    if not isinstance(data, list):
        raise RuntimeError(f"gh pr list 回傳格式非預期：{type(data).__name__}")
    return data


def _budget_at(budget_file: str, var: str, ref: str) -> int:
    budget = parse_budget(fetch_file(budget_file, ref), var)
    if budget is None:
        raise RuntimeError(f"{ref}:{budget_file} 找不到 {var} = <int>")
    return budget


def collect(path: str, budget_file: str, var: str, base: str) -> Report:
    """從 GitHub 收集資料並計算報告。"""
    main_lines = len(fetch_file(path, base).splitlines())
    main_budget = _budget_at(budget_file, var, base)
    prs: list[PrDelta] = []
    for pr in fetch_open_prs():
        files = pr.get("files") or []
        if not isinstance(files, list):
            raise RuntimeError(f"PR #{pr.get('number')} 的 files 格式非預期")
        delta = file_delta(files, path)
        if delta is None:
            continue
        head = str(pr.get("headRefName") or "")
        number = pr.get("number")
        if not head or not isinstance(number, int):
            raise RuntimeError(f"PR 資料缺少 number/headRefName：{pr!r}")
        # 只有 PR 自己改了 budget 檔，merge 後生效的才是 branch 上的值；否則 branch 上的
        # 只是舊 base 的殘值（#497：branch 仍是 1340，main 已是 1355），應以 main 為準
        touches_budget = any(e.get("path") == budget_file for e in files)
        budget = _budget_at(budget_file, var, head) if touches_budget else main_budget
        prs.append(PrDelta(number, head, delta, budget))
    return evaluate(main_lines, main_budget, prs)


def format_report(report: Report, path: str, base: str) -> str:
    lines = [
        f"目標檔：{path}",
        f"{base}：{report.main_lines} 行，budget {report.main_budget}",
    ]
    if not report.prs:
        lines.append("沒有 open PR 修改這個檔案。")
    for pr in report.prs:
        lines.append(
            f"  #{pr.number}（{pr.head_ref}）：{pr.delta:+d} 行，merge 後 budget {pr.budget}"
        )
    lines.append(
        f"全部 merge 後：{report.combined_lines} 行（最大 budget {report.combined_budget}）"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", default=DEFAULT_FILE, help="要檢查行數的檔案（repo 相對路徑）")
    parser.add_argument("--budget-file", default=DEFAULT_BUDGET_FILE, help="定義 budget 常數的檔案")
    parser.add_argument("--budget-var", default=DEFAULT_BUDGET_VAR, help="budget 常數名稱")
    parser.add_argument("--base", default="main", help="比較基準的 branch")
    args = parser.parse_args(argv)

    try:
        report = collect(args.file, args.budget_file, args.budget_var, args.base)
    except (RuntimeError, ValueError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    print(format_report(report, args.file, args.base))
    if report.violations:
        for v in report.violations:
            print(f"[FAIL] {v}", file=sys.stderr)
        return 1
    print("[OK] 單獨 merge 與全部 merge 都在 budget 內")
    return 0


if __name__ == "__main__":
    sys.exit(main())
