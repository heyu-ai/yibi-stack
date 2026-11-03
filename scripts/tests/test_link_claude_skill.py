"""link_claude_skill.sh 的行為測試。

背景：`make install` 原本會把 `skills/<name>` 一律連到 `~/.claude/skills/`，
但 `skills/<name>` 多半只是指向 `plugins/<pack>/skills/<name>` 的 symlink，
這些 skill 已由 plugin 機制提供，重複安裝會讓同一個 skill 在清單中出現兩次
（`pr-cycle-deep` 與 `dev-cycle:pr-cycle-deep`），且兩者來源不同、可能不同步。

Test ID 規則見 .claude/rules/09-test-conventions.md（LCS = link_claude_skill）。
"""

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "link_claude_skill.sh"
MAKEFILE = REPO_ROOT / "Makefile"


def _run(repo: Path, name: str, dst_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), str(repo), name, str(dst_dir)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _make_repo(tmp_path: Path) -> Path:
    """建一個假 repo：skills/native 是實體目錄，skills/viaplugin 是指向 plugin 的 symlink。"""
    repo = tmp_path / "repo"
    (repo / "skills" / "native").mkdir(parents=True)
    (repo / "skills" / "native" / "SKILL.md").write_text("x\n", encoding="utf-8")
    plugin_skill = repo / "plugins" / "dev-cycle" / "skills" / "viaplugin"
    plugin_skill.mkdir(parents=True)
    (plugin_skill / "SKILL.md").write_text("x\n", encoding="utf-8")
    (repo / "skills" / "viaplugin").symlink_to("../plugins/dev-cycle/skills/viaplugin")
    return repo


