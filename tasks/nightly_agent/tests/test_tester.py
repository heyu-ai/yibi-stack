"""NIGHTLY-VALIDATION：ephemeral lint validator 測試。"""

from pathlib import Path
from unittest.mock import patch

from tasks.nightly_agent.models import ArtifactProposal, ArtifactType
from tasks.nightly_agent.tester import TestValidator as ArtifactValidator


def make_proposal() -> ArtifactProposal:
    return ArtifactProposal(
        id="12345678-abcd",
        cluster_id="cluster-1",
        artifact_type=ArtifactType.CLAUDE_MD_GOTCHA,
        title="中文輸入，英文回覆",
        content="- **回覆語言規則**：收到中文輸入時使用繁體中文。",
        target_file="docs/nightly-validation-target.md",
    )


class TestValidationLocation:
    @patch("tasks.nightly_agent.tester._get_main_repo")
    def test_nightly_validation_001_record_is_outside_pytest_paths(
        self, mock_repo, tmp_path: Path
    ) -> None:
        """NIGHTLY-VALIDATION-001：validation record 位於 runtime，不被 pytest 收集。"""
        mock_repo.return_value = tmp_path
        validator = ArtifactValidator()
        result = validator.validate(make_proposal())

        record = Path(result.test_file)
        assert result.previously_failed is False
        assert result.passed is True
        assert result.behaviorally_validated is False
        assert "未做行為驗證" in result.after_output
        assert record.is_file()
        assert record.suffix == ".json"
        assert record.is_relative_to(tmp_path / ".runtime" / "nightly_agent")
        assert "tasks/nightly_agent/tests" not in record.as_posix()
        assert not (tmp_path / "docs/nightly-validation-target.md").exists()
