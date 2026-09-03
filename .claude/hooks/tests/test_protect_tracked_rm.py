"""protect-tracked-rm.py 的黑盒與單元測試。

<!-- verified: probe -->
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).parent.parent / "protect-tracked-rm.py"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("protect_tracked_rm", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HOOK_MODULE = _load_hook()


def _run(
    command: str,
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    timeout: float = 6,
) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    hook_env = os.environ.copy()
    if env is not None:
        hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=hook_env,
        timeout=timeout,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    _git(path, "config", "user.email", "hook-test@example.invalid")
    _git(path, "config", "user.name", "Hook Test")
    return path


def _track(repo: Path, relative: str, content: str = "tracked\n") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "--literal-pathspecs", "add", "--", relative)
    return path


def _commit(repo: Path, message: str = "test fixture") -> None:
    _git(repo, "commit", "-q", "-m", message)


def _fake_git(bin_dir: Path, body: str) -> Path:
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return script


@pytest.fixture
def tracked_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path / "repo")
    _track(repo, "tracked/file.txt")
    return repo


class TestTrackedTargets:
    def test_ptrm_dt_001_clean_tracked_entry_is_not_hidden_by_status(self, tmp_path: Path) -> None:
        """只有 ?? 狀態時，clean tracked 檔仍須由 ls-files 找到。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "mixed/.gitkeep")
        _commit(repo)
        (repo / "mixed" / "generated.txt").write_text("untracked\n", encoding="utf-8")
        status = _git(repo, "status", "--porcelain", "--", "mixed").stdout.splitlines()
        assert status and all(line.startswith("??") for line in status)

        result = _run("rm -rf mixed", repo)

        assert result.returncode == 2
        assert "mixed/.gitkeep" in result.stdout

    def test_ptrm_dt_002_tracked_regular_file_blocks(self, tracked_repo: Path) -> None:
        """已追蹤的一般檔案目標須攔截，且類型不得誤稱目錄。"""
        result = _run("rm -rf tracked/file.txt", tracked_repo)

        assert result.returncode == 2
        assert "目標（檔案）" in result.stdout
        assert "tracked/file.txt" in result.stdout

    def test_ptrm_dt_003_tracked_directory_blocks(self, tracked_repo: Path) -> None:
        """含已追蹤內容的目錄須攔截。"""
        result = _run("rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "目標（目錄）" in result.stdout
        assert "[BLOCKED] 遞迴 rm 目標包含 Git 已追蹤內容" in result.stderr
        assert "tracked/file.txt" in result.stderr

    def test_ptrm_dt_004_tracked_symlink_to_file_blocks(self, tmp_path: Path) -> None:
        """已追蹤、指向檔案的符號連結須按連結本身判定。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "target.txt")
        (repo / "file-link").symlink_to("target.txt")
        _git(repo, "add", "--", "file-link")

        result = _run("rm -rf file-link", repo)

        assert result.returncode == 2
        assert "目標（符號連結）" in result.stdout
        assert "file-link" in result.stdout

    def test_ptrm_dt_005_tracked_symlink_to_directory_blocks(self, tmp_path: Path) -> None:
        """已追蹤、指向目錄的符號連結須按連結本身判定。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "target/file.txt")
        (repo / "directory-link").symlink_to("target", target_is_directory=True)
        _git(repo, "add", "--", "directory-link")

        result = _run("rm -rf directory-link", repo)

        assert result.returncode == 2
        assert "目標（符號連結）" in result.stdout
        assert "directory-link" in result.stdout

    @pytest.mark.parametrize("kind", ["file", "directory", "file-symlink", "directory-symlink"])
    def test_ptrm_dt_006_untracked_targets_allow(self, tmp_path: Path, kind: str) -> None:
        """確認未追蹤的一般檔案、目錄與符號連結均放行。"""
        repo = _repo(tmp_path / "repo")
        if kind == "file":
            (repo / "candidate").write_text("untracked\n", encoding="utf-8")
        elif kind == "directory":
            (repo / "candidate").mkdir()
        elif kind == "file-symlink":
            (repo / "target.txt").write_text("untracked\n", encoding="utf-8")
            (repo / "candidate").symlink_to("target.txt")
        else:
            (repo / "target").mkdir()
            (repo / "candidate").symlink_to("target", target_is_directory=True)

        result = _run("rm -rf candidate", repo)

        assert result.returncode == 0
        assert result.stdout == ""

    def test_ptrm_dt_047_pathspec_magic_filename_blocks(self, tmp_path: Path) -> None:
        """Git pathspec magic 外觀的檔名仍須按字面值攔截。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, ":(top)victim")

        result = _run("rm -rf ':(top)victim'", repo)

        assert result.returncode == 2
        assert ":(top)victim" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("long-recursive", "rm --recursive tracked"),
            ("uppercase-recursive", "rm -R tracked"),
        ],
    )
    def test_ptrm_dt_050_recursive_flag_forms_block(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """長選項與單獨大寫 R 均須辨識為遞迴 rm。"""
        assert case_id
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout


class TestWrappersAndGrouping:
    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("sudo", "sudo rm -rf tracked"),
            ("absolute-bin", "/bin/rm -rf tracked"),
            ("absolute-usr-bin", "/usr/bin/rm -rf tracked"),
            ("command", "command rm -rf tracked"),
            ("env", "env rm -rf tracked"),
            ("env-assignment", "env FOO=1 rm -rf tracked"),
            ("time", "time rm -rf tracked"),
            ("timeout", "timeout 5 rm -rf tracked"),
            ("timeout-signal", "timeout -s KILL 5 rm -rf tracked"),
            ("nice-option", "nice -n 5 rm -rf tracked"),
            ("stdbuf-option", "stdbuf -o L rm -rf tracked"),
            ("nohup", "nohup rm -rf tracked"),
            ("watch", "watch rm -rf tracked"),
            ("watch-exec", "watch -x rm -rf tracked"),
            ("ionice", "ionice rm -rf tracked"),
            ("setsid", "setsid rm -rf tracked"),
            ("exec", "exec rm -rf tracked"),
            ("assignment", "FOO=1 rm -rf tracked"),
            ("sudo-option", "sudo -u root rm -rf tracked"),
        ],
    )
    def test_ptrm_dt_010_wrapper_forms_block(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """deny rule 可穿透的 wrapper 與 assignment prefix 也須攔截。"""
        assert case_id
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("env-short-value", "env -C other rm -rf tracked2"),
            ("env-long-value", "env --chdir other rm -rf tracked2"),
            ("env-long-equals", "env --chdir=other rm -rf tracked2"),
            ("sudo-short-value", "sudo -D other rm -rf tracked2"),
            ("sudo-long-value", "sudo --chdir other rm -rf tracked2"),
            ("sudo-long-equals", "sudo --chdir=other rm -rf tracked2"),
            ("sudo-chroot-value", "sudo -R other rm -rf tracked2"),
            ("sudo-chroot-equals", "sudo --chroot=other rm -rf tracked2"),
        ],
    )
    def test_ptrm_dt_017_wrapper_directory_option_changes_effective_cwd(
        self, tmp_path: Path, case_id: str, command: str
    ) -> None:
        """wrapper 的目錄選項須決定內層 rm 的有效 cwd。"""
        assert case_id
        repo = _repo(tmp_path / "repo")
        _track(repo, "other/tracked2/file.txt")

        result = _run(command, repo)

        assert result.returncode == 2
        assert f"目標（目錄）：{repo / 'other' / 'tracked2'}" in result.stdout

    def test_ptrm_dt_018_nested_wrapper_directory_options_are_relative(
        self, tmp_path: Path
    ) -> None:
        """內層 wrapper 的相對目錄須從外層 wrapper 更新後的 cwd 解算。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "other/nested/tracked3/file.txt")

        result = _run("env -C other sudo -D nested rm -rf tracked3", repo)

        assert result.returncode == 2
        assert f"目標（目錄）：{repo / 'other' / 'nested' / 'tracked3'}" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("subshell", "(rm -rf tracked)"),
            ("brace", "{ rm -rf tracked; }"),
            ("if", "if true; then rm -rf tracked; fi"),
            ("for", "for i in 1; do rm -rf tracked; done"),
            ("pipeline", "yes | rm -rf tracked"),
        ],
    )
    def test_ptrm_dt_011_group_and_control_forms_block(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """group、control structure 與 pipeline 內的 rm 均須攔截。"""
        assert case_id
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout

    def test_ptrm_dt_012_tilde_target_blocks(self, tmp_path: Path) -> None:
        """~ 路徑須依 hook 環境的 HOME 展開。"""
        home = _repo(tmp_path / "home")
        _track(home, "tracked/file.txt")
        caller = tmp_path / "caller"
        caller.mkdir()

        result = _run("rm -rf ~/tracked", caller, env={"HOME": str(home)})

        assert result.returncode == 2
        assert str(home / "tracked") in result.stdout

    def test_ptrm_eg_013_unmatched_group_blocks_conservatively(self, tracked_repo: Path) -> None:
        """含遞迴 rm 的不完整 grouping 不得 fail-open。"""
        result = _run("(rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "未配對" in result.stdout

    def test_ptrm_eg_014_unclosed_quote_blocks_conservatively(self, tracked_repo: Path) -> None:
        """shlex 無法解析時不得靜默放行。"""
        result = _run("rm -rf 'tracked", tracked_repo)

        assert result.returncode == 2
        assert "無法解析 Bash 指令" in result.stdout
        assert "無法解析 Bash 指令" in result.stderr
        assert "[BLOCKED] 無法確認 Git 追蹤狀態" in result.stderr

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf $TARGET",
            "rm -rf '$(printf tracked)'",
            "rm -rf `echo tracked`",
            "rm -rf '*.tmp'",
            "bash -c 'rm -rf tracked'",
            "eval 'rm -rf tracked'",
            "rm -rf",
            "rm -rf '&&'",
            "rm -rf '{'",
        ],
    )
    def test_ptrm_eg_015_dynamic_rm_blocks_conservatively(
        self, tracked_repo: Path, command: str
    ) -> None:
        """無法靜態決定目標或由 shell 再解析的遞迴 rm 不得 fail-open。"""
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "無法" in result.stdout

    def test_ptrm_dt_016_rm_text_in_data_is_not_a_command(self, tracked_repo: Path) -> None:
        """一般引數裡的 rm 文字不應被誤判成可執行指令。"""
        result = _run("echo 'rm -rf tracked'", tracked_repo)

        assert result.returncode == 0

    def test_ptrm_dt_019_background_separator_exposes_following_rm(
        self, tracked_repo: Path
    ) -> None:
        """單一 & 須切開 clause，讓後續遞迴 rm 被獨立檢查。"""
        result = _run("true & rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout

    def test_ptrm_dt_026_unspaced_redirection_keeps_rm_target(self, tracked_repo: Path) -> None:
        """未留空白的輸出重新導向不得與 rm target 黏成單一 token。"""
        result = _run("rm -rf tracked>output.txt", tracked_repo)

        assert result.returncode == 2
        assert f"目標（目錄）：{tracked_repo / 'tracked'}" in result.stdout

    @pytest.mark.parametrize("operator", [">", ">>", "<<", "<>", ">&", "<&"])
    def test_ptrm_ut_027_redirection_punctuation_stays_grouped(self, operator: str) -> None:
        """重新導向運算子須保留成單一 token。"""
        tokens = HOOK_MODULE._tokenize(f"rm -rf tracked{operator}output.txt")

        assert tokens == ["rm", "-rf", "tracked", operator, "output.txt"]

    def test_ptrm_dt_028_redirection_target_is_not_an_rm_target(self, tmp_path: Path) -> None:
        """重新導向目的檔不得被誤判為 rm target。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "tracked_log.txt")
        (repo / "untracked").mkdir()

        result = _run("rm -rf untracked > tracked_log.txt", repo)

        assert result.returncode == 0
        assert result.stdout == ""

    def test_ptrm_dt_029_case_without_rm_allows(self, tracked_repo: Path) -> None:
        """case pattern 的右括號不得因 confirm 內含 rm 字串而誤擋。"""
        result = _run('case "$x" in a) echo confirm;; esac', tracked_repo)

        assert result.returncode == 0
        assert result.stdout == ""

    def test_ptrm_dt_037_case_with_recursive_rm_still_blocks(self, tracked_repo: Path) -> None:
        """case clause 內真正的遞迴 rm 仍須檢查追蹤內容。"""
        result = _run("case $x in a) rm -rf tracked;; esac", tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("unlisted-long-option", "sudo --preserve-env VARLIST rm -rf tracked"),
            ("option-value-is-rm", "sudo -p rm -rf tracked"),
        ],
    )
    def test_ptrm_eg_038_unclassified_wrapper_blocks_conservatively(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """wrapper 定位不可靠但仍可見遞迴 rm 意圖時須保守攔截。"""
        assert case_id

        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "wrapper 或控制結構無法可靠分類遞迴 rm" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("git-rm", "git rm -r -- tracked"),
            ("git-rm-cached", "git rm --cached -r -- tracked"),
            ("pnpm-rm", "pnpm rm -r some-package"),
            ("cargo-rm", "cargo rm --dry-run serde"),
            ("docker-rm", "docker rm -f some-container"),
        ],
    )
    def test_ptrm_dt_050_rm_subcommand_of_other_tool_allows(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """git/pnpm/cargo/docker 等工具自己的 rm 子指令不得被誤判為 coreutils rm。

        迴歸測試：Batch 2 為了修「無法分類 wrapper 選項時靜默放行」而加的保守文字
        掃描（has_visible_recursive_rm）曾經只要在 clause 任何位置看到 "rm" token
        後面接著含 r/R 的 flag，就一律攔截——連 hook 自己在攔截訊息裡建議的復原指令
        ``git -C <root> rm -r -- <path>`` 都會被自己擋下。
        """
        assert case_id

        result = _run(command, tracked_repo)

        assert result.returncode == 0
        assert result.stdout == ""

    def test_ptrm_dt_051_own_remediation_command_is_not_blocked(self, tracked_repo: Path) -> None:
        """hook 攔截已追蹤內容後印出的復原指令本身不可被同一個 hook 擋下。"""
        blocked = _run("rm -rf tracked", tracked_repo)
        assert blocked.returncode == 2

        remediation = f"git -C {tracked_repo} rm -r -- tracked"
        result = _run(remediation, tracked_repo)

        assert result.returncode == 0
        assert result.stdout == ""

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("tool-name-as-target", "unrecognized_wrapper rm -rf tracked git"),
            ("tool-name-as-decoy-option-value", "sudo -u git -p rm -rf tracked"),
        ],
    )
    def test_ptrm_eg_052_rm_subcommand_tool_name_as_decoy_still_blocks(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """rm 子指令工具名稱只有出現在 clause 第一個 token 時才豁免，不可被當誘餌。

        迴歸測試：round-2 review（agy 獨立發現）指出，若把「clause 內任何位置出現
        已知工具名稱」當豁免條件，攻擊者可把 ``git`` 塞進不相關的選項值或直接當成
        rm 的目標參數，讓真正的遞迴 rm 逃過保守掃描而被靜默放行。
        """
        assert case_id

        result = _run(command, tracked_repo)

        assert result.returncode == 2

    @pytest.mark.parametrize(
        "command",
        [
            'bash -c "bin/rm -rf tracked"',
            'bash -c "./rm -rf tracked"',
        ],
    )
    def test_ptrm_eg_043_relative_rm_path_in_indirect_executor_blocks(
        self, tracked_repo: Path, command: str
    ) -> None:
        """間接 executor 內以相對路徑呼叫 rm 時不得靜默放行。"""
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "將在執行期解析遞迴 rm" in result.stdout

    @pytest.mark.parametrize(
        "command",
        [
            "echo tracked | xargs rm -rf",
            "find . -name x | xargs rm -rf",
        ],
    )
    def test_ptrm_eg_044_xargs_recursive_rm_blocks(self, tracked_repo: Path, command: str) -> None:
        """xargs 將 stdin 補成 rm target 時須保守攔截。"""
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "遞迴 rm 含動態或無法解析的目標" in result.stdout

    def test_ptrm_dt_045_parallel_recursive_rm_blocks(self, tracked_repo: Path) -> None:
        """parallel 後的 rm command template 須遞迴檢查。"""
        result = _run("parallel rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout

    @pytest.mark.parametrize(
        ("case_id", "command"),
        [
            ("xargs-replace-short", "xargs -I token rm -rf tracked"),
            ("xargs-max-args", "xargs -n 1 rm -rf tracked"),
            ("xargs-max-procs", "xargs -P 2 rm -rf tracked"),
            ("xargs-null", "xargs -0 rm -rf tracked"),
            ("xargs-replace-long", "xargs --replace rm -rf tracked"),
            ("xargs-no-run-if-empty", "xargs -r rm -rf tracked"),
            ("parallel-options", "parallel -n 1 -P 2 rm -rf tracked"),
        ],
    )
    def test_ptrm_dt_049_xargs_and_parallel_options_reach_rm(
        self, tracked_repo: Path, case_id: str, command: str
    ) -> None:
        """xargs 與 parallel 自身選項不得遮蔽後方的 rm。"""
        assert case_id
        result = _run(command, tracked_repo)

        assert result.returncode == 2
        assert "tracked/file.txt" in result.stdout


class TestCwdScoping:
    def test_ptrm_dt_020_cd_other_repo_blocks_relative_target(self, tmp_path: Path) -> None:
        """cd && 後的 relative target 必須對另一個 repo 解算。"""
        caller = _repo(tmp_path / "caller")
        other = _repo(tmp_path / "other repo")
        _track(other, "tracked/file.txt")
        command = f"cd {shlex.quote(str(other))} && rm -rf tracked"

        result = _run(command, caller)

        assert result.returncode == 2
        assert str(other / "tracked") in result.stdout
        assert f"git -C {shlex.quote(str(other))}" in result.stdout

    def test_ptrm_dt_021_cd_non_repo_avoids_caller_false_positive(self, tmp_path: Path) -> None:
        """cd ; 後的 target 不得錯用 caller repo 的 index。"""
        caller = _repo(tmp_path / "caller")
        _track(caller, "tracked/file.txt")
        plain = tmp_path / "plain"
        plain.mkdir()
        command = f"cd {shlex.quote(str(plain))}; rm -rf tracked"

        result = _run(command, caller)

        assert result.returncode == 0

    def test_ptrm_eg_022_dynamic_cd_blocks_conservatively(self, tracked_repo: Path) -> None:
        """無法靜態解析 cd 後，不得用錯誤 cwd 檢查後續 rm。"""
        result = _run("cd $OTHER; rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "有效 cwd" in result.stdout

    def test_ptrm_eg_024_dynamic_cd_then_indirect_rm_blocks(self, tracked_repo: Path) -> None:
        """動態 cd 後的間接 shell rm 也不得因 cwd unknown 而放行。"""
        result = _run("cd $OTHER; bash -c 'rm -rf tracked'", tracked_repo)

        assert result.returncode == 2
        assert "有效 cwd" in result.stdout

    def test_ptrm_dt_023_subshell_cd_does_not_escape_group(self, tmp_path: Path) -> None:
        """subshell 的 cd 不得污染右括號後的 cwd。"""
        caller = _repo(tmp_path / "caller")
        _track(caller, "tracked/file.txt")
        plain = tmp_path / "plain"
        plain.mkdir()
        command = f"(cd {shlex.quote(str(plain))}); rm -rf tracked"

        result = _run(command, caller)

        assert result.returncode == 2
        assert str(caller / "tracked") in result.stdout

    def test_ptrm_dt_025_background_cd_does_not_change_parent_cwd(self, tmp_path: Path) -> None:
        """背景執行的 cd 不得改變後續 clause 的父 shell cwd。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "tracked/file.txt")
        (repo / "sub").mkdir()

        result = _run("cd sub & rm -rf tracked", repo)

        assert result.returncode == 2
        assert f"目標（目錄）：{repo / 'tracked'}" in result.stdout

    def test_ptrm_dt_046_symlinked_cd_parent_traversal_uses_physical_cwd(
        self, tmp_path: Path
    ) -> None:
        """cd 進符號連結後的 .. target 須從實體 cwd 解算。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "actual/tracked/file.txt")
        (repo / "actual" / "sub").mkdir()
        (repo / "link").symlink_to("actual/sub", target_is_directory=True)

        result = _run("cd link && rm -rf ../tracked", repo)

        assert result.returncode == 2
        assert str(repo / "actual" / "tracked") in result.stdout

    def test_ptrm_dt_048_ordinary_cd_parent_traversal_does_not_false_positive(
        self, tmp_path: Path
    ) -> None:
        """一般目錄中的 .. target 不得被錯解到其他 tracked 路徑。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "tracked/file.txt")
        (repo / "ordinary" / "sub").mkdir(parents=True)
        (repo / "ordinary" / "tracked").mkdir()

        result = _run("cd ordinary/sub && rm -rf ../tracked", repo)

        assert result.returncode == 0
        assert result.stdout == ""


