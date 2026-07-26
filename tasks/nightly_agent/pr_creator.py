"""PR Creator：為通過 test 的 artifact 建立 GitHub PR。"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess  # nosec B404
import sys
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
        """建立 PR，回傳 PRRecord。

        所有寫入性 git 操作（checkout -b / add / commit / push）都在專屬的 `git worktree`
        內進行，絕不動到 main repo 的共用 checkout 與其目前的分支/未 commit 狀態——main repo
        當下可能正被人或其他 session 使用，任何未 commit 的追蹤檔案改動都會讓
        `git checkout -b` 直接失敗（`would be overwritten by checkout`），且失敗或中斷時
        殘留的分支/未 commit 內容會一路帶進下一次 checkout，污染 main repo（見
        `.runtime/logs/nightly-self-improvement_20260725_210002.log`：main repo 有未 commit
        檔案，同一次排程連續 4 次 create_pr 因此失敗）。worktree 與其分支用完即刪
        （`git worktree remove` 本身不會刪分支，需另外 `branch -D`），不論成功或失敗都不
        在 main repo 留下痕跡。
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe = re.sub(r"[^a-z0-9-]+", "-", proposal.title.casefold())[:40].strip("-")
        if not safe:
            stable_id = hashlib.sha256(
                f"{proposal.cluster_id}|{proposal.title}".encode()
            ).hexdigest()[:10]
            safe = f"friction-{stable_id}"
        branch = f"{self.config.pr_branch_prefix}/{date_str}/{safe}"

        worktree_dir = self._main_repo / ".claude" / "worktrees" / branch.replace("/", "-")
        self._cleanup_worktree(worktree_dir, branch)
        self._git(["worktree", "add", str(worktree_dir), "-b", branch, "origin/main"])
        try:
            artifact_path = worktree_dir / proposal.target_file
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            self._apply_artifact(proposal, artifact_path)

            self._git(["add", str(artifact_path)], cwd=worktree_dir)

            commit_msg = self._build_commit_message(proposal, test_result)
            self._git_commit(commit_msg, cwd=worktree_dir)

            self._git(["push", "origin", f"{branch}:{branch}"], cwd=worktree_dir)

            pr_body = self._build_pr_body(proposal, test_result)
            pr_url = self._gh_pr_create(branch, proposal.title, pr_body, cwd=worktree_dir)
            pr_number = self._extract_pr_number(pr_url)

            return PRRecord(
                proposal_id=proposal.id,
                cluster_id=proposal.cluster_id,
                pr_url=pr_url,
                pr_number=pr_number,
                branch=branch,
                artifact_file=proposal.target_file,
                test_file=proposal.test_file,
                behaviorally_validated=test_result.behaviorally_validated,
            )
        finally:
            # push 之後 origin 才是 canonical 副本；push 之前失敗時本地 branch 也沒有留著的
            # 必要——兩種情況下都刪掉本地 branch，只留 worktree 目錄本身的清除給下面處理。
            self._cleanup_worktree(worktree_dir, branch)

    def _is_registered_worktree(self, worktree_dir: Path) -> bool:
        """`worktree_dir` 目前是否仍被 git 註冊為（可能使用中的）worktree。"""
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(self._main_repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False
        target = str(worktree_dir.resolve())
        prefix = "worktree "
        for line in result.stdout.splitlines():
            if line.startswith(prefix) and line[len(prefix) :].strip() == target:
                return True
        return False

    def _cleanup_worktree(self, worktree_dir: Path, branch: str) -> None:
        """移除指定路徑的 worktree 與其分支（若存在）。

        刻意 best-effort、刻意包在 try/except 裡：`create_pr` 的 finally 區塊呼叫本函式時，
        若這裡讓 `OSError`/`subprocess` 例外往外拋，會蓋掉 `finally` 正在處理的原始例外，
        讓呼叫端連 digest／`LAST_FAILURE` marker 都寫不進去——比原本的失敗更糟。
        `shutil.rmtree` 只在 `worktree_dir` 已經**不被 git 註冊**為 worktree 時才會執行
        （例如上一次 `worktree add` 中斷留下的半殘留目錄）；仍被註冊、`--force` 卻移除失敗，
        代表可能真的被別的行程使用中，此時只警告、不強制刪除。
        """
        try:
            result = subprocess.run(  # nosec B603 B607
                [
                    "git",
                    "-C",
                    str(self._main_repo),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree_dir),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 and worktree_dir.exists():
                if self._is_registered_worktree(worktree_dir):
                    print(
                        f"[WARN] nightly-agent worktree 仍被 git 註冊為使用中，"
                        f"未強制刪除：{worktree_dir}：{result.stderr.strip()}",
                        file=sys.stderr,
                    )
                else:
                    shutil.rmtree(worktree_dir, ignore_errors=True)
                    subprocess.run(  # nosec B603 B607
                        ["git", "-C", str(self._main_repo), "worktree", "prune"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
            if worktree_dir.exists():
                print(f"[WARN] 無法清除 nightly-agent worktree：{worktree_dir}", file=sys.stderr)
            # best-effort：分支可能根本不存在（第一次為此 slug 執行的 pre-clean 呼叫），
            # 忽略結果即可，不需要另外處理 stderr。
            subprocess.run(  # nosec B603 B607
                ["git", "-C", str(self._main_repo), "branch", "-D", branch],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as e:
            print(
                f"[WARN] 清除 nightly-agent worktree 時發生例外：{worktree_dir}：{e}",
                file=sys.stderr,
            )

    def _git(self, args: list[str], cwd: Path | None = None) -> str:
        target = cwd if cwd is not None else self._main_repo
        result = subprocess.run(  # nosec B603
            ["git", "-C", str(target)] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {args[0]} 失敗：{result.stderr[:300]}")
        return result.stdout.strip()

    def _git_commit(self, message: str, cwd: Path | None = None) -> None:
        target = cwd if cwd is not None else self._main_repo
        msg_path = target / ".runtime" / "nightly_agent_commit_msg.txt"
        msg_path.parent.mkdir(parents=True, exist_ok=True)
        msg_path.write_text(message, encoding="utf-8")
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(target), "commit", "-F", str(msg_path)],
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
            f"Validation: {self._validation_summary(test_result)}\n"
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
            f"### Validation\n\n"
            f"- Result: {self._validation_summary(test_result)}\n"
            f"- Previously failing: `{test_result.previously_failed}`\n"
            f"- After artifact: `{test_result.passed}`\n\n"
            f"```\n{test_result.after_output[-400:]}\n```\n\n"
            f"---\n*Generated by `tasks.nightly_agent` on "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )

    @staticmethod
    def _validation_summary(test_result: TestResult) -> str:
        if test_result.behaviorally_validated:
            return "failing-then-passing behavior verified"
        return "artifact recorded; not behaviorally validated"

    def _gh_pr_create(self, branch: str, title: str, body: str, cwd: Path | None = None) -> str:
        target = cwd if cwd is not None else self._main_repo
        body_path = target / ".runtime" / "nightly_agent_pr_body.txt"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body, encoding="utf-8")

        if not self.config.github_repo:
            raise RuntimeError("無法解析 GitHub repo；請設定 github_repo 為 owner/repo")
        try:
            result = subprocess.run(  # nosec B603 B607
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    self.config.github_repo,
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
                cwd=str(target),
            )
        except FileNotFoundError as e:
            raise RuntimeError("找不到 gh CLI；請執行 brew install gh") from e

        if result.returncode != 0:
            raise RuntimeError(f"gh pr create 失敗：{result.stderr[:300]}")
        return result.stdout.strip()

    def _extract_pr_number(self, pr_url: str) -> int:
        m = re.search(r"/pull/(\d+)", pr_url)
        return int(m.group(1)) if m else 0
