"""D6 scanner：Git 工作流程 & Commit 品質（機械分 6/10）。"""

import json
import subprocess  # nosec B404
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6


def _is_git_repo(target_dir: Path) -> bool:
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(target_dir), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _get_recent_commits(target_dir: Path, n: int = 20) -> list[str]:
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(target_dir), "log", f"--max-count={n}", "--pretty=format:%s"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _hook_registered_in_settings(hook_filename: str, settings_path: Path) -> bool:
    """驗證 hook 檔案名稱是否出現在 settings.json 的任一 hook 命令字串中。

    放在 .claude/hooks/ 的腳本若未在 settings.json 登記，不會被 Claude Code 執行。
    """
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    hooks_str = json.dumps(data.get("hooks", {}))
    return hook_filename in hooks_str


def scan_git(target_dir: Path) -> MechanicalFinding:
    """掃描 worktree 設定、branch 保護 hook。語意分（4 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    if not _is_git_repo(target_dir):
        findings.append("WARN: 非 git repo，跳過 D6 掃描")
        return MechanicalFinding(
            dimension="D6",
            label="Git 工作流程 & Commit",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    worktrees_dir = target_dir / ".claude" / "worktrees"
    if worktrees_dir.exists():
        score += 3
        findings.append(".claude/worktrees/ 存在（worktree 隔離已設定）")
    else:
        findings.append("WARN: .claude/worktrees/ 不存在")

    hooks_dir = target_dir / ".claude" / "hooks"
    settings_path = target_dir / ".claude" / "settings.json"
    protect_files = (
        [f for f in hooks_dir.iterdir() if f.is_file() and "protect" in f.name.lower()]
        if hooks_dir.exists()
        else []
    )
    if protect_files:
        registered = any(_hook_registered_in_settings(f.name, settings_path) for f in protect_files)
        if registered:
            score += 3
            findings.append("branch 保護 hook 存在且已在 settings.json 登記（有效）")
        else:
            findings.append(
                "WARN: protect hook 存在（.claude/hooks/）但未在 settings.json 登記——hook 不會生效"
            )
    else:
        findings.append("WARN: 未找到 branch 保護 hook")

    commits = _get_recent_commits(target_dir)
    if commits:
        extra: dict[str, list[str]] = {"recent_commits": commits}
        findings.append(f"git log 取得最近 {len(commits)} 筆（供 agent 評估風格）")
    else:
        extra = {}

    return MechanicalFinding(
        dimension="D6",
        label="Git 工作流程 & Commit",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
        extra=extra,
    )
