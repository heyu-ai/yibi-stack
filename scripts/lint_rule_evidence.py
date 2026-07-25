#!/usr/bin/env python3
"""Lint：新增的 rule 檔 / hook 必須帶「證據標記」，否則擋 commit（retro-evidence-gate）。

`/pr-retro` 可能把未驗證的教訓寫成新 `.claude/rules/*.md` 或新 `.claude/hooks/*`。
本 lint 是 write-time gate 之外的 commit-time 第二道防線：對 git-staged diff 檢查
「證據標記」是否存在，分層強制——

- 新增 `.claude/rules/NN-*.md` 檔，或新增 `.claude/hooks/*` script → 缺標記即 **error**（擋 commit）。
- 既有 rule 檔新增 section（diff 中出現新的 `##` / `###` heading）→ 缺標記即 **warn-only**
  （不擋，靠 pre-commit `verbose: true` 讓警告可見；起步期漸進，避免龐大歷史 corpus 一次爆紅）。

接受的證據標記（擇一）：
- 結構化：`<!-- verified: probe -->`、`<!-- verified: incident PR#NNN -->`
- prose 慣例：`Probed.`、`verified on <tool> <version>`、`(Source: PR #NNN`

`check_rule_evidence(diff_text) -> list[str]`（error）與 `warn_rule_evidence(diff_text) -> list[str]`
（warn）為純函式，供測試以合成 diff 呼叫——這是關鍵：只對真實檔案斷言的 lint 無法測自己的
失敗路徑，「新檔缺標記必回非空」「錨點缺失不空洞通過」這些負向案例需要純函式入口。

用法：
  python3 scripts/lint_rule_evidence.py            # 讀 git staged diff
  python3 scripts/lint_rule_evidence.py <diff-file>  # 讀檔（測試 / 手動）

Exit code:
  0 -> 無 error（可能有 warn，已印到 stderr）
  1 -> 有 error（新檔 / 新 hook 缺證據標記）
  2 -> 設定錯誤（git 不可用）
"""

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 接受的證據標記。任一命中即視為該區塊「有證據」。
_EVIDENCE_MARKERS = [
    re.compile(r"<!--\s*verified:", re.IGNORECASE),  # 結構化
    re.compile(r"\bProbed\.", re.IGNORECASE),  # prose：實測過
    re.compile(r"\bverified on \S"),  # prose：verified on <tool> <version>
    re.compile(r"Source: PR #\d"),  # prose：(Source: PR #NNN
]

_NEW_RULE_FILE_RE = re.compile(r"^\.claude/rules/\d+[^/]*\.md$")
_NEW_HOOK_FILE_RE = re.compile(r"^\.claude/hooks/[^/]+$")
_EXISTING_RULE_FILE_RE = re.compile(r"^\.claude/rules/[^/]+\.md$")
# diff 新增行中的 section heading（`+## ` / `+### `），錨點 = 新 section。
_ADDED_HEADING_RE = re.compile(r"^\+(#{2,3})\s+(.*)$")


class _FileDiff:
    """一個檔案的 diff：新舊路徑 + 新增行（含 heading 標記）。"""

    def __init__(self, old_path: str, new_path: str) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.added_lines: list[str] = []  # 不含前綴 `+` 的內容

    @property
    def is_new_file(self) -> bool:
        return self.old_path == "/dev/null"


def _parse_diff(diff_text: str) -> list[_FileDiff]:
    """把 unified diff 切成 per-file，收集新增行。純字串解析，不呼叫 git。"""
    files: list[_FileDiff] = []
    current: _FileDiff | None = None
    old_path = ""
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current = None
            old_path = ""
            continue
        if line.startswith("--- "):
            old_path = _strip_diff_path(line[4:])
            continue
        if line.startswith("+++ "):
            new_path = _strip_diff_path(line[4:])
            current = _FileDiff(old_path, new_path)
            files.append(current)
            continue
        if current is not None and line.startswith("+") and not line.startswith("+++"):
            current.added_lines.append(line[1:])
    return files


