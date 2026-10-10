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


# range 模式的既有測試關心 merge-base 語意而非宣告內容；PR 側的新 rule 檔仍須帶一個有效宣告，
# 否則會因機械化宣告檢查（rule-mechanization-gate）而失敗。豁免形式不讀任何檔案。
_VALID_EXEMPTION = "<!-- gate: none (reason: judgment) — 測試夾具用的豁免宣告說明 -->\n"


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
    head = _commit_rule(
        tmp_path, "90-clean.md", "# Clean\n\n說明。Probed.\n" + _VALID_EXEMPTION, "add rule"
    )
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
    head = _commit_rule(
        tmp_path, "92-mine.md", "# Mine\n\n說明。Probed.\n" + _VALID_EXEMPTION, "pr work"
    )

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
    head = _commit_rule(
        tmp_path, "96-mine.md", "# Mine\n\n說明。Probed.\n" + _VALID_EXEMPTION, "pr work"
    )

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


# =====================================================================================
# rule-mechanization-gate：新增 rule section 必須連結既有 gate 或宣告為何無法機械化
#
# 對應 openspec/changes/add-rule-mechanization-gate 的 spec。純函式測試注入假檔案系統
# （不碰真實檔案系統）；`main()` 測試走 production 入口與真實 repo 檔案，兩條路徑都要
# 擋住每個 bad fixture——只測純函式的話，入口被短路成回傳 0 時對照仍全綠。
# =====================================================================================

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "rule_mechanization"

_BLOCKING_SHAPES = frozenset(
    {
        "bad_missing_declaration_new_file.diff",
        "bad_missing_declaration_existing_file.diff",
        "bad_pure_rename_into_rules.diff",
        "bad_new_file_no_sections.diff",
        "bad_dangling_link_existing_file.diff",
        "bad_link_to_rule_rename.diff",
        "bad_missing_symbol.diff",
        "bad_unknown_reason.diff",
        "bad_placeholder_explanation.diff",
        "bad_double_declaration.diff",
        # 以下五個形狀來自 PR #528 review：同一 hunk 兩個 section、git 對特殊檔名的 C-style 引號、
        # 二進位新檔、空的新檔、copy 進 rules（其中三個是真實 git 輸出）。
        "bad_two_sections_one_undeclared.diff",
        "bad_quoted_path_new_file.diff",
        "bad_binary_new_rule_file.diff",
        "bad_empty_new_rule_file.diff",
        "bad_copy_into_rules.diff",
    }
)

# 假檔案系統：`.claude/rules/` 與 SKILL.md 那兩筆刻意「存在但不合格」，證明拒絕的理由是
# 資格而不是存在性。
_FAKE_FS = {
    "scripts/lint_rule_evidence.py": "def check_rule_evidence(diff_text):\n    pass\n",
    "scripts/tests/test_lint_rule_evidence.py": "def test_x():\n    pass\n",
    ".claude/hooks/protect-push.sh": "#!/bin/bash\n",
    ".pre-commit-config.yaml": "repos: []\n",
    ".github/workflows/ci.yml": "name: ci\n",
    "tasks/foo/tests/test_x.py": "def test_x():\n    pass\n",
    ".claude/rules/13-bash-anti-patterns.md": "# rule\n",
    ".claude/rules/17-shell-script-authoring.md": "# rule\n",
    "plugins/growth/skills/pr-retrospective/SKILL.md": "# skill\n",
    # 下面三筆各自只被「一個」資格條件擋下，讓 eligibility 參數化測試能分辨是哪個條件在作用：
    # 子目錄的 SKILL.md（只有 SKILL.md 條件會擋）、tasks/ 下非 tests/ 的檔案（只有 tests/ 正則會擋）、
    # 含反斜線的路徑（前綴合格，只有反斜線條件會擋）。
    "scripts/sub/SKILL.md": "# skill\n",
    "tasks/foo/bar.py": "def bar():\n    pass\n",
    "scripts/sub\\x.py": "def x():\n    pass\n",
}


def _fake_read(path: str) -> str | None:
    return _FAKE_FS.get(path)