class TestLinkClaudeSkill:
    def test_lcs_dt_001_native_skill_is_linked(self, tmp_path: Path) -> None:
        """LCS-DT-001: skills/ 內的實體 skill 照舊連到 claude skill 目錄"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        result = _run(repo, "native", dst)

        assert result.returncode == 0, result.stderr
        link = dst / "native"
        assert link.is_symlink()
        assert link.readlink() == repo / "skills" / "native"

    def test_lcs_dt_002_plugin_provided_skill_is_not_linked(self, tmp_path: Path) -> None:
        """LCS-DT-002: 由 plugin 提供的 skill 不建立連結，且明確回報 SKIP"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert not (dst / "viaplugin").exists()
        assert not (dst / "viaplugin").is_symlink()
        assert "[SKIP]" in result.stderr

    def test_lcs_dt_003_prunes_previously_installed_duplicate(self, tmp_path: Path) -> None:
        """LCS-DT-003: 先前 make install 留下、指向本 repo 的重複連結會被移除"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(repo / "skills" / "viaplugin")

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert not (dst / "viaplugin").is_symlink()
        assert "[OK]" in result.stdout

    def test_lcs_dt_004_symlink_outside_plugins_is_still_linked(self, tmp_path: Path) -> None:
        """LCS-DT-004: skills/<name> 是 symlink 但指向 plugins/ 以外，不算 plugin 提供，照舊安裝"""
        repo = _make_repo(tmp_path)
        elsewhere = tmp_path / "elsewhere" / "outside"
        elsewhere.mkdir(parents=True)
        (elsewhere / "SKILL.md").write_text("x\n", encoding="utf-8")
        (repo / "skills" / "outside").symlink_to(elsewhere)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        result = _run(repo, "outside", dst)

        assert result.returncode == 0, result.stderr
        assert "[SKIP]" not in result.stderr
        assert (dst / "outside").is_symlink()
        assert (dst / "outside").readlink() == repo / "skills" / "outside"

    def test_lcs_eg_003_dangling_symlink_is_not_treated_as_plugin(self, tmp_path: Path) -> None:
        """LCS-EG-003: 失效的 symlink 無法證明由 plugin 提供，不可靜默跳過也不可誤刪既有連結"""
        repo = _make_repo(tmp_path)
        (repo / "skills" / "dangling").symlink_to("../plugins/dev-cycle/skills/gone")
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "dangling").symlink_to(repo / "skills" / "dangling")

        result = _run(repo, "dangling", dst)

        assert result.returncode == 0, result.stderr
        assert "[SKIP]" not in result.stderr
        assert (dst / "dangling").is_symlink()
        assert (dst / "dangling").readlink() == repo / "skills" / "dangling"

    def test_lcs_eg_004_plugin_detected_through_symlinked_repo_root(self, tmp_path: Path) -> None:
        """LCS-EG-004: repo 根目錄本身經由 symlink 傳入（如 macOS /var -> /private/var）仍要認得 plugin"""
        repo = _make_repo(tmp_path)
        repo_alias = tmp_path / "repo_alias"
        repo_alias.symlink_to(repo, target_is_directory=True)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        result = _run(repo_alias, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert "[SKIP]" in result.stderr
        assert not (dst / "viaplugin").is_symlink()

    def test_lcs_eg_001_foreign_symlink_is_left_alone(self, tmp_path: Path) -> None:
        """LCS-EG-001: 指向別處的同名 symlink 不是我們建的，不可移除"""
        repo = _make_repo(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(elsewhere)

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert (dst / "viaplugin").is_symlink()
        assert (dst / "viaplugin").readlink() == elsewhere

    def test_lcs_eg_002_real_directory_is_left_alone(self, tmp_path: Path) -> None:
        """LCS-EG-002: 同名的實體目錄（使用者自己放的）不可刪除"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        (dst / "viaplugin").mkdir(parents=True)
        (dst / "viaplugin" / "keep.txt").write_text("mine\n", encoding="utf-8")

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert (dst / "viaplugin" / "keep.txt").is_file()

    def test_lcs_vl_001_wrong_arg_count_fails_loud(self, tmp_path: Path) -> None:
        """LCS-VL-001: 參數數量不對時 exit 1 並寫 stderr，不靜默成功"""
        result = subprocess.run(  # nosec B603
            ["bash", str(SCRIPT), str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 1
        assert "[FAIL]" in result.stderr


class TestMakefileWiring:
    def test_lcs_st_001_install_routes_claude_dir_through_script(self) -> None:
        """LCS-ST-001: make install 的 skill 迴圈必須經由 link_claude_skill.sh

        若有人把 safe_symlink.sh 直接接回 CLAUDE_SKILL_DIR，plugin 重複安裝會
        無聲復發，而上面的腳本單測全綠。這裡鎖住接線本身。
        """
        text = MAKEFILE.read_text(encoding="utf-8")
        start = text.index("\ninstall: ")
        end = text.index("Installing plugin-only skills", start)
        install_loop = text[start:end]

        assert "link_claude_skill.sh" in install_loop
        assert '"$(CLAUDE_SKILL_DIR)"' in install_loop
        # CLAUDE_SKILL_DIR 不可再作為 safe_symlink.sh 的直接目的地
        for line in install_loop.splitlines():
            if "safe_symlink.sh" in line:
                assert "CLAUDE_SKILL_DIR" not in line, line


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), "--check", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class TestCheckMode:
    def test_lcs_ck_001_reports_plugin_and_native(self, tmp_path: Path) -> None:
        """LCS-CK-001: --check 對 plugin 提供者印 plugin、對實體 skill 印 native"""
        repo = _make_repo(tmp_path)

        plugin = _run_check([str(repo), "viaplugin"])
        native = _run_check([str(repo), "native"])

        assert plugin.returncode == 0, plugin.stderr
        assert plugin.stdout.strip() == "plugin"
        assert native.returncode == 0, native.stderr
        assert native.stdout.strip() == "native"

    def test_lcs_ck_002_outside_plugins_and_dangling_are_native(self, tmp_path: Path) -> None:
        """LCS-CK-002: --check 與安裝路徑共用同一判準：plugins/ 以外與失效 symlink 都是 native"""
        repo = _make_repo(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / "skills" / "outside").symlink_to(elsewhere)
        (repo / "skills" / "dangling").symlink_to("../plugins/dev-cycle/skills/gone")

        outside = _run_check([str(repo), "outside"])
        dangling = _run_check([str(repo), "dangling"])

        assert outside.stdout.strip() == "native"
        assert dangling.stdout.strip() == "native"

    def test_lcs_ck_003_is_read_only(self, tmp_path: Path) -> None:
        """LCS-CK-003: --check 不建立也不移除任何東西（含既有的重複連結）"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        dup = dst / "viaplugin"
        dup.symlink_to(repo / "skills" / "viaplugin")
        before = sorted(p.name for p in dst.iterdir())

        result = _run_check([str(repo), "viaplugin"])

        assert result.returncode == 0, result.stderr
        assert dup.is_symlink()
        assert sorted(p.name for p in dst.iterdir()) == before

    def test_lcs_ck_004_wrong_arg_count_fails_loud(self, tmp_path: Path) -> None:
        """LCS-CK-004: --check 參數數量不對時 exit 1 並寫 [FAIL]，不靜默印出 native"""
        result = _run_check([str(tmp_path)])

        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert result.stdout.strip() == ""


class TestStatusOwn:
    def _make_fixture(self, tmp_path: Path) -> tuple[Path, Path]:
        """最小 checkout + 隔離 HOME，讓 make status-own 只讀這份 fixture。"""
        repo = _make_repo(tmp_path)
        shutil.copy2(MAKEFILE, repo / "Makefile")
        scripts = repo / "scripts"
        scripts.mkdir()
        shutil.copy2(SCRIPT, scripts / "link_claude_skill.sh")
        # 第二個 plugin 提供的 skill 與第二個實體 skill，湊齊四種狀態
        plugin2 = repo / "plugins" / "dev-cycle" / "skills" / "viaplugin2"
        plugin2.mkdir(parents=True)
        (plugin2 / "SKILL.md").write_text("x\n", encoding="utf-8")
        (repo / "skills" / "viaplugin2").symlink_to("../plugins/dev-cycle/skills/viaplugin2")
        (repo / "skills" / "native2").mkdir()
        (repo / "skills" / "native2" / "SKILL.md").write_text("x\n", encoding="utf-8")
        home = tmp_path / "home"
        claude_skills = home / ".claude" / "skills"
        claude_skills.mkdir(parents=True)
        # native 已連結 -> OK；viaplugin 殘留舊重複連結 -> DUP；viaplugin2 乾淨 -> PL；native2 未連結 -> --
        (claude_skills / "native").symlink_to(repo / "skills" / "native")
        (claude_skills / "viaplugin").symlink_to(repo / "skills" / "viaplugin")
        return repo, home

    def _status_lines(self, repo: Path, home: Path) -> dict[str, str]:
        result = subprocess.run(  # nosec B603 B607
            ["make", "-C", str(repo), "status-own"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "HOME": str(home)},
        )
        assert result.returncode == 0, result.stderr
        # 資料列格式：`  CC:<狀態> AG:<狀態>  <name> [<scope>]`；說明列也以 CC: 開頭，
        # 但後面不接 AG:，所以要用完整格式比對，不能只看前綴。
        row = re.compile(r"^\s+CC:(\S+)\s+AG:(\S+)\s+(\S+)\s+\[")
        statuses: dict[str, str] = {}
        for line in result.stdout.splitlines():
            m = row.match(line)
            if m:
                statuses[m.group(3)] = m.group(1)
        assert statuses, f"解析不到任何資料列，輸出：{result.stdout!r}"
        return statuses

    def test_lcs_so_001_status_own_distinguishes_the_four_states(self, tmp_path: Path) -> None:
        """LCS-SO-001: status-own 的 CC 欄區分 OK / PL / DUP / --，不把刻意不連誤報成未安裝"""
        repo, home = self._make_fixture(tmp_path)

        statuses = self._status_lines(repo, home)

        assert statuses == {
            "native": "OK",
            "native2": "--",
            "viaplugin": "DUP",
            "viaplugin2": "PL",
        }
