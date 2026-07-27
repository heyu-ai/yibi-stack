"""lint_rule_evidence 純函式測試（合成 diff fixture）。

對應 testplan：REG-EG-001a/b/c（分層強制）、REG-VL-001（錨點缺失不空洞通過）、
2.3 new-section heuristic（編輯既有 section 不誤觸發）。加上 PR #339 mob review
找出的迴歸案例：settings.json / .pre-commit-config.yaml 新註冊 hook 未受檢查、
CLAUDE.md 未納入 always-loaded 文件面、無數字前綴的新 rule 檔逃過兩層檢查、巢狀
hook script 路徑逃過檢查、以及證據標記在 table row / fenced code block 內被誤判
為「已有證據」。

關鍵：只對真實檔案斷言的 lint 無法測自己的失敗路徑；這裡以純函式入口 + 合成 diff
驗證負向案例。
"""

import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lint_rule_evidence  # noqa: E402
from lint_rule_evidence import (  # noqa: E402
    check_rule_evidence,
    warn_rule_evidence,
)


def _new_file_diff(path: str, body_lines: list[str]) -> str:
    added = "\n".join(f"+{line}" for line in body_lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(body_lines)} @@\n"
        f"{added}\n"
    )


def _existing_file_diff(path: str, added_body: list[str]) -> str:
    added = "\n".join(f"+{line}" for line in added_body)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -10,0 +11 @@\n{added}\n"


def _existing_file_diff_multi_hunk(
    path: str, hunk1_added: list[str], hunk2_added: list[str]
) -> str:
    added1 = "\n".join(f"+{line}" for line in hunk1_added)
    added2 = "\n".join(f"+{line}" for line in hunk2_added)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -10,0 +11,{len(hunk1_added)} @@\n"
        f"{added1}\n"
        f"@@ -50,0 +52,{len(hunk2_added)} @@\n"
        f"{added2}\n"
    )


def _rename_diff(old_path: str, new_path: str, added_body: list[str]) -> str:
    added = "\n".join(f"+{line}" for line in added_body)
    return (
        f"diff --git a/{old_path} b/{new_path}\n"
        "similarity index 80%\n"
        f"rename from {old_path}\n"
        f"rename to {new_path}\n"
        f"--- a/{old_path}\n"
        f"+++ b/{new_path}\n"
        f"@@ -1,0 +1,{len(added_body)} @@\n"
        f"{added}\n"
    )


# --- REG-EG-001a：新 rule 檔缺證據標記 -> error 非空 ---


def test_new_rule_file_missing_evidence_is_error():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "一些沒有證據的規則內容。"])
    errors = check_rule_evidence(diff)
    assert errors, "新 rule 檔缺證據標記應回傳非空 error 清單"
    assert ".claude/rules/17-foo.md" in errors[0]


def test_new_rule_file_with_structured_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "規則內容。", "<!-- verified: probe -->"],
    )
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_prose_source_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "規則內容。（Source: PR #250 實測）"],
    )
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_probed_marker_passes():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "規則內容。Probed."])
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_verified_on_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "行為宣稱（verified on agy 1.1.2）。"],
    )
    assert check_rule_evidence(diff) == []


# --- REG-EG-001c：新 hook 檔缺證據標記 -> error 非空 ---


def test_new_hook_missing_evidence_is_error():
    diff = _new_file_diff(".claude/hooks/foo-check.py", ["import sys", "sys.exit(0)"])
    errors = check_rule_evidence(diff)
    assert errors
    assert ".claude/hooks/foo-check.py" in errors[0]


# --- REG-EG-001b：既有 rule 檔新增 section 缺標記 -> warn（非 error）---


def test_existing_rule_new_section_missing_evidence_is_warn_not_error():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "一段沒有證據的說明。"],
    )
    assert check_rule_evidence(diff) == [], "既有檔新 section 不應是 error（只 warn）"
    warns = warn_rule_evidence(diff)
    assert warns
    assert "新的反模式" in warns[0]


def test_existing_rule_new_section_with_marker_no_warn():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "說明。Probed."],
    )
    assert warn_rule_evidence(diff) == []


# --- 2.3 heuristic：編輯既有 section（無新 heading）不誤觸發 warn ---


def test_editing_existing_section_no_new_heading_no_warn():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["在既有段落裡多加一行說明，沒有新增 heading。"],
    )
    assert warn_rule_evidence(diff) == []
    assert check_rule_evidence(diff) == []


