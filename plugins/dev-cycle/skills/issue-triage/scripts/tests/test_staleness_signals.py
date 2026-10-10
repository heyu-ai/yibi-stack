"""staleness-signals.sh 的契約與行為測試（change: add-issue-triage-staleness-review）。

issue 引用的檔案若自建立以來被刪除、改名或大量變動，就是比天數更直接的「前提可能已消失」訊號。
腳本對 origin/main 的**歷史**計算（不看工作樹），每個路徑輸出一行：

    <路徑>\\t<狀態>\\t<細節>

狀態與細節：

    unchanged      仍存在，自 issue 建立後沒有 commit 動過它；細節為空
    changed        仍存在，自 issue 建立後被動過；細節為 commit 數
    deleted        已不存在，歷史上被刪除；細節為刪除它的 commit SHA
    renamed        已不存在於原路徑，歷史上被改名；細節為新路徑
    never-existed  origin/main 的歷史上從未有過這個路徑；細節為空

沒有任何路徑時輸出單行 NOT_APPLICABLE（「沒有漂移訊號」不等於「前提仍成立」，由呼叫端處理）。

Exit code 契約（與 staleness-signals.sh 檔頭一致）：

    0  成功
    1  腳本自身的未預期錯誤
    2  參數錯誤（缺建立時間、時間格式不對；路徑為空、絕對路徑、含 .. 段，或含 tab 或換行）
    3  不在 git repo 內，或 refs/remotes/origin/main 不存在（請先跑 check-baseline.sh）
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STALENESS_SIGNALS = SCRIPTS_DIR / "staleness-signals.sh"

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_NO_BASELINE = 3

CREATED_AT = "2026-03-01T00:00:00Z"
BEFORE = "2026-01-10T00:00:00Z"  # 早於 CREATED_AT
AFTER_1 = "2026-03-05T00:00:00Z"
AFTER_2 = "2026-03-06T00:00:00Z"
AFTER_3 = "2026-03-07T00:00:00Z"

_GIT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _clean_env(**overrides: str) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **overrides}
    for name in _GIT_ENV_VARS:
        if name not in overrides:
            env.pop(name, None)
    return env


def _git(repo: Path, *args: str, date: str | None = None) -> subprocess.CompletedProcess[str]:
    extra = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    return subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=_clean_env(**extra),
    )


def _commit(repo: Path, message: str, date: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _write(repo: Path, name: str, content: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    """建立有 origin/main 的 repo；呼叫端接著在 repo 內提交，最後 _publish 讓 origin/main 追上。"""
    origin = tmp_path / "origin.git"
    subprocess.run(  # nosec B603
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
        check=True,
        timeout=60,
        env=_clean_env(),
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "remote", "add", "origin", str(origin))
    _write(repo, "anchor.txt", "anchor\n")
    _commit(repo, "anchor", BEFORE)
    return repo


def _publish(repo: Path) -> None:
    _git(repo, "push", "-q", "origin", "main")


def _run(repo: Path, *args: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(STALENESS_SIGNALS), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=_clean_env(**env_overrides),
    )


def _rows(proc: subprocess.CompletedProcess[str]) -> list[list[str]]:
    return [line.split("\t") for line in proc.stdout.splitlines() if line]


class TestStaticContract:
    SRC = STALENESS_SIGNALS.read_text(encoding="utf-8") if STALENESS_SIGNALS.is_file() else ""

    def test_ss_dt_001_script_exists(self) -> None:
        assert STALENESS_SIGNALS.is_file(), f"缺少 {STALENESS_SIGNALS}"

    def test_ss_dt_002_header_documents_every_exit_code(self) -> None:
        head = "\n".join(self.SRC.splitlines()[:40])
        for code in ("0", "1", "2", "3"):
            assert re.search(rf"^#\s+{code}\b", head, re.MULTILINE), f"檔頭缺 exit {code}"

    def test_ss_dt_003_diagnostics_go_to_stderr(self) -> None:
        fail_lines = [
            line
            for line in self.SRC.splitlines()
            if "[FAIL]" in line and "echo" in line and not line.lstrip().startswith("#")
        ]
        assert fail_lines, "找不到任何 [FAIL] echo；空迴圈會讓下面的斷言空洞地通過"
        for line in fail_lines:
            assert ">&2" in line, line

    def test_ss_dt_004_reads_history_not_the_working_tree(self) -> None:
        """狀態必須由 origin/main 的歷史判斷；讀工作樹會把 untracked 檔案當成存在。"""
        assert "origin/main" in self.SRC
        assert "[ -e " not in self.SRC
        assert "[ -f " not in self.SRC

    def test_ss_dt_005_every_baseline_reference_uses_the_full_ref(self) -> None:
        """短名稱 `origin/main` 會先解析到同名的本機分支（refs/heads/origin/main）。

        非註解的程式行只要提到 origin/main，就必須是完整的 refs/remotes/origin/main。

        spec: issue-triage-staleness-review#same-named-local-branch-does-not-shadow-the-baseline
        tc: ITD-ST-010
        """
        lines = [
            line
            for line in self.SRC.splitlines()
            if "origin/main" in line and not line.lstrip().startswith("#")
        ]
        assert lines, "找不到任何提到 origin/main 的程式行；空迴圈會讓下面的斷言空洞地通過"
        for line in lines:
            assert "refs/remotes/origin/main" in line, line


class TestBehaviour:
    def test_ss_st_001_unchanged_file(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _write(repo, "src/stable.py", "x = 1\n")
        _commit(repo, "add stable", BEFORE)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/stable.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/stable.py", "unchanged", ""]]

    def test_ss_st_002_changed_counts_only_commits_after_creation(self, tmp_path: Path) -> None:
        """只計 issue 建立之後動過該檔案的 commit 數；建立前的不算。

        spec: issue-triage-staleness-review#referenced-file-changed-repeatedly
        tc: ITD-ST-002
        """
        repo = _make_repo(tmp_path)
        _write(repo, "src/hot.py", "v0\n")
        _commit(repo, "add hot", BEFORE)
        _write(repo, "src/hot.py", "v-before\n")
        _commit(repo, "edit before creation", "2026-02-01T00:00:00Z")
        for i, date in enumerate((AFTER_1, AFTER_2, AFTER_3), start=1):
            _write(repo, "src/hot.py", f"v{i}\n")
            _commit(repo, f"edit {i}", date)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/hot.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/hot.py", "changed", "3"]]

    def test_ss_st_003_deleted_reports_the_deleting_commit(self, tmp_path: Path) -> None:
        """已被刪除的路徑回報 deleted，細節為刪除它的 commit SHA。

        spec: issue-triage-staleness-review#referenced-file-was-deleted
        tc: ITD-ST-001
        """
        repo = _make_repo(tmp_path)
        _write(repo, "src/legacy.py", "old\n")
        _commit(repo, "add legacy", BEFORE)
        (repo / "src" / "legacy.py").unlink()
        deleting = _commit(repo, "remove legacy", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/legacy.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/legacy.py", "deleted", deleting]]

    def test_ss_st_004_renamed_reports_the_new_path(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _write(
            repo, "src/old_name.py", "same content that is long enough for rename detection\n" * 5
        )
        _commit(repo, "add old_name", BEFORE)
        _git(repo, "mv", "src/old_name.py", "src/new_name.py")
        _commit(repo, "rename", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/old_name.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/old_name.py", "renamed", "src/new_name.py"]]

    def test_ss_st_005_never_existed(self, tmp_path: Path) -> None:
        """歷史上從未存在的路徑回報 never-existed。

        「不是前提消失的證據」這條規則由 runbook 規定，見 ITS-DT-013。

        spec: issue-triage-staleness-review#never-existed-path-is-not-evidence-of-absence
        tc: ITD-ST-004
        """
        repo = _make_repo(tmp_path)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/typo_path.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/typo_path.py", "never-existed", ""]]

    def test_ss_st_006_no_paths_is_not_applicable(self, tmp_path: Path) -> None:
        """沒有任何路徑時輸出 NOT_APPLICABLE，而不是「沒有漂移」。

        spec: issue-triage-staleness-review#issue-references-no-paths
        tc: ITD-ST-003
        """
        repo = _make_repo(tmp_path)
        _publish(repo)
        proc = _run(repo, CREATED_AT)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert proc.stdout.strip() == "NOT_APPLICABLE"

    def test_ss_st_007_multiple_paths_one_line_each_in_order(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _write(repo, "a.py", "a\n")
        _write(repo, "b.py", "b\n")
        _commit(repo, "add a and b", BEFORE)
        _write(repo, "b.py", "b2\n")
        _commit(repo, "edit b", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "b.py", "missing.py", "a.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [
            ["b.py", "changed", "1"],
            ["missing.py", "never-existed", ""],
            ["a.py", "unchanged", ""],
        ]

    def test_ss_st_008_missing_baseline_ref_fails_without_state_lines(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)  # 從未 push，沒有 origin/main
        proc = _run(repo, CREATED_AT, "anchor.txt")
        assert proc.returncode == EXIT_NO_BASELINE, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_ss_st_009_reads_baseline_not_the_working_tree(self, tmp_path: Path) -> None:
        """工作樹裡有、但 origin/main 沒有的檔案（例如 untracked）必須回報 never-existed。"""
        repo = _make_repo(tmp_path)
        _publish(repo)
        _write(repo, "local_only.py", "untracked\n")
        proc = _run(repo, CREATED_AT, "local_only.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["local_only.py", "never-existed", ""]]

    def test_ss_st_010_glob_characters_are_literal(self, tmp_path: Path) -> None:
        """路徑必須逐字比對：a*.py 不能因為萬用字元而命中 a1.py。

        a1.py 必須是「已被刪除」的檔案：若路徑被當成 glob，刪除紀錄的查詢會命中它而回報 deleted。
        只放一個存在的 a1.py 測不到這條路徑（ls-tree 本身不展開 glob，突變會存活）。
        """
        repo = _make_repo(tmp_path)
        _write(repo, "a1.py", "a1\n")
        _commit(repo, "add a1", BEFORE)
        (repo / "a1.py").unlink()
        _commit(repo, "delete a1", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "a*.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["a*.py", "never-existed", ""]]

    def test_ss_st_011_pathspec_magic_is_literal(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _write(repo, "x.py", "x\n")
        _commit(repo, "add x", BEFORE)
        _publish(repo)
        proc = _run(repo, CREATED_AT, ":(glob)*.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [[":(glob)*.py", "never-existed", ""]]

    def test_ss_st_012_recreated_after_deletion_counts_as_changed(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _write(repo, "cycle.py", "v1\n")
        _commit(repo, "add", BEFORE)
        (repo / "cycle.py").unlink()
        _commit(repo, "delete", AFTER_1)
        _write(repo, "cycle.py", "v2\n")
        _commit(repo, "recreate", AFTER_2)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "cycle.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["cycle.py", "changed", "2"]]

    def test_ss_st_013_inherited_git_dir_does_not_redirect_to_another_repo(
        self, tmp_path: Path
    ) -> None:
        """decoy 是有效的 repo 且沒有 origin/main；若被 GIT_DIR 騙去讀它，會變成 exit 3。"""
        repo = _make_repo(tmp_path)
        _write(repo, "ok.py", "ok\n")
        _commit(repo, "add ok", BEFORE)
        _publish(repo)
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        _git(decoy, "init", "-q", "-b", "main")
        proc = _run(
            repo, CREATED_AT, "ok.py", GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy)
        )
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["ok.py", "unchanged", ""]]

    def test_ss_st_018_same_named_local_branch_does_not_shadow_the_baseline(
        self, tmp_path: Path
    ) -> None:
        """本機分支叫 `origin/main` 時，短名稱會先解析到它：remote 已刪掉的檔案會被當成還在。

        local 分支停在還有 premise.txt 的 commit，remote 的 main 已刪掉它：
        必須回報 deleted（遠端的事實），而不是 changed。

        spec: issue-triage-staleness-review#same-named-local-branch-does-not-shadow-the-baseline
        tc: ITD-ST-010
        """
        repo = _make_repo(tmp_path)
        _write(repo, "premise.txt", "premise\n")
        _commit(repo, "add premise", BEFORE)
        _publish(repo)
        _git(repo, "branch", "origin/main", "HEAD")
        (repo / "premise.txt").unlink()
        deleting = _commit(repo, "remove premise", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "premise.txt")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["premise.txt", "deleted", deleting]]
        assert "warning" not in proc.stderr

    def test_ss_st_019_local_branch_named_origin_main_is_not_a_baseline(
        self, tmp_path: Path
    ) -> None:
        """對照：沒有遠端 main（從未 push），但有本機分支 `origin/main`：仍然是 exit 3。

        spec: issue-triage-staleness-review#same-named-local-branch-does-not-shadow-the-baseline
        tc: ITD-ST-010
        """
        repo = _make_repo(tmp_path)
        _git(repo, "branch", "origin/main", "HEAD")
        proc = _run(repo, CREATED_AT, "anchor.txt")
        assert proc.returncode == EXIT_NO_BASELINE, proc.stdout
        assert proc.stdout == ""

    def test_ss_st_020_delete_recreate_delete_reports_the_last_deleting_commit(
        self, tmp_path: Path
    ) -> None:
        """刪除、重建、再刪除：細節必須是「最近一次」刪除它的 commit，單一 SHA。

        刪除紀錄的查詢少了 `-1` 會回傳兩個 SHA（換行分隔），輸出就不是單一欄位。

        spec: issue-triage-staleness-review#deleted-again-after-recreation
        tc: ITD-ST-009
        """
        repo = _make_repo(tmp_path)
        _write(repo, "cycle.py", "v1\n")
        _commit(repo, "add", BEFORE)
        (repo / "cycle.py").unlink()
        first_delete = _commit(repo, "delete", AFTER_1)
        _write(repo, "cycle.py", "v2\n")
        _commit(repo, "recreate", AFTER_2)
        (repo / "cycle.py").unlink()
        last_delete = _commit(repo, "delete again", AFTER_3)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "cycle.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert first_delete != last_delete
        assert _rows(proc) == [["cycle.py", "deleted", last_delete]]
        assert len(proc.stdout.splitlines()) == 1

    def test_ss_st_021_non_ascii_path_rename_is_reported(self, tmp_path: Path) -> None:
        """非 ASCII 檔名的改名：`git show` 預設把路徑引號跳脫成八進位，比對會失敗而誤判成 deleted。

        spec: issue-triage-staleness-review#referenced-file-was-renamed
        tc: ITD-ST-006
        """
        repo = _make_repo(tmp_path)
        _write(repo, "設計.md", "設計文件的內容，長到足以讓 git 偵測改名\n" * 5)
        _commit(repo, "add 設計", BEFORE)
        _git(repo, "mv", "設計.md", "design.md")
        _commit(repo, "rename 設計", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "設計.md")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["設計.md", "renamed", "design.md"]]

    def test_ss_st_022_rename_with_edits_is_still_a_rename(self, tmp_path: Path) -> None:
        """改名同時小幅修改（相似度低於 100%，狀態是 R 加兩位數）仍然是 renamed。

        spec: issue-triage-staleness-review#referenced-file-was-renamed
        tc: ITD-ST-007
        """
        repo = _make_repo(tmp_path)
        body = "".join(f"line {i} of the original file\n" for i in range(10))
        _write(repo, "src/old.py", body)
        _commit(repo, "add old", BEFORE)
        _git(repo, "mv", "src/old.py", "src/new.py")
        _write(repo, "src/new.py", body.replace("line 3 of", "line three of"))
        _commit(repo, "rename with an edit", AFTER_1)
        status = _git(repo, "show", "-M", "--name-status", "--format=", "HEAD").stdout
        assert re.match(r"R\d{3}\t", status) and not status.startswith("R100"), status
        _publish(repo)
        proc = _run(repo, CREATED_AT, "src/old.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["src/old.py", "renamed", "src/new.py"]]

    def test_ss_st_023_two_renames_in_one_commit_report_each_target(self, tmp_path: Path) -> None:
        """同一個 commit 改名兩個檔案：每個路徑必須對應到自己的新路徑，不是第一個 R 行。

        spec: issue-triage-staleness-review#referenced-file-was-renamed
        tc: ITD-ST-008
        """
        repo = _make_repo(tmp_path)
        _write(repo, "a.py", "".join(f"alpha {i} unique text\n" for i in range(8)))
        _write(repo, "b.py", "".join(f"beta {i} different words\n" for i in range(8)))
        _commit(repo, "add a and b", BEFORE)
        _git(repo, "mv", "a.py", "a_new.py")
        _git(repo, "mv", "b.py", "b_new.py")
        _commit(repo, "rename both", AFTER_1)
        _publish(repo)
        proc = _run(repo, CREATED_AT, "a.py", "b.py")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _rows(proc) == [["a.py", "renamed", "a_new.py"], ["b.py", "renamed", "b_new.py"]]


class TestArguments:
    def test_ss_st_014_missing_creation_time_is_a_usage_error(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _publish(repo)
        proc = _run(repo)
        assert proc.returncode == EXIT_USAGE, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_ss_st_015_malformed_creation_time_is_a_usage_error(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _publish(repo)
        proc = _run(repo, "yesterday", "anchor.txt")
        assert proc.returncode == EXIT_USAGE, proc.stdout
        assert proc.stdout == ""

    def test_ss_st_016_absolute_and_parent_paths_are_rejected(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _publish(repo)
        for bad in (
            "/etc/passwd",
            "../outside.py",
            "src/../../x.py",
            "a\tb.py",
            "a\nb.py",
            "",
            "..",
            "src/..",
        ):
            proc = _run(repo, CREATED_AT, bad)
            assert proc.returncode == EXIT_USAGE, (bad, proc.stdout)
            assert proc.stdout == "", bad
            assert "[FAIL]" in proc.stderr, bad

    def test_ss_st_017_paths_are_repo_root_relative_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """從 repo 的子目錄執行時，路徑仍是 repo 根目錄相對。

        舊版的 pathspec 相對於 cwd，同一個引數在子目錄會變成 `sub/sub/x.txt` 而回報
        never-existed，exit 0，與在根目錄執行的結果相反。

        spec: issue-triage-staleness-review#referenced-file-changed-repeatedly
        tc: ITD-ST-005
        """
        repo = _make_repo(tmp_path)
        _write(repo, "sub/x.txt", "v0\n")
        _write(repo, "sub/y.txt", "y\n")
        _commit(repo, "add sub files", BEFORE)
        _write(repo, "sub/x.txt", "v1\n")
        _commit(repo, "edit x", AFTER_1)
        _publish(repo)
        expected = [["sub/x.txt", "changed", "1"], ["sub/y.txt", "unchanged", ""]]
        from_root = _run(repo, CREATED_AT, "sub/x.txt", "sub/y.txt")
        assert from_root.returncode == EXIT_OK, from_root.stderr
        assert _rows(from_root) == expected
        from_sub = _run(repo / "sub", CREATED_AT, "sub/x.txt", "sub/y.txt")
        assert from_sub.returncode == EXIT_OK, from_sub.stderr
        assert _rows(from_sub) == expected


# 假的 git：只讓指定的子指令失敗，其餘轉給真的 git。略過 -c 與 -C 這類全域選項後的第一個字是子指令。
SHIM = """#!/usr/bin/env bash
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[$i]}" in
    -c | -C) i=$((i + 2)) ;;
    -*) i=$((i + 1)) ;;
    *) break ;;
  esac
