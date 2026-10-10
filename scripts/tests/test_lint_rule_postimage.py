"""lint_rule_evidence 的「完整 post-image」行為：以真實 git 驗證（Round 2 的四個 Critical 與其對照組）。

背景：舊版以 `--unified=0` 的 hunk 局部資訊推論 fence 狀態、改標題與二進位，這些資訊天生不完整：
git 會把舊的結尾 fence 對齊進 hunk、被刪掉的 fence 內「heading」會被當成真的、被 git 判為 binary 的既有
rule 檔整個隱形、`git add -N` 的 gate 被當成已存在。現在 lint 讀**完整 context 的 diff**
（`--unified=1000000`，每個檔案是單一 hunk，等於 index / head 的整份 post-image），staged 模式的
gate 則對 `git write-tree`（就是 `git commit` 會 commit 的樹）驗證。

每個測試都帶對照組：同一份輸入換成合法的版本必須通過，才證明測的是這個行為而不是探針本身。
測試不依賴執行機器的全域 git 設定（autouse fixture 把全域與系統設定關掉）。
"""

import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lint_rule_evidence  # noqa: E402

DECLARATION = "<!-- gate: none (reason: judgment) — 這個說明夠長所以是有效的宣告 -->\n"
EVIDENCE = "內文。(Source: PR #339)\n"


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """全域 / 系統 git 設定（color、mnemonicPrefix、gpgsign、hooksPath…）不得影響這裡的行為。"""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=30
    )
    return proc.stdout.strip()


def _make_repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _write(repo, {"seed.txt": b"seed\n", **files})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _write(repo: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _lint(repo: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str] | None = None) -> int:
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", repo)
    return lint_rule_evidence.main(argv or [])


def _stage_blob(repo: Path, rel_path: str, data: bytes) -> None:
    """不經工作樹直接把一個 blob 放進 index：macOS 的檔案系統建不出非 UTF-8 檔名，git 的 index 可以。"""
    sha = (
        subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=data,
            capture_output=True,
            check=True,
            timeout=30,
        )
        .stdout.decode()
        .strip()
    )
    _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{rel_path}")


def _rule(*sections: str) -> bytes:
    return ("# T\n\n" + "\n".join(sections)).encode()


def _declared(title: str, body: str = EVIDENCE) -> str:
    return f"## {title}\n\n{body}{DECLARATION}"


def _commit(repo: Path, message: str = "change") -> tuple[str, str]:
    """commit 目前的 index；回傳 `(base, head)` 給 range 模式用。"""
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "-m", message)
    return base, _git(repo, "rev-parse", "HEAD")


# --- A：既有 rule 檔被 git 判為 binary ----------------------------------------------------


def test_existing_rule_file_with_a_nul_byte_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """既有 rule 檔加入 NUL 位元組後被 git 判為 binary，不可讓新增的未宣告 section 隱形。

    spec: rule-mechanization-gate#rule-file-containing-a-nul-byte-is-rejected
    tc: RMG-DT-042
    """
    old = _rule(_declared("Old"))
    repo = _make_repo(tmp_path, {".claude/rules/01-a.md": old})
    _write(repo, {".claude/rules/01-a.md": old + b"\n## Brand New\nno decl\n\x00\n"})
    _git(repo, "add", "-A")

    rc = _lint(repo, monkeypatch)

    assert rc == 1
    assert "NUL" in capsys.readouterr().err


def test_a_nul_byte_is_rejected_even_when_the_new_section_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """對照：宣告齊全也不能放行含 NUL 的 rule 檔（它不是文字檔），所以這不是「缺宣告」的連帶結果。

    spec: rule-mechanization-gate#rule-file-containing-a-nul-byte-is-rejected
    tc: RMG-DT-042
    """
    old = _rule(_declared("Old"))
    repo = _make_repo(tmp_path, {".claude/rules/01-a.md": old})
    _write(repo, {".claude/rules/01-a.md": old + b"\n" + _declared("New").encode() + b"\x00\n"})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 1