# --- REG-VL-001：錨點缺失不空洞通過；真正空 diff 才回空 ---


def test_anchor_missing_is_not_vacuous_pass():
    """有新 rule 內容但缺證據標記（錨點缺失）-> 非空，不得因找不到錨點而回空。"""
    diff = _new_file_diff(".claude/rules/18-bar.md", ["# Bar", "內容但無任何證據錨點。"])
    assert check_rule_evidence(diff) != []


def test_empty_diff_returns_empty():
    """真正空的 diff（沒 stage 任何東西）-> 無可檢查，回空清單才正確。"""
    assert check_rule_evidence("") == []
    assert warn_rule_evidence("") == []


# --- 非 rule/hook 的新檔不受管 ---


def test_new_non_rule_file_ignored():
    diff = _new_file_diff("scripts/foo.py", ["print('hi')"])
    assert check_rule_evidence(diff) == []
    assert warn_rule_evidence(diff) == []


# --- AC-6 迴歸：既有 settings.json / .pre-commit-config.yaml 新註冊 hook 缺標記 -> error ---


def test_settings_json_new_hook_missing_evidence_is_error():
    diff = _existing_file_diff(
        ".claude/settings.json",
        ['"command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/foo-new-check.py || exit 2"'],
    )
    errors = check_rule_evidence(diff)
    assert errors, "settings.json 新註冊 hook 缺證據標記應回傳非空 error 清單"
    assert ".claude/settings.json" in errors[0]


def test_settings_json_new_hook_with_marker_passes():
    diff = _existing_file_diff(
        ".claude/settings.json",
        [
            '"command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/foo-new-check.py || exit 2",',
            "// <!-- verified: probe -->",
        ],
    )
    assert check_rule_evidence(diff) == []


def test_settings_json_edit_without_new_hook_command_ignored():
    """既有 settings.json 的其他編輯（不含新增 hook command）不應誤觸發。"""
    diff = _existing_file_diff(".claude/settings.json", ['"someOtherKey": "value"'])
    assert check_rule_evidence(diff) == []


def test_precommit_config_new_hook_id_missing_evidence_is_error():
    diff = _existing_file_diff(
        ".pre-commit-config.yaml",
        ["      - id: foo-new-check", "        entry: python3 scripts/foo_new_check.py"],
    )
    errors = check_rule_evidence(diff)
    assert errors
    assert ".pre-commit-config.yaml" in errors[0]


def test_precommit_config_new_hook_id_with_marker_passes():
    diff = _existing_file_diff(
        ".pre-commit-config.yaml",
        ["      - id: foo-new-check", "        # <!-- verified: probe -->"],
    )
    assert check_rule_evidence(diff) == []


# --- AC-6/AC-7 迴歸：CLAUDE.md 納入 always-loaded 文件面（既有檔新 section -> warn）---


def test_claude_md_new_section_missing_evidence_is_warn_not_error():
    diff = _existing_file_diff("CLAUDE.md", ["## 新的慣例", "一段沒有證據的說明。"])
    assert check_rule_evidence(diff) == [], "CLAUDE.md 新 section 不應是 error（只 warn）"
    warns = warn_rule_evidence(diff)
    assert warns
    assert "新的慣例" in warns[0]


def test_claude_md_new_section_with_marker_no_warn():
    diff = _existing_file_diff("CLAUDE.md", ["## 新的慣例", "說明。Probed."])
    assert warn_rule_evidence(diff) == []


# --- AC-6 迴歸：無數字前綴的新 rule 檔仍須受檢（NN- 只是命名慣例，非把關條件）---


def test_new_rule_file_without_numeric_prefix_missing_evidence_is_error():
    diff = _new_file_diff(
        ".claude/rules/retro-evidence.md", ["# Retro Evidence", "沒有證據的內容。"]
    )
    errors = check_rule_evidence(diff)
    assert errors, "無數字前綴的新 rule 檔缺證據標記，過去會同時逃過 error 與 warn 兩層"
    assert ".claude/rules/retro-evidence.md" in errors[0]


# --- AC-6 迴歸：巢狀 hook script 路徑仍須受檢 ---