def _fixture_text(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _existing_rule_section_diff(declaration_lines: list[str], evidence: bool = True) -> str:
    body = ["### Added Section", "", "內文。"]
    if evidence:
        body.append("(Source: PR #339)")
    body.extend(declaration_lines)
    return _existing_file_diff(".claude/rules/13-bash-anti-patterns.md", body)


def test_every_blocking_shape_has_a_fixture() -> None:
    """
    spec: rule-mechanization-gate#each-blocking-shape-has-its-own-fixture
    tc: RMG-VL-023
    """
    present = {p.name for p in _FIXTURE_DIR.glob("bad_*.diff")}
    assert present == _BLOCKING_SHAPES, (
        f"缺少：{sorted(_BLOCKING_SHAPES - present)}；多出：{sorted(present - _BLOCKING_SHAPES)}"
    )


@pytest.mark.parametrize("name", sorted(_BLOCKING_SHAPES))
def test_bad_fixture_passes_the_evidence_check(name: str) -> None:
    """對照組的前提：bad fixture 只因機械化宣告而失敗，證據標記本身是齊的。

    否則下面「被擋下」的斷言可能是被證據檢查擋的，測到的就不是這個 gate。
    """
    assert lint_rule_evidence.check_rule_evidence(_fixture_text(name)) == []


@pytest.mark.parametrize("name", sorted(_BLOCKING_SHAPES))
def test_bad_fixture_is_rejected_by_pure_function(name: str) -> None:
    # 所有擋下形狀都是 error 層級：任何 rule 檔缺宣告（新檔、既有檔）、任何假宣告，或看不到內容的純 rename
    errors = lint_rule_evidence.check_rule_mechanization(_fixture_text(name), _fake_read)
    assert errors, f"{name} 應為 error 層級"


@pytest.mark.parametrize("name", sorted(_BLOCKING_SHAPES))
def test_bad_fixture_is_rejected_by_main_entry(name: str) -> None:
    assert lint_rule_evidence.main([str(_FIXTURE_DIR / name)]) == 1


_GOOD_FIXTURES = sorted(p.name for p in _FIXTURE_DIR.glob("good_*.diff"))


def test_good_fixtures_exist() -> None:
    assert len(_GOOD_FIXTURES) >= 3, "good fixture 不足，下面的 parametrize 會空洞通過"


@pytest.mark.parametrize("name", _GOOD_FIXTURES)
def test_good_fixtures_report_nothing(name: str) -> None:
    """
    spec: rule-mechanization-gate#section-with-a-valid-gate-link-passes
    spec: rule-mechanization-gate#complete-exemption-passes
    tc: RMG-DT-001, RMG-DT-010
    """
    diff = _fixture_text(name)
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []
    assert lint_rule_evidence.main([str(_FIXTURE_DIR / name)]) == 0


# --- 連結資格（spec 的 eligibility 表）---


@pytest.mark.parametrize(
    ("link", "resolves"),
    [
        ("scripts/lint_rule_evidence.py::check_rule_evidence", True),
        (".claude/hooks/protect-push.sh", True),
        ("scripts/tests/test_lint_rule_evidence.py", True),
        (".pre-commit-config.yaml", True),
        (".github/workflows/ci.yml", True),
        ("tasks/foo/tests/test_x.py", True),
        (".claude/rules/17-shell-script-authoring.md", False),
        ("plugins/growth/skills/pr-retrospective/SKILL.md", False),
        ("scripts/missing.py", False),
        ("scripts/../.claude/rules/13-bash-anti-patterns.md", False),
        ("/etc/passwd", False),
        # 每列只有一個資格條件能擋下它（見 `_FAKE_FS` 的註解）：拿掉該條件，該列就會轉成 True。
        ("scripts/sub/SKILL.md", False),
        ("tasks/foo/bar.py", False),
        ("scripts/sub\\x.py", False),
        # symbol 的前綴邊界：`rule_evidence` 是 `check_rule_evidence` 的後綴，不是獨立的字。
        ("scripts/lint_rule_evidence.py::rule_evidence", False),
    ],
)
def test_gate_link_eligibility(link: str, resolves: bool) -> None:
    """
    spec: rule-mechanization-gate#link-to-a-nonexistent-path-is-an-error
    spec: rule-mechanization-gate#link-to-another-rule-file-is-rejected
    spec: rule-mechanization-gate#each-eligibility-condition-is-individually-enforced
    tc: RMG-VL-005, RMG-VL-006, RMG-EP-041
    """
    diff = _existing_rule_section_diff([f"<!-- gate: {link} -->"])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert (errors == []) is resolves, f"{link} -> {errors}"


def test_gate_link_with_missing_symbol_is_error() -> None:
    """
    spec: rule-mechanization-gate#link-to-a-missing-symbol-is-an-error
    tc: RMG-VL-007
    """
    diff = _existing_rule_section_diff(["<!-- gate: scripts/lint_rule_evidence.py::no_such_fn -->"])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert errors and "no_such_fn" in errors[0]


def test_gate_link_symbol_is_matched_as_a_whole_word() -> None:
    """`check_rule` 是 `check_rule_evidence` 的前綴，不可因子字串命中而通過。

    spec: rule-mechanization-gate#link-to-a-missing-symbol-is-an-error
    tc: RMG-VL-007
    """
    diff = _existing_rule_section_diff(["<!-- gate: scripts/lint_rule_evidence.py::check_rule -->"])
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


# --- 豁免理由封閉列舉 ---


@pytest.mark.parametrize("reason", ["judgment", "no-observable-signal", "hook-cost"])
def test_every_listed_exemption_reason_passes(reason: str) -> None:
    """
    spec: rule-mechanization-gate#complete-exemption-passes
    tc: RMG-DT-010
    """
    diff = _existing_rule_section_diff(
        [f"<!-- gate: none (reason: {reason}) — 這個判斷需要讀完整個 prompt 才能做 -->"]
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []


@pytest.mark.parametrize("explanation", ["TBD", "TODO", "N/A", "none", "太短了", ""])
def test_placeholder_or_short_explanation_is_error(explanation: str) -> None:
    """
    spec: rule-mechanization-gate#placeholder-explanation-is-rejected
    tc: RMG-VL-009
    """
    diff = _existing_rule_section_diff([f"<!-- gate: none (reason: judgment) — {explanation} -->"])
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


def test_exemption_without_explanation_separator_is_error() -> None:
    diff = _existing_rule_section_diff(["<!-- gate: none (reason: judgment) -->"])
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


# --- 缺宣告在新檔與既有檔一律是 error（不分層）---


def test_missing_declaration_in_existing_file_is_error() -> None:
    """
    spec: rule-mechanization-gate#section-without-a-declaration-is-reported
    tc: RMG-DT-002
    """
    diff = _existing_rule_section_diff([])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert errors and "Added Section" in errors[0]


def test_missing_declaration_in_existing_file_exits_one(tmp_path: Path) -> None:
    """
    spec: rule-mechanization-gate#new-section-in-existing-rule-file-fails
    tc: RMG-DT-012
    """
    diff_file = tmp_path / "existing-undeclared.diff"
    diff_file.write_text(_existing_rule_section_diff([]), encoding="utf-8")
    assert lint_rule_evidence.main([str(diff_file)]) == 1


def test_no_mechanization_warn_function_remains() -> None:
    """缺宣告已全面升為 error，不應殘留一個永遠回空清單的 warn 入口誤導讀者。"""
    assert not hasattr(lint_rule_evidence, "warn_rule_mechanization")


def test_renamed_in_rule_file_without_declaration_is_error() -> None:
    """
    spec: rule-mechanization-gate#rename-into-the-rules-directory-is-treated-as-new
    tc: RMG-DT-014
    """
    diff = _rename_diff(
        "scripts/notes.md",
        ".claude/rules/renamed-in.md",
        ["# Renamed", "", "## Section", "", "內文。(Source: PR #339)"],
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


def test_declaration_only_inside_a_fence_does_not_count() -> None:
    """
    spec: rule-mechanization-gate#declaration-quoted-in-a-code-fence-does-not-count
    tc: RMG-DT-003
    """
    diff = _existing_rule_section_diff(
        ["```text", "<!-- gate: scripts/lint_rule_evidence.py -->", "```"]
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


def test_unchanged_sections_are_not_scanned() -> None:
    """只在既有 section 內新增內容（沒有新 heading）不觸發。"""
    diff = _existing_file_diff(".claude/rules/13-bash-anti-patterns.md", ["只是補一句內文。"])
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []


# --- 與證據檢查互相獨立 ---


def test_evidence_marker_does_not_satisfy_the_declaration() -> None:
    """
    spec: rule-mechanization-gate#evidence-marker-does-not-satisfy-the-declaration
    tc: RMG-EG-018
    """
    diff = _existing_rule_section_diff([], evidence=True)
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


def test_declaration_does_not_satisfy_the_evidence_marker() -> None:
    """
    spec: rule-mechanization-gate#declaration-does-not-satisfy-the-evidence-marker
    tc: RMG-EG-019
    """
    diff = _new_file_diff(
        ".claude/rules/25-no-evidence.md",
        [
            "# No Evidence",
            "",
            "## Section",
            "",
            "內文，沒有證據標記。",
            "<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->",
        ],
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []
    assert lint_rule_evidence.check_rule_evidence(diff), "證據檢查仍須獨立擋下"


def test_range_mode_runs_the_declaration_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兩個執行點都要有宣告檢查：range 模式（CI）不可只跑證據檢查。

    spec: rule-mechanization-gate#both-execution-points-run-the-declaration-check
    tc: RMG-DT-024
    """
    _init_repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD")
    rule = tmp_path / ".claude" / "rules" / "26-range.md"
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text("# Range\n\n## Section\n\n內文。(Source: PR #339)\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add undeclared rule")
    head = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1


def test_staged_mode_runs_the_declaration_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pre-commit 的 staged 模式是另一個執行點，同樣必須擋下缺宣告的新 rule 檔。

    repo 內明確開啟 `diff.mnemonicPrefix`：這個設定讓 `git diff --cached` 輸出 `c/` `i/` 前綴，
    曾使 staged 模式整個 lint 靜默 no-op。測試自帶設定，不依賴執行機器的全域 git 設定，CI 上
    同樣能重現。

    spec: rule-mechanization-gate#both-execution-points-run-the-declaration-check
    spec: rule-mechanization-gate#staged-mode-survives-diff-mnemonicprefix
    tc: RMG-DT-024, RMG-DT-025
    """
    _init_repo(tmp_path)
    _git(tmp_path, "config", "diff.mnemonicPrefix", "true")
    rule = tmp_path / ".claude" / "rules" / "28-staged.md"
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text("# Staged\n\n## Section\n\n內文。(Source: PR #339)\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)

    assert lint_rule_evidence.main([]) == 1


# --- 純 rename（沒有 hunk）進 .claude/rules/：看不到內容，fail-closed ---
#
# 100% 相似度的 rename 在 git 輸出裡只有 `rename from/to`，沒有 `---`/`+++`，舊 parser 因此
# 完全看不到它——證據與宣告兩個檢查都沒機會跑，整份檔案靜默通過。

_PURE_RENAME_INTO_RULES = (
    "diff --git a/scripts/notes.md b/.claude/rules/renamed-pure.md\n"
    "similarity index 100%\n"
    "rename from scripts/notes.md\n"
    "rename to .claude/rules/renamed-pure.md\n"
)


def _pure_rename_diff(old_path: str, new_path: str) -> str:
    return (
        f"diff --git a/{old_path} b/{new_path}\n"
        "similarity index 100%\n"
        f"rename from {old_path}\n"
        f"rename to {new_path}\n"
    )


def test_parse_diff_records_a_pure_rename_without_chunks() -> None:
    files = lint_rule_evidence._parse_diff(_PURE_RENAME_INTO_RULES)
    assert len(files) == 1
    assert files[0].pure_rename is True
    assert (files[0].old_path, files[0].new_path) == (
        "scripts/notes.md",
        ".claude/rules/renamed-pure.md",
    )
    assert files[0].chunks == []


def test_parse_diff_rename_with_hunks_is_one_file_not_two() -> None:
    """帶內容變更的 rename 同時有 `rename from/to` 與 `---`/`+++`；不可被算成兩個檔案。"""
    diff = _rename_diff("scripts/notes.md", ".claude/rules/renamed-in.md", ["# T", "內文。"])
    files = lint_rule_evidence._parse_diff(diff)
    assert len(files) == 1
    assert files[0].pure_rename is False
    assert files[0].added_lines == ["# T", "內文。"]


def test_parse_diff_keeps_neighbours_of_a_pure_rename() -> None:
    """純 rename 夾在其他檔案之間、以及排在最後（EOF 沒有下一個 `diff --git`）都要被收到。"""
    diff = (
        _new_file_diff(".claude/rules/29-first.md", ["# First", "內文。"])
        + _pure_rename_diff("scripts/a.md", ".claude/rules/middle.md")
        + _existing_file_diff(".claude/rules/13-bash-anti-patterns.md", ["補一句。"])
        + _pure_rename_diff("scripts/b.md", ".claude/rules/last.md")
    )
    files = lint_rule_evidence._parse_diff(diff)
    assert [(f.new_path, f.pure_rename) for f in files] == [
        (".claude/rules/29-first.md", False),
        (".claude/rules/middle.md", True),
        (".claude/rules/13-bash-anti-patterns.md", False),
        (".claude/rules/last.md", True),
    ]


def test_pure_rename_into_rules_is_error() -> None:
    """
    spec: rule-mechanization-gate#pure-rename-into-the-rules-directory-is-rejected
    tc: RMG-DT-015
    """
    errors = lint_rule_evidence.check_rule_mechanization(_PURE_RENAME_INTO_RULES, _fake_read)
    assert len(errors) == 1
    assert ".claude/rules/renamed-pure.md" in errors[0] and "純 rename" in errors[0]


def test_pure_rename_within_rules_or_elsewhere_is_not_flagged() -> None:
    """只擋「從 rules 目錄外進來」：目錄內改名是既有檔；與 rules 無關的 rename 不是本 gate 的事。

    spec: rule-mechanization-gate#pure-rename-that-stays-inside-the-rules-directory-is-not-flagged
    tc: RMG-DT-016
    """
    for old, new in [
        (".claude/rules/old.md", ".claude/rules/new.md"),
        (".claude/rules/old.md", "docs/moved-out.md"),
        ("scripts/a.md", "scripts/b.md"),
    ]:
        diff = _pure_rename_diff(old, new)
        assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == [], (old, new)


def test_pure_rename_does_not_change_the_evidence_lint() -> None:
    """純 rename 只由機械化檢查擋下，證據 lint 的結果不變，避免同一件事被兩個 lint 重複回報。

    spec: rule-mechanization-gate#pure-rename-is-reported-once-by-the-declaration-check
    tc: RMG-EG-020
    """
    assert lint_rule_evidence.check_rule_evidence(_PURE_RENAME_INTO_RULES) == []
    assert lint_rule_evidence.warn_rule_evidence(_PURE_RENAME_INTO_RULES) == []


def test_real_git_pure_rename_is_blocked_in_staged_and_range_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真實 git 輸出（不是手寫 fixture）：`git mv` 進 .claude/rules/ 後兩個執行點都要擋。

    spec: rule-mechanization-gate#pure-rename-into-the-rules-directory-is-rejected
    spec: rule-mechanization-gate#both-execution-points-run-the-declaration-check
    tc: RMG-DT-015, RMG-DT-024
    """
    _init_repo(tmp_path)
    notes = tmp_path / "scripts" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("# Notes\n\n## Section\n\n內文。(Source: PR #339)\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed notes")
    base = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    (tmp_path / ".claude" / "rules").mkdir(parents=True)

    _git(tmp_path, "mv", "scripts/notes.md", ".claude/rules/moved-in.md")
    assert lint_rule_evidence.main([]) == 1, "staged 模式"

    _git(tmp_path, "commit", "-q", "-m", "move notes into rules")
    head = _git(tmp_path, "rev-parse", "HEAD")
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1, "range 模式"


# --- 無法驗證連結時大聲失敗 ---


def test_unverifiable_link_exits_2_and_never_prints_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    spec: rule-mechanization-gate#unverifiable-gate-link-exits-2
    tc: RMG-EG-021
    """

    def unreadable(path: str) -> str | None:
        raise PermissionError(f"denied: {path}")

    diff_file = tmp_path / "link.diff"
    diff_file.write_text(_fixture_text("good_valid_link.diff"), encoding="utf-8")

    rc = lint_rule_evidence.main([str(diff_file)], read_gate_file=unreadable)

    captured = capsys.readouterr()
    assert rc == 2
    assert "[FAIL]" in captured.err
    assert "[OK]" not in captured.out


# --- scenario 專屬測試：每個 spec scenario 至少有一個直接斷言其 WHEN/THEN 的測試 ---
#
# 下面這幾個 scenario 原本只被參數化的 fixture 測試間接覆蓋，或根本沒有測試（「宣告在 heading
# 的 hunk 之外」就是補 testplan 時發現 spec 有寫、卻從沒被測過的一條）。


def test_two_declarations_in_one_section_are_rejected() -> None:
    """同一個 section 的連結 + 豁免、或兩個連結，互相矛盾或重複。

    spec: rule-mechanization-gate#two-declarations-in-one-section-are-rejected
    tc: RMG-DT-004
    """
    link = "<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->"
    exemption = (
        "<!-- gate: none (reason: judgment) — 同一個 section 不能同時宣稱有 gate 又宣稱沒有 -->"
    )
    for declarations in ([link, exemption], [link, link]):
        diff = _existing_rule_section_diff(declarations)
        errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
        assert errors and "2 個宣告" in errors[0], declarations


def test_link_to_a_nonexistent_path_names_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """dangling link：exit 非零，且錯誤輸出點名那個不存在的路徑。

    spec: rule-mechanization-gate#link-to-a-nonexistent-path-is-an-error
    tc: RMG-VL-005
    """
    diff_file = tmp_path / "dangling.diff"
    diff_file.write_text(_fixture_text("bad_dangling_link_existing_file.diff"), encoding="utf-8")

    assert lint_rule_evidence.main([str(diff_file)]) == 1
    assert "scripts/does_not_exist.py" in capsys.readouterr().err


def test_link_to_a_rule_file_is_rejected_as_not_a_gate() -> None:
    """目標檔案存在（假檔案系統裡有）但是 rule 檔：被拒絕的理由是資格，不是存在性。

    spec: rule-mechanization-gate#link-to-another-rule-file-is-rejected
    tc: RMG-VL-006
    """
    diff = _existing_rule_section_diff(["<!-- gate: .claude/rules/13-bash-anti-patterns.md -->"])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert errors and "rule 檔" in errors[0] and "不算 gate" in errors[0]


def test_unknown_exemption_reason_is_rejected() -> None:
    """reason 不在封閉列舉內：點名那個 reason，且不因說明夠長而通過。

    spec: rule-mechanization-gate#unknown-reason-is-rejected
    tc: RMG-VL-008
    """
    diff = _existing_rule_section_diff(
        ["<!-- gate: none (reason: other) — 這個理由不在封閉列舉內所以必須被擋下 -->"]
    )
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert errors and "other" in errors[0] and "封閉列舉" in errors[0]


def test_new_rule_file_without_declaration_exits_one() -> None:
    """新 rule 檔的 section 缺宣告：main() exit 1。

    spec: rule-mechanization-gate#new-rule-file-without-declarations-fails
    tc: RMG-DT-011
    """
    assert (
        lint_rule_evidence.main([str(_FIXTURE_DIR / "bad_missing_declaration_new_file.diff")]) == 1
    )


def test_new_file_without_sections_or_declaration_exits_one() -> None:
    """沒有任何 ##/### 的新 rule 檔也要檔案層級宣告，否則整份檔案會逃過檢查。

    spec: rule-mechanization-gate#new-rule-file-without-any-section-needs-a-file-level-declaration
    tc: RMG-DT-017
    """
    assert lint_rule_evidence.main([str(_FIXTURE_DIR / "bad_new_file_no_sections.diff")]) == 1


def test_declaration_outside_the_headings_hunk_is_reported_missing(tmp_path: Path) -> None:
    """宣告在別的 hunk（heading 插在既有內文之上，宣告落在未變動行）：保守地報缺宣告。

    spec: rule-mechanization-gate#declaration-outside-the-headings-hunk-is-reported-missing
    tc: RMG-DT-013
    """
    diff = _existing_file_diff_multi_hunk(
        ".claude/rules/13-bash-anti-patterns.md",
        ["### Heading Above Existing Body", "", "(Source: PR #339)"],
        ["<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->"],
    )
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert errors and "Heading Above Existing Body" in errors[0]

    diff_file = tmp_path / "two-hunks.diff"
    diff_file.write_text(diff, encoding="utf-8")
    assert lint_rule_evidence.main([str(diff_file)]) == 1


# --- production 預設讀檔函式：只有「不存在」是答案，其他 OS 錯誤是「無法驗證」---


def test_default_reader_maps_only_absence_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real.py").write_text("def sym():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "blob.dat").write_bytes(b"\xff\xfe\x00")
    read = lint_rule_evidence._read_repo_file

    assert "def sym" in (read("scripts/real.py") or "")
    assert read("scripts/absent.py") is None
    assert read("scripts") is None, "連結指到目錄不是 gate 檔"
    assert read("scripts/real.py/child") is None, "NotADirectoryError 等同不存在"
    assert read("scripts/blob.dat") == "", "存在但不是文字檔：連結成立、沒有 symbol 可比對"


def test_default_reader_does_not_swallow_other_os_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """權限錯誤等代表無法驗證，必須 raise 給 `main()` 轉 exit 2，不可吞成「不存在」。

    spec: rule-mechanization-gate#unverifiable-gate-link-exits-2
    tc: RMG-EG-021
    """
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real.py").write_text("x = 1\n", encoding="utf-8")

    def denied(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(f"denied: {self}")

    monkeypatch.setattr(Path, "read_text", denied)

    with pytest.raises(PermissionError):
        lint_rule_evidence._read_repo_file("scripts/real.py")


# --- 新檔沒有任何 section 時的檔案層級宣告 ---


def test_new_file_without_sections_accepts_a_file_level_declaration() -> None:
    """
    spec: rule-mechanization-gate#new-rule-file-without-any-section-needs-a-file-level-declaration
    tc: RMG-DT-017
    """
    diff = _new_file_diff(
        ".claude/rules/27-flat.md",
        [
            "# Flat",
            "",
            "內文。(Source: PR #339)",
            "<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->",
        ],
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []


# --- 真實資料對照 ---

_REAL_RULE = ".claude/rules/05-pydantic-models.md"
_INJECTED_HEADING = "### Injected Undeclared Section"


def _inject_section(text: str, declaration: str | None) -> str:
    """在真實 rule 檔第一個 `## ` heading 前插入一個新 section；找不到錨點就 raise。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            injected = [_INJECTED_HEADING, "", "注入的內文。(Source: PR #339)"]
            if declaration is not None:
                injected.append(declaration)
            injected.append("")
            return "\n".join(lines[:index] + injected + lines[index:]) + "\n"
    raise LookupError(f"找不到注入錨點（`## ` heading）：{_REAL_RULE}")


def _real_rule_diff(declaration: str | None) -> str:
    import difflib

    original = (lint_rule_evidence.REPO_ROOT / _REAL_RULE).read_text(encoding="utf-8")
    modified = _inject_section(original, declaration)
    body = difflib.unified_diff(
        original.splitlines(),
        modified.splitlines(),
        fromfile=f"a/{_REAL_RULE}",
        tofile=f"b/{_REAL_RULE}",
        n=0,
        lineterm="",
    )
    return f"diff --git a/{_REAL_RULE} b/{_REAL_RULE}\n" + "\n".join(body) + "\n"


def test_real_rule_copy_with_injected_section_is_flagged() -> None:
    errors = lint_rule_evidence.check_rule_mechanization(_real_rule_diff(None), _fake_read)
    assert errors and "Injected Undeclared Section" in errors[0]


def test_real_rule_copy_with_declared_section_is_clean() -> None:
    """對照的對照：同一份真實檔案、同一個注入，只差宣告，反應必須翻轉。"""
    diff = _real_rule_diff("<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->")
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []


def test_injection_anchor_missing_fails() -> None:
    """
    spec: rule-mechanization-gate#injection-anchor-absent-fails-the-control
    tc: RMG-VL-022
    """
    with pytest.raises(LookupError):
        _inject_section("# 只有 H1\n\n沒有二級標題。\n", None)


# =====================================================================================
# PR #528 review 修補（一）：lint 讀 diff 的方式與 gate 連結的資料來源
#
# 下面的測試全部用真實 git 在暫存 repo 產生 diff，不手寫 git 輸出：這一組缺陷（C-style 引號、
# 使用者的 diff 設定、binary / 空檔 / copy 的輸出形狀）都是「git 實際輸出的形狀與手寫 fixture
# 不同」造成的，手寫 fixture 只會證明 parser 讀得懂自己想像的輸入。
# =====================================================================================

_UNDECLARED = "# T\n\n## Section\n\n內文。(Source: PR #339)\n"
_DECLARED = _UNDECLARED + _VALID_EXEMPTION


def _real_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _init_repo(tmp_path)
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", tmp_path)
    return tmp_path


def _put(repo: Path, rel: str, content: str | bytes) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


# --- C-style 引號：非 ASCII / 特殊字元檔名不可讓整個檔案對兩個 lint 隱形 ---


@pytest.mark.parametrize("filename", ["規則.md", 'a"b.md', "tab\tname.md"])
def test_special_filename_new_rule_file_is_checked_in_staged_and_range_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    filename: str,
) -> None:
    """git 預設把非 ASCII 與特殊字元路徑 C-style 引號成 `"b/\\350..."`，舊 parser 留著開頭的引號，
    路徑正則對不上，整個檔案靜默通過（exit 0 `[OK]`）。

    spec: rule-mechanization-gate#non-ascii-and-special-character-paths-are-checked
    tc: RMG-DT-026
    """
    repo = _real_repo(tmp_path, monkeypatch)
    base = _git(repo, "rev-parse", "HEAD")
    rel = f".claude/rules/{filename}"
    _put(repo, rel, _UNDECLARED)
    _git(repo, "add", "-A")

    assert lint_rule_evidence.main([]) == 1, "staged 模式：未宣告的特殊檔名 rule 檔必須被擋下"
    err = capsys.readouterr().err
    assert filename in err and "缺少機械化宣告" in err, "錯誤輸出要點名真實檔名，不是引號形式"

    head1 = _commit_all(repo, "add undeclared rule")
    assert lint_rule_evidence.main(["--base", base, "--head", head1]) == 1, "range 模式"

    # 對照：同樣特殊檔名、宣告齊全的另一個檔案必須通過（不能因為修補而誤擋）
    _put(repo, f".claude/rules/declared-{filename}", _DECLARED)
    _git(repo, "add", "-A")
    assert lint_rule_evidence.main([]) == 0, "對照：宣告齊全的特殊檔名不得誤報"
    head2 = _commit_all(repo, "add declared rule")
    assert lint_rule_evidence.main(["--base", head1, "--head", head2]) == 0


def test_cjk_pure_rename_into_rules_is_blocked_in_staged_and_range_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """純 rename 的 `rename to "..."` 同樣被引號：CJK 檔名的 `git mv` 進 rules 曾經完全隱形。

    spec: rule-mechanization-gate#non-ascii-and-special-character-paths-are-checked
    tc: RMG-DT-026
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, "scripts/筆記.md", _UNDECLARED)
    base = _commit_all(repo, "seed notes")
    (repo / ".claude" / "rules").mkdir(parents=True)

    _git(repo, "mv", "scripts/筆記.md", ".claude/rules/筆記.md")
    assert lint_rule_evidence.main([]) == 1, "staged 模式"
    assert ".claude/rules/筆記.md" in capsys.readouterr().err

    head = _commit_all(repo, "move notes into rules")
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1, "range 模式"


def test_diff_file_with_git_default_quoting_is_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positional diff 檔模式讀到的是別處產生的 diff（可能是 git 預設引號形式）：同樣要解碼。

    spec: rule-mechanization-gate#non-ascii-and-special-character-paths-are-checked
    tc: RMG-DT-026
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, ".claude/rules/規則.md", _UNDECLARED)
    _git(repo, "add", "-A")
    raw = _git(
        repo,
        "-c",
        "core.quotePath=true",
        "diff",
        "--cached",
        "--unified=0",
        "--src-prefix=a/",
        "--dst-prefix=b/",
    )
    assert '+++ "b/.claude/rules/\\350\\246\\217\\345\\211\\207.md"' in raw, (
        "錨點：git 真的輸出了引號形式"
    )
    diff_file = tmp_path.parent / f"{tmp_path.name}-quoted.diff"
    diff_file.write_text(raw + "\n", encoding="utf-8")

    assert lint_rule_evidence.main([str(diff_file)]) == 1


def test_undecodable_quoted_path_is_checked_not_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """引號裡不是合法 UTF-8 的路徑以 surrogateescape 保留位元組，照樣判定是不是 rules 檔並檢查。

    舊行為是 exit 2；現在整份 diff 以 bytes 讀入、surrogateescape 解碼，非 UTF-8 的檔名不再是
    「看不懂所以放棄」，而是被檢查（缺證據即 exit 1），訊息輸出也不可因為 surrogate 而崩潰。

    spec: rule-mechanization-gate#non-utf8-input-neither-crashes-nor-bypasses
    tc: RMG-DT-049
    """
    diff = (
        'diff --git "a/x" "b/\\377\\376.md"\n'
        "new file mode 100644\n"
        "--- /dev/null\n"
        '+++ "b/.claude/rules/\\377\\376.md"\n'
        "@@ -0,0 +1 @@\n"
        "+內容\n"
    )
    diff_file = tmp_path / "bad-quote.diff"
    diff_file.write_text(diff, encoding="utf-8")

    assert lint_rule_evidence.main([str(diff_file)]) == 1
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.err and "[OK]" not in captured.out


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain/path.md", "plain/path.md"),
        ('"a\\tb"', "a\tb"),
        ('"a\\"b"', 'a"b'),
        ('"a\\\\b"', "a\\b"),
        ('"a\\nb"', "a\nb"),
        ('"\\350\\246\\217\\345\\211\\207"', "規則"),
        ('"mix\\350\\246\\217-ascii"', "mix規-ascii"),
    ],
)
def test_unquote_c_path_decodes_git_escapes(raw: str, expected: str) -> None:
    """
    spec: rule-mechanization-gate#non-ascii-and-special-character-paths-are-checked
    tc: RMG-DT-026
    """
    assert lint_rule_evidence._unquote_c_path(raw) == expected


@pytest.mark.parametrize("raw", ['"unterminated', '"bad\\qescape"', '"\\35"'])
def test_unquote_c_path_rejects_what_it_cannot_decode(raw: str) -> None:
    """格式錯誤的引號（沒結尾、未知跳脫、不完整八進位）仍 raise，由 `main()` 轉 exit 2。

    spec: rule-mechanization-gate#undecodable-quoted-path-exits-2
    tc: RMG-EG-027
    """
    with pytest.raises(ValueError):
        lint_rule_evidence._unquote_c_path(raw)


@pytest.mark.parametrize("quoted", ['"b/unterminated', '"b/bad\\qescape.md"', '"b/\\35.md"'])
def test_malformed_quoted_path_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], quoted: str
) -> None:
    """格式錯誤的引號路徑（沒結尾、未知跳脫、不完整八進位）無法判定是不是 rules 檔：exit 2。

    spec: rule-mechanization-gate#undecodable-quoted-path-exits-2
    tc: RMG-EG-027
    """
    diff = (
        "diff --git a/x b/x\nnew file mode 100644\n--- /dev/null\n"
        f"+++ {quoted}\n@@ -0,0 +1 @@\n+內容\n"
    )
    diff_file = tmp_path / "malformed-quote.diff"
    diff_file.write_text(diff, encoding="utf-8")

    assert lint_rule_evidence.main([str(diff_file)]) == 2
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.err and "[OK]" not in captured.out


def test_unquote_c_path_keeps_non_utf8_bytes_instead_of_raising() -> None:
    """格式正確但位元組不是 UTF-8（`\\377`）：以 surrogateescape 保留，可比對 `.claude/rules/`。

    spec: rule-mechanization-gate#non-utf8-input-neither-crashes-nor-bypasses
    tc: RMG-DT-049
    """
    decoded = lint_rule_evidence._unquote_c_path('"\\377\\376.md"')

    assert decoded.encode("utf-8", errors="surrogateescape") == b"\xff\xfe.md"


# --- 使用者的 git 設定不可讓 staged 模式變成 no-op ---


@pytest.mark.parametrize("setting", ["color", "external", "textconv"])
def test_user_diff_config_cannot_turn_staged_mode_into_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    """`color.ui=always`、`diff.external`、textconv 都會改寫 `git diff` 的輸出，舊指令因此讀不到
    `+## Section` 而靜默通過；`--no-color --no-ext-diff --no-textconv` 把輸出釘回純文字。

    spec: rule-mechanization-gate#user-diff-configuration-cannot-hide-a-change
    tc: RMG-DT-028
    """
    repo = _real_repo(tmp_path, monkeypatch)
    if setting == "color":
        _git(repo, "config", "color.ui", "always")
    elif setting == "external":
        _git(repo, "config", "diff.external", "true")
    else:
        _put(repo, ".gitattributes", "*.md diff=hide\n")
        _git(repo, "config", "diff.hide.textconv", "true")
    _put(repo, ".claude/rules/30-cfg.md", _UNDECLARED)
    _git(repo, "add", "-A")

    raw = _git(repo, "diff", "--cached", "--unified=0")
    assert "\n+## Section" not in raw, f"錨點：{setting} 設定確實改壞了未加旗標的 git diff 輸出"
    assert lint_rule_evidence.main([]) == 1

    # 對照：宣告齊全的內容必須通過。textconv 讓新檔看起來像空檔，沒有 `--no-textconv` 時會被
    # 「空的新 rule 檔」fail-closed 擋下——只看上面那個 exit 1，這個旗標拿掉也不會有人發現。
    _put(repo, ".claude/rules/30-cfg.md", _DECLARED)
    _git(repo, "add", "-A")
    assert lint_rule_evidence.main([]) == 0


# --- copy 偵測：`diff.renames=copies` 不可讓 copy 進 rules 變成看不到內容 ---


@pytest.mark.parametrize("declared", [False, True])
def test_diff_renames_copies_config_cannot_hide_a_copy_into_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    declared: bool,
) -> None:
    """來源檔在同一次變更裡也被修改時，`diff.renames=copies` 會讓 git 輸出沒有 hunk 的
    `copy from/to`。明確的 `-M` 讓 git 改輸出一般的新檔 diff，lint 於是看得到內容：

    - 未宣告的內容：被擋下，且錯誤點名 section 標題（證明是內容被看見，不是 fail-closed 的盲擋）。
    - 宣告齊全的內容：通過（若退回只看 copy 標頭，合法的複製反而會被誤擋）。

    spec: rule-mechanization-gate#copy-into-the-rules-directory-is-rejected
    tc: RMG-DT-029
    """
    repo = _real_repo(tmp_path, monkeypatch)
    content = _DECLARED if declared else _UNDECLARED
    _put(repo, "scripts/notes.md", content)
    _commit_all(repo, "seed notes")
    _git(repo, "config", "diff.renames", "copies")
    _put(repo, ".claude/rules/copied.md", content)
    _put(repo, "scripts/notes.md", content + "額外一行。\n")
    _git(repo, "add", "-A")

    raw = _git(repo, "diff", "--cached", "--unified=0")
    assert "copy from scripts/notes.md" in raw, "錨點：未加 -M 時 git 真的輸出沒有 hunk 的 copy"

    rc = lint_rule_evidence.main([])
    err = capsys.readouterr().err
    if declared:
        assert rc == 0, err
    else:
        assert rc == 1
        assert "Section" in err and "純 copy" not in err


