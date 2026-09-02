"""LINTBASH-* tests for scripts/lint_skill_bash.py。

在本次修復之前，這支 script 完全沒有專屬測試檔（pr-test-analyzer 的 PTA-2 finding：
`rg -c 'lint_skill_bash' scripts/tests/*.py` 零命中）。它是本 repo 唯一會對
dangling symlink 硬失敗的 gate，卻沒有任何回歸鎖。

每個測試在 tmp_path 建一個最小合成 repo（含真正的 `.claude/hooks/` 兩支 hook script，
因為 script 的 `_active_hooks()` 依賴它們存在才會跑 anti-pattern 掃描），
用 subprocess 執行真正的 CLI 進入點。
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "lint_skill_bash.py"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REAL_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"


def _make_repo(tmp_path: Path, *, with_hooks: bool = True) -> Path:
    """建一個最小 repo：scripts/lint_skill_bash.py + commands/ + skills/ + 選擇性的
    .claude/hooks/（複製真實的兩支 hook，讓 anti-pattern 掃描能真正跑起來）。
    """
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(_SCRIPT, root / "scripts" / _SCRIPT.name)
    (root / "commands").mkdir()
    (root / "skills").mkdir()

    if with_hooks:
        hooks_dir = root / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        for name in ("bash-ap1-inline-check.sh", "bash-ap2-check.py"):
            shutil.copy2(_REAL_HOOKS_DIR / name, hooks_dir / name)
        (hooks_dir / "bash-ap1-inline-check.sh").chmod(
            (hooks_dir / "bash-ap1-inline-check.sh").stat().st_mode
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        )
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "lint_skill_bash.py"), *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class TestHappyPath:
    def test_lintbash_ok_001_clean_repo_passes(self, tmp_path: Path) -> None:
        """LINTBASH-OK-001: 沒有 markdown 檔案 -> [SKIP]、exit 0"""
        root = _make_repo(tmp_path)
        result = _run(root)
        assert result.returncode == 0, result.stderr

    def test_lintbash_ok_002_clean_bash_block_passes(self, tmp_path: Path) -> None:
        """LINTBASH-OK-002: 乾淨的 bash block -> [OK]、exit 0（正向對照，先確認基準線）"""
        root = _make_repo(tmp_path)
        (root / "commands" / "clean.md").write_text(
            "# demo\n\n```bash\necho hello\n```\n", encoding="utf-8"
        )
        result = _run(root)
        assert result.returncode == 0, result.stderr
        assert "[OK]" in result.stdout


class TestDanglingSymlink:
    def test_lintbash_sl_001_dangling_command_symlink_hard_fails(self, tmp_path: Path) -> None:
        """LINTBASH-SL-001: dangling commands/*.md symlink -> exit 1，具名 [FAIL]，無 traceback"""
        root = _make_repo(tmp_path)
        os.symlink("../plugins/nope/commands/ghost.md", root / "commands" / "ghost.md")

        result = _run(root)
        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert "ghost.md" in result.stderr
        assert "Traceback" not in result.stderr

    def test_lintbash_sl_002_dangling_symlink_hard_fails_even_without_hooks(
        self, tmp_path: Path
    ) -> None:
        """LINTBASH-SL-002: 即使 .claude/hooks/ 不存在，dangling symlink 仍必須硬失敗

        對應 SF-2（Claude R1 silent-failure-hunter finding）：修復前，broken-symlink
        掃描寫在 main() 裡，但 module-level 的 `_ACTIVE_HOOKS` 檢查會在 hook 檔案缺失時於
        **import 時** `sys.exit(0)`，早於 main() 執行——於是「hook 檔案被搬走/改名」與
        「plugin 端漏改頂層 symlink」同時發生時，dangling symlink 完全偵測不到，
        且錯誤地回報 exit 0。這裡刻意不建 .claude/hooks/，驗證 dangling symlink 檢查
        與 hook 可用性無關，一律先跑。
        """
        root = _make_repo(tmp_path, with_hooks=False)
        os.symlink("../plugins/nope/commands/ghost.md", root / "commands" / "ghost.md")

        result = _run(root)
        assert result.returncode == 1, (
            f"hooks 不存在時 dangling symlink 檢查應仍然執行並 exit 1，"
            f"實際 stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "ghost.md" in result.stderr


class TestMissingHooks:
    def test_lintbash_mh_001_no_hooks_warns_but_does_not_crash(self, tmp_path: Path) -> None:
        """LINTBASH-MH-001: .claude/hooks/ 不存在、無 dangling symlink -> [WARN] + exit 0

        hook 缺失本身不是斷掉的 symlink，故 exit 0 是正確行為——只是 anti-pattern
        掃描被跳過。訊息走 stderr（rule 13：[WARN] 前綴一律 >&2）。
        """
        root = _make_repo(tmp_path, with_hooks=False)
        (root / "commands" / "demo.md").write_text(
            "# demo\n\n```bash\necho hi\n```\n", encoding="utf-8"
        )
        result = _run(root)
        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr


class TestStructuralReadFailure:
    def test_lintbash_toctou_001_unreadable_file_hard_fails_in_warn_only_mode(
        self, tmp_path: Path
    ) -> None:
        """LINTBASH-TOCTOU-001: 不可讀檔案（OSError）在 warn-only 模式下仍必須 exit 1

        對應 D8（Codex R1 + Claude test-analyzer PTA-8 收斂）：修復前，`lint_file()` 的
        `except OSError` 分支把讀取失敗併入一般 violation 清單，warn-only 模式下
        `main()` 對非空 violations 仍 return 0——與 docstring 承諾的「（任何模式）
        偵測到讀取失敗 -> 1」矛盾。用 `chmod 000` 觸發真正的 PermissionError
        （TOCTOU 的具體成因之一：find_broken_links() 通過之後、read_text() 之前，
        檔案權限被改變）。
        """
        root = _make_repo(tmp_path)
        target = root / "commands" / "unreadable.md"
        target.write_text("```bash\necho hi\n```\n", encoding="utf-8")
        target.chmod(0o000)
        try:
            result = _run(root)  # 預設 warn-only，不帶 --fail
        finally:
            target.chmod(0o644)

        assert result.returncode == 1, (
            f"warn-only 模式下讀取失敗仍應 exit 1（結構性錯誤不受 warn-only 豁免）。"
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_lintbash_toctou_002_genuine_anti_pattern_still_warn_only_without_fail_flag(
        self, tmp_path: Path
    ) -> None:
        """LINTBASH-TOCTOU-002: 負面對照——真正的 anti-pattern violation（非讀取失敗）
        在 warn-only 模式下仍應 exit 0，不能因為修 D8 而連坐提高成 hard-fail。
        """
        root = _make_repo(tmp_path)
        # AP2 違規：bash 字串內含 em dash
        (root / "commands" / "violation.md").write_text(
            '# demo\n\n```bash\necho "em—dash"\n```\n', encoding="utf-8"
        )
        result = _run(root)
        assert result.returncode == 0, (
            f"style violation 在 warn-only（無 --fail）下應仍 exit 0，不應被 D8 修法波及。"
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_lintbash_toctou_003_genuine_anti_pattern_fails_with_fail_flag(
        self, tmp_path: Path
    ) -> None:
        """LINTBASH-TOCTOU-003: 負面對照——真正的 anti-pattern violation 帶 --fail 時
        仍照舊 exit 1（既有行為不因 D8 修法而改變）。
        """
        root = _make_repo(tmp_path)
        (root / "commands" / "violation.md").write_text(
            '# demo\n\n```bash\necho "em—dash"\n```\n', encoding="utf-8"
        )
        result = _run(root, "--fail")
        assert result.returncode == 1, result.stdout


class TestRelativeAddDir:
    """ADD-DIR detection: --add-dir with a relative path in bash fences.

    Detection output lands on stdout (hooks-present path, merged with other violations)
    or stderr (no-hooks path). Tests check combined output for detection presence.
    """

    @staticmethod
    def _combined(result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_lintbash_ad_001_relative_dot_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-001: --add-dir . in a bash fence is flagged."""
        root = _make_repo(tmp_path)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)

    def test_lintbash_ad_002_absolute_var_not_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-002: --add-dir "$REPO_ROOT" is safe — must NOT flag."""
        root = _make_repo(tmp_path)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            "---\nname: agy-review\n---\n\n```bash\n"
            'agy -p "$P" --add-dir "$REPO_ROOT" --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" not in self._combined(result), self._combined(result)

    def test_lintbash_ad_003_absolute_path_not_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-003: --add-dir /abs/path is safe — must NOT flag."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            "---\nname: test-skill\n---\n\n```bash\n"
            'agy -p "$P" --add-dir /Users/me/repo --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" not in self._combined(result), self._combined(result)

    def test_lintbash_ad_004_quoted_relative_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-004: --add-dir "." (double-quoted dot) is flagged."""
        root = _make_repo(tmp_path)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir "." --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)

    def test_lintbash_ad_005_relative_subdir_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-005: --add-dir ./subdir is flagged."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            "---\nname: test-skill\n---\n\n```bash\n"
            'agy -p "$P" --add-dir ./subdir --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)

    def test_lintbash_ad_006_braced_var_not_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-006: --add-dir "${WT_ROOT}" is safe — must NOT flag."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            "---\nname: test-skill\n---\n\n```bash\n"
            'agy -p "$P" --add-dir "${WT_ROOT}" --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" not in self._combined(result), self._combined(result)

    def test_lintbash_ad_007_warn_only_exit_zero(self, tmp_path: Path) -> None:
        """LINTBASH-AD-007: ADD-DIR violation in warn-only mode -> exit 0."""
        root = _make_repo(tmp_path)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert result.returncode == 0, result.stderr

    def test_lintbash_ad_008_fail_mode_exit_one(self, tmp_path: Path) -> None:
        """LINTBASH-AD-008: ADD-DIR violation with --fail -> exit 1."""
        root = _make_repo(tmp_path)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root, "--fail")
        assert result.returncode == 1, result.stdout

    def test_lintbash_ad_009_no_hooks_still_detects(self, tmp_path: Path) -> None:
        """LINTBASH-AD-009: ADD-DIR detection works even without hooks."""
        root = _make_repo(tmp_path, with_hooks=False)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" in self._combined(result), (
            f"ADD-DIR detection should work independently of hooks. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert result.returncode == 0, (
            f"warn-only mode (no --fail) should exit 0 even with violations. rc={result.returncode}"
        )

    def test_lintbash_ad_010_equals_sign_relative_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-010: --add-dir=. (equals-sign form) is flagged."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            '---\nname: test-skill\n---\n\n```bash\nagy -p "$P" --add-dir=. --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)

    def test_lintbash_ad_011_equals_sign_absolute_not_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-011: --add-dir="$REPO_ROOT" (equals-sign) is safe."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            "---\nname: test-skill\n---\n\n```bash\n"
            'agy -p "$P" --add-dir="$REPO_ROOT" --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" not in self._combined(result), self._combined(result)

    def test_lintbash_ad_012_single_quoted_absolute_not_flagged(self, tmp_path: Path) -> None:
        """LINTBASH-AD-012: --add-dir '/abs/path' (single-quoted absolute) is safe."""
        root = _make_repo(tmp_path)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "skills" / "test-skill" / "SKILL.md").write_text(
            "---\nname: test-skill\n---\n\n```bash\n"
            "agy -p \"$P\" --add-dir '/Users/me/repo' --sandbox\n```\n",
            encoding="utf-8",
        )
        result = _run(root)
        assert "[ADD-DIR]" not in self._combined(result), self._combined(result)

    def test_lintbash_ad_013_rule_file_excluded_ac3(self, tmp_path: Path) -> None:
        """LINTBASH-AD-013: AC-3 regression — .claude/rules/ files are NOT scanned."""
        root = _make_repo(tmp_path)
        rules_dir = root / ".claude" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "13-bash-anti-patterns.md").write_text(
            "# Wrong example\n\n```bash\nagy --add-dir . --sandbox\n```\n",
            encoding="utf-8",
        )
        result = _run(root, "--fail")
        assert result.returncode == 0, (
            f"Rule files under .claude/rules/ must not be scanned (AC-3). "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        combined = self._combined(result)
        assert "[ADD-DIR]" not in combined, combined

    def test_lintbash_ad_014_no_hooks_fail_mode_exit_one(self, tmp_path: Path) -> None:
        """LINTBASH-AD-014: ADD-DIR violation + no hooks + --fail -> exit 1."""
        root = _make_repo(tmp_path, with_hooks=False)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root, "--fail")
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)
        assert result.returncode == 1, (
            f"no-hooks + --fail + violation should exit 1. rc={result.returncode}"
        )

    def test_lintbash_ad_015_no_hooks_hook_skip_warning_always_shown(self, tmp_path: Path) -> None:
        """LINTBASH-AD-015: hook-skip warning appears even when ADD-DIR violations exist."""
        root = _make_repo(tmp_path, with_hooks=False)
        (root / "skills" / "agy-review").mkdir(parents=True)
        (root / "skills" / "agy-review" / "SKILL.md").write_text(
            '---\nname: agy-review\n---\n\n```bash\nagy -p "$P" --add-dir . --sandbox\n```\n',
            encoding="utf-8",
        )
        result = _run(root)
        assert "no hook files found" in result.stderr, (
            f"hook-skip warning should appear even with ADD-DIR violations. "
            f"stderr={result.stderr!r}"
        )
        assert "[ADD-DIR]" in self._combined(result), self._combined(result)
