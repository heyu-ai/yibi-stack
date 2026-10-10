"""last-human-activity.sh 的契約與行為測試（change: add-issue-triage-staleness-review）。

issue 的「最後一次實質人為活動」是過期分層的輸入。它必須排除 bot 與 skill 自己貼的留言，
否則 stale bot 或這個 skill 的每次盤點都會重置時鐘，過期檢視等於失效。

bot 判定必須用 GitHub 的帳號型別（REST 的 user.type 為 Bot），不能看 login 文字：
實測 gh issue list 的 JSON 會去掉 [bot] 後綴（github-actions[bot] 顯示為 github-actions），
Copilot 這類 bot 更是本來就沒有後綴。所以腳本走 REST，並在這裡以真實形狀的 JSON 回放。

假的 gh 只認三種呼叫形式（也是腳本對外的契約，靜態測試會確認腳本沒有偏離）：

    gh api user
    gh api repos/{owner}/{repo}/issues/<n>
    gh api repos/{owner}/{repo}/issues/<n>/comments --paginate

Exit code 契約（與 last-human-activity.sh 檔頭一致）：

    0  成功
    1  腳本自身的未預期錯誤
    2  參數錯誤（缺 issue 編號或不是正整數）
    3  gh API 呼叫失敗（user、issue、comments 任一個）
    4  缺 jq，或 API 回應無法解析
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
LAST_HUMAN_ACTIVITY = SCRIPTS_DIR / "last-human-activity.sh"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_GH_FAILED = 3
EXIT_BAD_RESPONSE = 4

ISSUE_CREATED = "2026-01-01T00:00:00Z"
VIEWER = "howie"

STALE_MARKER = "<!-- issue-triage:stale-notice 2026-09-01 -->"
CLOSE_MARKER = "<!-- issue-triage:close 2026-09-01 -->"

FAKE_GH = """#!/usr/bin/env bash
# 假的 gh：只認 `api user`、`api repos/{owner}/{repo}/issues/<n>`、
# `api repos/{owner}/{repo}/issues/<n>/comments --paginate` 三種呼叫
args="$*"
case "$args" in
  "api user")
    if [ "${FAKE_GH_FAIL:-}" = "user" ]; then echo "gh: simulated user failure" >&2; exit 1; fi
    printf '{"login":"%s"}\\n' "${FAKE_GH_VIEWER}"
    ;;
  "api repos/{owner}/{repo}/issues/"*"/comments --paginate")
    if [ "${FAKE_GH_FAIL:-}" = "comments" ]; then
      echo "gh: simulated comments failure" >&2
      exit 1
    fi
    cat "${FAKE_GH_COMMENTS_FILE}"
    ;;
  "api repos/{owner}/{repo}/issues/"*)
    if [ "${FAKE_GH_FAIL:-}" = "issue" ]; then echo "gh: simulated issue failure" >&2; exit 1; fi
    printf '{"created_at":"%s"}\\n' "${FAKE_GH_ISSUE_CREATED}"
    ;;
  *)
    echo "unexpected gh args: $args" >&2
    exit 99
    ;;