def test_copy_without_hunk_into_rules_is_rejected_by_the_parser_fallback() -> None:
    """即使輸出仍出現沒有 hunk 的 copy（例如非本 lint 產生的 diff 檔），也不可當成通過。

    spec: rule-mechanization-gate#copy-into-the-rules-directory-is-rejected
    tc: RMG-DT-029
    """
    errors = lint_rule_evidence.check_rule_mechanization(
        _fixture_text("bad_copy_into_rules.diff"), _fake_read
    )
    assert len(errors) == 1
    assert ".claude/rules/copied.md" in errors[0] and "copy" in errors[0]


def test_copy_between_rule_files_is_still_a_new_rule_file() -> None:
    """來源本身就在 rules 目錄內的 copy 也是新檔：不能套用「目錄內改名」的豁免。

    spec: rule-mechanization-gate#copy-into-the-rules-directory-is-rejected
    tc: RMG-DT-029
    """
    diff = (
        "diff --git a/.claude/rules/a.md b/.claude/rules/b.md\n"
        "similarity index 100%\n"
        "copy from .claude/rules/a.md\n"
        "copy to .claude/rules/b.md\n"
    )
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert len(errors) == 1 and ".claude/rules/b.md" in errors[0]


def test_copy_out_of_rules_is_not_flagged() -> None:
    diff = (
        "diff --git a/.claude/rules/a.md b/docs/a.md\n"
        "similarity index 100%\n"
        "copy from .claude/rules/a.md\n"
        "copy to docs/a.md\n"
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []


# --- 看不到內容的新 rule 檔：二進位與空檔 ---


def test_binary_new_rule_file_is_rejected_in_staged_and_range_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """含 NUL 的新檔被 git 判為 `Binary files /dev/null and b/<p> differ`：沒有 `+++`，
    舊 parser 建不出記錄，整個檔案靜默通過。證據 lint 的結果不變（仍忽略它）。

    spec: rule-mechanization-gate#binary-new-rule-file-is-rejected
    tc: RMG-DT-030
    """
    repo = _real_repo(tmp_path, monkeypatch)
    base = _git(repo, "rev-parse", "HEAD")
    _put(repo, ".claude/rules/31-bin.md", b"# B\n\x00\x01\n")
    _git(repo, "add", "-A")
    raw = lint_rule_evidence._staged_diff()
    assert "Binary files /dev/null and b/.claude/rules/31-bin.md differ" in raw, "錨點"

    assert lint_rule_evidence.main([]) == 1
    err = capsys.readouterr().err
    assert ".claude/rules/31-bin.md" in err and "二進位" in err

    head = _commit_all(repo, "add binary rule")
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1

    assert lint_rule_evidence.check_rule_evidence(raw) == [], "證據 lint 的既有行為不變"
    assert lint_rule_evidence.warn_rule_evidence(raw) == []


def test_empty_new_rule_file_is_rejected_in_staged_and_range_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """空的新檔只有 `new file mode` + `index`、沒有 `+++`。空檔沒有任何地方可以放宣告，
    檔案層級宣告規則因此一定不滿足。

    spec: rule-mechanization-gate#empty-new-rule-file-is-rejected
    tc: RMG-DT-031
    """
    repo = _real_repo(tmp_path, monkeypatch)
    base = _git(repo, "rev-parse", "HEAD")
    _put(repo, ".claude/rules/32-empty.md", "")
    _git(repo, "add", "-A")
    raw = lint_rule_evidence._staged_diff()
    assert "new file mode" in raw and "+++" not in raw, "錨點：空檔的 diff 沒有 `+++`"

    assert lint_rule_evidence.main([]) == 1
    err = capsys.readouterr().err
    assert ".claude/rules/32-empty.md" in err and "空" in err

    head = _commit_all(repo, "add empty rule")
    assert lint_rule_evidence.main(["--base", base, "--head", head]) == 1

    assert lint_rule_evidence.check_rule_evidence(raw) == []
    assert lint_rule_evidence.warn_rule_evidence(raw) == []


def test_binary_and_empty_files_outside_rules_are_not_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """對照：同樣的形狀放在 rules 目錄之外，不是本 gate 的事。"""
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, "scripts/blob.bin", b"\x00\x01\x02")
    _put(repo, "scripts/empty.txt", "")
    _git(repo, "add", "-A")

    assert lint_rule_evidence.main([]) == 0


