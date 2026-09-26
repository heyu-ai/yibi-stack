#!/usr/bin/env python3
"""testplan 與測試之間的雙向追溯檢查（testplan-trace capability）。

背景：過去判斷「TC 有沒有被測到」是拿 TC-ID 字串去 grep 測試碼，通用 ID（例如 SMK-001）會在
fixture 裡誤命中，TC 改名後也沒有任何東西報錯。這支 checker 改以測試 docstring 的明確宣告為準：

    def test_login():
        \"\"\"
        spec: login#require-password
        tc: LOGIN-VL-001
        \"\"\"

用法：
  python3 check_testplan_trace.py [--repo-root <path>] [--openspec-dir openspec]
                                  [--change <name>] [--tests-dir <path> ...]
                                  [--strict] [--report]

退出碼：0 = 無 FAIL（可能有 WARN）；1 = 至少一筆 FAIL；2 = 設定錯誤（repo root 不存在、指定的
change 不存在、enforced testplan 無法解析出 TC 表）。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# TC-ID：大寫英數字段以連字號串接，至少兩段（LOGIN-VL-001、SMK-001、REG-EG-001a）
_TC_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Za-z0-9]+)+\b")
_TC_LINE_RE = re.compile(r"^\s*tc:\s*(?P<ids>.+?)\s*$")
_SPEC_LINE_RE = re.compile(
    r"(?<![A-Za-z])spec:\s+[A-Za-z0-9][A-Za-z0-9-]*#(?P<slug>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)"
)
_ENFORCED_RE = re.compile(r"^(?:>\s*)?trace:\s*enforced\s*$", re.MULTILINE)
_MANUAL_HEADING_RE = re.compile(r"^##\s+Manual Verification\s*$")
_MANUAL_ITEM_RE = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s+(?P<id>MV-\d+)\b(?P<text>.*)$")
_HEADING_RE = re.compile(r"^#{1,2}\s")
_CHECKBOX_RE = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]", re.MULTILINE)
_SLUG_CELL_RE = re.compile(r"scenario\s*slug", re.IGNORECASE)
_TC_CELL_RE = re.compile(r"^TC-ID", re.IGNORECASE)

KIND_AUTO = "auto"
KIND_MANUAL = "manual"
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}


@dataclass(frozen=True)
class Binding:
    """一個測試函式宣告的綁定。"""

    nodeid: str
    tc_ids: tuple[str, ...]
    spec_slugs: tuple[str, ...]


@dataclass(frozen=True)
class ManualItem:
    """Manual Verification checklist 的一項。"""

    item_id: str
    checked: bool
    text: str


@dataclass
class Testplan:
    """單一 testplan.md 的解析結果。"""

    __test__ = False  # 名稱以 Test 開頭，避免 pytest 誤收集

    enforced: bool = False
    has_kind: bool = False
    parse_ok: bool = False
    tcs: dict[str, str] = field(default_factory=dict)
    seams: dict[str, str] = field(default_factory=dict)
    tc_slugs: dict[str, set[str]] = field(default_factory=dict)
    manual: list[ManualItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 測試檔解析
# ---------------------------------------------------------------------------


def _docstring_binding(docstring: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """從 docstring 取出 (tc_ids, spec_slugs)；只認每行開頭的 tc: 宣告。"""
    if not docstring:
        return (), ()
    tc_ids: list[str] = []
    for line in docstring.splitlines():
        m = _TC_LINE_RE.match(line)
        if m:
            tc_ids.extend(_TC_ID_RE.findall(m.group("ids")))
    slugs = tuple(m.group("slug") for m in _SPEC_LINE_RE.finditer(docstring))
    return tuple(tc_ids), slugs


def parse_bindings(path: Path, root: Path) -> list[Binding]:
    """解析單一測試檔中所有 test_* 函式／方法的綁定。

    以 ast 讀 docstring，所以字串常數、註解、測試資料裡的 TC-ID 都不算綁定。
    檔案語法錯誤時 raise SyntaxError，由呼叫端決定如何回報。
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()

    bindings: list[Binding] = []

    def visit(nodes: list[ast.stmt], prefix: str) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}::{node.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test"):
                    continue
                tc_ids, slugs = _docstring_binding(ast.get_docstring(node))
                bindings.append(Binding(f"{prefix}::{node.name}", tc_ids, slugs))

    visit(tree.body, rel)
    return bindings


def discover_test_files(roots: list[Path]) -> list[Path]:
    """列出 roots 下的 test_*.py 與 *_test.py，略過虛擬環境與 .claude/worktrees。"""
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            parts = set(path.parts)
            if parts & _SKIP_DIRS:
                continue
            if ".claude" in path.parts and "worktrees" in path.parts:
                continue
            name = path.name
            if name.startswith("test_") or name.endswith("_test.py"):
                found.append(path)
    return found


# ---------------------------------------------------------------------------
# testplan 解析
# ---------------------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip().strip("`").strip() for cell in body.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c)


def _iter_tables(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """回傳所有 markdown 表格的 (header, rows)。"""
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines) - 1:
        line, nxt = lines[i], lines[i + 1]
        if line.lstrip().startswith("|") and nxt.lstrip().startswith("|"):
            header, sep = _split_row(line), _split_row(nxt)
            if _is_separator(sep):
                rows: list[list[str]] = []
                j = i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    rows.append(_split_row(lines[j]))
                    j += 1
                tables.append((header, rows))
                i = j
                continue
        i += 1
    return tables


def _col(header: list[str], pattern: re.Pattern[str]) -> int | None:
    for idx, cell in enumerate(header):
        if pattern.search(cell):
            return idx
    return None


def _is_tc_table(header: list[str]) -> bool:
    if not header or not _TC_CELL_RE.match(header[0]) or header[0].upper() != "TC-ID":
        return False
    lowered = {c.lower() for c in header}
    return "test purpose" in lowered or "expected result" in lowered


def parse_testplan(text: str) -> Testplan:
    """解析 testplan.md 文字。不做 I/O，方便以合成資料測試。"""
    plan = Testplan(enforced=bool(_ENFORCED_RE.search(text)))
    lines = text.replace("\r\n", "\n").split("\n")

    for header, rows in _iter_tables(lines):
        if _is_tc_table(header):
            plan.parse_ok = True
            kind_idx = _col(header, re.compile(r"^kind$", re.IGNORECASE))
            seam_idx = _col(header, re.compile(r"^seam$", re.IGNORECASE))
            if kind_idx is not None:
                plan.has_kind = True
            for row in rows:
                if not row or not _TC_ID_RE.fullmatch(row[0]):
                    continue
                kind = KIND_AUTO
                if kind_idx is not None and kind_idx < len(row):
                    # 無法辨識的值一律當成 auto：寧可多要求一個測試，不要漏掉
                    kind = KIND_MANUAL if row[kind_idx].lower() == KIND_MANUAL else KIND_AUTO
                plan.tcs[row[0]] = kind
                if seam_idx is not None and seam_idx < len(row) and row[seam_idx]:
                    plan.seams[row[0]] = row[seam_idx]

        slug_idx = _col(header, _SLUG_CELL_RE)
        tc_idx = _col(header, _TC_CELL_RE)
        if slug_idx is not None and tc_idx is not None:
            for row in rows:
                if max(slug_idx, tc_idx) >= len(row):
                    continue
                slug = row[slug_idx].strip().strip("`")
                if not slug or slug in {"-", "—"}:
                    continue
                for tc_id in _TC_ID_RE.findall(row[tc_idx]):
                    plan.tc_slugs.setdefault(tc_id, set()).add(slug)

    in_manual = False
    for line in lines:
        if _MANUAL_HEADING_RE.match(line):
            in_manual = True
            continue
        if in_manual and _HEADING_RE.match(line):
            in_manual = False
        if in_manual:
            m = _MANUAL_ITEM_RE.match(line)
            if m:
                plan.manual.append(
                    ManualItem(m.group("id"), m.group("mark") in "xX", m.group("text").strip())
                )
    return plan


def parse_tasks_state(text: str) -> tuple[int, int]:
    """回傳 tasks.md 的 (checkbox 總數, 已勾選數)。"""
    marks = [m.group("mark") for m in _CHECKBOX_RE.finditer(text)]
    return len(marks), sum(1 for mark in marks if mark in "xX")


# ---------------------------------------------------------------------------
# 檢查核心（純函式）
# ---------------------------------------------------------------------------

SEVERITY_WARN = "WARN"
SEVERITY_FAIL = "FAIL"


class ConfigError(RuntimeError):
    """設定錯誤：不能當成「沒有 finding」回報（exit 2）。"""


@dataclass(frozen=True)
class ChangeInput:
    """一個 active change 的檢查輸入。"""

    name: str
    plan: Testplan
    tasks_total: int
    tasks_done: int


@dataclass(frozen=True)
class Finding:
    """一筆檢查結果。"""

    severity: str
    kind: str
    change: str
    tc_id: str
    detail: str

    def render(self) -> str:
        return f"[{self.severity}] {self.kind}: {self.change} {self.tc_id} -- {self.detail}"


def _severity(change: ChangeInput, strict: bool) -> str:
    """依 ratchet 決定此 change 的 finding 嚴重度。

    只有宣告 trace: enforced 且 TC 表有 Kind 欄的 testplan 會升到 FAIL；
    升級條件為 --strict，或 tasks.md 至少一個 checkbox 且全部勾選（change 宣稱完成）。
    """
    plan = change.plan
    if not (plan.enforced and plan.has_kind):
        return SEVERITY_WARN
    claims_done = change.tasks_total > 0 and change.tasks_done == change.tasks_total
    return SEVERITY_FAIL if strict or claims_done else SEVERITY_WARN


def check_trace(
    active: list[ChangeInput],
    archived: dict[str, Testplan],
    bindings: list[Binding],
    *,
    strict: bool,
) -> list[Finding]:
    """對 active change 做 missing／orphan／mismatch／collision／manual-open／unparsable 檢查。

    enforced testplan 無法解析出 TC 表時 raise ConfigError（呼叫端轉為 exit 2）。
    """
    for change in active:
        if change.plan.enforced and not change.plan.parse_ok:
            raise ConfigError(
                f"{change.name}：testplan 宣告 trace: enforced，但找不到可解析的 TC 表"
            )

    findings: list[Finding] = []
    severity = {change.name: _severity(change, strict) for change in active}

    # 每個 TC-ID 由哪些 testplan 定義（active 與 archived）
    defined_by: dict[str, list[str]] = {}
    for change in active:
        for tc_id in change.plan.tcs:
            defined_by.setdefault(tc_id, []).append(change.name)
    for name, plan in archived.items():
        for tc_id in plan.tcs:
            defined_by.setdefault(tc_id, []).append(f"archive/{name}")

    bound: dict[str, list[Binding]] = {}
    for binding in bindings:
        for tc_id in binding.tc_ids:
            bound.setdefault(tc_id, []).append(binding)

    for change in active:
        plan = change.plan
        sev = severity[change.name]
        if not plan.parse_ok:
            findings.append(
                Finding(
                    SEVERITY_WARN,
                    "unparsable",
                    change.name,
                    "-",
                    "legacy testplan 找不到可解析的 TC 表",
                )
            )
            continue

        for tc_id, kind in plan.tcs.items():
            if kind == KIND_AUTO and tc_id not in bound:
                findings.append(
                    Finding(sev, "missing", change.name, tc_id, "沒有任何測試以 tc 行綁定此 TC")
                )
            others = [owner for owner in defined_by.get(tc_id, []) if owner != change.name]
            if others:
                findings.append(
                    Finding(
                        sev,
                        "collision",
                        change.name,
                        tc_id,
                        f"同一 TC-ID 也定義於 {', '.join(others)}",
                    )
                )

        for tc_id, tests in bound.items():
            if tc_id not in plan.tcs:
                continue
            expected = plan.tc_slugs.get(tc_id)
            if not expected:
                continue  # testplan 沒有映射此 TC 的 scenario，無從判斷
            for binding in tests:
                if not binding.spec_slugs:
                    findings.append(
                        Finding(
                            sev,
                            "mismatch",
                            change.name,
                            tc_id,
                            f"{binding.nodeid} 有 tc 行但沒有 spec 行",
                        )
                    )
                elif not set(binding.spec_slugs) & expected:
                    got, want = sorted(binding.spec_slugs), sorted(expected)
                    detail = f"{binding.nodeid} 的 spec slug {got} 不在 {want}"
                    findings.append(Finding(sev, "mismatch", change.name, tc_id, detail))

        if strict and plan.enforced:
            for item in plan.manual:
                if not item.checked:
                    findings.append(
                        Finding(
                            SEVERITY_FAIL,
                            "manual-open",
                            change.name,
                            item.item_id,
                            item.text or "未完成的人工驗證",
                        )
                    )

    # orphan：綁定的 ID 不存在於任何 testplan；以 spec slug 歸屬到唯一的 active change，
    # 歸屬不到（零個或多個）就只報 WARN
    slugs_of = {change.name: set().union(*change.plan.tc_slugs.values()) for change in active}
    for tc_id, tests in bound.items():
        if tc_id in defined_by:
            continue
        for binding in tests:
            owners = [name for name, slugs in slugs_of.items() if set(binding.spec_slugs) & slugs]
            if len(owners) == 1:
                sev, owner = severity[owners[0]], owners[0]
            else:
                sev, owner = SEVERITY_WARN, "-"
            findings.append(
                Finding(
                    sev,
                    "orphan",
                    owner,
                    tc_id,
                    f"{binding.nodeid} 引用了任何 testplan 都沒有定義的 TC",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# I/O 與 CLI
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"無法讀取 {path}：{e}") from e


def load_changes(
    openspec_root: Path, only: str | None
) -> tuple[list[ChangeInput], dict[str, Testplan]]:
    """讀取 active change（含 testplan.md 者）與 archived testplan。"""
    changes_dir = openspec_root / "changes"
    active: list[ChangeInput] = []
    if changes_dir.is_dir():
        for change_dir in sorted(p for p in changes_dir.iterdir() if p.is_dir()):
            if change_dir.name == "archive":
                continue
            if only is not None and change_dir.name != only:
                continue
            testplan = change_dir / "testplan.md"
            if not testplan.is_file():
                continue
            tasks = change_dir / "tasks.md"
            total, done = parse_tasks_state(_read(tasks)) if tasks.is_file() else (0, 0)
            active.append(
                ChangeInput(change_dir.name, parse_testplan(_read(testplan)), total, done)
            )
    if only is not None and not active:
        raise ConfigError(
            f"找不到 active change：{only}（{changes_dir}/{only}/testplan.md 不存在）"
        )

    archived: dict[str, Testplan] = {}
    archive_dir = changes_dir / "archive"
    if archive_dir.is_dir():
        for testplan in sorted(archive_dir.glob("*/testplan.md")):
            archived[testplan.parent.name] = parse_testplan(_read(testplan))
    return active, archived


def load_bindings(roots: list[Path], repo_root: Path) -> list[Binding]:
    """解析所有測試檔的綁定；語法錯誤的檔案回報 [WARN] 後略過（pytest 自己會紅）。"""
    import sys

    bindings: list[Binding] = []
    for path in discover_test_files(roots):
        try:
            bindings.extend(parse_bindings(path, repo_root))
        except (SyntaxError, UnicodeDecodeError, OSError) as e:
            print(f"[WARN] 無法解析測試檔 {path}：{e}", file=sys.stderr)
    return bindings


def render_report(active: list[ChangeInput], bindings: list[Binding]) -> list[str]:
    """報告模式：每個 TC 的 Kind、綁定的 nodeid 與狀態。"""
    by_tc: dict[str, list[str]] = {}
    for binding in bindings:
        for tc_id in binding.tc_ids:
            by_tc.setdefault(tc_id, []).append(binding.nodeid)
    lines = ["change\tTC-ID\tkind\tstatus\ttests"]
    for change in active:
        for tc_id, kind in change.plan.tcs.items():
            tests = by_tc.get(tc_id, [])
            status = "manual" if kind == KIND_MANUAL else ("bound" if tests else "missing")
            lines.append(f"{change.name}\t{tc_id}\t{kind}\t{status}\t{', '.join(tests) or '-'}")
    return lines


def _git_toplevel() -> Path | None:
    import subprocess  # nosec B404

    try:
        proc = subprocess.run(  # nosec B603
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(proc.stdout.strip()) if proc.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="testplan 與測試之間的雙向追溯檢查")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--openspec-dir", default="openspec")
    parser.add_argument("--change", default=None)
    parser.add_argument("--tests-dir", type=Path, action="append", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root if args.repo_root is not None else _git_toplevel()
    if repo_root is None or not repo_root.is_dir():
        print(f"[FAIL] repo root 不存在或無法判定：{repo_root}", file=sys.stderr)
        return 2
    openspec_root = repo_root / args.openspec_dir
    test_roots = [p if p.is_absolute() else repo_root / p for p in (args.tests_dir or [repo_root])]

    try:
        active, archived = load_changes(openspec_root, args.change)
        bindings = load_bindings(test_roots, repo_root)
        findings = check_trace(active, archived, bindings, strict=args.strict)
    except ConfigError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    if args.report:
        print("\n".join(render_report(active, bindings)))
        return 0

    for finding in findings:
        print(finding.render())
    return 1 if any(f.severity == SEVERITY_FAIL for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
