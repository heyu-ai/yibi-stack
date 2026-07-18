"""Artifact lint 驗證器：以 failing→passing 語意驗證暫存 artifact。"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404
from pathlib import Path

from tasks._paths import PROJECT_ROOT

from .models import ArtifactProposal, ArtifactType, TestResult


def _get_main_repo() -> Path:
    """以 git common dir 定位主 repo；linked worktree 亦安全。"""
    result = subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).parent
    return PROJECT_ROOT


def _extract_bad_command(proposal: ArtifactProposal) -> str:
    for description in proposal.friction_descriptions:
        match = re.search(r"`([^`]{5,80})`", description)
        if match:
            return match.group(1)
    if "worktree" in proposal.target_file:
        return "git checkout main"
    return 'echo "example bad command"'


def _extract_distinctive_phrase(content: str) -> str:
    for pattern in (r"\*\*([^*]{5,60})\*\*", r"##\s+(.{5,60})"):
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
    for line in content.splitlines():
        candidate = line.strip().lstrip("-# *")
        if len(candidate) > 10:
            return candidate[:60]
    return content[:40]


class TestValidator:
    """執行 lint-style failing→passing 驗證，不產生 pytest collection 項目。"""

    def __init__(self, generated_tests_dir: str | Path = "") -> None:
        self._main_repo = _get_main_repo()
        configured = (
            Path(generated_tests_dir)
            if generated_tests_dir
            else Path(".runtime/nightly_agent/generated_tests")
        )
        self.generated_tests_dir = (
            configured if configured.is_absolute() else self._main_repo / configured
        )

    def validate(self, proposal: ArtifactProposal) -> TestResult:
        """寫入 validation record，確認套用前失敗、暫時套用後通過，再還原。"""
        self.generated_tests_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^a-z0-9_]+", "_", proposal.title.lower()).strip("_")
        safe_title = safe_title[:40] or f"friction_{proposal.id[:8]}"
        record_path = self.generated_tests_dir / f"lint_{safe_title}_{proposal.id[:8]}.json"

        before_passed, before_message = self._lint(proposal)
        record = {
            "proposal_id": proposal.id,
            "kind": "nightly-agent-artifact-lint",
            "before": before_message,
        }
        try:
            record_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            raise RuntimeError(f"無法寫入 validation record：{record_path}") from e

        if before_passed:
            return TestResult(
                proposal_id=proposal.id,
                test_file=str(record_path),
                passed=False,
                previously_failed=False,
                before_output=before_message,
                error="套用 artifact 前 lint 已通過；friction 可能已修正，略過 PR",
            )

        artifact_path = self._main_repo / proposal.target_file
        original = self._read_original(artifact_path)
        self._apply_artifact(proposal, artifact_path)
        try:
            after_passed, after_message = self._lint(proposal)
        finally:
            self._rollback_artifact(artifact_path, original)

        record["after"] = after_message
        record["passed"] = after_passed
        try:
            record_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            raise RuntimeError(f"無法更新 validation record：{record_path}") from e

        proposal.test_file = str(record_path)
        proposal.test_content = json.dumps(record, ensure_ascii=False)
        return TestResult(
            proposal_id=proposal.id,
            test_file=str(record_path),
            passed=after_passed,
            previously_failed=True,
            before_output=before_message,
            after_output=after_message,
            error="" if after_passed else "套用 artifact 後 lint 仍失敗",
        )

    def _lint(self, proposal: ArtifactProposal) -> tuple[bool, str]:
        target = self._main_repo / proposal.target_file
        if not target.is_file():
            return False, f"[FAIL] 找不到 artifact：{target}"
        if proposal.artifact_type == ArtifactType.HOOKIFY_RULE:
            return self._lint_hook(target, proposal)
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as e:
            return False, f"[FAIL] 無法讀取 artifact：{e}"
        phrase = _extract_distinctive_phrase(proposal.content)
        passed = phrase.casefold() in content.casefold()
        return passed, "[PASS] 文件包含預期規則" if passed else f"[FAIL] 文件缺少：{phrase}"

    def _lint_hook(self, target: Path, proposal: ArtifactProposal) -> tuple[bool, str]:
        bad_payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": _extract_bad_command(proposal)},
            }
        )
        try:
            result = subprocess.run(  # nosec B603
                ["python3", str(target)],
                input=bad_payload,
                capture_output=True,
                text=True,
                timeout=10,
            )
            good_result = subprocess.run(  # nosec B603
                ["python3", str(target)],
                input=json.dumps(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": 'echo "安全命令"'},
                    }
                ),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"[FAIL] hook lint 無法執行：{e}"
        passed = result.returncode != 0 and good_result.returncode == 0
        message = "[PASS] hook 阻擋已知錯誤命令並允許安全命令"
        if result.returncode == 0:
            message = "[FAIL] hook 未阻擋錯誤命令"
        elif good_result.returncode != 0:
            message = "[FAIL] hook 錯誤阻擋安全命令"
        return passed, message

    @staticmethod
    def _read_original(path: Path) -> str | None:
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"無法讀取原始 artifact：{path}") from e

    def _apply_artifact(self, proposal: ArtifactProposal, artifact_path: Path) -> None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if proposal.artifact_type == ArtifactType.HOOKIFY_RULE:
            artifact_path.write_text(proposal.content, encoding="utf-8")
            return
        existing = self._read_original(artifact_path) or ""
        separator = "\n\n" if existing else ""
        artifact_path.write_text(
            existing.rstrip("\n") + separator + proposal.content + "\n", encoding="utf-8"
        )

    @staticmethod
    def _rollback_artifact(artifact_path: Path, original: str | None) -> None:
        try:
            if original is None:
                artifact_path.unlink(missing_ok=True)
            else:
                artifact_path.write_text(original, encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"rollback 失敗（無法還原 artifact）：{artifact_path}") from e