# --- gate 連結的資料來源：看「將被 commit / 被審查」的內容，不是工作樹 ---


def test_staged_mode_reads_the_gate_from_the_index_not_the_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """只存在於磁碟、沒有 stage 的 gate script，commit 之後連結就是 dangling：舊實作讀工作樹，
    誤報通過；反過來，已 stage 但磁碟上已不在的 gate 連結其實有效，不該誤擋。

    spec: rule-mechanization-gate#staged-mode-reads-gate-links-from-the-index
    tc: RMG-DT-032
    """
    repo = _real_repo(tmp_path, monkeypatch)
    link = "<!-- gate: scripts/new_gate.py::gate -->\n"
    _put(repo, ".claude/rules/33-link.md", _UNDECLARED + link)
    _put(repo, "scripts/new_gate.py", "def gate():\n    pass\n")
    _git(repo, "add", ".claude/rules/33-link.md")  # gate script 刻意不 stage

    assert lint_rule_evidence.main([]) == 1, "gate 只在磁碟上：commit 後會是 dangling link"
    assert "scripts/new_gate.py" in capsys.readouterr().err

    _git(repo, "add", "scripts/new_gate.py")
    assert lint_rule_evidence.main([]) == 0, "對照：gate 已 stage 則通過"

    (repo / "scripts" / "new_gate.py").write_text("# 工作樹版本沒有 symbol\n", encoding="utf-8")
    assert lint_rule_evidence.main([]) == 0, "symbol 比對用 index 的內容，不是工作樹"

    (repo / "scripts" / "new_gate.py").unlink()
    assert lint_rule_evidence.main([]) == 0, "對照：index 有、磁碟沒有，連結有效"