def test_nested_hook_script_missing_evidence_is_error():
    diff = _new_file_diff(".claude/hooks/lib/foo-check.py", ["import sys", "sys.exit(0)"])
    errors = check_rule_evidence(diff)
    assert errors, "巢狀路徑下的新 hook script 缺證據標記，過去因單層路徑正則逃過檢查"
    assert ".claude/hooks/lib/foo-check.py" in errors[0]


# --- AC-7 迴歸：證據標記只在 table row / fenced code block 內出現時，不算真的有證據 ---


def test_marker_only_in_table_row_is_not_counted_as_evidence():
    """rule 11 自己的新 section 曾以此方式誤判：表格內「範例」文字含標記字串，
    被當成該 section 已有真實證據，實際上該 section 從未真的宣稱自己已驗證。
    """
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        [
            "## 新的反模式",
            "說明。",
            "| 類型 | 範例 |",
            "| --- | --- |",
            "| 結構化 | `<!-- verified: probe -->` |",
        ],
    )
    warns = warn_rule_evidence(diff)
    assert warns, "table row 裡的標記語法範例不應被視為真實證據"


def test_marker_only_in_fenced_code_block_is_not_counted_as_evidence():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        [
            "## 新的反模式",
            "說明。範例標記語法：",
            "```",
            "<!-- verified: probe -->",
            "```",
        ],
    )
    warns = warn_rule_evidence(diff)
    assert warns, "fenced code block 內的標記語法範例不應被視為真實證據"


def test_marker_outside_table_and_fence_still_counts_as_evidence():
    """確認上面兩個負向控制不是矯枉過正：真正在 prose 行內出現的標記仍要通過。"""
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "說明。<!-- verified: probe -->"],
    )
    assert warn_rule_evidence(diff) == []


# --- exit-code 契約迴歸：git 不可用時 _staged_diff 應轉為 RuntimeError（main() 的 exit 2 路徑）---


def test_staged_diff_wraps_missing_git_binary_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(RuntimeError):
        lint_rule_evidence._staged_diff()


# --- AC-6 迴歸：rename 進受保護目錄不得繞過 error gate（Codex + Gemini 皆發現）---


def test_rename_non_rule_file_into_rules_dir_missing_evidence_is_error():
    diff = _rename_diff(
        "scripts/old-notes.md", ".claude/rules/renamed-in.md", ["# Renamed", "沒有證據的內容。"]
    )
    errors = check_rule_evidence(diff)
    assert errors, (
        "從受保護目錄外 rename 進來的檔案缺證據標記，過去因 is_new_file 只看"
        "old_path == /dev/null 而誤判為既有檔，繞過 error gate"
    )
    assert ".claude/rules/renamed-in.md" in errors[0]


def test_rename_hook_script_from_scripts_dir_missing_evidence_is_error():
    diff = _rename_diff("scripts/helper.py", ".claude/hooks/renamed-in.py", ["import sys"])
    errors = check_rule_evidence(diff)
    assert errors
    assert ".claude/hooks/renamed-in.py" in errors[0]


def test_rename_within_rules_dir_not_treated_as_new_file():
    """既有 rule 檔改名（仍在 .claude/rules/ 內）不是「新檔」——走既有檔 warn 路徑，非 error。"""
    diff = _rename_diff(
        ".claude/rules/13-old-name.md", ".claude/rules/13-new-name.md", ["## 新段落", "沒有證據。"]
    )
    assert check_rule_evidence(diff) == []
    warns = warn_rule_evidence(diff)
    assert warns


# --- AC-6/AC-7 迴歸：證據標記正則本身仍過寬（Codex 指出，第一輪只修了 table/fence 過濾）---


def test_verified_colon_with_unenumerated_value_is_not_evidence():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md", ["# Foo", "內容。<!-- verified: something-else -->"]
    )
    errors = check_rule_evidence(diff)
    assert errors, "verified: 後接非封閉列舉允許的值（非 probe、非 incident PR#NNN）不應被當成證據"


def test_verified_on_with_only_one_token_is_not_evidence():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "內容。verified on agy"])
    errors = check_rule_evidence(diff)
    assert errors, "verified on 缺版本號（只有一個 token）不應被當成證據"


def test_verified_on_with_tool_and_version_is_evidence():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "內容。verified on agy 1.1.2"])
    assert check_rule_evidence(diff) == []


def test_verified_incident_structured_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md", ["# Foo", "內容。<!-- verified: incident PR#250 -->"]
    )
    assert check_rule_evidence(diff) == []


