#!/usr/bin/env python3
"""Lint：改動 SKILL.md 的 `description` 就必須同時維護該 skill 的 trigger_eval.json。

`description` 是 skill 唯一的觸發面——改它就是改觸發行為。skill_eval 的回歸 gate 只在
fixture 存在時才有東西可比，所以「改了 description、沒動 fixture」是這個 repo 最常見的
靜默失效路徑：eval 照跑、照報 [OK]，但比對的是改動前的觸發假設。

本 lint 是 **coverage** gate，不是 eval 本身：它只確定性地檢查「該有 fixture 的地方有沒有
fixture、有沒有跟著改」，不呼叫任何 LLM，因此可以放進 CI。真正的觸發評測（需要 judge
subagent）跑在 scheduler / 本機，不在 GitHub Actions——那裡沒有互動式 agent 可以判斷。

分層強制（起步期）：
- 全部為 **warn-only**（exit 0），因為 31 個 skill 目前只有少數有 fixture，一上線就 blocking
  會讓每個 SKILL.md 改動都紅。覆蓋率鋪開後以 `--fail` 翻成 blocking。

`check_skill_eval_coverage(diff_text, has_fixture) -> list[str]` 為純函式，`has_fixture` 以
callable 注入，供測試以合成 diff + 假的存在性判斷呼叫——只對真實檔案斷言的 lint 無法測
自己的失敗路徑。

用法：
  python3 scripts/lint_skill_eval_coverage.py                       # 讀 git staged diff（pre-commit）
  python3 scripts/lint_skill_eval_coverage.py --base <A> --head <B>   # 讀 commit range（CI）
  python3 scripts/lint_skill_eval_coverage.py <diff-file>             # 讀檔（測試 / 手動）
  python3 scripts/lint_skill_eval_coverage.py --fail ...              # 把 warn 升級為 exit 1

Exit code:
  0 -> 無問題，或有 warn 但未帶 --fail
  1 -> 帶 --fail 且有未覆蓋的 skill
  2 -> 設定錯誤（引數矛盾、git 不可用、commit 解不開）
"""

import re
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent

# 兩個 SKILL.md 落點：repo 根的 skills/<name>/，與 plugin 內任意深度的
# plugins/<pack>/skills/<...>/。`.+` 而非 `[^/]+` 是刻意的——mycelium 的 sub-skill
# 多一層（rule 02：`*` 不跨 `/` 的同類陷阱）。
_SKILL_MD_RE = re.compile(r"^(?:skills/[^/]+|plugins/[^/]+/skills/.+)/SKILL\.md$")
_FIXTURE_NAME = "trigger_eval.json"
# frontmatter 的 description 行；只認行首，避免命中 body 裡談論 description 的散文。
_DESCRIPTION_RE = re.compile(r"^description:\s*\S")


class _FileDiff:
    """一個檔案的 diff：新舊路徑 + 新增行（不含前綴 `+`）。"""

    def __init__(self, old_path: str, new_path: str) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.added_lines: list[str] = []


def _parse_diff(diff_text: str) -> list[_FileDiff]:
    """把 unified diff 切成逐檔的新舊路徑與新增行。"""
    files: list[_FileDiff] = []
    current: _FileDiff | None = None
    old_path: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            raw = line[4:].strip()
            old_path = "/dev/null" if raw == "/dev/null" else raw.removeprefix("a/")
            continue
        if line.startswith("+++ "):
            raw = line[4:].strip()
            new_path = "/dev/null" if raw == "/dev/null" else raw.removeprefix("b/")
            current = _FileDiff(old_path or "/dev/null", new_path)
            files.append(current)
            old_path = None
            continue
        # `+++` 已在上面吃掉，這裡的 `+` 一定是內容行。
        if current is not None and line.startswith("+"):
            current.added_lines.append(line[1:])
    return files


def _touched_skill_mds(diffs: list[_FileDiff]) -> list[_FileDiff]:
    """回傳本次 diff 中被改動的 SKILL.md（依路徑排序）。"""
    return sorted(
        (fd for fd in diffs if _SKILL_MD_RE.fullmatch(fd.new_path)),
        key=lambda fd: fd.new_path,
    )


def _touched_fixture_dirs(diffs: list[_FileDiff]) -> set[str]:
    """回傳本次 diff 中被改動的 trigger_eval.json 所在目錄（POSIX 字串）。"""
    return {
        str(PurePosixPath(fd.new_path).parent)
        for fd in diffs
        if PurePosixPath(fd.new_path).name == _FIXTURE_NAME and fd.new_path != "/dev/null"
    }


def _is_new_skill_md(fd: _FileDiff) -> bool:
    """新增的 SKILL.md——含「從受保護範圍外 rename 進來」。

    只看 `old_path == "/dev/null"` 會漏掉 rename：把 `drafts/foo/SKILL.md` 移進
    `skills/foo/` 時 old_path 是真實路徑，於是被當成「既有檔案」而跳過新檔檢查
    （rule 02 記載的同一個陷阱）。
    """
    return not _SKILL_MD_RE.fullmatch(fd.old_path)