def test_range_mode_reads_the_gate_from_the_requested_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """range 模式審的是 `--head`：checkout 在別的 commit 時，不可拿 checkout 的內容當答案。

    spec: rule-mechanization-gate#range-mode-reads-gate-links-from-the-head
    tc: RMG-DT-033
    """
    repo = _real_repo(tmp_path, monkeypatch)
    base = _git(repo, "rev-parse", "HEAD")
    link = "<!-- gate: scripts/new_gate.py -->\n"

    _put(repo, ".claude/rules/34-link.md", _UNDECLARED + link)
    _put(repo, "scripts/new_gate.py", "def gate():\n    pass\n")
    head_with_gate = _commit_all(repo, "rule and gate")
    _git(repo, "checkout", "-q", base)
    assert not (repo / "scripts" / "new_gate.py").exists(), "錨點：checkout 不含 gate"
    assert lint_rule_evidence.main(["--base", base, "--head", head_with_gate]) == 0

    # 對照：head 沒有 gate，但目前 checkout 的工作樹有 -> 仍須判為 dangling
    _git(repo, "checkout", "-q", "-b", "gate-only", base)
    _put(repo, "scripts/new_gate.py", "def gate():\n    pass\n")
    _commit_all(repo, "gate only")
    _git(repo, "checkout", "-q", "-b", "rule-only", base)
    _put(repo, ".claude/rules/34-link.md", _UNDECLARED + link)
    head_without_gate = _commit_all(repo, "rule only")
    _git(repo, "checkout", "-q", "gate-only")
    assert (repo / "scripts" / "new_gate.py").exists(), "錨點：checkout 含 gate"
    assert lint_rule_evidence.main(["--base", base, "--head", head_without_gate]) == 1


