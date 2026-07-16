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


def _gh_tsv(tmp_path: Path, *rows: tuple[str, str, str, str, str]) -> str:
    """寫一個 gh stub 要吐的 TSV 檔，回傳路徑。

    row = (headRefName, headRefOid, state, baseRefName, mergeCommitOid)。
    欄位順序與 clean_wt.sh 的 `gh pr list --json ... -q '... | @tsv'` 一致；
    該 jq 運算式與欄位名已對真實 gh 實測驗證（見模組 docstring）。
    """
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

    def test_cwt_eg_003_never_deletes_base_branch_when_not_checked_out(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-003: 主 repo checkout 在別的分支時，base 分支（main）仍不得被刪。

        舊版此測試是**假測試**：它在 main 被 checkout 的狀態下斷言 `main in branches`，
        而那是 git 本身保證的（不能 branch -D 目前 checkout 的分支）。於是
        MAIN_BRANCH_CHECKED_OUT 守衛遮蔽了 BASE_BRANCH 守衛，後者從未被執行——
        突變測試證實：刪掉 BASE_BRANCH 那一行，25/25 仍全綠。

        本版把主 repo checkout 到別的分支，讓 BASE_BRANCH 守衛成為唯一擋下 main 的東西。
        這不是假想情境：實測時本 repo 的主 repo 正 checkout 在 nightly-agent/... 分支上。
        """
        env = _env(tmp_path)
        # 主 repo 離開 main -> main 不再受 git 自身保護，且內容當然「已在 origin/main」
        _git(repo, "checkout", "-qb", "some-other-branch", env=env)

        r = _run(repo, env, "--apply")

        branches = _git(repo, "branch", "--format=%(refname:short)", env=env)
        assert "main" in branches.split(), f"base 分支不得被刪:\n{r.stdout}\n{r.stderr}"
        # 不能直接找 "main" 子字串：區塊標題本身就含 "origin/main"（rule 09 斷言語意精確性）。
        # 改為逐行比對「條目行」——條目的格式是縮排 + 分支名 + 兩個空白。
        safe_entries = [
            ln.strip().split("  ")[0]
            for ln in _section(r.stdout, "SAFE").splitlines()
            if ln.startswith("  ") and ln.strip() and not ln.strip().startswith("(")
        ]
        assert "main" not in safe_entries, (
            f"base 分支不得出現在 SAFE 清單，實際條目={safe_entries}:\n{r.stdout}"
        )

    def test_cwt_eg_011_untracked_file_blocks_even_with_showuntrackedfiles_no(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-011: status.showUntrackedFiles=no 時，普通 untracked 檔案仍須 BLOCKED。

        迴歸測試（實測會遺失檔案）：該設定會讓 untracked 檔案從 `git status --porcelain`
        消失，而 `git worktree remove` 也不會拒絕（兩層問的是同一個被蒙蔽的 status）。
        腳本因此一律傳 --untracked-files=all 覆寫它。
        這種檔案不是任何東西的副本，也不可重生 -> 刪了就是永久遺失。
        """
        env = _env(tmp_path)
        wt = tmp_path / "wt-uno"
        _git(repo, "worktree", "add", "-q", "-b", "hidden-work", str(wt), "HEAD", env=env)
        _git(wt, "config", "status.showUntrackedFiles", "no", env=env)
        (wt / "notes.txt").write_text("IRREPLACEABLE\n", encoding="utf-8")

        # fixture 自我驗證：預設 status 真的看不到它，否則沒在測這個 vector
        blind = _git(wt, "status", "--porcelain", env=env)
        assert blind == "", f"fixture 失效：status 仍看得到 untracked 檔案:\n{blind}"

        r = _run(repo, env, "--apply")

        assert "hidden-work" in _section(r.stdout, "BLOCKED"), (
            f"showUntrackedFiles=no 不得讓 untracked 檔案隱形:\n{r.stdout}"
        )
        assert (wt / "notes.txt").is_file(), "未追蹤的手寫檔案被刪除了"

    def test_cwt_eg_016_registered_but_missing_worktree_path_is_blocked(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-016: worktree 已註冊但路徑不存在 -> BLOCKED（缺少證據，不是「乾淨」）。

        舊版的閘門是 `[ -n "$wt_path" ] && [ -d "$wt_path" ]`：路徑不可讀時整段被**跳過**，
        於是「無法判斷髒不髒」被當成「沒有 worktree，所以乾淨」，違反腳本自己宣告的不變量。
        且 `git worktree remove` 對 prunable 的項目會成功（只是 prune），於是 `--apply` 會
        印出 `[OK] worktree 已移除` —— 對一個它從未檢查過的目錄。

        真實觸發情境：worktree 目錄被搬走、外接碟未掛載、或被 rm -rf 但沒 prune。
        """
        env = _env(tmp_path)
        wt = tmp_path / "wt-vanished"
        _git(repo, "worktree", "add", "-q", "-b", "vanished-branch", str(wt), "HEAD", env=env)
        # 把目錄搬走（模擬未掛載／被移動），但保留主 repo 的註冊
        wt.rename(tmp_path / "wt-moved-away")

        # fixture 自我驗證：git 仍認為它是註冊中的 worktree
        wt_list = _git(repo, "worktree", "list", "--porcelain", env=env)
        assert "vanished-branch" in wt_list, f"fixture 失效：worktree 註冊已消失:\n{wt_list}"

        r = _run(repo, env, "--apply")

        assert "vanished-branch" in _section(r.stdout, "BLOCKED"), (
            f"路徑不可讀的 worktree 必須 BLOCKED，不可視為乾淨:\n{r.stdout}"
        )
        assert "vanished-branch" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"無法確認內容的分支不得被刪:\n{r.stdout}\n{r.stderr}"
        )

    def test_cwt_eg_017_unreadable_worktree_status_is_blocked(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-017: worktree 路徑存在但 status 讀不出來 -> BLOCKED（fail closed）。

        與 EG-016 是**不同的**防線，兩者互為後盾（突變測試證實：只測其中一個時，另一個的
        突變會存活，因為 fixture 根本走不到它）：
          - EG-016：路徑不存在 -> `-d` 檢查擋下（inspect_worktree 根本沒被呼叫）
          - EG-017（本測試）：路徑存在但 `git status` 失敗 -> inspect_worktree 的
            `return 1` 擋下。真實情境：權限問題、檔案系統錯誤、repo 損毀。

        「無法判斷髒不髒」必須等於 BLOCKED，不能等於「乾淨」。
        """
        env = _env(tmp_path)
        wt = tmp_path / "wt-unreadable"
        _git(repo, "worktree", "add", "-q", "-b", "unreadable-branch", str(wt), "HEAD", env=env)
        # 目錄仍在（-d 通過），但把 .git 檔換成垃圾 -> git status 失敗
        (wt / ".git").write_text("this is not a valid gitfile\n", encoding="utf-8")

        # fixture 自我驗證：路徑存在，且 status 真的失敗（否則測到的不是這條路）
        assert wt.is_dir(), "fixture 失效：路徑必須存在才會走到 inspect_worktree"
        probe = subprocess.run(  # nosec B603
            ["git", "-C", str(wt), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            check=False,
            env=env,
        )
        assert probe.returncode != 0, f"fixture 失效：status 沒有失敗:\n{probe.stderr.decode()}"

        r = _run(repo, env, "--apply")

        assert "unreadable-branch" in _section(r.stdout, "BLOCKED"), (
            f"status 讀不出來必須 BLOCKED，不可視為乾淨:\n{r.stdout}"
        )
        assert "unreadable-branch" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"無法確認內容的分支不得被刪:\n{r.stdout}\n{r.stderr}"
        )

    def test_cwt_st_004_removes_clean_worktree_and_branch(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-004: 乾淨且非呼叫端的 worktree -> --apply 應移除目錄並刪除分支。

        這是本工具的招牌路徑，先前完全沒有覆蓋（突變成 no-op 後 25/25 仍全綠）。
        """
        env = _env(tmp_path)
        wt = tmp_path / "wt-clean"
        _git(repo, "worktree", "add", "-q", "-b", "clean-wt-branch", str(wt), "HEAD", env=env)

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert not wt.exists(), f"worktree 目錄應被移除:\n{r.stdout}"
        assert "clean-wt-branch" not in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_eg_012_gitignored_files_do_not_block(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-012: worktree 的 gitignored 檔案**不**阻擋刪除（刻意的設計）。

        worktree 裡的 gitignored 內容全是衍生物：`.env` / `.runtime/` 由 /newjob Step 2b
        從主 repo `cp` 進來（正本留在主 repo，本腳本從不碰主 repo），`.venv/`、
        `__pycache__/` 可重生。擋下它們會讓每個 worktree 都卡在 BLOCKED（實測：本 repo
        每個 worktree 有 37~42 個 gitignored 項目，約 95% 是快取），使用者只好每次都加
        override，於是守衛形同虛設。

        本測試釘住這個決定：若有人日後加回 gitignored 閘門，它會變紅並讀到這段理由。
        """
        env = _env(tmp_path)
        (repo / ".gitignore").write_text(".env\n.venv/\n", encoding="utf-8")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-qm", "add gitignore", env=env)
        _git(repo, "push", "-q", "origin", "main", env=env)

        wt = tmp_path / "wt-ign"
        _git(repo, "worktree", "add", "-q", "-b", "ign-branch", str(wt), "HEAD", env=env)
        (wt / ".env").write_text("COPIED_FROM_MAIN_REPO=1\n", encoding="utf-8")
        (wt / ".venv").mkdir()
        (wt / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")

        # fixture 自我驗證：這些檔案真的被 gitignore（否則測到的是別的東西）
        assert _git(wt, "check-ignore", ".env", env=env) == ".env"

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "ign-branch" not in _section(r.stdout, "BLOCKED"), (
            f"gitignored 檔案不應阻擋（見腳本檔頭理由）:\n{r.stdout}"
        )
        assert "ign-branch" not in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_st_005_stale_marker_respects_threshold(self, repo: Path, tmp_path: Path) -> None:
        """CWT-ST-005: --stale-days 的**有效**路徑：門檻決定 [STALE] 標記出現與否。

        先前只測了拒絕非法值，有效路徑零覆蓋（`-ge` 突變成 `-lt` 後仍全綠）。
        """
        env = _env(tmp_path)
        old = {
            **env,
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
        }
        _git(repo, "checkout", "-qb", "ancient", env=env)
        (repo / "old.txt").write_text("old\n", encoding="utf-8")
        _git(repo, "add", "-A", env=old)
        _git(repo, "commit", "-qm", "ancient work", env=old)
        _git(repo, "checkout", "-q", "main", env=env)

        r_low = _run(repo, env, "--stale-days", "1")
        assert "[STALE]" in _section(r_low.stdout, "REVIEW"), (
            f"門檻 1 天時，2020 年的分支必須標記 [STALE]:\n{r_low.stdout}"
        )

        r_high = _run(repo, env, "--stale-days", "99999")
        assert "[STALE]" not in _section(r_high.stdout, "REVIEW"), (
            f"門檻 99999 天時不得標記 [STALE]:\n{r_high.stdout}"
        )


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

        mc = _git(repo, "rev-parse", "main", env=env_setup)
        tsv = _gh_tsv(tmp_path, ("feat-advanced", merged_sha, "MERGED", "main", mc))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)

        r = _run(repo, env, "--apply")

        assert "feat-advanced" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"PR MERGED 但本地 tip 已前進，分支不得被刪:\n{r.stdout}\n{r.stderr}"
        )
        assert "feat-advanced" not in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_006_e3_rescues_squash_then_drift(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-006: E1/E2 都不成立，但 PR 的 merge commit 仍在 base 歷史中 -> SAFE。

        這是 E3 存在的**唯一**理由，也是它在真實 repo 的實際收益：
        分支 squash 合併後 main 又改到同一個檔案 -> merge-tree 回報 conflict（E2 fail
        closed）、tip 也不是祖先（E1 不成立）。實測（PR #239，2026-07-16）：本 repo 4 個
        已合併分支中有 1 個（worktree-fix-232 / PR #234）正是這個形狀。

        fixture 自我驗證：先在無 gh 的情況下跑一次，確認 E1/E2 真的不成立，
        否則這個測試根本沒在測 E3（會因為錯的理由變綠）。
        """
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-drift", env=env_setup)
        tip = _commit(repo, env_setup, "drift.txt", "v1\n", "v1")
        _git(repo, "checkout", "-q", "main", env=env_setup)
        _git(repo, "merge", "--squash", "feat-drift", env=env_setup)
        _git(repo, "commit", "-qm", "squash drift", env=env_setup)
        merge_commit = _git(repo, "rev-parse", "HEAD", env=env_setup)
        _commit(repo, env_setup, "drift.txt", "v2\n", "main moved on")
        _git(repo, "push", "-q", "origin", "main", env=env_setup)

        no_gh = _env(tmp_path)
        r0 = _run(repo, no_gh)
        assert "feat-drift" not in _section(r0.stdout, "SAFE"), (
            f"fixture 失效：E1/E2 已判為 SAFE，本測試無法證明 E3 的作用:\n{r0.stdout}"
        )

        tsv = _gh_tsv(tmp_path, ("feat-drift", tip, "MERGED", "main", merge_commit))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env)

        assert "feat-drift" in _section(r.stdout, "SAFE"), r.stdout
        assert "merge commit" in _section(r.stdout, "SAFE"), (
            f"SAFE 理由必須指明是靠 E3 判定的:\n{r.stdout}"
        )

    def test_cwt_dt_009_e3_refuses_when_base_history_rewritten(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-009: PR 說已合併，但 merge commit 已不在 base 歷史中 -> 絕不可 SAFE。

        這是保留 E3 的**代價**，也是強化版必須擋下的情境（否則 E3 就該被移除）：
        PR 紀錄講的是過去發生過的事。base 被改寫（force push / rebase）後，squash commit
        可能已不在歷史裡——內容其實已經不見，而 PR 上仍寫著 MERGED。
        舊版只憑 state+headRefOid 就判 SAFE -> 刪除 -> 永久遺失。

        fixture 自我驗證：先斷言 merge commit 真的不再是 origin/main 的祖先。
        """
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-rewritten", env=env_setup)
        tip = _commit(repo, env_setup, "gone.txt", "v1\n", "v1")
        _git(repo, "checkout", "-q", "main", env=env_setup)
        _git(repo, "merge", "--squash", "feat-rewritten", env=env_setup)
        _git(repo, "commit", "-qm", "squash", env=env_setup)
        merge_commit = _git(repo, "rev-parse", "HEAD", env=env_setup)
        _git(repo, "push", "-q", "origin", "main", env=env_setup)

        # 改寫 main 的歷史：丟掉那個 squash commit，改成一段不含該內容的歷史
        _git(repo, "reset", "-q", "--hard", "HEAD~1", env=env_setup)
        _commit(repo, env_setup, "other.txt", "unrelated\n", "rewritten history")
        _git(repo, "push", "-q", "-f", "origin", "main", env=env_setup)
        _git(repo, "fetch", "-q", "origin", env=env_setup)

        # fixture 自我驗證：內容真的已經不在 origin/main 裡
        anc = subprocess.run(  # nosec B603
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", merge_commit, "origin/main"],
            capture_output=True,
            check=False,
            env=env_setup,
        )
        assert anc.returncode != 0, "fixture 失效：merge commit 仍是 origin/main 的祖先"

        tsv = _gh_tsv(tmp_path, ("feat-rewritten", tip, "MERGED", "main", merge_commit))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env, "--apply")

        assert "feat-rewritten" not in _section(r.stdout, "SAFE"), (
            f"base 歷史被改寫後 E3 必須拒絕:\n{r.stdout}"
        )
        assert "feat-rewritten" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"內容已不在 base，分支不得被刪:\n{r.stdout}\n{r.stderr}"
        )

    def test_cwt_dt_010_e3_refuses_when_merge_commit_missing(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-010: PR 沒有 mergeCommit（欄位為空）-> E3 不成立，不得 SAFE。

        gh 對某些 PR 可能回傳空的 mergeCommit。空值不可被當成「通過」。
        """
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-nomc", env=env_setup)
        tip = _commit(repo, env_setup, "d.txt", "v1\n", "v1")
        _git(repo, "checkout", "-q", "main", env=env_setup)
        _git(repo, "merge", "--squash", "feat-nomc", env=env_setup)
        _git(repo, "commit", "-qm", "squash", env=env_setup)
        _commit(repo, env_setup, "d.txt", "v2\n", "main moved on")
        _git(repo, "push", "-q", "origin", "main", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-nomc", tip, "MERGED", "main", ""))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env)

        assert "feat-nomc" not in _section(r.stdout, "SAFE"), (
            f"mergeCommit 為空時 E3 不得成立:\n{r.stdout}"
        )

    def test_cwt_dt_007_merged_pr_into_other_base_is_not_safe(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-DT-007: PR 合併進的是別的 base（非 main）-> 不算內容已進 main。"""
        env_setup = _env(tmp_path)
        _git(repo, "checkout", "-qb", "feat-otherbase", env=env_setup)
        tip = _commit(repo, env_setup, "x.txt", "x\n", "x")
        _git(repo, "checkout", "-q", "main", env=env_setup)
        mc = _git(repo, "rev-parse", "main", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-otherbase", tip, "MERGED", "develop", mc))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env)

        assert "feat-otherbase" not in _section(r.stdout, "SAFE"), r.stdout

    def test_cwt_dt_008_open_pr_is_kept(self, repo: Path, tmp_path: Path) -> None:
        """CWT-DT-008: open PR 的分支 -> KEEP，即使內容已在 main。"""
        env_setup = _env(tmp_path)
        _git(repo, "branch", "feat-open", "HEAD", env=env_setup)
        tip = _git(repo, "rev-parse", "feat-open", env=env_setup)

        tsv = _gh_tsv(tmp_path, ("feat-open", tip, "OPEN", "main", ""))
        env = _env(tmp_path, FAKE_GH_TSV=tsv)
        r = _run(repo, env, "--apply")

        assert "feat-open" in _section(r.stdout, "KEEP"), r.stdout
        assert "feat-open" in _git(repo, "branch", "--format=%(refname:short)", env=env)

    def test_cwt_eg_004_gh_failure_is_fatal_under_apply(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-004: gh 失敗時 --apply 必須致命，不得把失敗讀成「沒有 open PR」。

        迴歸測試（實測會誤刪）：舊版 has_open_pr 在 HAS_GH=0 時回 false，於是「gh 掛掉」
        被讀成「這個分支沒有 open PR」——內容已在 main 的 open-PR 分支照樣被刪，exit 0。
        與 fetch 閘門同一套推理：--apply 會刪東西，證據／政策來源不可用就不刪。

        fixture 刻意讓分支**內容已在 main**（E1 成立），所以唯一擋下它的只有 gh 閘門；
        否則測試會因為錯的理由變綠。
        """
        env_setup = _env(tmp_path)
        _git(repo, "branch", "has-open-pr", "HEAD", env=env_setup)

        env = _env(tmp_path, FAKE_GH_FAIL="1")
        r = _run(repo, env, "--apply")

        assert r.returncode == 1, f"gh 失敗時 --apply 必須 exit 1:\n{r.stdout}\n{r.stderr}"
        assert "gh 不可用" in r.stderr, r.stderr
        assert "has-open-pr" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"gh 失敗後不得刪任何東西:\n{r.stdout}\n{r.stderr}"
        )

    def test_cwt_eg_010_gh_failure_in_report_mode_warns_only(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-010: 報告模式下 gh 失敗只 [WARN]（只是看，不刪東西）。"""
        env_setup = _env(tmp_path)
        _git(repo, "branch", "some-branch", "HEAD", env=env_setup)

        env = _env(tmp_path, FAKE_GH_FAIL="1")
        r = _run(repo, env)

        assert r.returncode == 0, r.stderr
        assert "gh 不可用" in r.stderr, r.stderr


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


class TestCleanWtDeleteRace:
    def test_cwt_eg_013_refuses_to_delete_a_branch_that_advanced_after_classification(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-013: 分類後分支又長出新 commit -> 刪除必須被拒絕（compare-and-swap）。

        迴歸測試（實測會遺失 commit）：`git branch -D` 只認**名字**、不驗 SHA，所以分類到
        刪除之間（中間隔著 port 清理的 uv 子行程，每個約 1 秒）併發寫入的 commit 會被一起
        強制刪掉。本 repo 會跨 worktree 跑平行 background session，窗口是真的。
        改用 `git update-ref -d <ref> <expected_tip>` 後，ref 移動過就會被 git 拒絕。

        注入點：用 uv stub 在 port 清理階段推進分支，精準模擬那個窗口。
        """
        env_base = _env(tmp_path)
        _git(repo, "branch", "racy-branch", "HEAD", env=env_base)  # 內容已在 main -> SAFE
        (repo / "tasks" / "local_port_manager").mkdir(parents=True)

        # uv stub：被呼叫時（port 清理階段）在 racy-branch 上補一個新 commit
        race_marker = tmp_path / "raced"
        uv_stub = f"""#!/usr/bin/env bash
if [ ! -f "{race_marker}" ]; then
  : > "{race_marker}"
  git -C "{repo}" branch -f racy-branch "$(git -C "{repo}" commit-tree \\
      "$(git -C "{repo}" rev-parse main^{{tree}})" -p racy-branch -m "concurrent work")"
fi
echo "project          service      category   port     note"
echo "--------------------------------------------------------"
echo "racy-branch      postgres     db         5433"
exit 0
"""
        _mkstub(tmp_path / "stubbin", "uv", uv_stub)
        env = _env(tmp_path)

        before = _git(repo, "rev-parse", "racy-branch", env=env)
        r = _run(repo, env, "--apply")
        after = _git(repo, "rev-parse", "racy-branch", env=env)

        assert race_marker.is_file(), "fixture 失效：uv stub 沒被呼叫，競態沒被注入"
        assert before != after, "fixture 失效：分支沒有在分類後前進"
        assert "racy-branch" in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"分類後前進的分支不得被刪（CAS 應拒絕）:\n{r.stdout}\n{r.stderr}"
        )
        assert r.returncode == 1, f"刪除被拒必須 exit 1:\n{r.stdout}\n{r.stderr}"


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

    def test_cwt_eg_009_port_registry_read_failure_warns_and_still_deletes(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-009: port registry 讀不到時發出 [WARN]，但仍完成刪除（清理是收尾，不是閘門）。

        舊版是**假測試**：docstring 承諾 [WARN] 卻從未斷言它（把 WARN 拿掉，25/25 仍全綠），
        且註解宣稱走的是「uv 不存在 -> 安靜跳過」那條路——實際上本機的 PATH 有真的 uv，
        走的是 WARN 那條路，於是它在不同機器上測到不同東西，而兩邊都 pass。
        本版用會失敗的 uv stub 固定路徑，並斷言語意唯一的字串（rule 09）。
        """
        env_base = _env(tmp_path)
        _git(repo, "branch", "noport-branch", "HEAD", env=env_base)
        (repo / "tasks" / "local_port_manager").mkdir(parents=True)
        _mkstub(tmp_path / "stubbin", "uv", "#!/usr/bin/env bash\nexit 1\n")
        env = _env(tmp_path)

        r = _run(repo, env, "--apply")

        assert "讀取 port registry 失敗" in r.stderr, (
            f"registry 讀取失敗必須發出具體的 [WARN]:\n{r.stderr}"
        )
        assert "noport-branch" not in _git(repo, "branch", "--format=%(refname:short)", env=env), (
            f"port 清理失敗不得阻擋刪除:\n{r.stdout}\n{r.stderr}"
        )
        assert r.returncode == 1, "port 清理失敗屬於部分失敗，應反映在 exit code"

    def test_cwt_eg_014_module_present_but_uv_missing_warns(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """CWT-EG-014: module 在但 uv 不在 -> [WARN]，不可與「別的 repo 沒這個 module」共用沉默。

        fail-open 必須逐一列出它寬恕的條件（rule 11）：「別的 repo 沒有 local_port_manager」
        是正常狀態（安靜跳過），但「本 repo 有 module 卻沒有 uv」是錯誤狀態，會讓 port 登記
        永久洩漏，必須出聲。
        """
        env_base = _env(tmp_path)
        _git(repo, "branch", "nouv-branch", "HEAD", env=env_base)
        (repo / "tasks" / "local_port_manager").mkdir(parents=True)

        # PATH 只留 stub 目錄 + 系統基本路徑，且不提供 uv -> command -v uv 找不到
        env = _env(tmp_path)
        env["PATH"] = f"{tmp_path / 'stubbin'}:/usr/bin:/bin:/usr/sbin:/sbin"

        r = _run(repo, env, "--apply")

        assert "uv 不存在" in r.stderr, f"module 在但 uv 不在時必須 [WARN]:\n{r.stderr}"

    def test_cwt_eg_015_no_port_module_is_silent(self, repo: Path, tmp_path: Path) -> None:
        """CWT-EG-015: repo 沒有 local_port_manager -> 安靜跳過（別的專案的正常狀態）。"""
        env = _env(tmp_path)
        _git(repo, "branch", "otherrepo-branch", "HEAD", env=env)
        # 刻意不建立 tasks/local_port_manager

        r = _run(repo, env, "--apply")

        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "uv 不存在" not in r.stderr, f"沒有 module 時不該抱怨 uv:\n{r.stderr}"
        assert "port" not in r.stderr.lower(), f"沒有 module 時不該提及 port:\n{r.stderr}"


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