def check_skill_eval_coverage(diff_text: str, has_fixture: Callable[[str], bool]) -> list[str]:
    """回傳未覆蓋訊息清單。

    `has_fixture(skill_dir)` 判斷該 SKILL.md 所在目錄是否已有 fixture——傳目錄而非
    skill 名稱，是為了不在此重建一份「名稱 -> 路徑」解析：fixture 依約定就躺在 SKILL.md
    旁邊，直接看那個路徑既精確又不必與 skill_eval 的索引邏輯保持同步。
    """
    diffs = _parse_diff(diff_text)
    fixture_touched = _touched_fixture_dirs(diffs)
    messages: list[str] = []

    for fd in _touched_skill_mds(diffs):
        is_new = _is_new_skill_md(fd)
        desc_changed = any(_DESCRIPTION_RE.match(line) for line in fd.added_lines)
        if not (is_new or desc_changed):
            continue  # 只動 body，不影響觸發面
        reason = "新增 skill" if is_new else "改動 description"
        skill_dir = str(PurePosixPath(fd.new_path).parent)
        if not has_fixture(skill_dir):
            messages.append(
                f"{fd.new_path}：{reason}，但該 skill 沒有 {_FIXTURE_NAME}。"
                f"觸發回歸 gate 對它完全無效——請在 SKILL.md 旁建立 fixture"
                "（5 direct / 5 indirect / 5 negative）"
            )
        elif skill_dir not in fixture_touched:
            messages.append(
                f"{fd.new_path}：{reason}，但同一個 diff 未改動 {_FIXTURE_NAME}。"
                "description 是唯一的觸發面，改它等於改觸發行為；"
                "請一併檢視 fixture 的 direct/indirect/negative 是否仍成立"
            )
    return messages


def _default_has_fixture(skill_dir: str) -> bool:
    """檔案系統的存在性判斷。

    刻意不 import `tasks.skill_eval`：本 lint 掛在 pre-commit 的 `language: system`，
    跑的是系統 python3，沒有 pydantic——import 會炸成 traceback 而非給出判斷。
    """
    return (REPO_ROOT / skill_dir / _FIXTURE_NAME).is_file()


def _run_git_diff(args: list[str], label: str) -> str:
    cmd = ["git", "-C", str(REPO_ROOT), "diff", "--unified=0", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # nosec B603
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"{label} 無法執行：{e}") from e
    if proc.returncode != 0:
        raise RuntimeError(f"{label} 失敗：{proc.stderr.strip()}")
    return proc.stdout


def _parse_args(argv: list[str]) -> tuple[str | None, str | None, str | None, bool]:
    """回傳 `(base, head, diff_file, fail_mode)`；引數矛盾時 raise ValueError（由 main 轉 exit 2）。"""
    base: str | None = None
    head: str | None = None
    fail_mode = False
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--fail":
            fail_mode = True
            i += 1
            continue
        if arg in ("--base", "--head"):
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} 後面需要一個 commit-ish 引數")
            value = argv[i + 1]
            # 空字串必須擋在這裡：`git diff "...head"` 是合法 range（等同 HEAD...head），
            # CI 的 checkout 就在 head，於是 exit 0 回空 diff，gate 通過卻什麼都沒讀。
            if not value.strip():
                raise ValueError(f"{arg} 的值不可為空字串（空值會退化成 HEAD...HEAD 的空 diff）")
            if arg == "--base":
                base = value
            else:
                head = value
            i += 2
            continue
        if arg.startswith("-"):
            raise ValueError(f"未知選項：{arg}")
        positional.append(arg)
        i += 1

    if (base is None) != (head is None):
        raise ValueError("--base 與 --head 必須成對出現（只給一半無法界定 range）")
    if base is not None and positional:
        raise ValueError("range 模式（--base/--head）與 diff 檔路徑不可同時指定")
    if len(positional) > 1:
        raise ValueError(f"最多只能指定一個 diff 檔路徑，收到 {len(positional)} 個")
    return base, head, (positional[0] if positional else None), fail_mode


def main(argv: list[str]) -> int:
    try:
        base, head, diff_file, fail_mode = _parse_args(argv)
    except ValueError as e:
        print(f"[FAIL] 引數錯誤：{e}", file=sys.stderr)
        return 2

    try:
        if base is not None and head is not None:
            # 三點：只看 head 自 merge-base 以來新增了什麼，不把別人合進 base 的改動算進來。
            diff_text = _run_git_diff([f"{base}...{head}", "--"], f"git diff {base}...{head}")
        elif diff_file is not None:
            diff_text = Path(diff_file).read_text(encoding="utf-8")
        else:
            diff_text = _run_git_diff(["--cached"], "git diff --cached")
    except (RuntimeError, OSError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    messages = check_skill_eval_coverage(diff_text, _default_has_fixture)
    if not messages:
        print("[OK] 改動的 SKILL.md 觸發面皆有對應 fixture")
        return 0

    label = "[FAIL]" if fail_mode else "[WARN]"
    print(f"{label} {len(messages)} 個 skill 的觸發面改動未被 fixture 覆蓋：", file=sys.stderr)
    for m in messages:
        print(f"  {m}", file=sys.stderr)
    print(
        "\n撰寫指引：negative prompt 取材自 sibling skill 自己 description 的觸發關鍵字"
        "（`python3 scripts/lint_skill_overlap.py` 會列出高重疊配對），"
        "indirect 盡量取自真實 transcript 的使用者措辭。",
        file=sys.stderr,
    )
    return 1 if fail_mode else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