def test_diff_file_mode_reads_the_gate_from_the_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positional diff 檔不帶 git 脈絡，沒有 index 或 head 可讀，所以讀工作樹（文件化的行為）。

    spec: rule-mechanization-gate#diff-file-mode-reads-gate-links-from-the-working-tree
    tc: RMG-DT-034
    """
    repo = _real_repo(tmp_path, monkeypatch)
    diff = _existing_rule_section_diff(["<!-- gate: scripts/new_gate.py -->"])
    diff_file = tmp_path.parent / f"{tmp_path.name}-link.diff"
    diff_file.write_text(diff, encoding="utf-8")

    assert lint_rule_evidence.main([str(diff_file)]) == 1
    _put(repo, "scripts/new_gate.py", "def gate():\n    pass\n")
    assert lint_rule_evidence.main([str(diff_file)]) == 0


def test_git_failure_while_reading_a_gate_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """讀 gate 時 git 本身失敗不是「路徑不存在」：必須 exit 2，不可吞成連結有效或無效。

    spec: rule-mechanization-gate#git-failure-while-reading-a-gate-exits-2
    tc: RMG-EG-035
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, ".claude/rules/35-link.md", _UNDECLARED + "<!-- gate: scripts/g.py -->\n")
    _put(repo, "scripts/g.py", "x = 1\n")
    _git(repo, "add", "-A")
    assert lint_rule_evidence.main([]) == 0, "前提：不壞掉時是通過的"
    capsys.readouterr()

    def broken(*_args: object, **_kwargs: object) -> bytes:
        raise OSError("simulated git failure")

    monkeypatch.setattr(lint_rule_evidence, "_git_bytes", broken)
    assert lint_rule_evidence.main([]) == 2
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.err and "[OK]" not in captured.out


