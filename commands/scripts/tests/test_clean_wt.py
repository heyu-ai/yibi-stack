"""clean_wt.sh 的行為測試。

這支腳本的核心保證是「不誤刪」，所以測試重心放在**該擋的有沒有擋住**：
- 分類正確（SAFE / KEEP / BLOCKED / REVIEW）
- 預設不刪任何東西
- worktree 裡的未提交內容一定擋下（分支比對看不到它）
- 沒有**正面證據**就不歸 SAFE（fail closed，寧可留著也不猜）

前一版的測試對**每個** case 都停用 gh，於是 gh 證據路徑（KEEP 與 SAFE 兩條短路）完全沒被
覆蓋——這正是「PR 用分支名稱比對」的致命 bug 能全綠通過的原因：測試只覆蓋了本來就
fail-safe 的路徑。因此本檔用 PATH 上的 gh stub 明確覆蓋 gh 路徑。

gh stub 的限制（誠實記錄）：stub 直接印出 TSV，等同於假設 `gh --json ... -q '<expr>'` 的
jq 運算式正確，因此**不覆蓋該運算式本身**。運算式與 `--json` 欄位名已對真實 gh 實測驗證
（headRefName / headRefOid / state / baseRefName 皆存在且輸出 TSV）。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "commands" / "scripts" / "clean_wt.sh"

# 忽略所有參數、直接印出 TSV 的 gh 替身。腳本只吃 `gh pr list ... -q '<tsv expr>'` 的輸出，
# 所以印 TSV 就能驅動全部 gh 分支邏輯。
_GH_STUB = """#!/usr/bin/env bash
if [ "${FAKE_GH_FAIL:-0}" = "1" ]; then
  echo "fake gh failure" >&2
  exit 1
fi
if [ -n "${FAKE_GH_TSV:-}" ] && [ -f "${FAKE_GH_TSV}" ]; then
  cat "${FAKE_GH_TSV}"
fi
exit 0
"""

# local_port_manager 的 uv 替身：把每次呼叫記到 $FAKE_UV_LOG，並模擬 `list` 的表格輸出。
_UV_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${FAKE_UV_LOG}"
for a in "$@"; do
  if [ "$a" = "list" ]; then
    echo "project          service      category   port     note"
    echo "--------------------------------------------------------"
    echo "${FAKE_UV_PROJECT}  postgres     db         5433"
    echo "${FAKE_UV_PROJECT}  redis        cache      6380"
    exit 0
  fi
done
exit 0
"""


def _mkstub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """乾淨的執行環境；PATH 前置 stub 目錄，讓 gh 走替身而非真實憑證。"""
    bin_dir = tmp_path / "stubbin"
    _mkstub(bin_dir, "gh", _GH_STUB)
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "no-gitconfig"),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        **extra,
    }