@pytest.mark.parametrize("attribute", ["binary", "-diff"])
def test_a_binary_attribute_neither_hides_nor_falsely_blocks_a_rule_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    """`.gitattributes` 把 rule 檔標成 binary / -diff 時，git 不輸出內容；lint 要針對該檔以 `--text` 重讀。

    重讀後內容可見：未宣告的新 section 照樣被擋（不是繞過），宣告齊全的則通過（不是誤擋）。

    spec: rule-mechanization-gate#a-binary-attribute-does-not-hide-or-falsely-block-a-rule-file
    tc: RMG-DT-043
    """
    old = _rule(_declared("Old"))
    repo = _make_repo(
        tmp_path,
        {
            ".claude/rules/01-a.md": old,
            ".gitattributes": f".claude/rules/*.md {attribute}\n".encode(),
        },
    )
    _write(repo, {".claude/rules/01-a.md": old + b"\n## Brand New\nno decl\n"})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 1, "未宣告的新 section 必須被擋"

    _write(repo, {".claude/rules/01-a.md": old + b"\n" + _declared("Brand New").encode()})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 0, "宣告齊全的不可被誤擋"


def test_a_real_binary_elsewhere_in_the_diff_is_not_dumped_as_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--text` 只針對被判為 binary 的 rule 檔；diff 裡真正的二進位檔（圖片等）不能被當文字處理而讓 lint 壞掉。

    spec: rule-mechanization-gate#a-binary-attribute-does-not-hide-or-falsely-block-a-rule-file
    tc: RMG-DT-043
    """
    old = _rule(_declared("Old"))
    repo = _make_repo(tmp_path, {".claude/rules/01-a.md": old})
    _write(repo, {"assets/logo.bin": bytes(range(256)) * 400})
    _write(repo, {".claude/rules/01-a.md": old + b"\n" + _declared("New").encode()})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 0


# --- B：舊的結尾 fence 被 git 對齊進 hunk -------------------------------------------------

_FENCED_EXISTING = _rule(_declared("Old") + "\n```bash\necho a\n```\n")


def _slid_fence_change(new_section: str) -> bytes:
    changed = _FENCED_EXISTING.replace(b"echo a\n", b"echo a2\n")
    return changed + b"\n" + new_section.encode()


def test_fence_state_comes_from_the_whole_file_not_the_hunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改最後一個 code block、並在其後新增未宣告 section：git 會把舊的結尾 ``` 對齊進新增行。

    舊版以 hunk 局部狀態把它讀成「開」，新 section 被當成 fence 內容而消失。完整 context 下那一行
    是 context 行，fence 狀態是對的。

    spec: rule-mechanization-gate#fence-state-comes-from-the-whole-file-not-the-hunk
    tc: RMG-DT-044
    """
    section = "## Brand New Section\n\n" + EVIDENCE + "\n```bash\necho b\n```\n"
    repo = _make_repo(tmp_path, {".claude/rules/50-existing.md": _FENCED_EXISTING})
    _write(repo, {".claude/rules/50-existing.md": _slid_fence_change(section)})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 1, "未宣告的新 section 必須被擋"

    declared = _declared("Brand New Section") + "\n```bash\necho b\n```\n"
    _write(repo, {".claude/rules/50-existing.md": _slid_fence_change(declared)})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 0, "對照：宣告齊全的同一個形狀必須通過"


def test_a_heading_inside_a_fence_is_not_a_section_in_the_post_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fence 內的 `##` 範例不是 section（舊版即使有效宣告也報錯、且作者無從修正）。

    spec: rule-mechanization-gate#fence-state-comes-from-the-whole-file-not-the-hunk
    tc: RMG-DT-044
    """
    content = _rule(_declared("Real") + "\n```markdown\n## When to use\n## Steps\n```\n")
    repo = _make_repo(tmp_path, {})
    _write(repo, {".claude/rules/50-new.md": content})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 0


# --- C：retitle 豁免必須是真的 heading + 相同內文 -------------------------------------------