# --- AC-7 迴歸：不相關 hunk 攤平合併導致證據標記被誤判歸屬（Gemini 發現）---


def test_evidence_in_unrelated_later_hunk_does_not_cover_earlier_missing_section():
    diff = _existing_file_diff_multi_hunk(
        ".claude/rules/13-bash-anti-patterns.md",
        hunk1_added=["## 新的反模式一", "沒有證據的說明。"],
        hunk2_added=["在既有段落補一行 Probed. 但跟上面的新 section 完全無關。"],
    )
    warns = warn_rule_evidence(diff)
    assert warns, "後面不相關 hunk 的證據標記字串不應覆蓋前面 hunk 新增 heading 缺證據的事實"
    assert "新的反模式一" in warns[0]


def test_evidence_in_same_hunk_as_new_heading_still_counts():
    """確認上面的負向控制不是矯枉過正：同一個 hunk 內的證據標記仍要通過。"""
    diff = _existing_file_diff_multi_hunk(
        ".claude/rules/13-bash-anti-patterns.md",
        hunk1_added=["## 新的反模式二", "說明。Probed."],
        hunk2_added=["在既有段落補一行，跟新 section 無關。"],
    )
    warns = warn_rule_evidence(diff)
    assert warns == [], "同一個 hunk 內的證據標記應正常算數"