class TestTriStateFailures:
    def test_ptrm_eg_030_corrupt_index_blocks_and_logs(self, tracked_repo: Path) -> None:
        """rev-parse 成功但 ls-files 遇到損壞 index 時須 block loud。"""
        (tracked_repo / ".git" / "index").write_bytes(b"broken-index")

        result = _run("rm -rf tracked", tracked_repo)

        assert result.returncode == 2
        assert "無法確認 Git 追蹤狀態" in result.stdout
        assert "無法列出 Git 已追蹤內容" in result.stderr

    def test_ptrm_eg_031_git_missing_blocks_and_logs(
        self, tracked_repo: Path, tmp_path: Path
    ) -> None:
        """PATH 找不到 git 時須 block loud。"""
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()

        result = _run("rm -rf tracked", tracked_repo, env={"PATH": str(empty_bin)})

        assert result.returncode == 2
        assert "找不到 git 執行檔" in result.stdout
        assert "找不到 git 執行檔" in result.stderr

    def test_ptrm_eg_032_git_timeout_blocks_and_logs(
        self, tracked_repo: Path, tmp_path: Path
    ) -> None:
        """git 探測超過 timeout 時須 block loud。"""
        bin_dir = tmp_path / "slow-bin"
        _fake_git(bin_dir, "/bin/sleep 5")

        result = _run("rm -rf tracked", tracked_repo, env={"PATH": str(bin_dir)})

        assert result.returncode == 2
        assert "git 探測逾時" in result.stdout
        assert "git 探測逾時" in result.stderr

    def test_ptrm_eg_033_git_nonzero_blocks_and_preserves_stderr(
        self, tracked_repo: Path, tmp_path: Path
    ) -> None:
        """非 not-a-repo 的非零退出須保留 stderr 並攔截。"""
        bin_dir = tmp_path / "failing-bin"
        _fake_git(bin_dir, "printf '%s\\n' '探測失敗細節' >&2\nexit 7")

        result = _run("rm -rf tracked", tracked_repo, env={"PATH": str(bin_dir)})

        assert result.returncode == 2
        assert "探測失敗細節" in result.stdout
        assert "探測失敗細節" in result.stderr

    def test_ptrm_dt_034_not_a_repo_is_confirmed_untracked(self, tmp_path: Path) -> None:
        """健康的非 repo 路徑是確認無追蹤內容，不是探測失敗。"""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "candidate").mkdir()

        result = _run("rm -rf candidate", plain)

        assert result.returncode == 0
        assert result.stderr == ""

    def test_ptrm_ut_035_tracked_files_exposes_three_states(self, tmp_path: Path) -> None:
        """helper 必須明確區分 list、空 list 與 None。"""
        repo = _repo(tmp_path / "repo")
        _track(repo, "tracked.txt")
        plain = tmp_path / "plain"
        plain.mkdir()

        assert HOOK_MODULE._tracked_files(repo / "tracked.txt", repo) == ["tracked.txt"]
        assert HOOK_MODULE._tracked_files(plain / "missing", plain) == []
        (repo / ".git" / "index").write_bytes(b"broken-index")
        assert HOOK_MODULE._tracked_files(repo / "tracked.txt", repo) is None

    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (OSError("作業系統失敗"), "無法啟動 git 探測"),
            (subprocess.SubprocessError("子行程失敗"), "git 子行程失敗"),
        ],
    )
    def test_ptrm_ut_036_other_subprocess_exceptions_return_none_and_log(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        exception: BaseException,
        expected: str,
    ) -> None:
        """其他 OSError 與 SubprocessError 也必須回傳 None 並寫 stderr。"""
        plain = tmp_path / "plain"
        plain.mkdir()

        def raise_error(*_args: object, **_kwargs: object) -> None:
            raise exception

        monkeypatch.setattr(HOOK_MODULE.subprocess, "run", raise_error)
        errors: list[str] = []

        assert HOOK_MODULE._tracked_files(plain / "candidate", plain, errors) is None
        assert expected in capsys.readouterr().err
        assert expected in errors[-1]

    def test_ptrm_eg_051_unexpected_main_exception_exits_two_without_traceback(
        self,
        tracked_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """main 內未預期錯誤須由 hook 自身保守攔截，不得洩漏 traceback。"""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf tracked"},
            "cwd": str(tracked_repo),
        }

        def raise_unexpected(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("未預期測試錯誤")

        monkeypatch.setattr(HOOK_MODULE, "_parse_rm_invocations", raise_unexpected)
        monkeypatch.setattr(HOOK_MODULE.sys, "stdin", StringIO(json.dumps(payload)))

        with pytest.raises(SystemExit) as exited:
            HOOK_MODULE.main()

        assert exited.value.code == 2
        captured = capsys.readouterr()
        assert "hook 發生未預期錯誤：未預期測試錯誤" in captured.err
        assert "Traceback" not in captured.err


class TestInputBoundary:
    def test_ptrm_eg_040_non_bash_payload_allows(self, tmp_path: Path) -> None:
        """非 Bash tool 不屬於此 hook。"""
        payload = {"tool_name": "Read", "tool_input": {"command": "rm -rf tracked"}}
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0

    def test_ptrm_eg_041_non_string_command_allows(self, tmp_path: Path) -> None:
        """外部 payload 的 command 型別錯誤時不可進入 parser。"""
        payload = {"tool_name": "Bash", "tool_input": {"command": None}, "cwd": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0

    def test_ptrm_eg_042_indirect_rm_text_scan_is_not_exponential(self) -> None:
        """_RECURSIVE_RM_TEXT_RE 不得對長重複輸入產生 catastrophic backtracking。

        CodeQL 對舊版 `(?:[^\\s;|(){}]*\\s+)*` 巢狀量詞回報 high-severity
        「Inefficient regular expression」（PR #418）：以 tab 重複組成、且結尾不構成
        合法比對的字串會觸發指數級 backtracking。此測試直接對 regex 施加惡意輸入，
        以極短的 wall-clock 上限斷言修正後的單一量詞版本維持線性時間。
        """
        malicious = "\t" * 100 + "rm\t" + "\t" * 4000
        start = time.monotonic()
        HOOK_MODULE._RECURSIVE_RM_TEXT_RE.search(malicious)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0