def _strip_diff_path(raw: str) -> str:
    """`a/path` / `b/path` / `/dev/null` -> 正規化路徑。"""
    raw = raw.strip()
    if raw == "/dev/null":
        return raw
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


def _has_evidence(lines: list[str]) -> bool:
    blob = "\n".join(lines)
    return any(marker.search(blob) for marker in _EVIDENCE_MARKERS)


def _sections_missing_evidence(added_lines: list[str]) -> list[str]:
    """回傳「新增了 heading 但該 section 內無證據標記」的 heading 標題清單。

    以新增行中的 heading 為錨點：只有 heading 本身被新增（即新 section）才計入；
    只在既有 section 內新增內容（無新 heading）不會誤觸發。
    """
    missing: list[str] = []
    current_heading: str | None = None
    current_block: list[str] = []

    def _flush() -> None:
        if current_heading is not None and not _has_evidence(current_block):
            missing.append(current_heading)

    for line in added_lines:
        match = _ADDED_HEADING_RE.fullmatch("+" + line)
        if match is not None:
            _flush()
            current_heading = match.group(2).strip()
            current_block = [line]
        elif current_heading is not None:
            current_block.append(line)
    _flush()
    return missing


def check_rule_evidence(diff_text: str) -> list[str]:
    """回傳 **error** 訊息清單（空 = 無 error）；新 rule 檔 / 新 hook 缺證據標記即 error。"""
    errors: list[str] = []
    for fd in _parse_diff(diff_text):
        path = fd.new_path
        is_new_rule = fd.is_new_file and _NEW_RULE_FILE_RE.fullmatch(path)
        is_new_hook = fd.is_new_file and _NEW_HOOK_FILE_RE.fullmatch(path)
        if not (is_new_rule or is_new_hook):
            continue
        if not _has_evidence(fd.added_lines):
            kind = "rule 檔" if is_new_rule else "hook"
            errors.append(
                f"{path}：新增的 {kind} 缺少證據標記。"
                "須帶 `<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`，"
                "或 prose `Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`。"
            )
    return errors


def warn_rule_evidence(diff_text: str) -> list[str]:
    """回傳 **warn** 訊息清單；既有 rule 檔新增 section 缺證據標記（起步期不擋 commit）。"""
    warns: list[str] = []
    for fd in _parse_diff(diff_text):
        if fd.is_new_file or not _EXISTING_RULE_FILE_RE.fullmatch(fd.new_path):
            continue
        for heading in _sections_missing_evidence(fd.added_lines):
            warns.append(
                f"{fd.new_path}：新增 section「{heading}」缺證據標記（建議補 probe 或 PR cite）"
            )
    return warns


def _staged_diff() -> str:
    cmd = ["git", "-C", str(REPO_ROOT), "diff", "--cached", "--unified=0"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # nosec B603
    if proc.returncode != 0:
        raise RuntimeError(f"git diff --cached 失敗：{proc.stderr.strip()}")
    return proc.stdout


def main(argv: list[str]) -> int:
    if argv:
        try:
            diff_text = Path(argv[0]).read_text(encoding="utf-8")
        except OSError as e:
            print(f"[FAIL] 無法讀取 diff 檔：{e}", file=sys.stderr)
            return 2
    else:
        try:
            diff_text = _staged_diff()
        except RuntimeError as e:
            print(f"[FAIL] {e}", file=sys.stderr)
            return 2

    warns = warn_rule_evidence(diff_text)
    for w in warns:
        print(f"  [WARN] {w}", file=sys.stderr)

    errors = check_rule_evidence(diff_text)
    if errors:
        print(f"[FAIL] {len(errors)} 個新增 rule/hook 缺證據標記：", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\n修法：為新 rule/hook 補上證據標記——"
            "可機械實測者附 probe 輸出並標 `<!-- verified: probe -->`；"
            "事件佐證者標 `(Source: PR #NNN` 或 `<!-- verified: incident PR#NNN -->`；"
            "若屬主觀 / 單次，改 park 到 typed-lessons 而非寫入 always-loaded 面。",
            file=sys.stderr,
        )
        return 1

    print("[OK] 新增 rule/hook 皆帶證據標記" + (f"（另有 {len(warns)} 個 warn）" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