_LEGACY = _rule("## Keep\n\n" + EVIDENCE + DECLARATION + "\n### Old Title\n\n舊的內文。\n")


def test_retitle_exemption_requires_an_identical_body_and_a_real_heading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只改標題文字（內文一字不動）是改標題；刪掉 fence 內的範例或整段換掉都不是。

    spec: rule-mechanization-gate#retitle-exemption-requires-an-identical-body-and-a-real-heading
    tc: RMG-DT-045
    """
    # (i) 純改標題：legacy section 本來就沒有宣告，不可逼人回頭補
    repo = _make_repo(tmp_path, {".claude/rules/60-x.md": _LEGACY})
    _write(repo, {".claude/rules/60-x.md": _LEGACY.replace(b"Old Title", b"New Title")})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 0, "純改標題必須通過"


def test_deleting_a_fenced_example_heading_does_not_exempt_a_new_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """被刪掉的「heading」其實在 fence 內：不是 heading，不能拿來豁免真正的新 section。

    spec: rule-mechanization-gate#retitle-exemption-requires-an-identical-body-and-a-real-heading
    tc: RMG-DT-045
    """
    before = _rule(_declared("Keep") + "\n```markdown\n### Example\n範例內文\n```\n")
    after_bad = _rule(_declared("Keep") + "\n### New Rule\n\n未宣告的新規則。\n" + EVIDENCE)
    repo = _make_repo(tmp_path, {".claude/rules/60-x.md": before})
    _write(repo, {".claude/rules/60-x.md": after_bad})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 1, "以未宣告的新 section 取代 fence 範例必須被擋"

    after_ok = _rule(
        _declared("Keep") + "\n" + _declared("New Rule", "未宣告的新規則。\n" + EVIDENCE)
    )
    _write(repo, {".claude/rules/60-x.md": after_ok})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 0, "對照：宣告齊全則通過"


def test_replacing_a_whole_section_is_not_a_retitle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """刪掉 `### Old Title` 與其內文、換上不同內文的 `### New Title`：內文不同，不是改標題。

    spec: rule-mechanization-gate#retitle-exemption-requires-an-identical-body-and-a-real-heading
    tc: RMG-DT-045
    """
    repo = _make_repo(tmp_path, {".claude/rules/60-x.md": _LEGACY})
    replaced = _LEGACY.replace(
        "### Old Title\n\n舊的內文。\n".encode(), "### New Title\n\n全新的規則。\n".encode()
    )
    _write(repo, {".claude/rules/60-x.md": replaced})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 1


# --- D：intent-to-add 的 gate ---------------------------------------------------------------

_GATE_RULE = _rule("## Sec\n\n" + EVIDENCE + "<!-- gate: scripts/gate.py -->\n")


def _stage_rule_and_gate(repo: Path, gate_mode: str) -> None:
    (repo / "scripts").mkdir(exist_ok=True)
    _write(repo, {"scripts/gate.py": b"x = 1\n", ".claude/rules/70-y.md": _GATE_RULE})
    if gate_mode == "add":
        _git(repo, "add", "scripts/gate.py")
    elif gate_mode == "intent":
        _git(repo, "add", "-N", "scripts/gate.py")
    _git(repo, "add", ".claude/rules/70-y.md")


@pytest.mark.parametrize(
    ("gate_mode", "expected"),
    [("add", 0), ("intent", 1), ("untracked", 1)],
)
def test_intent_to_add_gate_is_not_an_existing_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_mode: str, expected: int
) -> None:
    """`git add -N` 的 gate 在 index 裡是 stage 0 的空 blob，但 git 不會把它放進 commit。

    staged 模式要對 `git write-tree`（commit 實際會寫的樹）驗證，所以它跟「完全未追蹤」一樣是 dangling。

    spec: rule-mechanization-gate#intent-to-add-gate-is-not-an-existing-gate
    tc: RMG-DT-046
    """
    repo = _make_repo(tmp_path, {})
    _stage_rule_and_gate(repo, gate_mode)

    assert _lint(repo, monkeypatch) == expected


def test_a_legitimately_staged_empty_gate_still_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """對照：合法 `git add` 的空檔 gate 也是空 blob，不能被當成 intent-to-add 誤擋。

    spec: rule-mechanization-gate#intent-to-add-gate-is-not-an-existing-gate
    tc: RMG-DT-046
    """
    repo = _make_repo(tmp_path, {})
    (repo / "scripts").mkdir()
    _write(repo, {"scripts/gate.py": b"", ".claude/rules/70-y.md": _GATE_RULE})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 0


# --- 完整 context 帶來的語意變化：宣告不必與 heading 在同一個 hunk ---------------------------------


def test_a_declaration_below_an_inserted_heading_counts_even_if_it_is_not_an_added_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """heading 插在既有（已宣告）內文之上：宣告是 context 行，仍屬於這個 section。

    舊版（`--unified=0`）看不到 context，只能保守地報缺宣告；現在內容是完整的，不需要那個誤報。

    spec: rule-mechanization-gate#declaration-below-an-inserted-heading-counts-even-if-not-added
    tc: RMG-DT-047
    """
    existing = _rule(EVIDENCE + DECLARATION)
    repo = _make_repo(tmp_path, {".claude/rules/80-z.md": existing})
    inserted = b"# T\n\n## Inserted Above\n\n" + EVIDENCE.encode() + DECLARATION.encode()
    _write(repo, {".claude/rules/80-z.md": inserted})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 0


# --- header 與內容的分辨 -----------------------------------------------------------------------


def test_content_lines_that_look_like_diff_headers_are_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新增行 `++ note` 在 diff 裡是 `+++ note`，不是檔頭；它後面的 heading 不能被丟掉。

    spec: rule-mechanization-gate#content-lines-that-look-like-diff-headers-are-content
    tc: RMG-DT-048
    """
    existing = _rule(_declared("Old"))
    repo = _make_repo(tmp_path, {".claude/rules/90-h.md": existing})
    _write(repo, {".claude/rules/90-h.md": existing + b"\n++ note\n## Brand New\nno decl\n"})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 1, "`++ note` 之後的未宣告 section 必須被擋"

    _write(repo, {".claude/rules/90-h.md": existing + b"\n+ note\n## Brand New\nno decl\n"})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 1, "對照：`+ note` 本來就會被擋"