esac
"""

REAL_BASH = shutil.which("bash") or "bash"


_ids = itertools.count(1000)


def _comment(
    login: str | None, user_type: str, created_at: str, body: str = "hello"
) -> dict[str, object]:
    """REST 留言物件的真實形狀（以 cli/cli 實測）；已刪除帳號以 user 為 null 表示。"""
    user = None if login is None else {"login": login, "type": user_type}
    return {"id": next(_ids), "user": user, "created_at": created_at, "body": body}


def _setup(tmp_path: Path, comments_json: str) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    (tmp_path / "comments.json").write_text(comments_json, encoding="utf-8")
    return bindir


def _run(
    tmp_path: Path,
    comments: list[dict[str, object]] | str,
    *args: str,
    path_override: str | None = None,
    **env_overrides: str,
) -> subprocess.CompletedProcess[str]:
    comments_json = comments if isinstance(comments, str) else json.dumps(comments)
    bindir = _setup(tmp_path, comments_json)
    env = {
        **os.environ,
        "PATH": path_override or f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_VIEWER": VIEWER,
        "FAKE_GH_ISSUE_CREATED": ISSUE_CREATED,
        "FAKE_GH_COMMENTS_FILE": str(tmp_path / "comments.json"),
        **env_overrides,
    }
    return subprocess.run(  # nosec B603
        [REAL_BASH, str(LAST_HUMAN_ACTIVITY), *(args or ("42",))],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=env,
    )


def _fields(proc: subprocess.CompletedProcess[str]) -> list[str]:
    assert proc.stdout.endswith("\n"), repr(proc.stdout)
    assert proc.stdout.count("\n") == 1, repr(proc.stdout)
    return proc.stdout.rstrip("\n").split("\t")


class TestStaticContract:
    SRC = LAST_HUMAN_ACTIVITY.read_text(encoding="utf-8") if LAST_HUMAN_ACTIVITY.is_file() else ""

    def test_lh_dt_001_script_exists(self) -> None:
        assert LAST_HUMAN_ACTIVITY.is_file(), f"缺少 {LAST_HUMAN_ACTIVITY}"

    def test_lh_dt_002_header_documents_every_exit_code(self) -> None:
        head = "\n".join(self.SRC.splitlines()[:45])
        for code in ("0", "1", "2", "3", "4"):
            assert re.search(rf"^#\s+{code}\b", head, re.MULTILINE), f"檔頭缺 exit {code}"

    def test_lh_dt_003_diagnostics_go_to_stderr(self) -> None:
        fail_lines = [
            line
            for line in self.SRC.splitlines()
            if "[FAIL]" in line and "echo" in line and not line.lstrip().startswith("#")
        ]
        assert fail_lines, "找不到任何 [FAIL] echo；空迴圈會讓下面的斷言空洞地通過"
        for line in fail_lines:
            assert ">&2" in line, line

    def test_lh_dt_004_bot_is_decided_by_account_type_not_login_text(self) -> None:
        """gh issue list 的 JSON 會去掉 [bot] 後綴，只能靠 REST 的帳號型別。"""
        body = self.SRC.split("set -euo pipefail", 1)[-1]
        assert "user.type" in body, "腳本沒有依帳號型別判定 bot"
        assert "[bot]" not in body, "腳本不得依 login 文字（[bot] 後綴）判定 bot"

    def test_lh_dt_005_uses_only_the_three_documented_gh_calls(self) -> None:
        calls = [
            line.strip()
            for line in self.SRC.splitlines()
            if re.search(r"\bgh\s+api\b", line) and not line.lstrip().startswith("#")
        ]
        assert len(calls) == 3, calls
        joined = "\n".join(calls)
        assert "gh api user" in joined
        assert re.search(r"issues/\$\{ISSUE\}/comments\"?\s+--paginate", joined)
        assert re.search(r"issues/\$\{ISSUE\}\"?(\s|\)|$)", joined)


class TestBehaviour:
    def test_lh_st_001_no_comments_falls_back_to_issue_creation(self, tmp_path: Path) -> None:
        """沒有留言時，最後人為活動就是 issue 建立時間。

        spec: issue-triage-staleness-review#issue-without-comments
        tc: ITA-ST-001
        """
        proc = _run(tmp_path, [])
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == [ISSUE_CREATED, ""]

    def test_lh_st_002_latest_human_comment_wins(self, tmp_path: Path) -> None:
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment("bob", "User", "2026-03-01T00:00:00Z"),
            _comment("carol", "User", "2026-02-15T00:00:00Z"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-03-01T00:00:00Z", ""]

    def test_lh_st_003_bot_with_suffix_does_not_reset_the_clock(self, tmp_path: Path) -> None:
        """github-actions[bot] 這類 type 為 Bot 的留言不重置時鐘。

        spec: issue-triage-staleness-review#bot-comment-does-not-reset-the-clock
        tc: ITA-ST-002
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment("github-actions[bot]", "Bot", "2026-09-30T00:00:00Z"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", ""]

    def test_lh_st_004_bot_without_suffix_is_still_a_bot(self, tmp_path: Path) -> None:
        """Copilot 的 login 本來就沒有 [bot] 後綴，只能靠帳號型別辨識。

        spec: issue-triage-staleness-review#bot-account-without-a-login-suffix
        tc: ITA-ST-003
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment("Copilot", "Bot", "2026-09-30T00:00:00Z"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", ""]

    def test_lh_st_005_login_that_looks_like_a_bot_but_is_a_user_counts(
        self, tmp_path: Path
    ) -> None:
        """反向對照：名字叫 something[bot] 但型別是 User，不能被當成 bot 排除。"""
        comments = [_comment("not-really[bot]", "User", "2026-05-01T00:00:00Z")]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-05-01T00:00:00Z", ""]

    def test_lh_st_006_deleted_author_counts_as_human(self, tmp_path: Path) -> None:
        """已刪除帳號（user 為 null）的留言算人為活動，往較安全的方向失敗。

        spec: issue-triage-staleness-review#deleted-author-counts-as-human
        tc: ITA-ST-004
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment(None, "User", "2026-04-01T00:00:00Z"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-04-01T00:00:00Z", ""]

    def test_lh_st_007_unknown_account_type_counts_as_human(self, tmp_path: Path) -> None:
        """沒見過的帳號型別（例如 Organization）往安全方向失敗：視為人為活動。"""
        comments = [_comment("some-org", "Organization", "2026-06-01T00:00:00Z")]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-06-01T00:00:00Z", ""]

    def test_lh_st_008_skill_comment_from_the_running_account_is_excluded(
        self, tmp_path: Path
    ) -> None:
        """標記加上「作者是目前登入帳號」才是 skill 自己的留言，不重置時鐘。

        spec: issue-triage-staleness-review#triage-comment-does-not-reset-the-clock
        tc: ITA-ST-005
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment(VIEWER, "User", "2026-09-01T00:00:00Z", f"請確認\n{CLOSE_MARKER}"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", ""]

    def test_lh_st_009_marker_pasted_by_another_account_counts_as_activity(
        self, tmp_path: Path
    ) -> None:
        """另一個帳號貼上 triage 標記：該留言算人為活動，不會被隱形。

        spec: issue-triage-staleness-review#pasted-marker-from-another-account-counts-as-activity
        tc: ITA-ST-006
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment("mallory", "User", "2026-09-15T00:00:00Z", f"我也貼一個\n{CLOSE_MARKER}"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-09-15T00:00:00Z", ""]

    def test_lh_st_010_running_accounts_own_comment_without_marker_counts(
        self, tmp_path: Path
    ) -> None:
        """使用者自己手打的留言（沒有標記）是人為活動；排除只靠標記，不靠帳號。"""
        comments = [_comment(VIEWER, "User", "2026-07-01T00:00:00Z", "我手動補充一下")]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-07-01T00:00:00Z", ""]

    def test_lh_st_011_viewer_match_is_case_insensitive(self, tmp_path: Path) -> None:
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment("HOWIE", "User", "2026-09-01T00:00:00Z", CLOSE_MARKER),
        ]
        proc = _run(tmp_path, comments, FAKE_GH_VIEWER="Howie")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", ""]

    def test_lh_st_012_stale_notice_time_is_reported_and_excluded(self, tmp_path: Path) -> None:
        """stale notice 的時間單獨回報（供寬限期判斷），且不計入人為活動。

        spec: issue-triage-staleness-review#grace-period-elapsed-without-response
        tc: ITA-ST-007
        """
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment(VIEWER, "User", "2026-09-01T00:00:00Z", f"仍需要嗎？\n{STALE_MARKER}"),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", "2026-09-01T00:00:00Z"]

    def test_lh_st_013_latest_stale_notice_wins(self, tmp_path: Path) -> None:
        comments = [
            _comment(VIEWER, "User", "2026-05-01T00:00:00Z", STALE_MARKER),
            _comment(VIEWER, "User", "2026-09-01T00:00:00Z", STALE_MARKER),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == [ISSUE_CREATED, "2026-09-01T00:00:00Z"]

    def test_lh_st_014_other_marker_kinds_are_not_a_stale_notice(self, tmp_path: Path) -> None:
        comments = [_comment(VIEWER, "User", "2026-09-01T00:00:00Z", CLOSE_MARKER)]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == [ISSUE_CREATED, ""]

    def test_lh_st_015_stale_notice_marker_from_another_account_is_ignored(
        self, tmp_path: Path
    ) -> None:
        """另一個帳號貼出的 stale notice 標記不被辨識，且該留言算人為活動。

        spec: issue-triage-staleness-review#stale-notice-marker-from-another-account-is-ignored
        tc: ITA-ST-008
        """
        comments = [_comment("mallory", "User", "2026-09-01T00:00:00Z", STALE_MARKER)]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-09-01T00:00:00Z", ""]

    def test_lh_st_016_paginated_output_is_read_as_one_stream(self, tmp_path: Path) -> None:
        """gh api --paginate 會把每一頁的陣列連續輸出，不是一個合併過的陣列。"""
        page1 = json.dumps([_comment("alice", "User", "2026-02-01T00:00:00Z")])
        page2 = json.dumps([_comment("bob", "User", "2026-08-01T00:00:00Z")])
        proc = _run(tmp_path, f"{page1}\n{page2}\n")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-08-01T00:00:00Z", ""]

    def test_lh_st_017_body_missing_or_null_is_tolerated(self, tmp_path: Path) -> None:
        comment = _comment("alice", "User", "2026-03-01T00:00:00Z")
        comment["body"] = None
        proc = _run(tmp_path, [comment])
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-03-01T00:00:00Z", ""]

    def test_lh_st_025_incomplete_marker_prefix_in_prose_is_human_activity(
        self, tmp_path: Path
    ) -> None:
        """自己的留言只是在內文提到標記前綴（沒有日期、沒有結尾）：算人為活動，也不是 notice。

        舊判定只比對前綴，會把這種留言當成 skill 的 notice 並從活動度量隱形。

        spec: issue-triage-staleness-review#incomplete-marker-is-human-activity
        tc: ITA-ST-009
        """
        comments = [
            _comment(
                VIEWER,
                "User",
                "2026-09-20T00:00:00Z",
                "parser token 是 <!-- issue-triage:stale-notice",
            ),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-09-20T00:00:00Z", ""]

    def test_lh_st_026_look_alike_kind_is_not_a_known_marker(self, tmp_path: Path) -> None:
        """`stale-notice-foo` 不是已知的標記種類：不得被當成 stale notice（舊的 \\b 邊界會放行）。

        spec: issue-triage-staleness-review#incomplete-marker-is-human-activity
        tc: ITA-ST-010
        """
        for kind in ("stale-notice-foo", "stale-noticex", "closed", "unknown-kind"):
            marker = f"<!-- issue-triage:{kind} 2026-09-20 -->"
            proc = _run(tmp_path, [_comment(VIEWER, "User", "2026-09-20T00:00:00Z", marker)])
            assert proc.returncode == EXIT_OK, (kind, proc.stderr)
            assert _fields(proc) == ["2026-09-20T00:00:00Z", ""], kind

    def test_lh_st_027_marker_in_the_middle_of_prose_is_human_activity(
        self, tmp_path: Path
    ) -> None:
        """完整標記出現在內文中段、後面還有文字：它不是這則留言的最後一行，算人為活動。

        spec: issue-triage-staleness-review#incomplete-marker-is-human-activity
        tc: ITA-ST-011
        """
        body = f"{STALE_MARKER}\n其實我還想補充一件事"
        proc = _run(tmp_path, [_comment(VIEWER, "User", "2026-09-20T00:00:00Z", body)])
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-09-20T00:00:00Z", ""]

    def test_lh_st_028_marker_without_a_date_is_not_a_marker(self, tmp_path: Path) -> None:
        for marker in (
            "<!-- issue-triage:stale-notice -->",
            "<!-- issue-triage:stale-notice 2026-9-1 -->",
            "<!-- issue-triage:stale-notice 2026-09-20",
        ):
            proc = _run(tmp_path, [_comment(VIEWER, "User", "2026-09-20T00:00:00Z", marker)])
            assert proc.returncode == EXIT_OK, (marker, proc.stderr)
            assert _fields(proc) == ["2026-09-20T00:00:00Z", ""], marker

    def test_lh_st_029_genuine_marker_survives_crlf_and_trailing_blank_lines(
        self, tmp_path: Path
    ) -> None:
        """對照：網頁編輯器存的留言是 CRLF，尾端也可能有空白行；真正的標記仍要被辨識。

        spec: issue-triage-staleness-review#grace-period-elapsed-without-response
        tc: ITA-ST-012
        """
        body = f"仍需要嗎？\r\n{STALE_MARKER}\r\n\r\n  \n"
        comments = [
            _comment("alice", "User", "2026-02-01T00:00:00Z"),
            _comment(VIEWER, "User", "2026-09-01T00:00:00Z", body),
        ]
        proc = _run(tmp_path, comments)
        assert proc.returncode == EXIT_OK, proc.stderr
        assert _fields(proc) == ["2026-02-01T00:00:00Z", "2026-09-01T00:00:00Z"]

    def test_lh_st_030_every_known_marker_kind_is_excluded_when_it_is_the_last_line(
        self, tmp_path: Path
    ) -> None:
        """SKILL.md 的四種標記種類（close、update-scope、merge、stale-notice）都要被辨識。"""
        for kind in ("close", "update-scope", "merge", "stale-notice"):
            marker = f"<!-- issue-triage:{kind} 2026-09-20 -->"
            body = f"內文\n{marker}"
            proc = _run(tmp_path, [_comment(VIEWER, "User", "2026-09-20T00:00:00Z", body)])
            assert proc.returncode == EXIT_OK, (kind, proc.stderr)
            assert _fields(proc)[0] == ISSUE_CREATED, kind

    def test_lh_st_031_marker_must_be_the_whole_last_line(self, tmp_path: Path) -> None:
        """最後一行除了標記還有別的文字（前綴或後綴）：不是標記行，算人為活動。

        spec: issue-triage-staleness-review#incomplete-marker-is-human-activity
        tc: ITA-ST-013
        """
        for line in (f"參考 {STALE_MARKER}", f"{STALE_MARKER} 以上", f"> {STALE_MARKER}"):
            proc = _run(tmp_path, [_comment(VIEWER, "User", "2026-09-20T00:00:00Z", line)])
            assert proc.returncode == EXIT_OK, (line, proc.stderr)
            assert _fields(proc) == ["2026-09-20T00:00:00Z", ""], line


class TestFailures:
    def test_lh_st_018_viewer_lookup_failure_exits_3_without_output(self, tmp_path: Path) -> None:
        """取不到目前帳號時，不得回退成「沒有人是 skill」而把 skill 的留言算成人為活動。

        spec: issue-triage-staleness-review#comment-lookup-fails-for-one-issue
        tc: ITA-EG-009
        """
        proc = _run(
            tmp_path, [_comment("alice", "User", "2026-02-01T00:00:00Z")], FAKE_GH_FAIL="user"
        )
        assert proc.returncode == EXIT_GH_FAILED, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_lh_st_019_comments_failure_exits_3_without_output(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, [], FAKE_GH_FAIL="comments")
        assert proc.returncode == EXIT_GH_FAILED, proc.stdout
        assert proc.stdout == ""

    def test_lh_st_020_issue_failure_exits_3_without_output(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, [], FAKE_GH_FAIL="issue")
        assert proc.returncode == EXIT_GH_FAILED, proc.stdout
        assert proc.stdout == ""

    def test_lh_st_021_unparsable_comments_exit_4_without_output(self, tmp_path: Path) -> None:
        proc = _run(tmp_path, "this is not json")
        assert proc.returncode == EXIT_BAD_RESPONSE, proc.stdout
        assert "[FAIL]" in proc.stderr
        assert proc.stdout == ""

    def test_lh_st_022_missing_jq_exits_4(self, tmp_path: Path) -> None:
        only_fake_gh = tmp_path / "bin"
        _setup(tmp_path, "[]")
        proc = _run(tmp_path, [], path_override=str(only_fake_gh))
        assert proc.returncode == EXIT_BAD_RESPONSE, proc.stdout
        assert "jq" in proc.stderr
        assert proc.stdout == ""

    def test_lh_st_023_missing_issue_number_is_a_usage_error(self, tmp_path: Path) -> None:
        bindir = _setup(tmp_path, "[]")
        proc = subprocess.run(  # nosec B603
            [REAL_BASH, str(LAST_HUMAN_ACTIVITY)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        )
        assert proc.returncode == EXIT_USAGE, proc.stdout
        assert proc.stdout == ""

    def test_lh_st_024_non_numeric_issue_number_is_a_usage_error(self, tmp_path: Path) -> None:
        for bad in ("abc", "4x", "-1", "1/../2", "0", ""):
            proc = _run(tmp_path, [], bad)
            assert proc.returncode == EXIT_USAGE, (bad, proc.stdout)
            assert proc.stdout == "", bad
