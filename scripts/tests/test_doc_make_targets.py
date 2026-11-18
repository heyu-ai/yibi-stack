"""MAKEDOC-* doc-guard：文件中教讀者執行的 `make <target>` 必須存在於 Makefile。

AGENTS.md Known Gotchas：「target names in README/CLAUDE.md must be copied directly from the
Makefile — never rephrase as a readable label ... or users get a make error」。這條原本只靠人記；
這裡把它變成測試。

只看程式碼脈絡，避免散文誤報（"make the"、"make target"）：
- 行內反引號開頭的 `` `make <target> ``
- code fence 內以 `make <target>` 開頭的行（可帶 `$ ` 提示字元）

範圍是 git 追蹤的 Markdown，排除 `openspec/`、`docs/`（歷史紀錄與規格草稿）與 CHANGELOG。
"""

import re
import subprocess  # nosec B404
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 文件刻意舉例的「其他專案」target，值是理由。新增前先確認它真的不是本 repo 的 target。
_EXTERNAL_TARGETS = {
    "seed": "newjob.md 舉例使用者專案自己的 Makefile（`make seed`），不是本 repo 的 target",
}

_INLINE = re.compile(r"`make\s+([a-z][a-z0-9_-]*)")
_FENCE_LINE = re.compile(r"^\s*(?:\$\s*)?make\s+([a-z][a-z0-9_-]*)")
_TARGET_DEF = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)")


def makefile_targets(text: str) -> set[str]:
    """Makefile 中明確宣告的 target（不含 .PHONY 之類的特殊 target）。"""
    return {
        m.group(1)
        for line in text.splitlines()
        if (m := _TARGET_DEF.match(line)) and not m.group(1).startswith(".")
    }


def doc_make_targets(text: str) -> list[tuple[int, str]]:
    """回傳 [(行號, target), ...]，只取程式碼脈絡裡的 `make <target>`。"""
    found: list[tuple[int, str]] = []
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        pattern = _FENCE_LINE if in_fence else _INLINE
        found.extend((n, t) for t in pattern.findall(line))
    return found


def _tracked_docs() -> list[Path]:
    """git 追蹤的 Markdown；symlink（例如 CLAUDE.md -> AGENTS.md）依實際檔案去重，壞掉的略過。"""
    out = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    docs: dict[Path, Path] = {}
    for f in out:
        if f.startswith(("openspec/", "docs/")) or f == "CHANGELOG.md":
            continue
        path = REPO_ROOT / f
        if path.is_file():  # 壞掉的 symlink 由 lint-skill-bash 處理
            docs.setdefault(path.resolve(), path)
    return sorted(docs.values())


class TestDocMakeTargets:
    def test_makedoc_vl_001_documented_targets_exist(self) -> None:
        """MAKEDOC-VL-001: 文件中的 `make <target>` 都是 Makefile 宣告的 target。"""
        targets = makefile_targets((REPO_ROOT / "Makefile").read_text(encoding="utf-8"))
        assert {"install", "ci", "release"} <= targets, "解析前提不成立：Makefile target 解析失敗"
        seen = 0
        problems: list[str] = []
        for doc in _tracked_docs():
            for line_no, target in doc_make_targets(doc.read_text(encoding="utf-8")):
                seen += 1
                if target not in targets and target not in _EXTERNAL_TARGETS:
                    problems.append(f"{doc.relative_to(REPO_ROOT)}:{line_no}: make {target}")
        assert seen > 0, "解析前提不成立：文件裡沒有找到任何 make 指令"
        assert problems == [], "文件引用了 Makefile 沒有的 target：\n" + "\n".join(problems)

    def test_makedoc_vl_002_external_targets_are_really_external(self) -> None:
        """MAKEDOC-VL-002: 例外清單裡的 target 若之後真的加進 Makefile，例外就該移除。"""
        targets = makefile_targets((REPO_ROOT / "Makefile").read_text(encoding="utf-8"))
        assert set(_EXTERNAL_TARGETS) & targets == set()


class TestDetectsBadTargets:
    """負向對照：解析函式對已知壞輸入要能抓到，且不誤報散文。"""

    def test_makedoc_dt_001_inline_and_fence(self) -> None:
        """MAKEDOC-DT-001: 行內反引號與 fence 內的 make 都會被抽出。"""
        text = "跑 `make patch-pr-agents`。\n\n```bash\nmake install-al\n$ make ci\n```\n"
        assert doc_make_targets(text) == [(1, "patch-pr-agents"), (4, "install-al"), (5, "ci")]

    def test_makedoc_dt_002_prose_is_ignored(self) -> None:
        """MAKEDOC-DT-002: 散文裡的 make（"make the"、"make target"）不算。"""
        text = "This would make the target fail; make sure to copy names.\n"
        assert doc_make_targets(text) == []

    def test_makedoc_dt_003_makefile_parsing(self) -> None:
        """MAKEDOC-DT-003: 解析 target 定義，不把變數賦值或 .PHONY 當成 target。"""
        text = ".PHONY: a b\nVAR := 1\nCC = cc\ninstall: deps ## help\nci:\n\techo\n"
        assert makefile_targets(text) == {"install", "ci"}