def _gh_tsv(tmp_path: Path, *rows: tuple[str, str, str, str]) -> str:
    """寫一個 gh stub 要吐的 TSV 檔，回傳路徑。row = (headRefName, headRefOid, state, base)。"""
    f = tmp_path / "gh.tsv"
    f.write_text("".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    return str(f)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    r = subprocess.run(  # nosec B603
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return r.stdout.strip()


def _run(
    repo: Path, env: dict[str, str], *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd or repo),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


def _section(stdout: str, name: str) -> str:
    """取出某個分類區塊的內容（到下一個 ══ 標題為止）。"""
    parts = stdout.split("══ ")
    for p in parts:
        if p.startswith(name):
            return p
    return ""


def _commit(repo: Path, env: dict[str, str], fname: str, body: str, msg: str) -> str:
    (repo / fname).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", msg, env=env)
    return _git(repo, "rev-parse", "HEAD", env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一個有 origin/main 的最小 repo（origin 是本地 bare repo）。"""
    env = _env(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(  # nosec B603
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=env
    )
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True, env=env)  # nosec B603
    _commit(work, env, "seed.txt", "seed\n", "seed")
    _git(work, "remote", "add", "origin", str(origin), env=env)
    _git(work, "push", "-q", "origin", "main", env=env)
    return work


class TestCleanWtClassification:
    def test_cwt_st_001_default_is_report_only(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-001: 預設只報告，絕不刪除任何分支。"""
        env = _env(tmp_path)
        _git(repo, "branch", "leftover", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "只報告" in r.stdout
        assert "leftover" in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_dt_001_merged_ancestor_branch_is_safe(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-001: tip 已是 origin/main 祖先的分支 -> SAFE（E1）。"""
        env = _env(tmp_path)
        _git(repo, "branch", "already-in", "HEAD", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "already-in" in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_002_branch_with_unique_commits_is_review_not_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-002: 有獨有 commit 且無 PR 的分支 -> REVIEW，不得歸 SAFE。"""
        env = _env(tmp_path)
        _git(repo, "checkout", "-qb", "unique-work", env=env)
        _commit(repo, env, "new.txt", "unique\n", "unique work")
        _git(repo, "checkout", "-q", "main", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "unique-work" not in _section(r.stdout, "SAFE"), r.stdout
        assert "unique-work" in _section(r.stdout, "REVIEW"), r.stdout

    def test_cwt_dt_003_multi_commit_squash_merge_is_safe(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-003: 多 commit 分支被 squash 進 main -> SAFE（E2 merge-tree）。

        前一版靠 git cherry 比對 patch-id，多 commit squash 對不上（上游一個大 patch vs
        分支多個小 patch），只能落到 REVIEW。merge-tree 比對的是**內容**而非 patch-id，
        因此能正確判定。實測（真實 repo）：worktree-fix-232-worktree-install-guard 已由
        PR #234 squash 合併，git cherry 仍回報 8 個未合併 patch。
        """
        env = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-squash", env=env)
        _commit(repo, env, "a.txt", "one\n", "c1")
        _commit(repo, env, "b.txt", "two\n", "c2")
        _git(repo, "checkout", "-q", "main", env=env)
        _git(repo, "merge", "--squash", "feat-squash", env=env)
        _git(repo, "commit", "-qm", "squashed feat", env=env)
        _git(repo, "push", "-q", "origin", "main", env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "feat-squash" in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_004_content_only_in_merge_commit_is_never_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-004: 內容只存在於 merge commit 的分支 -> 絕不可歸 SAFE。

        迴歸測試（前一版實測會遺失資料）：git cherry 內部設 max_parents=1，merge commit
        永不列出，因此手動衝突解決的內容完全隱形 -> 無 `+` 輸出 -> 判為「所有 patch 已在
        上游」-> SAFE -> git branch -D -> 永久遺失。
        """
        env = _env(tmp_path)
        base_sha = _git(repo, "rev-parse", "HEAD", env=env)
        _commit(repo, env, "mainfile.txt", "mainwork\n", "mainwork")
        _git(repo, "push", "-q", "origin", "main", env=env)

        _git(repo, "checkout", "-q", "-b", "merge-only", base_sha, env=env)
        _git(repo, "merge", "-q", "--no-ff", "main", "-m", "merge main into branch", env=env)
        # 只存在於這個 merge commit 裡的內容
        (repo / "resolved.txt").write_text("only-in-merge-commit\n", encoding="utf-8")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-q", "--amend", "--no-edit", env=env)
        _git(repo, "checkout", "-q", "main", env=env)

        # fixture 自我驗證：測的形狀必須真的成立，否則測試沒有意義
        assert _git(repo, "show", "merge-only:resolved.txt", env=env) == "only-in-merge-commit"
        assert _git(repo, "show", "main:resolved.txt", env=env) == ""
        assert len(_git(repo, "rev-list", "--parents", "-n1", "merge-only", env=env).split()) == 3

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "merge-only" not in _section(r.stdout, "SAFE"), (
            f"merge commit 內的獨有內容必須擋下:\n{r.stdout}"
        )

    def test_cwt_eg_001_dirty_worktree_is_blocked(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-001: worktree 有未提交變更 -> BLOCKED，即使分支本身與 main 無差異。"""
        env = _env(tmp_path)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "dirty-branch", str(wt), env=env)
        (wt / "uncommitted.txt").write_text("work in progress\n", encoding="utf-8")

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "dirty-branch" in _section(r.stdout, "BLOCKED"), r.stdout
        assert "dirty-branch" not in _section(r.stdout, "SAFE")

    def test_cwt_eg_002_apply_never_deletes_blocked(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-002: 即使加 --apply，BLOCKED 的分支仍不得被刪。"""
        env = _env(tmp_path)
        wt = tmp_path / "wt2"
        _git(repo, "worktree", "add", "-q", "-b", "dirty-keep", str(wt), env=env)
        (wt / "wip.txt").write_text("wip\n", encoding="utf-8")

        r = _run(repo, env, "--apply")

        assert "dirty-keep" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"--apply 不得刪除 BLOCKED 分支:\n{r.stdout}\n{r.stderr}"
        )

    def test_cwt_st_002_apply_deletes_safe_branch(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-002: --apply 會刪除 SAFE 分類的分支。"""
        env = _env(tmp_path)
        _git(repo, "branch", "gone-already", "HEAD", env=env)

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, r.stderr
        assert "gone-already" not in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_eg_003_never_deletes_main(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-003: main 永遠不出現在任何刪除清單。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--apply")

        assert r.returncode == 0, r.stderr
        assert "main" in _git(repo, "branch", "--format=%(refname:short)", env=env)


class TestCleanWtGhEvidence:
    """gh 證據路徑。前一版對此零覆蓋，導致「用分支名稱比對 PR」的致命 bug 全綠通過。"""

    def test_cwt_dt_005_merged_pr_with_advanced_local_tip_is_not_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-005: PR 已 MERGED，但本地分支之後又有新 commit -> 絕不可歸 SAFE。

        迴歸測試（前一版會永久遺失資料）：舊碼用 `gh pr list --head "$b"` 取 PR 狀態，
        MERGED 就直接短路成 SAFE。但那回答的是「有沒有同名 head-ref 的 PR 被合併過」，
        不是「這個本地分支現在的內容有沒有被合併」。本 repo 標準流程是
        `gh pr merge --squash --delete-branch`：遠端分支被刪、本地還在。此時在本地再
        commit（未開新 PR），PR 狀態仍是 MERGED -> SAFE -> 標記「僅本地」-> branch -D
        -> 沒有遠端可救回 -> 永久遺失。
        """
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-advanced", env=env_setup)
        merged_sha = _commit(repo, env_setup, "merged.txt", "merged work\n", "merged work")
        # main squash 合併了上面那個 commit
        _git(repo, "checkout", "-q", "main", env=env_setup)
        _git(repo, "merge", "--squash", "feat-advanced", env=env_setup)
        _git(repo, "commit", "-qm", "squash merged work", env=env_setup)
        _git(repo, "push", "-q", "origin", "main", env=env_setup)
        # 分支在合併「之後」又長出未合併的新工作
        _git(repo, "checkout", "-q", "feat-advanced", env=env_setup)
        _commit(repo, env_setup, "unmerged.txt", "work after the merge\n", "work after merge")
        _git(repo, "checkout", "-q", "main", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-advanced", merged_sha, "MERGED", "main"))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)

        r = _run(repo, env, "--apply")

        assert "feat-advanced" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"PR MERGED 但本地 tip 已前進，分支不得被刪:\n{r.stdout}\n{r.stderr}"
        )
        assert "feat-advanced" not in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_006_merged_pr_matching_tip_is_safe(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-006: PR MERGED 且 headRefOid == 本地 tip -> SAFE（E3 輔助證據）。

        這裡刻意造出 E1/E2 都不成立的情境：分支 squash 合併後 main 又改到同一個檔案，
        merge-tree 因此回報 conflict（E2 fail closed）、tip 也不是祖先（E1 不成立）。
        只有綁 SHA 的 PR 證據能救回這種常見情況。
        """
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-drift", env=env_setup)
        tip = _commit(repo, env_setup, "drift.txt", "v1\n", "v1")
        _git(repo, "checkout", "-q", "main", env=env_setup)
        _git(repo, "merge", "--squash", "feat-drift", env=env_setup)
        _git(repo, "commit", "-qm", "squash drift", env=env_setup)
        _commit(repo, env_setup, "drift.txt", "v2\n", "main moved on")
        _git(repo, "push", "-q", "origin", "main", env=env_setup)

        # 先確認 E1/E2 真的不成立，否則這個測試沒在測 E3
        no_gh = _env(tmp_path)
        r0 = _run(repo, no_gh)
        assert "feat-drift" not in _section(r0.stdout, "SAFE"), (
            f"fixture 失效：E1/E2 已判為 SAFE，本測試無法證明 E3 的作用:\n{r0.stdout}"
        )

        tsv = _gh_tsv(tmp_path, ("feat-drift", tip, "MERGED", "main"))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env)

        assert "feat-drift" in _section(r.stdout, "SAFE"), r.stdout
        assert "headRefOid" in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_007_merged_pr_into_other_base_is_not_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-007: PR 合併進的是別的 base（非 main）-> 不算內容已進 main。"""
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-otherbase", env=env_setup)
        tip = _commit(repo, env_setup, "x.txt", "x\n", "x")
        _git(repo, "checkout", "-q", "main", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-otherbase", tip, "MERGED", "develop"))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env)

        assert "feat-otherbase" not in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_008_open_pr_is_kept(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-008: open PR 的分支 -> KEEP，即使內容已在 main。"""
        env_setup = _env(tmp_path)
        _git(repo, "branch", "feat-open", "HEAD", env=env_setup)
        tip = _git(repo, "rev-parse", "feat-open", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-open", tip, "OPEN", "main"))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env, "--apply")

        assert "feat-open" in _section(r.stdout, "KEEP"), r.stdout
        assert "feat-open" in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_eg_004_gh_failure_degrades_to_git_evidence(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-004: gh 失敗 -> [WARN] 並降級用 git 證據，不得把失敗讀成「無 open PR 可刪」。"""
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-ghfail", env=env_setup)
        _commit(repo, env_setup, "n.txt", "n\n", "n")
        _git(repo, "checkout", "-q", "main", env=env_setup)

        env = _env(tmp_path, FAKE_GH_FAIL="1")
        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "[WARN]" in r.stderr
        assert "feat-ghfail" not in _section(r.stdout, "SAFE"), r.stdout


class TestCleanWtCallerSafety:
    def test_cwt_eg_005_never_removes_the_callers_own_worktree(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-005: 絕不刪除呼叫端所在的 worktree／分支，即使它符合 SAFE 條件。

        迴歸測試（前一版實測重現：呼叫者的 cwd 執行後消失）。pr-cycle-fast Step 8 正是在
        剛合併完的 worktree 裡、同一個 session 內呼叫本腳本，而該 worktree 此刻剛好 SAFE。
        """
        env = _env(tmp_path)
        wt = tmp_path / "caller-wt"
        # 分支停在 main 的 commit 上 -> 內容已在 main -> 符合 SAFE 條件
        _git(repo, "worktree", "add", "-q", "-b", "caller-branch", str(wt), "HEAD", env=env)

        r = _run(repo, env, "--apply", cwd=wt)

        assert wt.is_dir(), f"呼叫端的 worktree 目錄被刪了:\n{r.stdout}\n{r.stderr}"
        assert "caller-branch" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"呼叫端所在分支被刪了:\n{r.stdout}"
        )
        assert "caller-branch" in _section(r.stdout, "KEEP"), r.stdout


class TestCleanWtApplyGates:
    def test_cwt_eg_006_apply_aborts_when_fetch_fails(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-006: --apply 時 fetch 失敗必須致命，不可拿過期的 origin/main 當刪除依據。

        遠端 history 變動後，過期的 ref 可能「證明」其實還沒合併的工作已經合併。
        """
        env = _env(tmp_path)
        _git(repo, "branch", "victim", "HEAD", env=env)
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"), env=env)

        r = _run(repo, env, "--apply")

        assert r.returncode == 1, f"fetch 失敗時 --apply 必須 exit 1:\n{r.stdout}\n{r.stderr}"
        assert "[FAIL]" in r.stderr
        assert "victim" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            "fetch 失敗後不得刪任何東西"
        )

    def test_cwt_eg_007_report_mode_tolerates_fetch_failure(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-007: 報告模式下 fetch 失敗只 [WARN]（只是看，不刪東西）。"""
        env = _env(tmp_path)
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"), env=env)

        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "[WARN]" in r.stderr

    def test_cwt_eg_008_apply_exits_nonzero_when_deletion_fails(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-008: 刪除失敗時 --apply 必須 exit 1，不得印成功後 exit 0。

        前一版的刪除迴圈跑在 pipeline 的 subshell 裡，失敗旗標傳不回主 shell，
        於是任何失敗都被吞掉。locked worktree 是最容易觸發的真實情境。
        """
        env = _env(tmp_path)
        wt = tmp_path / "locked-wt"
        _git(repo, "worktree", "add", "-q", "-b", "locked-branch", str(wt), "HEAD", env=env)
        _git(repo, "worktree", "lock", str(wt), env=env)

        r = _run(repo, env, "--apply")

        assert r.returncode == 1, f"刪除失敗必須 exit 1:\n{r.stdout}\n{r.stderr}"
        assert "locked-branch" in _git(repo, "branch", "--format=%(refname:short)", env=env)


class TestCleanWtPortRelease:
    def test_cwt_st_003_apply_releases_port_registrations(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-003: --apply 刪分支前會釋放該分支的 port 登記。

        /newjob Step 2c 用 branch name 當 project key 登記 host port；刪分支卻不 release，
        登記就永久洩漏，下一個 worktree 被推去用更高的 port，無限累積。
        """
        env_base = _env(tmp_path)
        _git(repo, "branch", "ported-branch", "HEAD", env=env_base)
        # PM_AVAILABLE 需要 repo 裡有這個 module
        (repo / "tasks" / "local_port_manager").mkdir(parents=True)
        uv_log = tmp_path / "uv.log"
        uv_log.write_text("", encoding="utf-8")
        _mkstub(tmp_path / "stubbin", "uv", _UV_STUB)
        env = _env(
            tmp_path,
            FAKE_UV_LOG=str(uv_log),
            FAKE_UV_PROJECT="ported-branch",
        )

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        calls = uv_log.read_text(encoding="utf-8")
        assert "release ported-branch postgres" in calls, f"postgres 未被釋放:\n{calls}"
        assert "release ported-branch redis" in calls, f"redis 未被釋放:\n{calls}"
        assert "ported-branch" not in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_eg_009_port_release_failure_does_not_block_deletion(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-009: port registry 讀不到時 [WARN] 但仍完成刪除（port 清理是收尾，不是閘門）。"""
        env_base = _env(tmp_path)
        _git(repo, "branch", "noport-branch", "HEAD", env=env_base)
        (repo / "tasks" / "local_port_manager").mkdir(parents=True)
        # 沒有 uv stub -> command -v uv 找不到（或找到真 uv 但 repo 無此 module）-> 安靜跳過
        env = _env(tmp_path)

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "noport-branch" not in _git(repo, "branch", "--format=%(refname:short)", env=env)


class TestCleanWtArgs:
    @pytest.mark.parametrize("bad", ["abc", "-1", ""])
    def test_cwt_vl_001_rejects_non_numeric_stale_days(
        self, repo: Path, tmp_path: Path, bad: str
    ) -> None:
        """CWT-VL-001: --stale-days 非數值時 fail loud，不得靜默採用預設。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--stale-days", bad)
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr

    def test_cwt_vl_002_rejects_stale_days_without_value(self, repo: Path, tmp_path: Path) -> None:
        """CWT-VL-002: --stale-days 漏傳值時給 clean [FAIL]，不得因 set -u 噴 stacktrace。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--stale-days")
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr
        assert "unbound variable" not in r.stderr

    def test_cwt_vl_003_rejects_unknown_flag(self, repo: Path, tmp_path: Path) -> None:
        """CWT-VL-003: 未知參數必須 fail，不可被當成 no-op 忽略。"""
        env = _env(tmp_path)
        r = _run(repo, env, "--force")
        assert r.returncode == 1
        assert "[FAIL]" in r.stderr
