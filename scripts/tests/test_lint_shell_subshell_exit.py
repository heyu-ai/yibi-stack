"""lint_shell_subshell_exit.py 的行為測試。

這支 lint 抓的是 PR #234 實際踩到的陷阱：`$()` 是 subshell，裡面的 `exit` 只結束
subshell 不結束腳本，於是呼叫端把「無法判定」當成「沒找到」而靜默放行。

關鍵在於**不是每個 `exit` 都有問題**——判準是三個條件的合取，測試也照這個結構寫：
    exit 在 function 內  ⋀  該 function 被 $() 呼叫  ⋀  呼叫點讓 set -e 不觸發

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINT = REPO_ROOT / "scripts" / "lint_shell_subshell_exit.py"


def _run_lint(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(LINT), str(target)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


class TestLintShellSubshellExit:
    def test_lsse_dt_001_if_guarded_call_is_flagged(self, tmp_path: Path) -> None:
        """LSSE-DT-001: `if X=$(fn)` 包住呼叫時必須報（PR #234 的真實 bug 原貌）。

        if 讓 set -e 不觸發，subshell 的 exit 只殺 subshell，呼叫端落到放行路徑。
        """
        f = _write(
            tmp_path,
            "buggy.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_find() {\n"
            '  if [ "$1" = "deep" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            "  return 1\n"
            "}\n"
            'if BROKEN=$(_find "$DIR"); then\n'
            "  exit 1\n"
            "fi\n"
            "exit 0\n",
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到真實 fail-open：{r.stdout!r}"
        assert "_find" in r.stderr

    def test_lsse_dt_002_or_guarded_call_is_flagged(self, tmp_path: Path) -> None:
        """LSSE-DT-002: `X=$(fn) || RC=$?` 同樣讓 set -e 不觸發，必須報。"""
        f = _write(
            tmp_path,
            "or_guard.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_walk() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 2\n"
            "  fi\n"
            "}\n"
            "RC=0\n"
            'OUT=$(_walk "$X") || RC=$?\n'
            'echo "$RC"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到 || 形式的 fail-open：{r.stdout!r}"

    def test_lsse_eg_001_return_code_form_is_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-001: function 用 return code 表達失敗時不得報（PR #234 的修法）。

        這是本 lint 最重要的負向控制：修好的碼被吵，等於逼人把正確寫法改回錯的。
        """
        f = _write(
            tmp_path,
            "fixed.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_find() {\n"
            '  if [ "$1" = "deep" ]; then\n'
            "    return 2\n"
            "  fi\n"
            "  return 1\n"
            "}\n"
            "RC=0\n"
            'BROKEN=$(_find "$DIR") || RC=$?\n'
            'if [ "$RC" -eq 2 ]; then exit 1; fi\n'
            "exit 0\n",
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報在正確的 return code 寫法上：{r.stderr!r}"

    def test_lsse_eg_002_direct_call_with_exit_is_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-002: 被直接呼叫的 function 用 exit 完全正常，不得報。

        die() 這種 helper 是 shell 常見慣例；報它會產生大量噪音。
        """
        f = _write(
            tmp_path,
            "direct.sh",
            "#!/bin/bash\n"
            "die() {\n"
            '  echo "[FAIL] $1" >&2\n'
            "  exit 1\n"
            "}\n"
            'if [ ! -d "$DIR" ]; then\n'
            '  die "no dir"\n'
            "fi\n",
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報在直接呼叫的 die() 上：{r.stderr!r}"

    def test_lsse_eg_003_bare_assignment_with_set_e_is_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-003: 裸賦值 + set -e 會被 set -e 接住，無 fail-open，不得報。

        這是本 lint 第一版的實際誤報：它報了 bump-version/scripts/bump.sh 的
        bump_semver，但那裡是 `new_version=$(bump_semver ...)` 裸賦值，subshell
        exit 1 讓賦值非零，set -e 於是中止腳本——沒有 fail-open。
        判準因此收窄成「呼叫點讓 set -e 不觸發」或「腳本沒有 set -e」。
        """
        f = _write(
            tmp_path,
            "bare_set_e.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "bump_semver() {\n"
            "  if ! echo \"$1\" | grep -qE '^[0-9]'; then\n"
            '    echo "[FAIL] bad version" >&2\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "1.2.3"\n'
            "}\n"
            'new_version=$(bump_semver "$current")\n'
            'echo "$new_version"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報在被 set -e 接住的裸賦值上：{r.stderr!r}"

    def test_lsse_dt_003_bare_assignment_without_set_e_is_flagged(self, tmp_path: Path) -> None:
        """LSSE-DT-003: 沒有 set -e 時，裸賦值也會真的往下跑，必須報。

        與 LSSE-EG-003 成對：同樣的呼叫形式，差別只在有沒有 set -e。
        """
        f = _write(
            tmp_path,
            "bare_no_set_e.sh",
            "#!/bin/bash\n"
            "_check() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "ok"\n'
            "}\n"
            'RESULT=$(_check "$X")\n'
            'echo "continued: $RESULT"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到無 set -e 的 fail-open：{r.stdout!r}"

    def test_lsse_eg_004_name_mentioned_inside_substitution_is_not_flagged(
        self, tmp_path: Path
    ) -> None:
        """LSSE-EG-004: function 名只是「出現在」$() 裡（非被呼叫）不得報。

        這是本 lint 第一版的另一個實際誤報：.claude/hooks/bash-ap1-inline-check.sh
        的 block() 是直接呼叫的，但檔案裡另有 $(...) 區段提到 block 字樣，
        第一版的「名字有沒有出現在某個 $() 內」判準因此誤報。
        判準收窄成「function 名必須是 $( 之後的第一個 token」。
        """
        f = _write(
            tmp_path,
            "mention.sh",
            "#!/bin/bash\n"
            "block() {\n"
            '  echo "$1"\n'
            "  exit 2\n"
            "}\n"
            "LOG=$(python3 logger.py block --mode strict)\n"
            'if [ "$bad" ]; then\n'
            '  block "reason"\n'
            "fi\n",
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報：block 只是被當成引數提及，非 $() 呼叫：{r.stderr!r}"

    def test_lsse_eg_005_exit_in_comment_is_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-005: 只出現在註解裡的 exit 不得報。"""
        f = _write(
            tmp_path,
            "comment.sh",
            "#!/bin/bash\n"
            "_helper() {\n"
            "  # 注意：這裡不可以 exit 1\n"
            '  echo "ok"\n'
            "  return 0\n"
            "}\n"
            "if X=$(_helper); then\n"
            '  echo "$X"\n'
            "fi\n",
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報在註解裡的 exit 上：{r.stderr!r}"

    def test_lsse_dt_004_recursive_substitution_call_is_flagged(self, tmp_path: Path) -> None:
        """LSSE-DT-004: 遞迴 helper（含 $() 自呼叫）內的 exit 仍須被抓到。

        **本測試證明的範圍（誠實標註）**：它證明的是「遞迴形式不會讓偵測漏掉」，
        **不是**「不排除自身呼叫點」這個實作決定——因為本 fixture 有外部呼叫點
        `RESULT=$(_walk "$DIR")`，排不排除自身它都會被抓到。

        這點是突變測試逼出來的：拿掉自身排除後本測試仍 PASS，代表它對那個決定
        零鑑別力。留著它是因為它仍守住「遞迴形式的整體偵測」，但不得宣稱它守住
        了別的東西——那正是 rule 09 記載的假測試（docstring 宣稱 X、實際測 Y）。

        會遞迴又有 exit 的 function，現實中必然也有外部呼叫點（否則是死碼），
        所以沒有任何真實情境能區分那個實作決定。
        """
        f = _write(
            tmp_path,
            "recursive.sh",
            "#!/bin/bash\n"
            "_walk() {\n"
            '  if [ "$1" = "/" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  PARENT=$(_walk "$(dirname "$1")")\n'
            '  echo "$PARENT"\n'
            "}\n"
            'RESULT=$(_walk "$DIR")\n',
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到遞迴 $() 自呼叫的 fail-open：{r.stdout!r}"

    def test_lsse_vl_001_no_args_exits_zero(self) -> None:
        """LSSE-VL-001: 無檔案引數時 exit 0（pre-commit 可能傳空清單）。"""
        r = subprocess.run(  # nosec B603
            [sys.executable, str(LINT)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert r.returncode == 0

    def test_lsse_st_001_whole_repo_is_clean(self) -> None:
        """LSSE-ST-001: 現有 repo 的所有 shell 檔必須零誤報。

        這條是 lint 能否進 pre-commit 的門檻：對既有正確的碼吵，等於逼所有人加
        # noqa 或關掉它。實測第一版報了 3 個檔案，全是誤報，判準因此重寫。
        """
        listed = subprocess.run(  # nosec B603
            ["git", "-C", str(REPO_ROOT), "ls-files", "*.sh"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        files = [
            REPO_ROOT / line
            for line in listed.stdout.splitlines()
            if line and (REPO_ROOT / line).is_file()
        ]
        assert files, "測試前提不成立：repo 應有 .sh 檔"

        r = subprocess.run(  # nosec B603
            [sys.executable, str(LINT), *[str(f) for f in files]],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert r.returncode == 0, f"現有 repo 出現誤報：\n{r.stderr}"
