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


def _run_lint(target: Path, strict: bool = True) -> subprocess.CompletedProcess[str]:
    # 偵測/負向控制測試用 strict（--fail）驗 exit code：偵測 -> 1、乾淨 -> 0。
    # 預設 advisory 模式（strict=False）由 VL-002 單獨驗（有 finding 仍 exit 0）。
    cmd = [sys.executable, str(LINT)]
    if strict:
        cmd.append("--fail")
    cmd.append(str(target))
    return subprocess.run(  # nosec B603
        cmd,
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

    def test_lsse_vl_002_advisory_default_warns_but_exits_zero(self, tmp_path: Path) -> None:
        """LSSE-VL-002: 預設 advisory 模式——即使有 finding 也 exit 0，只印 [WARN]。

        與 DT-003 成對：完全相同的 fixture，差別只在有沒有 --fail。
        DT-003（strict）-> exit 1；本測試（advisory 預設）-> exit 0 但 stderr 仍報 finding。
        這是 PR #241 mob review 後「blocking -> advisory」的行為契約。
        """
        f = _write(
            tmp_path,
            "advisory.sh",
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
        r = _run_lint(f, strict=False)
        assert r.returncode == 0, f"advisory 預設不應阻擋：{r.stderr!r}"
        assert "_check" in r.stderr, "advisory 仍須把 finding 印到 stderr"
        assert "[WARN]" in r.stderr, "advisory 模式應標 [WARN] 而非 [FAIL]"

    def test_lsse_dt_005_local_masks_exit_status_sc2155(self, tmp_path: Path) -> None:
        """LSSE-DT-005: `local X=$(fn)` 讓 set -e 失效（SC2155），必須報。

        `local` 的 exit status 永遠為 0，蓋掉 command substitution 的非零，
        即使有 set -e 也接不住。`declare`/`export`/`readonly` 同理。
        """
        f = _write(
            tmp_path,
            "sc2155.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_resolve() {\n"
            '  if [ ! -d "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "$1"\n'
            "}\n"
            'local RESULT=$(_resolve "$DIR")\n'
            'echo "$RESULT"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到 local 蓋掉 exit status 的 SC2155：{r.stdout!r}"
        assert "_resolve" in r.stderr

    def test_lsse_dt_006_quoted_substitution_is_flagged(self, tmp_path: Path) -> None:
        """LSSE-DT-006: `X="$(fn)"` 加引號仍是 command substitution，必須報。

        舊版 _strip_noise 清掉雙引號內容，導致 bash 最佳實踐的加引號形式
        對 lint 完全不可見——是最常見的漏報。
        """
        f = _write(
            tmp_path,
            "quoted.sh",
            "#!/bin/bash\n"
            "_lookup() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "found"\n'
            "}\n"
            'if RESULT="$(_lookup "$KEY")"; then\n'
            '  echo "$RESULT"\n'
            "fi\n",
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到加引號的 $() 漏報：{r.stdout!r}"
        assert "_lookup" in r.stderr

    def test_lsse_eg_006_final_position_and_or_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-006: `true && X=$(fn)` 最後位置，set -e 仍有效，不得報。

        POSIX：set -e 只對 AND-OR list 中「非最後一個」命令停用。
        `$(fn)` 在 `&&` 之後的最終位置，失敗時 set -e 會接住。
        """
        f = _write(
            tmp_path,
            "final_pos.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_check() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "ok"\n'
            "}\n"
            'true && RESULT=$(_check "$X")\n'
            'echo "$RESULT"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報：final position && 的 set-e 有效：{r.stderr!r}"

    def test_lsse_eg_007_set_o_errexit_recognized(self, tmp_path: Path) -> None:
        """LSSE-EG-007: `set -o errexit` 長式等同 `set -e`，不得因不認而誤報。"""
        f = _write(
            tmp_path,
            "errexit_long.sh",
            "#!/usr/bin/env bash\n"
            "set -o errexit\n"
            "set -o nounset\n"
            "set -o pipefail\n"
            "_helper() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "ok"\n'
            "}\n"
            'RESULT=$(_helper "$X")\n'
            'echo "$RESULT"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報：set -o errexit 未被識別：{r.stderr!r}"

    def test_lsse_eg_008_if_body_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-008: `if true; then X=$(fn); fi` body 呼叫受 set -e 保護，不得報。

        if 條件位置讓 set -e 不觸發，但 `; then` 之後的 body 不受此影響。
        舊版只看 before 有沒有 `if` 就判定，沒區分條件與 body。
        """
        f = _write(
            tmp_path,
            "if_body.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_resolve() {\n"
            '  if [ ! -d "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "$1"\n'
            "}\n"
            'if true; then RESULT=$(_resolve "$DIR"); fi\n'
            'echo "$RESULT"\n',
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報：if body 受 set -e 保護：{r.stderr!r}"

    def test_lsse_vl_003_unicode_decode_error_handled(self, tmp_path: Path) -> None:
        """LSSE-VL-003: 非 UTF-8 檔案不中止整批掃描，印 [WARN] 並 exit 0。"""
        f = tmp_path / "binary.sh"
        f.write_bytes(b"#!/bin/bash\n\xff\xfe invalid utf-8\n")
        r = _run_lint(f)
        assert r.returncode == 0, "非 UTF-8 檔不應阻擋"
        assert "[WARN]" in r.stderr

    def test_lsse_dt_001_reports_correct_line_numbers(self, tmp_path: Path) -> None:
        """LSSE-DT-001b: 偵測報告的行號必須對應 exit 實際位置與 call-site 位置。

        DT-001 只驗 exit code；本測試加驗行號，防止 `i+1`→`i` 突變存活。
        """
        f = _write(
            tmp_path,
            "lineno.sh",
            "#!/usr/bin/env bash\n"  # 1
            "set -euo pipefail\n"  # 2
            "_find() {\n"  # 3
            '  if [ "$1" = "deep" ]; then\n'  # 4
            "    exit 1\n"  # 5
            "  fi\n"  # 6
            "  return 1\n"  # 7
            "}\n"  # 8
            'if BROKEN=$(_find "$DIR"); then\n'  # 9
            "  exit 1\n"  # 10
            "fi\n"  # 11
            "exit 0\n",  # 12
        )
        r = _run_lint(f)
        assert r.returncode == 1
        assert ":5:" in r.stderr, f"exit 行號應為 5：{r.stderr}"
        assert "9" in r.stderr, f"call-site 行號應含 9：{r.stderr}"

    def test_lsse_dt_007_export_masks_exit_status(self, tmp_path: Path) -> None:
        """LSSE-DT-007: `export X=$(fn)` 同 local，builtin 蓋掉 exit status。"""
        f = _write(
            tmp_path,
            "export_sc2155.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_compute() {\n"
            '  if [ -z "$1" ]; then\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "value"\n'
            "}\n"
            'export RESULT=$(_compute "$X")\n',
        )
        r = _run_lint(f)
        assert r.returncode == 1, f"未抓到 export 蓋掉 exit status：{r.stdout!r}"

    def test_lsse_eg_009_single_quoted_not_flagged(self, tmp_path: Path) -> None:
        """LSSE-EG-009: 單引號內的 $(fn) 不展開，不得報。"""
        f = _write(
            tmp_path,
            "single_quote.sh",
            "#!/bin/bash\n_helper() {\n  exit 1\n}\necho 'do not expand $(_helper)'\n",
        )
        r = _run_lint(f)
        assert r.returncode == 0, f"誤報：單引號內的 $() 不應被偵測：{r.stderr!r}"

    def test_lsse_st_001_whole_repo_is_clean(self) -> None:
        """LSSE-ST-001: 現有 repo 追蹤的 shell 檔必須零誤報。

        掃描範圍對齊 pre-commit hook（`types: [shell]`）：*.sh 檔 + shebang
        含 bash/sh 的無副檔名檔（如 scripts/lessons、scripts/resolve-skill-repo）。
        """
        listed = subprocess.run(  # nosec B603
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        files: list[Path] = []
        for line in listed.stdout.splitlines():
            if not line:
                continue
            p = REPO_ROOT / line
            if not p.is_file():
                continue
            if p.suffix == ".sh":
                files.append(p)
            elif not p.suffix:
                try:
                    first = p.read_bytes()[:256]
                    if first.startswith(b"#!") and (
                        b"bash" in first.split(b"\n")[0] or b"/sh" in first.split(b"\n")[0]
                    ):
                        files.append(p)
                except OSError:
                    pass
        assert files, "測試前提不成立：repo 應有 shell 檔"

        r = subprocess.run(  # nosec B603
            [sys.executable, str(LINT), "--fail", *[str(f) for f in files]],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert r.returncode == 0, f"現有 repo 出現誤報：\n{r.stderr}"