# --- CI range mode（`--base` / `--head`）：PR #347 CI wiring 對應的實作面 ---
#
# PR #347 把 `.github/workflows/ci.yml` 接成 `lint_rule_evidence.py --base <sha> --head <sha>`，
# 但腳本當時只有 positional diff-file 模式，`--base` 被當成檔名 -> exit 2
# （`[FAIL] 無法讀取 diff 檔：[Errno 2] No such file or directory: '--base'`）。
# 當時的整合測試只斷言「workflow YAML 字串裡有 --base」，沒有任何測試真的用這組 flag
# 呼叫過腳本，所以本機全綠、CI 必紅。以下測試建真 git repo 跑真 range，補上那個缺口。


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(  # nosec B603
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return proc.stdout.strip()


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")


def _commit_rule(repo: Path, name: str, body: str, message: str) -> str:
    rules_dir = repo / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_range_mode_flags_are_accepted_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI 實際呼叫形狀的最小契約：`--base`/`--head` 不得被當成 positional 檔名。

    這是 PR #347 CI 失敗的直接迴歸——修復前本測試以 exit 2 +
    `無法讀取 diff 檔：... '--base'` 失敗。
    """
    _init_repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD")
    head = _commit_rule(tmp_path, "90-clean.md", "# Clean\n\n說明。Probed.\n", "add rule")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 0


def test_range_mode_blocks_known_bad_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正向對照：已知該被擋的輸入（新 rule 檔缺證據標記）必須在 range mode 下回 exit 1。

    沒有這條，上面那個「回 0」的測試沒有資訊量——一個永遠回 0 的 range mode 也會通過。
    """
    _init_repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD")
    head = _commit_rule(tmp_path, "91-bare.md", "# Bare\n\n沒有任何證據的說明。\n", "add rule")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1


def test_range_mode_uses_merge_base_not_two_dot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """base 分支在 fork 之後**新增**的檔案不算在這條 PR 頭上。

    **這條測試證明不了三點語意**（PR #347 mob review，三家獨立以 mutation 實證）：此形狀在
    兩點下呈現為 head **刪除**該檔（`+++ /dev/null`），而 `_is_newly_protected` 對 `/dev/null`
    的 fullmatch 必為 None，error 層根本不看它——兩點與三點輸出相同判定，把 `...` 換成 `..`
    本測試照樣綠。真正能分辨的是下一條
    `test_range_mode_two_dot_would_falsely_blame_a_base_side_deletion`。
    保留本條是因為它仍覆蓋了「base 新增檔案」這個獨立案例（Codex R2 明確建議增加而非取代）。
    """
    _init_repo(tmp_path)
    fork_point = _git(tmp_path, "rev-parse", "HEAD")

    # PR 分支：只加一個帶證據的 rule 檔
    _git(tmp_path, "checkout", "-q", "-b", "pr")
    head = _commit_rule(tmp_path, "92-mine.md", "# Mine\n\n說明。Probed.\n", "pr work")

    # base 分支在 fork 之後前進，並加了一個「缺證據」的 rule 檔（別人的改動）
    _git(tmp_path, "checkout", "-q", "main")
    base = _commit_rule(tmp_path, "93-theirs.md", "# Theirs\n\n缺證據。\n", "other work")
    assert base != fork_point

    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 0, (
        "base 分支上別人新增的缺證據 rule 檔不應讓這條 PR 變紅"
    )


def test_range_mode_two_dot_would_falsely_blame_a_base_side_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**這條才是三點語意鎖**：把 `...` 換成 `..` 會讓它轉紅。

    形狀：一個缺證據標記的 rule 檔在 fork **之前**就存在；fork 之後 base 分支把它刪掉，
    head 分支原封不動。
    - 三點 `base...head`：以 merge-base 為基準，head 什麼都沒動 -> 空 diff -> exit 0（正確）。
    - 兩點 `base head`：base 已無該檔、head 有 -> git 報成 head **新增**了它 ->
      `_is_newly_protected` 命中 -> exit 1，把別人刪掉的檔算成本 PR 新增的缺證據 rule 檔。

    上一條測試（base 新增檔案）在兩種語意下都是 exit 0，所以證明不了任何事——本條補上。
    （PR #347 mob review：Claude comment-analyzer / test-analyzer / code-reviewer 三家各自
    以 mutation 實證舊測試存活，並提出同一個替代 fixture。）
    """
    _init_repo(tmp_path)
    # fork 之前就存在的缺證據 rule 檔
    _commit_rule(tmp_path, "95-preexisting.md", "# Pre-existing\n\n缺證據。\n", "seed rule")
    fork_point = _git(tmp_path, "rev-parse", "HEAD")

    # PR 分支：完全不碰那個檔
    _git(tmp_path, "checkout", "-q", "-b", "pr")
    head = _commit_rule(tmp_path, "96-mine.md", "# Mine\n\n說明。Probed.\n", "pr work")

    # base 分支在 fork 之後刪掉那個既有檔
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / ".claude" / "rules" / "95-preexisting.md").unlink()
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base removes the old rule")
    base = _git(tmp_path, "rev-parse", "HEAD")
    assert base != fork_point

    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 0, (
        "base 分支刪掉的既有缺證據檔不得被算成本 PR 新增——若這裡回 1，range mode 已退回兩點語意"
    )


def test_range_mode_rejects_empty_flag_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空字串值必須 exit 2，不得退化成 `HEAD...HEAD` 的空 diff 而靜默通過。

    `""` 不是 `None`，會通過成對檢查進入 range 模式；而 `git diff "...head"` 是合法 range
    （等同 `HEAD...head`），CI 的 checkout 就在 head，於是 exit 0 回空 diff、gate 印 [OK]。
    （PR #347 mob review：test-analyzer / silent-failure / code-reviewer 三家獨立提出，
    皆誠實標註目前 wiring 下兩個 SHA 必為非空，屬殘餘風險而非活 bug。）
    """
    _init_repo(tmp_path)
    head = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", "", "--head", head]) == 2
    assert lint_rule_evidence.main(["--base", head, "--head", ""]) == 2
    assert lint_rule_evidence.main(["--base", "   ", "--head", head]) == 2


def test_range_mode_requires_both_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只給一半的 range 是設定錯誤，必須 exit 2，不得靜默退回 staged-diff 模式。"""
    _init_repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", base]) == 2
    assert lint_rule_evidence.main(["--head", base]) == 2


def test_range_mode_unresolvable_revision_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """解不開的 SHA（shallow checkout 缺物件是 CI 上的真實情境）必須 exit 2，不得回 0。

    回 0 會讓 gate 在「根本沒讀到 diff」的情況下報告通過——本 repo 最常見的假綠形狀。
    """
    _init_repo(tmp_path)
    head = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", "0" * 40, "--head", head]) == 2


def test_range_mode_and_diff_file_are_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同時給 range 與 diff 檔是矛盾輸入，必須 exit 2 而非任選一個。"""
    _init_repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD")
    diff_file = tmp_path / "some.diff"
    diff_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", base, "--head", base, str(diff_file)]) == 2


def test_positional_diff_file_mode_still_works(tmp_path: Path) -> None:
    """既有 positional 模式不得因新增 flag 而回歸。"""
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(
        _new_file_diff(".claude/rules/94-bare.md", ["# Bare", "缺證據。"]), encoding="utf-8"
    )
    assert lint_rule_evidence.main([str(diff_file)]) == 1
