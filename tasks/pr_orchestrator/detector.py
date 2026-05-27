"""gh CLI wrappers：PR 偵測、CI 狀態、merge 狀態查詢。"""

from __future__ import annotations

import json
import re as _re
import subprocess  # nosec B404
from pathlib import Path

from .models import CIFailure, PRInfo


def _gh(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh 指令失敗：{result.stderr.strip()}")
    return result.stdout.strip()


def pr_for_branch(branch: str) -> PRInfo:
    """回傳目前分支對應的 PR；沒有 PR 或有多筆時 raise RuntimeError。"""
    raw = _gh(
        [
            "pr",
            "list",
            "--head",
            branch,
            "--json",
            "number,headRefName,headRefOid,baseRefName,mergeable,mergeStateStatus,author",
            "--limit",
            "5",
        ]
    )
    items = json.loads(raw or "[]")
    if not items:
        raise RuntimeError(f"分支 '{branch}' 沒有對應的 open PR")
    if len(items) > 1:
        nums = [str(i["number"]) for i in items]
        raise RuntimeError(
            f"分支 '{branch}' 對應多個 PR：{', '.join(nums)}；請用 --pr <n> 明確指定"
        )
    item = items[0]
    return PRInfo(
        number=item["number"],
        head_ref_name=item["headRefName"],
        head_ref_oid=item["headRefOid"],
        base_ref_name=item["baseRefName"],
        mergeable=item.get("mergeable", "UNKNOWN"),
        merge_state_status=item.get("mergeStateStatus", "UNKNOWN"),
        author_login=item.get("author", {}).get("login", ""),
    )


def pr_by_number(pr_number: int) -> PRInfo:
    """以 PR 號碼取得 PRInfo。"""
    raw = _gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,headRefName,headRefOid,baseRefName,mergeable,mergeStateStatus,author",
        ]
    )
    item = json.loads(raw)
    return PRInfo(
        number=item["number"],
        head_ref_name=item["headRefName"],
        head_ref_oid=item["headRefOid"],
        base_ref_name=item["baseRefName"],
        mergeable=item.get("mergeable", "UNKNOWN"),
        merge_state_status=item.get("mergeStateStatus", "UNKNOWN"),
        author_login=item.get("author", {}).get("login", ""),
    )


def current_branch() -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        msg = result.stderr.strip() or "detached HEAD？"
        raise RuntimeError(f"無法取得目前分支：{msg}")
    return branch


def current_user() -> str:
    raw = _gh(["api", "user", "-q", ".login"])
    return raw.strip()


def pr_diff_files(pr_number: int) -> list[str]:
    """取得 PR diff 涉及的所有檔案路徑（`gh pr diff --name-only`）。"""
    raw = _gh(["pr", "diff", str(pr_number), "--name-only"])
    return [line for line in raw.splitlines() if line.strip()]


def fetch_failed_check_logs(pr_number: int) -> list[CIFailure]:
    """取得每個失敗 check run 的 log 文字。

    使用 gh pr checks --json name,state,link，從 link URL 提取 workflow run ID，
    再透過 gh run view <run_id> --log-failed 取得失敗 log。
    同一 run 中的多個失敗 job 只擷取一次 log（避免重複）。
    """
    raw = _gh(
        [
            "pr",
            "checks",
            str(pr_number),
            "--json",
            "name,state,link",
        ]
    )
    checks = json.loads(raw or "[]")
    failures: list[CIFailure] = []
    seen_run_ids: set[str] = set()
    for c in checks:
        if c.get("state", "").upper() not in {"FAILURE", "TIMED_OUT"}:
            continue
        link = c.get("link", "")
        # Extract workflow run ID from URL: .../actions/runs/<run_id>/...
        m = _re.search(r"/actions/runs/(\d+)", link)
        if not m:
            continue
        run_id = m.group(1)
        if run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        try:
            log_text = _gh(["run", "view", run_id, "--log-failed"])
        except RuntimeError as e:
            log_text = f"[LOG_FETCH_ERROR: {e}]"
        failures.append(
            CIFailure(
                run_id=run_id,
                job_name=c.get("name", run_id),
                log_text=log_text,
            )
        )
    return failures


def is_conflicting(pr_number: int) -> bool:
    info = pr_by_number(pr_number)
    return info.mergeable == "CONFLICTING"


def all_checks_passing(pr_number: int) -> bool:
    raw = _gh(
        [
            "pr",
            "checks",
            str(pr_number),
            "--json",
            "state",
        ]
    )
    checks = json.loads(raw or "[]")
    if not checks:
        return False
    return all(c.get("state", "").upper() == "SUCCESS" for c in checks)
