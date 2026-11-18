"""ALLOWLIST-* tests for scripts/lint_allowlist.py。

驗證 settings JSON `permissions.allow` 的 rule 16 Red Flag 偵測，含負向對照。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
import json
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parent.parent / "lint_allowlist.py"
_spec = importlib.util.spec_from_file_location("lint_allowlist", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
lint_allowlist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_allowlist)


class TestCheckEntry:
    @pytest.mark.parametrize(
        ("entry", "flag"),
        [
            ("Bash(git -C * status)", "RF1"),
            ("Bash(uv run --directory * pytest)", "RF1"),
            ("Bash(git *)", "RF2"),
            ("Bash(npm:*)", "RF2"),
            ("Bash(rm -rf:*)", "RF2"),
            ("Bash(curl https://example.com/*)", "RF2"),
            ("Bash(rg *)", "RF2"),
            ('Bash(PATH="/x:$PATH" git *)', "RF3"),
            ("Bash(cat ${HOME}/x:*)", "RF3"),
            ("Bash(* > *)", "RF5"),
            ("Bash(* | sh)", "RF5"),
        ],
    )
    def test_allowlist_dt_001_red_flags(self, entry: str, flag: str) -> None:
        """ALLOWLIST-DT-001: rule 16 Red Flag 1/2/3/5 的範例都被抓到。"""
        assert flag in lint_allowlist.check_entry(entry)

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(make ci)",
            "Bash(git status:*)",
            "Bash(git log --oneline -5)",
            "Bash(npm run *)",
            "Bash(uv run pytest:*)",
            "Bash(ls:*)",
            "Bash(bash /Users/me/.agents/skills/foo/scripts/setup.sh)",
            "Read(~/.zshrc)",
            "Edit(/Users/me/.claude/jobs/**)",
            "WebFetch(domain:*.anthropic.com)",
            "mcp__hindsight__hindsight_search_pages",
        ],
    )
    def test_allowlist_vl_001_safe_patterns(self, entry: str) -> None:
        """ALLOWLIST-VL-001: rule 16 Safe Pattern Examples 與非 Bash 規則不誤報。"""
        assert lint_allowlist.check_entry(entry) == []


class TestLintSettings:
    def test_allowlist_dt_002_only_allow_is_scanned(self) -> None:
        """ALLOWLIST-DT-002: deny 裡的危險 pattern 是正確用法，不報；allow 裡的才報。"""
        text = json.dumps(
            {"permissions": {"allow": ["Bash(git *)"], "deny": ["Bash(curl *)", "Bash(rm *)"]}}
        )
        findings = lint_allowlist.lint_settings(text)
        assert [entry for entry, _ in findings] == ["Bash(git *)"]

    @pytest.mark.parametrize(
        "text", ["{}", '{"permissions": {}}', '{"permissions": {"allow": []}}']
    )
    def test_allowlist_vl_002_no_allow_list(self, text: str) -> None:
        """ALLOWLIST-VL-002: 沒有 allow list 時不報。"""
        assert lint_allowlist.lint_settings(text) == []

    def test_allowlist_eg_001_invalid_json_raises(self) -> None:
        """ALLOWLIST-EG-001: JSON 壞掉要 fail loud，不能當成「沒有違規」。"""
        with pytest.raises(ValueError):
            lint_allowlist.lint_settings("{not json")


class TestMain:
    def test_allowlist_dt_003_warn_only_by_default(self, tmp_path: Path, capsys) -> None:
        """ALLOWLIST-DT-003: 預設 advisory（exit 0、警告寫 stderr），--fail 才 exit 1。"""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git *)"]}}))
        assert lint_allowlist.main([str(settings)]) == 0
        err = capsys.readouterr().err
        assert "Bash(git *)" in err and "RF2" in err
        assert lint_allowlist.main(["--fail", str(settings)]) == 1

    def test_allowlist_eg_002_unreadable_file_exits_2(self, tmp_path: Path) -> None:
        """ALLOWLIST-EG-002: 檔案讀不到或 JSON 壞掉 -> exit 2（設定錯誤，不是乾淨）。"""
        bad = tmp_path / "settings.json"
        bad.write_text("{not json")
        assert lint_allowlist.main([str(bad)]) == 2
        assert lint_allowlist.main([str(tmp_path / "missing.json")]) == 2