def test_git_gate_reader_raises_for_an_unresolvable_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spec: rule-mechanization-gate#git-failure-while-reading-a-gate-exits-2
    tc: RMG-EG-035
    """
    _real_repo(tmp_path, monkeypatch)
    read = lint_rule_evidence._git_gate_reader("0" * 40)
    with pytest.raises(OSError):
        read("scripts/x.py")


@pytest.mark.parametrize("ref", [None, "HEAD"])
def test_git_gate_reader_only_accepts_an_exact_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str | None
) -> None:
    """連到目錄、或帶 glob 字元的路徑不是 gate 檔：只有精確路徑的 blob 才算存在。

    spec: rule-mechanization-gate#link-to-a-directory-is-treated-as-absent
    tc: RMG-VL-036
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, "scripts/sub/a.py", "def a():\n    pass\n")
    _put(repo, "scripts/b.py", "def b():\n    pass\n")
    _commit_all(repo, "add scripts")
    read = lint_rule_evidence._git_gate_reader(ref)

    assert "def a" in (read("scripts/sub/a.py") or "")
    assert read("scripts/sub") is None, "目錄不是 gate 檔"
    assert read("scripts/*.py") is None, "pathspec glob 不可展開成別的檔案"
    assert read("scripts/absent.py") is None


@pytest.mark.parametrize("ref", [None, "HEAD"])
def test_git_gate_reader_treats_the_path_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str | None
) -> None:
    """檔名本身含 glob 字元（`[1]`）時，連結要精確指到那個檔案，而不是被當成 pattern 後找不到自己。

    spec: rule-mechanization-gate#link-to-a-directory-is-treated-as-absent
    tc: RMG-VL-036
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, "scripts/x[1].py", "def literal():\n    pass\n")
    _commit_all(repo, "add bracket-named gate")

    assert "def literal" in (lint_rule_evidence._git_gate_reader(ref)("scripts/x[1].py") or "")


def test_git_gate_reader_refuses_an_unmerged_index_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """合併衝突中的檔案（index stage 非 0）無法判定內容：raise，不可挑一個 stage 當答案。

    spec: rule-mechanization-gate#git-failure-while-reading-a-gate-exits-2
    tc: RMG-EG-035
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, "scripts/g.py", "x = 0\n")
    base = _commit_all(repo, "seed gate")
    _git(repo, "checkout", "-q", "-b", "side", base)
    _put(repo, "scripts/g.py", "x = 'side'\n")
    _commit_all(repo, "side edit")
    _git(repo, "checkout", "-q", "main")
    _put(repo, "scripts/g.py", "x = 'main'\n")
    _commit_all(repo, "main edit")
    merge = subprocess.run(  # nosec B603
        ["git", "-C", str(repo), "merge", "side"], capture_output=True, text=True, check=False
    )
    assert merge.returncode != 0, "錨點：這個合併必須真的產生衝突"

    with pytest.raises(OSError):
        lint_rule_evidence._git_gate_reader(None)("scripts/g.py")


def test_staged_diff_does_not_quote_non_ascii_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-c core.quotePath=false` 讓非 ASCII 路徑照原樣輸出（解碼器是第二道防線，不是唯一一道）。

    spec: rule-mechanization-gate#non-ascii-and-special-character-paths-are-checked
    tc: RMG-DT-026
    """
    repo = _real_repo(tmp_path, monkeypatch)
    _put(repo, ".claude/rules/規則.md", _UNDECLARED)
    _git(repo, "add", "-A")

    assert "+++ b/.claude/rules/規則.md" in lint_rule_evidence._staged_diff()


# =====================================================================================
# PR #528 review 修補（二）：section 的切法（fence、改標題、同一 hunk 多個 section）與邊界釘死
# =====================================================================================

_EXEMPTION_LINE = "<!-- gate: none (reason: judgment) — 這個判斷需要讀完整個 prompt 才能做 -->"
_RULE_13 = ".claude/rules/13-bash-anti-patterns.md"


def _hunk_diff(path: str, removed: list[str], added: list[str]) -> str:
    """帶有被移除行的單一 hunk（`--unified=0`）；用來構造「改標題」這類形狀。"""
    rem = "".join(f"-{line}\n" for line in removed)
    add = "".join(f"+{line}\n" for line in added)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -10,{len(removed)} +10,{len(added)} @@\n{rem}{add}"
    )


# --- fenced code block 內的 heading 不是 section ---


@pytest.mark.parametrize(
    "fence",
    [
        ["```markdown", "## When to use", "## Steps", "```"],
        ["~~~markdown", "## When to use", "## Steps", "~~~"],
        ["````markdown", "```", "## When to use", "```", "## Steps", "````"],
    ],
    ids=["backtick", "tilde", "nested-longer-fence"],
)
def test_heading_inside_a_code_fence_is_not_a_section(fence: list[str]) -> None:
    """rule 11 之類的文件會在 fence 裡示範 `## When to use`：那不是新 section，錯誤也沒有辦法修
    （宣告放在哪都救不了一個不存在的 section）。

    spec: rule-mechanization-gate#heading-inside-a-code-fence-is-not-a-section
    tc: RMG-EP-037
    """
    body = ["### Real Section", "", "(Source: PR #339)", _EXEMPTION_LINE, "", *fence]
    diff = _existing_file_diff(_RULE_13, body)

    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []
    assert lint_rule_evidence.warn_rule_evidence(diff) == [], "證據檢查共用同一個切法"


