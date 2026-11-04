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


class TestNotPrunedWarning:
    """plugin 提供的 skill，dst 已存在但不是本 repo 的連結：不處理，但要 [WARN] 提醒可能重複。"""

    def test_lcs_pw_001_link_to_other_checkout_warns_and_is_untouched(self, tmp_path: Path) -> None:
        """LCS-PW-001: 指向別的 checkout 的 skills/<name> 連結不刪除，並 [WARN]"""
        repo = _make_repo(tmp_path)
        other = tmp_path / "other checkout" / "skills" / "viaplugin"
        other.mkdir(parents=True)
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(other)

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr
        assert "viaplugin" in result.stderr
        assert str(dst / "viaplugin") in result.stderr
        assert (dst / "viaplugin").is_symlink()
        assert (dst / "viaplugin").readlink() == other

    def test_lcs_pw_002_foreign_symlink_warns(self, tmp_path: Path) -> None:
        """LCS-PW-002: 指向任意他處的 symlink 也 [WARN]，且不動它"""
        repo = _make_repo(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(elsewhere)

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr
        assert (dst / "viaplugin").readlink() == elsewhere

    def test_lcs_pw_003_real_directory_warns_and_is_untouched(self, tmp_path: Path) -> None:
        """LCS-PW-003: 實體目錄 [WARN] 且內容原封不動"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        (dst / "viaplugin").mkdir(parents=True)
        (dst / "viaplugin" / "keep.txt").write_text("mine\n", encoding="utf-8")

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr
        assert (dst / "viaplugin" / "keep.txt").read_text(encoding="utf-8") == "mine\n"

    def test_lcs_pw_004_absent_destination_does_not_warn(self, tmp_path: Path) -> None:
        """LCS-PW-004: dst 不存在（正常乾淨狀態）只有 [SKIP]，不出現 [WARN]"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert "[SKIP]" in result.stderr
        assert "[WARN]" not in result.stderr

    def test_lcs_pw_005_exact_match_is_pruned_without_warning(self, tmp_path: Path) -> None:
        """LCS-PW-005: 與預期完全相符的連結被移除，不 [WARN]，並提示如何取得 plugin"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(repo / "skills" / "viaplugin")

        result = _run(repo, "viaplugin", dst)

        assert result.returncode == 0, result.stderr
        assert not (dst / "viaplugin").is_symlink()
        assert "[WARN]" not in result.stderr
        assert "claude plugin install" in result.stdout


class TestCdpathIsolation:
    def test_lcs_cd_001_cdpath_does_not_hijack_relative_repo_root(self, tmp_path: Path) -> None:
        """LCS-CD-001: 環境有 CDPATH 且含同名相對路徑時，判準不可被它帶偏"""
        parent = tmp_path / "parent"
        parent.mkdir()
        _make_repo(parent)  # parent/repo：viaplugin 是 plugin 提供
        decoy = tmp_path / "cdpath_dir"
        (decoy / "repo" / "skills" / "viaplugin").mkdir(parents=True)

        result = subprocess.run(  # nosec B603
            ["bash", str(SCRIPT), "--check", "repo", "viaplugin"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=parent,
            env={**os.environ, "CDPATH": str(decoy)},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "plugin"


class TestPluginsBoundary:
    """判準是 `<repo>/plugins/` 之下，不是「repo 之內」，也不是前綴相同的 plugins-old/。"""

    def _repo(self, tmp_path: Path) -> Path:
        repo = _make_repo(tmp_path)
        (repo / "docs" / "x").mkdir(parents=True)
        (repo / "plugins-old" / "x").mkdir(parents=True)
        (repo / "skills" / "inrepo").symlink_to("../docs/x")
        (repo / "skills" / "plugins-old-skill").symlink_to("../plugins-old/x")
        return repo

    def test_lcs_bd_001_check_reports_native_for_in_repo_non_plugin_targets(
        self, tmp_path: Path
    ) -> None:
        """LCS-BD-001: 指向 repo 內 plugins/ 以外（含 plugins-old/）的 symlink 在 --check 是 native"""
        repo = self._repo(tmp_path)

        assert _run_check([str(repo), "inrepo"]).stdout.strip() == "native"
        assert _run_check([str(repo), "plugins-old-skill"]).stdout.strip() == "native"

    def test_lcs_bd_002_install_mode_links_them(self, tmp_path: Path) -> None:
        """LCS-BD-002: 安裝模式照舊連結，沒有 [SKIP]"""
        repo = self._repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()

        for name in ("inrepo", "plugins-old-skill"):
            result = _run(repo, name, dst)
            assert result.returncode == 0, result.stderr
            assert "[SKIP]" not in result.stderr
            assert (dst / name).readlink() == repo / "skills" / name


class TestExitCodes:
    def test_lcs_ec_001_native_blocked_by_real_directory_exits_2(self, tmp_path: Path) -> None:
        """LCS-EC-001: 實體目錄擋住 native skill 時，沿用 safe_symlink.sh 的 exit 2"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        (dst / "native").mkdir(parents=True)

        result = _run(repo, "native", dst)

        assert result.returncode == 2, result.stderr
        assert (dst / "native").is_dir()
        assert not (dst / "native").is_symlink()

    def test_lcs_ec_002_unremovable_duplicate_exits_1_with_fail(self, tmp_path: Path) -> None:
        """LCS-EC-002: 重複連結移不掉（目錄唯讀）時 exit 1 並 [FAIL]，連結仍在"""
        repo = _make_repo(tmp_path)
        dst = tmp_path / "claude_skills"
        dst.mkdir()
        (dst / "viaplugin").symlink_to(repo / "skills" / "viaplugin")
        dst.chmod(0o555)
        try:
            result = _run(repo, "viaplugin", dst)
            still_there = (dst / "viaplugin").is_symlink()
        finally:
            dst.chmod(0o755)

        assert result.returncode == 1, result.stderr
        assert "[FAIL]" in result.stderr
        assert still_there

    def test_lcs_ec_003_four_arguments_fail_loud(self, tmp_path: Path) -> None:
        """LCS-EC-003 (AC-6): 4 個參數 exit 1 並 [FAIL]，不靜默忽略多的參數"""
        result = subprocess.run(  # nosec B603
            ["bash", str(SCRIPT), str(tmp_path), "native", str(tmp_path), "extra"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 1
        assert "[FAIL]" in result.stderr

    def test_lcs_ec_004_check_with_three_arguments_fails_loud(self, tmp_path: Path) -> None:
        """LCS-EC-004 (AC-6): --check 帶 3 個參數 exit 1 並 [FAIL]"""
        result = _run_check([str(tmp_path), "native", "extra"])

        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert result.stdout.strip() == ""


def _write_skill(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("---\nname: x\nscope: global\n---\nx\n", encoding="utf-8")


def _clean_git_env() -> dict[str, str]:
    drop = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
    return {k: v for k, v in os.environ.items() if k not in drop}


class TestMakefileWiring:
    """真的跑 make install（隔離 HOME、小型假 skills/plugins），驗證接線而不是檢查 Makefile 字串。

    Makefile 的 install 迴圈有兩半：CC 半（經 link_claude_skill.sh 連到 ~/.claude/skills）
    與 AG 半（safe_symlink.sh 連到 ~/.agents/skills）。AG 半不會被 handover wrapper 的
    make install fixture 間接涵蓋（該測試不檢查任何 skills 目錄），所以這裡直接斷言兩半。
    """

    def _make_install_root(self, tmp_path: Path) -> tuple[Path, dict[str, str]]:
        root = tmp_path / "checkout"
        root.mkdir()
        shutil.copy2(MAKEFILE, root / "Makefile")
        scripts = root / "scripts"
        scripts.mkdir()
        for name in (
            "assert_not_worktree.sh",
            "safe_symlink.sh",
            "link_claude_skill.sh",
            "register_skill_repo.py",
            "lessons",
            "handover",
            "resolve-skill-repo",
        ):
            shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
        for name in ("tasks", "commands"):
            (root / name).symlink_to(REPO_ROOT / name, target_is_directory=True)
        _write_skill(root / "skills" / "native")
        _write_skill(root / "plugins" / "dev-cycle" / "skills" / "viaplugin")
        (root / "skills" / "viaplugin").symlink_to("../plugins/dev-cycle/skills/viaplugin")
        subprocess.run(  # nosec B603 B607
            ["git", "init", "-q", str(root)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            env=_clean_git_env(),
        )
        home = tmp_path / "home"
        (home / ".claude" / "skills").mkdir(parents=True)
        return root, {**_clean_git_env(), "HOME": str(home)}

    def _make_install(self, root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607
            ["make", "install"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )

    def test_lcs_st_001_install_wires_both_halves(self, tmp_path: Path) -> None:
        """LCS-ST-001: make install 在 CC / AG 兩個目錄各自套用正確的連結規則，並清掉舊重複連結"""
        root, env = self._make_install_root(tmp_path)
        home = Path(env["HOME"])
        cc = home / ".claude" / "skills"
        ag = home / ".agents" / "skills"
        (cc / "viaplugin").symlink_to(root / "skills" / "viaplugin")  # 舊版殘留的重複連結

        result = self._make_install(root, env)

        assert result.returncode == 0, result.stderr + result.stdout
        # 實體 skill：兩邊都連到本 repo
        assert (cc / "native").readlink() == root / "skills" / "native"
        assert (ag / "native").readlink() == root / "skills" / "native"
        # plugin 提供的 skill：CC 不連（且舊重複連結被清掉），AG 照連
        assert not (cc / "viaplugin").is_symlink()
        assert not (cc / "viaplugin").exists()
        assert (ag / "viaplugin").readlink() == root / "skills" / "viaplugin"

    def test_lcs_st_002_link_script_failure_aborts_install(self, tmp_path: Path) -> None:
        """LCS-ST-002: link_claude_skill.sh 失敗（實體目錄擋路）時 make install 必須非 0 結束"""
        root, env = self._make_install_root(tmp_path)
        blocker = Path(env["HOME"]) / ".claude" / "skills" / "native"
        blocker.mkdir()
        (blocker / "keep.txt").write_text("mine\n", encoding="utf-8")

        result = self._make_install(root, env)

        assert result.returncode != 0, result.stdout
        assert (blocker / "keep.txt").is_file()


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

    def _run_status(self, repo: Path, home: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607
            ["make", "-C", str(repo), "status-own"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "HOME": str(home)},
        )

    def _status_lines(self, repo: Path, home: Path) -> dict[str, tuple[str, str]]:
        result = self._run_status(repo, home)
        assert result.returncode == 0, result.stderr
        # 資料列格式：`  CC:<狀態> AG:<狀態>  <name> [<scope>]`；說明列也以 CC: 開頭，
        # 但後面不接 AG:，所以要用完整格式比對，不能只看前綴。
        row = re.compile(r"^\s+CC:(\S+)\s+AG:(\S+)\s+(\S+)\s+\[")
        statuses: dict[str, tuple[str, str]] = {}
        for line in result.stdout.splitlines():
            m = row.match(line)
            if m:
                statuses[m.group(3)] = (m.group(1), m.group(2))
        assert statuses, f"解析不到任何資料列，輸出：{result.stdout!r}"
        return statuses

    def test_lcs_so_001_status_own_distinguishes_the_four_states(self, tmp_path: Path) -> None:
        """LCS-SO-001: status-own 的 CC 欄區分 OK / PL / DUP / --，AG 欄獨立判斷"""
        repo, home = self._make_fixture(tmp_path)
        ag = home / ".agents" / "skills"
        ag.mkdir(parents=True)
        # AG 欄：native 與 viaplugin 已連結 -> OK；其餘 --
        (ag / "native").symlink_to(repo / "skills" / "native")
        (ag / "viaplugin").symlink_to(repo / "skills" / "viaplugin")

        statuses = self._status_lines(repo, home)

        assert statuses == {
            "native": ("OK", "OK"),
            "native2": ("--", "--"),
            "viaplugin": ("DUP", "OK"),
            "viaplugin2": ("PL", "--"),
        }

    def test_lcs_so_002_check_failure_fails_the_target(self, tmp_path: Path) -> None:
        """LCS-SO-002: link_claude_skill.sh 不見了時 status-own 非 0 並 [FAIL]，不可靜默顯示 OK"""
        repo, home = self._make_fixture(tmp_path)
        (repo / "scripts" / "link_claude_skill.sh").unlink()

        result = self._run_status(repo, home)

        assert result.returncode != 0, result.stdout
        assert "[FAIL]" in result.stderr

    def test_lcs_so_003_foreign_symlink_on_plugin_skill_is_pl_not_dup(self, tmp_path: Path) -> None:
        """LCS-SO-003: plugin skill 的 dst 是別的 checkout 的連結而非本 repo 的，仍顯示 PL"""
        repo, home = self._make_fixture(tmp_path)
        other = tmp_path / "other checkout" / "skills" / "viaplugin2"
        other.mkdir(parents=True)
        (home / ".claude" / "skills" / "viaplugin2").symlink_to(other)

        statuses = self._status_lines(repo, home)

        assert statuses["viaplugin2"][0] == "PL"
        assert statuses["viaplugin"][0] == "DUP"