def test_a_removed_line_that_looks_like_a_quoted_header_does_not_crash_the_lint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """移除的行 `-- "x" y` 在 diff 裡是 `--- "x" y`；不可被當成路徑去 unquote 而讓整個 lint exit 2。

    spec: rule-mechanization-gate#content-lines-that-look-like-diff-headers-are-content
    tc: RMG-DT-048
    """
    repo = _make_repo(tmp_path, {"q.sql": b'select 1;\n-- "x" y\nselect 2;\n'})
    _write(repo, {"q.sql": b"select 1;\nselect 2;\n"})
    _git(repo, "add", "-A")

    assert _lint(repo, monkeypatch) == 0


def test_a_replaced_line_that_looks_like_a_header_pair_is_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-- "x" y` 被換成 `++ "x" y`：diff 裡是緊鄰的 `--- "x" y` / `+++ "x" y`，長得像一組檔頭。

    只有 hunk 的行數還沒用完這個資訊能分辨它；誤判成檔頭會去 unquote 路徑而 exit 2。

    spec: rule-mechanization-gate#content-lines-that-look-like-diff-headers-are-content
    tc: RMG-DT-048
    """
    repo = _make_repo(tmp_path, {"q.sql": b'select 1;\n-- "x" y\n'})
    _write(repo, {"q.sql": b'select 1;\n++ "x" y\n'})
    _git(repo, "add", "-A")
    monkeypatch.setattr(lint_rule_evidence, "REPO_ROOT", repo)
    raw = lint_rule_evidence._staged_diff()
    assert '\n--- "x" y\n+++ "x" y\n' in raw, "錨點：git 真的輸出了成對的假檔頭"

    assert _lint(repo, monkeypatch) == 0


# --- 非 UTF-8 -----------------------------------------------------------------------------------


def test_non_utf8_input_neither_crashes_nor_bypasses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 UTF-8 的檔案內容不可讓 lint traceback；非 UTF-8 的 rule 檔名照樣要被檢查。

    spec: rule-mechanization-gate#non-utf8-input-neither-crashes-nor-bypasses
    tc: RMG-DT-049
    """
    repo = _make_repo(tmp_path, {})
    _write(repo, {"notes.txt": b"caf\xe9\n"})
    _git(repo, "add", "-A")
    assert _lint(repo, monkeypatch) == 0, "非 UTF-8 的無關檔案不可使 lint 壞掉"

    bad_name = os.fsdecode(b".claude/rules/\xff\xfe.md")
    _stage_blob(repo, bad_name, _rule("## Sec\n\n" + EVIDENCE))
    assert _lint(repo, monkeypatch) == 1, "非 UTF-8 檔名的未宣告 rule 檔必須被擋"


# --- range 模式與 staged 模式看到同一份 post-image -------------------------------------------


def test_range_mode_sees_the_same_post_image_as_staged_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI 讀的是 `--head` 的樹；A（NUL）、B（滑進 hunk 的 fence）、C（刪掉 fence 內範例）在 range 模式同樣要擋。

    spec: rule-mechanization-gate#range-mode-sees-the-same-post-image-as-staged-mode
    tc: RMG-DT-050
    """
    repo = _make_repo(
        tmp_path,
        {
            ".claude/rules/01-a.md": _rule(_declared("Old")),
            ".claude/rules/50-existing.md": _FENCED_EXISTING,
            ".claude/rules/60-x.md": _rule(
                _declared("Keep") + "\n```markdown\n### Example\n範例\n```\n"
            ),
        },
    )
    _write(
        repo,
        {
            ".claude/rules/01-a.md": _rule(_declared("Old")) + b"\n## New A\nno decl\n\x00\n",
            ".claude/rules/50-existing.md": _slid_fence_change(
                "## Brand New Section\n\n" + EVIDENCE + "\n```bash\necho b\n```\n"
            ),
            ".claude/rules/60-x.md": _rule(
                _declared("Keep") + "\n### New Rule\n\n未宣告。\n" + EVIDENCE
            ),
        },
    )
    _git(repo, "add", "-A")
    base, head = _commit(repo)

    rc = _lint(repo, monkeypatch, ["--base", base, "--head", head])

    assert rc == 1


