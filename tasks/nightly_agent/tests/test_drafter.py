"""NIGHTLY-drafter tests (mock Claude API)."""

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
    def _make_mock_client(self, text_response: str) -> MagicMock:
        mock_block = MagicMock()
        mock_block.text = text_response
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_draft_ap2_produces_hookify_rule(self) -> None:
        config = NightlyAgentConfig()
        drafter = ArtifactDrafter(config)
        drafter._client = self._make_mock_client(
            "#!/usr/bin/env python3\nimport sys, json\ndata = json.load(sys.stdin)\nsys.exit(0)\n"
        )
        cluster = make_cluster(FrictionType.AP2_BLOCK)
        proposal = drafter.draft(cluster)
        assert proposal.artifact_type == ArtifactType.HOOKIFY_RULE
        assert proposal.content.startswith("#!")

    def test_draft_worktree_produces_gotcha(self) -> None:
        config = NightlyAgentConfig()
        drafter = ArtifactDrafter(config)
        drafter._client = self._make_mock_client(
            "- **Worktree main conflict**: Never checkout main in a linked worktree. Fix: use a feature branch."
        )
        cluster = make_cluster(FrictionType.WORKTREE_CONFLICT)
        proposal = drafter.draft(cluster)
        assert proposal.artifact_type == ArtifactType.CLAUDE_MD_GOTCHA

    def test_draft_fills_source_session_ids(self) -> None:
        config = NightlyAgentConfig()
        drafter = ArtifactDrafter(config)
        drafter._client = self._make_mock_client("- **Test**: some gotcha text. Fix: do better.")
        cluster = make_cluster(count=2)
        proposal = drafter.draft(cluster)
        assert len(proposal.source_session_ids) == 2

    def test_draft_raises_on_empty_api_response(self) -> None:
        config = NightlyAgentConfig()
        drafter = ArtifactDrafter(config)
        mock_response = MagicMock()
        mock_response.content = []  # empty
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        drafter._client = mock_client
        cluster = make_cluster()
        with pytest.raises(RuntimeError, match="草擬 artifact 失敗"):
            drafter.draft(cluster)

    def test_no_api_key_raises(self) -> None:
        config = NightlyAgentConfig()
        drafter = ArtifactDrafter(config)
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY if set
            import os

            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                drafter._get_client()
