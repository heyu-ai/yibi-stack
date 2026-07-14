"""resolve-skill-repo 與 safe_symlink.sh 的行為測試。

兩支腳本共同承擔一個保證：skill 永遠不會靜默跑在錯的 checkout 上。
- resolve-skill-repo：從自身位置 self-locate，且驗身分（tasks/）而非僅驗存在。
- safe_symlink.sh：make install 必須把過期的 symlink 重指到目前 checkout，
  否則 self-locate 會忠實地解析到舊 checkout。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts" / "resolve-skill-repo"
SAFE_SYMLINK = REPO_ROOT / "scripts" / "safe_symlink.sh"


def _run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, capture_output=True, text=True, timeout=30, check=False, **kw
    )


def _make_fake_repo(root: Path, marker: bool = True) -> Path:
    """建立一個含 resolve-skill-repo 的最小 git repo。"""
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", str(root)])
    if marker:
        (root / "tasks").mkdir()
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    dst = scripts_dir / "resolve-skill-repo"
    dst.write_text(RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
    dst.chmod(0o755)
    return dst


class TestResolveSkillRepo:
    def test_rsr_st_001_resolves_own_checkout_when_run_directly(self, tmp_path: Path) -> None:
        """RSR-ST-001: 直接執行時解析到自己所屬的 checkout。"""
        script = _make_fake_repo(tmp_path / "repo_a")
        result = _run(["bash", str(script)])
        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip()).resolve() == (tmp_path / "repo_a").resolve()

    def test_rsr_st_002_resolves_real_checkout_through_file_symlink(self, tmp_path: Path) -> None:
        """RSR-ST-002: 經「檔案層」symlink 執行時仍解析到實體檔案所屬的 checkout。

        這是本設計最容易錯的一點：`cd $(dirname $0) && pwd -P` 只穿透目錄 symlink，
        穿不透檔案 symlink，會回傳 bin 目錄而非真實 checkout（且不報錯）。
        """
        script = _make_fake_repo(tmp_path / "repo_a")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        link = bin_dir / "resolve-skill-repo"
        link.symlink_to(script)

        result = _run(["bash", str(link)])
        assert result.returncode == 0, result.stderr
        # 必須是 repo_a，而不是 bin/
        assert Path(result.stdout.strip()).resolve() == (tmp_path / "repo_a").resolve()

    def test_rsr_st_003_resolves_through_relative_symlink_chain(self, tmp_path: Path) -> None:
        """RSR-ST-003: 相對路徑的多段 symlink 鏈也能解析到實體檔案。"""
        script = _make_fake_repo(tmp_path / "repo_a")
        mid = tmp_path / "mid"
        mid.mkdir()
        hop1 = mid / "hop1"
        hop1.symlink_to(os.path.relpath(script, mid))
        hop2 = mid / "hop2"
        hop2.symlink_to("hop1")

        result = _run(["bash", str(hop2)])
        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip()).resolve() == (tmp_path / "repo_a").resolve()

    def test_rsr_eg_001_fails_when_resolved_repo_lacks_tasks(self, tmp_path: Path) -> None:
        """RSR-EG-001: 驗身分而非僅驗存在 -- 解析到的 repo 沒有 tasks/ 就必須 fail。

        這是 PR #221/#224 的核心：舊寫法只驗 [ -d ]，讓「存在但是錯的 repo」靜默通過。
        """
        script = _make_fake_repo(tmp_path / "wrong_repo", marker=False)
        result = _run(["bash", str(script)])
        assert result.returncode == 1
        assert "tasks/" in result.stderr
        assert result.stdout.strip() == ""

    def test_rsr_eg_002_fails_outside_any_git_repo(self, tmp_path: Path) -> None:
        """RSR-EG-002: 不在 git repo 內時 fail loud，並帶回 git 原始錯誤。"""
        plain = tmp_path / "plain"
        plain.mkdir()
        script = plain / "resolve-skill-repo"
        script.write_text(RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
        script.chmod(0o755)

        # 讓 git 不會往上找到真正的 repo
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
        result = _run(["bash", str(script)], env=env)
        assert result.returncode == 1
        assert "[FAIL]" in result.stderr
        assert result.stdout.strip() == ""

    def test_rsr_eg_003_does_not_leak_git_warning_into_output(self, tmp_path: Path) -> None:
        """RSR-EG-003: git 在成功時輸出的 warning 不得混進 stdout。

        成功路徑若用 2>&1 取值，SKILL_REPO 會變成 "warning: ...\\n/path"，
        後續 -d 檢查失敗並誤報「指向錯 repo」。
        """
        script = _make_fake_repo(tmp_path / "repo_a")
        # 指向不存在的 gitconfig，促使 git 走 stderr 提示路徑；即使不觸發 warning，
        # stdout 也必須是乾淨的單行路徑。
        env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "nope.gitconfig")}
        result = _run(["bash", str(script)], env=env)
        assert result.returncode == 0, result.stderr
        out = result.stdout.strip()
        assert "\n" not in out
        assert "warning" not in out.lower()
        assert Path(out).resolve() == (tmp_path / "repo_a").resolve()


class TestSafeSymlink:
    def test_ssl_st_001_creates_link_when_absent(self, tmp_path: Path) -> None:
        """SSL-ST-001: 目標不存在時建立 symlink。"""
        src = tmp_path / "src.sh"
        src.write_text("x", encoding="utf-8")
        dst = tmp_path / "bin" / "src.sh"
        dst.parent.mkdir()

        result = _run(["bash", str(SAFE_SYMLINK), str(src), str(dst)])
        assert result.returncode == 0, result.stderr
        assert dst.is_symlink()
        assert Path(os.readlink(dst)) == src

    def test_ssl_dt_001_repoints_stale_symlink_to_current_checkout(self, tmp_path: Path) -> None:
        """SSL-DT-001: 既有 symlink 指向舊 checkout 時必須重指。

        舊版無條件 no-op，導致換 checkout 重跑 make install 後仍指向舊 repo,
        self-locate 於是忠實解析到舊 checkout -- 正是本 PR 要消滅的失敗模式。
        """
        old = tmp_path / "old" / "resolve-skill-repo"
        new = tmp_path / "new" / "resolve-skill-repo"
        for p in (old, new):
            p.parent.mkdir(parents=True)
            p.write_text("x", encoding="utf-8")
        dst = tmp_path / "bin" / "resolve-skill-repo"
        dst.parent.mkdir()
        dst.symlink_to(old)

        result = _run(["bash", str(SAFE_SYMLINK), str(new), str(dst)])
        assert result.returncode == 0, result.stderr
        assert Path(os.readlink(dst)) == new, "stale symlink 未被重指"

    def test_ssl_dt_002_is_noop_when_target_already_correct(self, tmp_path: Path) -> None:
        """SSL-DT-002: 目標已正確時維持 no-op（冪等，不必要地重建連結）。"""
        src = tmp_path / "src.sh"
        src.write_text("x", encoding="utf-8")
        dst = tmp_path / "bin" / "src.sh"
        dst.parent.mkdir()
        dst.symlink_to(src)

        result = _run(["bash", str(SAFE_SYMLINK), str(src), str(dst)])
        assert result.returncode == 0, result.stderr
        assert "↻" in result.stdout
        assert Path(os.readlink(dst)) == src

    def test_ssl_eg_001_relinks_dangling_symlink(self, tmp_path: Path) -> None:
        """SSL-EG-001: 斷掉的 symlink 會被重建。"""
        src = tmp_path / "src.sh"
        src.write_text("x", encoding="utf-8")
        dst = tmp_path / "bin" / "src.sh"
        dst.parent.mkdir()
        dst.symlink_to(tmp_path / "gone")

        result = _run(["bash", str(SAFE_SYMLINK), str(src), str(dst)])
        assert result.returncode == 0, result.stderr
        assert Path(os.readlink(dst)) == src

    @pytest.mark.parametrize("args", [[], ["only-one"]])
    def test_ssl_vl_001_requires_both_arguments(self, args: list[str]) -> None:
        """SSL-VL-001: 缺引數時 fail loud，不得靜默成功。"""
        result = _run(["bash", str(SAFE_SYMLINK), *args])
        assert result.returncode == 1
        assert "required" in result.stderr