@pytest.mark.parametrize("which", ["nul", "slid-fence", "fenced-heading"])
def test_range_mode_blocks_each_postimage_shape_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], which: str
) -> None:
    """上一個測試把三個形狀放在同一個 commit；這裡各自獨立，避免其中一個掩蓋另一個的失敗。

    spec: rule-mechanization-gate#range-mode-sees-the-same-post-image-as-staged-mode
    tc: RMG-DT-050
    """
    cases = {
        "nul": (
            _rule(_declared("Old")),
            _rule(_declared("Old")) + b"\n## New A\nno decl\n\x00\n",
        ),
        "slid-fence": (
            _FENCED_EXISTING,
            _slid_fence_change("## Brand New Section\n\n" + EVIDENCE + "\n```bash\necho b\n```\n"),
        ),
        "fenced-heading": (
            _rule(_declared("Keep") + "\n```markdown\n### Example\n範例\n```\n"),
            _rule(_declared("Keep") + "\n### New Rule\n\n未宣告。\n" + EVIDENCE),
        ),
    }
    before, after = cases[which]
    repo = _make_repo(tmp_path, {".claude/rules/10-r.md": before})
    _write(repo, {".claude/rules/10-r.md": after})
    _git(repo, "add", "-A")
    base, head = _commit(repo)

    rc = _lint(repo, monkeypatch, ["--base", base, "--head", head])

    assert rc == 1, capsys.readouterr().err
