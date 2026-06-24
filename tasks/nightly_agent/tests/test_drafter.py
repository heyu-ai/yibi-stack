"""NIGHTLY-drafter tests (mock claude CLI subprocess)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from tasks.nightly_agent.drafter import ArtifactDrafter, _cluster_user_prompt, _make_slug
from tasks.nightly_agent.models import (
    ArtifactType,
    FrictionCluster,
    FrictionEvent,
    FrictionType,
    NightlyAgentConfig,
)


def make_cluster(
    friction_type: FrictionType = FrictionType.AP2_BLOCK,
    count: int = 2,
    keywords: list[str] | None = None,
) -> FrictionCluster:
    events = [
        FrictionEvent(
            id=str(uuid.uuid4()),
            session_id=f"session-{i}",
            timestamp="2026-05-27T03:00:00Z",
            project="yibi-stack",
            friction_type=friction_type,
            description=f"friction description {i}",
            raw_text=f"raw snippet {i}: bash ap2 unicode em dash",
            source_file="fake.jsonl",
        )
        for i in range(count)
    ]
    return FrictionCluster(
        id=str(uuid.uuid4()),
        friction_type=friction_type,
        events=events,
        common_keywords=keywords or ["bash", "ap2", "unicode"],
    )


class TestMakeSlug:
    def test_kebab_from_keywords(self) -> None:
        cluster = make_cluster(keywords=["bash", "unicode", "error"])
        slug = _make_slug(cluster)
        assert slug == "bash-unicode-error"

    def test_fallback_to_friction_type(self) -> None:
        cluster = FrictionCluster(
            id="x",
            friction_type=FrictionType.WORKTREE_CONFLICT,
            events=[],
            common_keywords=[],
        )
        assert "worktree" in _make_slug(cluster)


class TestClusterUserPrompt:
    def test_prompt_contains_friction_type(self) -> None:
        cluster = make_cluster(FrictionType.AP2_BLOCK)
        prompt = _cluster_user_prompt(cluster)
        assert "ap2_block" in prompt

    def test_prompt_contains_occurrences(self) -> None:
        cluster = make_cluster(count=3)
        prompt = _cluster_user_prompt(cluster)
        assert "3" in prompt

    def test_prompt_contains_event_snippets(self) -> None:
        cluster = make_cluster()
        prompt = _cluster_user_prompt(cluster)
        assert "friction description" in prompt


class TestArtifactDrafter:
    @staticmethod
    def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
        """模擬 subprocess.run 回傳的 CompletedProcess。"""
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_ap2_produces_hookify_rule(
        self, mock_run: MagicMock, _mock_bin: MagicMock
    ) -> None:
        mock_run.return_value = self._completed(
            "#!/usr/bin/env python3\nimport sys, json\ndata = json.load(sys.stdin)\nsys.exit(0)\n"
        )
        drafter = ArtifactDrafter(NightlyAgentConfig())
        proposal = drafter.draft(make_cluster(FrictionType.AP2_BLOCK))
        assert proposal.artifact_type == ArtifactType.HOOKIFY_RULE
        assert proposal.content.startswith("#!")

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_invokes_claude_print_with_model(
        self, mock_run: MagicMock, _mock_bin: MagicMock
    ) -> None:
        mock_run.return_value = self._completed("- **X**: y. Fix: z.")
        drafter = ArtifactDrafter(NightlyAgentConfig(draft_model="claude-sonnet-4-6"))
        drafter.draft(make_cluster(FrictionType.WORKTREE_CONFLICT))
        argv = mock_run.call_args.args[0]
        assert argv[0] == "/fake/bin/claude"
        assert "--print" in argv
        assert "--model" in argv and "claude-sonnet-4-6" in argv
        assert "--system-prompt" in argv

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_worktree_produces_gotcha(
        self, mock_run: MagicMock, _mock_bin: MagicMock
    ) -> None:
        mock_run.return_value = self._completed(
            "- **Worktree main conflict**: Never checkout main in a linked worktree."
            " Fix: use a feature branch."
        )
        drafter = ArtifactDrafter(NightlyAgentConfig())
        proposal = drafter.draft(make_cluster(FrictionType.WORKTREE_CONFLICT))
        assert proposal.artifact_type == ArtifactType.CLAUDE_MD_GOTCHA

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_fills_source_session_ids(
        self, mock_run: MagicMock, _mock_bin: MagicMock
    ) -> None:
        mock_run.return_value = self._completed("- **Test**: some gotcha text. Fix: do better.")
        drafter = ArtifactDrafter(NightlyAgentConfig())
        proposal = drafter.draft(make_cluster(count=2))
        assert len(proposal.source_session_ids) == 2

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_raises_on_empty_stdout(self, mock_run: MagicMock, _mock_bin: MagicMock) -> None:
        mock_run.return_value = self._completed("")  # empty stdout
        drafter = ArtifactDrafter(NightlyAgentConfig())
        with pytest.raises(RuntimeError, match="草擬 artifact 失敗"):
            drafter.draft(make_cluster())

    @patch.object(ArtifactDrafter, "_resolve_claude_bin", return_value="/fake/bin/claude")
    @patch("tasks.nightly_agent.drafter.subprocess.run")
    def test_draft_raises_on_nonzero_exit(self, mock_run: MagicMock, _mock_bin: MagicMock) -> None:
        mock_run.return_value = self._completed("", returncode=1, stderr="boom")
        drafter = ArtifactDrafter(NightlyAgentConfig())
        with pytest.raises(RuntimeError, match="草擬 artifact 失敗"):
            drafter.draft(make_cluster())

    @patch("tasks.nightly_agent.drafter.os.path.isfile", return_value=False)
    @patch("tasks.nightly_agent.drafter.shutil.which", return_value=None)
    def test_missing_claude_binary_raises(
        self, _mock_which: MagicMock, _mock_isfile: MagicMock
    ) -> None:
        drafter = ArtifactDrafter(NightlyAgentConfig())
        with pytest.raises(RuntimeError, match="claude CLI"):
            drafter._resolve_claude_bin()