def test_heading_after_a_closed_fence_is_still_a_section() -> None:
    """對照：fence 關閉之後的 heading 仍是 section，不能因為前面出現過 fence 就整段放行。

    spec: rule-mechanization-gate#heading-inside-a-code-fence-is-not-a-section
    tc: RMG-EP-037
    """
    body = ["### Real Section", _EXEMPTION_LINE, "(Source: PR #339)", "```", "## Inside", "```"]
    body += ["### After Fence", "(Source: PR #339)"]
    errors = lint_rule_evidence.check_rule_mechanization(
        _existing_file_diff(_RULE_13, body), _fake_read
    )
    assert len(errors) == 1 and "After Fence" in errors[0]


def test_tilde_fenced_declaration_does_not_count() -> None:
    """宣告引用在 `~~~` fence 裡同樣只是範例（過去只認 backtick fence）。

    spec: rule-mechanization-gate#declaration-quoted-in-a-code-fence-does-not-count
    tc: RMG-DT-003
    """
    diff = _existing_rule_section_diff(
        ["~~~text", "<!-- gate: scripts/lint_rule_evidence.py -->", "~~~"]
    )
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read)


# --- 改標題不是新 section ---


def test_retitled_heading_is_not_a_new_section() -> None:
    """`-### Old` / `+### New` 是改標題：既有 section 不回溯補宣告（Non-goal），不可擋 commit。

    spec: rule-mechanization-gate#retitled-heading-is-not-a-new-section
    tc: RMG-DT-038
    """
    diff = _hunk_diff(_RULE_13, ["### Old Title", "內文。"], ["### New Title", "內文。"])

    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []
    assert lint_rule_evidence.warn_rule_evidence(diff) == []
    assert lint_rule_evidence.check_rule_evidence(diff) == []


def test_heading_whose_level_changed_is_still_checked() -> None:
    """對照：同一段文字但層級不同（`##` -> `###`）不算改標題，仍是一個新 section。

    spec: rule-mechanization-gate#retitled-heading-is-not-a-new-section
    tc: RMG-DT-038
    """
    diff = _hunk_diff(_RULE_13, ["## Same Words"], ["### Same Words", "內文。(Source: PR #339)"])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert len(errors) == 1 and "Same Words" in errors[0]


def test_each_removed_heading_excuses_only_one_added_heading() -> None:
    """對照：改標題只豁免「一對一」；多出來的新 heading 仍是新 section。

    spec: rule-mechanization-gate#retitled-heading-is-not-a-new-section
    tc: RMG-DT-038
    """
    diff = _hunk_diff(
        _RULE_13,
        ["### Old Title", "內文。"],
        ["### New Title", "內文。", "### Brand New", "(Source: PR #339)"],
    )
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert len(errors) == 1 and "Brand New" in errors[0]


def test_removed_heading_in_another_hunk_does_not_excuse_an_added_one() -> None:
    """被移除的 heading 只在「同一個 hunk」內豁免新增的 heading，不跨 hunk 借用。

    spec: rule-mechanization-gate#retitled-heading-is-not-a-new-section
    tc: RMG-DT-038
    """
    diff = (
        f"diff --git a/{_RULE_13} b/{_RULE_13}\n--- a/{_RULE_13}\n+++ b/{_RULE_13}\n"
        "@@ -10 +9,0 @@\n-### Gone Elsewhere\n"
        "@@ -50,0 +50,2 @@\n+### Truly New\n+(Source: PR #339)\n"
    )
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert len(errors) == 1 and "Truly New" in errors[0]


def test_retitled_heading_fixture_reports_nothing() -> None:
    """committed 的真實 git 形狀：改標題的 diff 通過兩個入口。

    spec: rule-mechanization-gate#retitled-heading-is-not-a-new-section
    tc: RMG-DT-038
    """
    diff = _fixture_text("good_retitled_heading.diff")
    assert "\n-### " in diff and "\n+### " in diff, "錨點：fixture 真的含一對被移除與新增的 heading"
    assert lint_rule_evidence.check_rule_mechanization(diff, _fake_read) == []
    assert lint_rule_evidence.main([str(_FIXTURE_DIR / "good_retitled_heading.diff")]) == 0


# --- 同一個 hunk 裡的每個 section 都要各自檢查 ---


def test_second_undeclared_section_in_one_hunk_is_reported_exactly_once() -> None:
    """第一個 section 有宣告、第二個沒有：只報第二個。能讓「只檢查第一個」的實作現形。

    spec: rule-mechanization-gate#every-section-in-a-hunk-is-checked
    tc: RMG-DT-039
    """
    body = [
        "### Declared First",
        "(Source: PR #339)",
        _EXEMPTION_LINE,
        "### Undeclared Second",
        "(Source: PR #339)",
    ]
    errors = lint_rule_evidence.check_rule_mechanization(
        _existing_file_diff(_RULE_13, body), _fake_read
    )
    assert len(errors) == 1 and "Undeclared Second" in errors[0]
    assert "Declared First" not in errors[0]


def test_first_undeclared_section_in_one_hunk_is_reported_exactly_once() -> None:
    """順序相反：第一個沒宣告、第二個有。能讓「只檢查最後一個」的實作現形。

    spec: rule-mechanization-gate#every-section-in-a-hunk-is-checked
    tc: RMG-DT-039
    """
    body = [
        "### Undeclared First",
        "(Source: PR #339)",
        "### Declared Second",
        "(Source: PR #339)",
        _EXEMPTION_LINE,
    ]
    errors = lint_rule_evidence.check_rule_mechanization(
        _existing_file_diff(_RULE_13, body), _fake_read
    )
    assert len(errors) == 1 and "Undeclared First" in errors[0]
    assert "Declared Second" not in errors[0]


def test_a_declaration_belongs_to_the_section_it_follows_not_the_next_one() -> None:
    """兩個 section 各自帶宣告：互不侵佔，也不會被誤判成「同一個 section 兩個宣告」。

    spec: rule-mechanization-gate#every-section-in-a-hunk-is-checked
    tc: RMG-DT-039
    """
    body = ["### One", _EXEMPTION_LINE, "(Source: PR #339)", "### Two", _EXEMPTION_LINE]
    body.append("(Source: PR #339)")
    assert (
        lint_rule_evidence.check_rule_mechanization(_existing_file_diff(_RULE_13, body), _fake_read)
        == []
    )


# --- 豁免說明的長度邊界與空白處理 ---


@pytest.mark.parametrize(
    ("explanation", "accepted"),
    [
        ("abcdefghijk", False),  # 11 個非空白字元：差一個
        ("abcdefghijkl", True),  # 12 個：恰好達標
        ("abcdef ghijk", False),  # 含空白共 12 個字元但只有 11 個非空白：空白不可算進去
        ("abcdef ghijkl", True),  # 12 個非空白，中間有空白
        ("   abcdefghijk   ", False),  # 前後空白不可把 11 個字元墊成 17 個
    ],
)
def test_exemption_explanation_length_boundary(explanation: str, accepted: bool) -> None:
    """下限是「12 個非空白字元」：差一個要擋、空白不算數、前後空白不能墊高長度。

    spec: rule-mechanization-gate#exemption-explanation-length-boundary
    tc: RMG-BVA-040
    """
    diff = _existing_rule_section_diff([f"<!-- gate: none (reason: judgment) — {explanation} -->"])
    errors = lint_rule_evidence.check_rule_mechanization(diff, _fake_read)
    assert (errors == []) is accepted, f"{explanation!r} -> {errors}"