done
if [ "${args[$i]:-}" = "${SHIM_FAIL_SUBCMD}" ]; then
  echo "shim: simulated failure of git ${SHIM_FAIL_SUBCMD}" >&2
  exit 3
fi
exec "${SHIM_REAL_GIT}" "$@"
"""


class TestUnexpectedGitFailure:
    @pytest.mark.parametrize(
        ("subcommand", "path"),
        [
            ("ls-tree", "anchor.txt"),
            ("rev-list", "anchor.txt"),
            ("log", "gone.py"),
            ("show", "gone.py"),
        ],
    )
    def test_ss_eg_024_a_failing_git_subcommand_exits_1_without_state_lines(
        self, tmp_path: Path, subcommand: str, path: str
    ) -> None:
        """git 自己壞掉不是「沒有漂移」：exit 1、stdout 為空、stderr 以 [FAIL] 說明。

        每個子指令都在「會走到它」的路徑上測：rev-list 對仍存在的路徑，log 與 show 對已刪除的路徑。
        分支若把 `fail 1` 改成 `true`，這裡會變成 exit 0 並輸出一行錯誤的狀態。

        spec: issue-triage-staleness-review#drift-lookup-fails-for-one-issue
        tc: ITD-EG-011
        """
        repo = _make_repo(tmp_path)
        _write(repo, "gone.py", "old\n")
        _commit(repo, "add gone", BEFORE)
        (repo / "gone.py").unlink()
        _commit(repo, "remove gone", AFTER_1)
        _publish(repo)
        shim_dir = tmp_path / "shim-bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(SHIM, encoding="utf-8")
        shim.chmod(0o755)
        real_git = shutil.which("git")
        assert real_git, "找不到真的 git"
        proc = _run(
            repo,
            CREATED_AT,
            path,
            PATH=f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
            SHIM_FAIL_SUBCMD=subcommand,
            SHIM_REAL_GIT=real_git,
        )
        assert proc.returncode == EXIT_UNEXPECTED, (proc.stdout, proc.stderr)
        assert proc.stdout == ""
        assert "[FAIL]" in proc.stderr
