"""PR Creator：為通過 test 的 artifact 建立 GitHub PR。"""

from __future__ import annotations

import contextlib
import re
import subprocess  # nosec B404
from datetime import datetime
from pathlib import Path

from tasks._paths import PROJECT_ROOT

from .models import ArtifactProposal, ArtifactType, NightlyAgentConfig, PRRecord, TestResult


def _get_main_repo() -> Path:
    """Return main repo root (resolves worktree → main via --git-common-dir)."""
    result = subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).parent
    return PROJECT_ROOT


class PRCreator:
    """在 main repo 建立 PR branch 並呼叫 gh pr create。"""

    def __init__(self, config: NightlyAgentConfig) -> None:
        self.config = config
        self._main_repo = _get_main_repo()

    def create_pr(self, proposal: ArtifactProposal, test_result: TestResult) -> PRRecord:
        """建立 PR，回傳 PRRecord。"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe = re.sub(r"[^a-z0-9-]", "-", proposal.title.lower())[:40].strip("-")
        branch = f"{self.config.pr_branch_prefix}/{date_str}/{safe}"

        # All git operations run against main repo (not worktree)
        self._git(["checkout", "-b", branch, "origin/main"])

        artifact_path = self._main_repo / proposal.target_file
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_artifact(proposal, artifact_path)

        self._git(["add", str(artifact_path)])

        if proposal.test_file and Path(proposal.test_file).exists():
            self._git(["add", proposal.test_file])

        commit_msg = self._build_commit_message(proposal, test_result)
        self._git_commit(commit_msg)

        self._git(["push", "origin", f"{branch}:{branch}"])

        pr_body = self._build_pr_body(proposal, test_result)
        pr_url = self._gh_pr_create(branch, proposal.title, pr_body)
        pr_number = self._extract_pr_number(pr_url)

        with contextlib.suppress(RuntimeError):
            self._git(["checkout", "-"])

        return PRRecord(
            proposal_id=proposal.id,
            cluster_id=proposal.cluster_id,
            pr_url=pr_url,
            pr_number=pr_number,
            branch=branch,
            artifact_file=proposal.target_file,
            test_file=proposal.test_file,
        )

    def _git(self, args: list[str]) -> str:
        result = subprocess.run(  # nosec B603
            ["git", "-C", str(self._main_repo)] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {args[0]} 失敗：{result.stderr[:300]}")
        return result.stdout.strip()

    def _git_commit(self, message: str) -> None:
        msg_path = self._main_repo / ".runtime" / "nightly_agent_commit_msg.txt"
        msg_path.parent.mkdir(parents=True, exist_ok=True)
        msg_path.write_text(message, encoding="utf-8")
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(self._main_repo), "commit", "-F", str(msg_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git commit 失敗：{result.stderr[:300]}")

    def _apply_artifact(self, proposal: ArtifactProposal, artifact_path: Path) -> None:
        if proposal.artifact_type == ArtifactType.HOOKIFY_RULE:
            artifact_path.write_text(proposal.content, encoding="utf-8")
        else:
            if artifact_path.exists():
                existing = artifact_path.read_text(encoding="utf-8")
                if not existing.endswith("\n"):
                    existing += "\n"
                artifact_path.write_text(
                    existing + "\n" + proposal.content + "\n", encoding="utf-8"
                )
            else:
                artifact_path.write_text(proposal.content + "\n", encoding="utf-8")

    def _build_commit_message(self, proposal: ArtifactProposal, test_result: TestResult) -> str:
        ftype = proposal.friction_descriptions[0] if proposal.friction_descriptions else "friction"
        return (
            f"fix(nightly-agent): {proposal.title}\n\n"
            f"Artifact type: {proposal.artifact_type}\n"
            f"Friction type: {proposal.cluster_id[:8]} — {ftype[:80]}\n"
            f"Sessions: {', '.join(proposal.source_session_ids[:3])}\n"
            f"Test: failing-then-passing verified\n"
        )

    def _build_pr_body(self, proposal: ArtifactProposal, test_result: TestResult) -> str:
        session_links = "\n".join(f"- Session `{sid}`" for sid in proposal.source_session_ids[:5])
        friction_list = "\n".join(f"- {d}" for d in proposal.friction_descriptions[:5])
        return (
            f"## Nightly Self-Improvement Agent\n\n"
            f"**Artifact type:** `{proposal.artifact_type}`  \n"
            f"**Target file:** `{proposal.target_file}`\n\n"
            f"### Friction events this prevents\n\n"
            f"{friction_list}\n\n"
            f"### Source sessions\n\n"
            f"{session_links}\n\n"
            f"### Test validation\n\n"
            f"- Previously failing: `{test_result.previously_failed}`\n"
            f"- After artifact: `{test_result.passed}`\n\n"
            f"```\n{test_result.after_output[-400:]}\n```\n\n"
            f"---\n*Generated by `tasks.nightly_agent` on "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )

    def _gh_pr_create(self, branch: str, title: str, body: str) -> str:
        body_path = self._main_repo / ".runtime" / "nightly_agent_pr_body.txt"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body, encoding="utf-8")

        try:
            result = subprocess.run(  # nosec B603 B607
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    self.config.github_repo or ".",
                    "--base",
                    "main",
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body-file",
                    str(body_path),
                    "--label",
                    "nightly-agent",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self._main_repo),
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "gh CLI が見つかりません。brew install gh を実行してください。"
            ) from e

        if result.returncode != 0:
            raise RuntimeError(f"gh pr create 失敗：{result.stderr[:300]}")
        return result.stdout.strip()

    def _extract_pr_number(self, pr_url: str) -> int:
        m = re.search(r"/pull/(\d+)", pr_url)
        return int(m.group(1)) if m else 0
