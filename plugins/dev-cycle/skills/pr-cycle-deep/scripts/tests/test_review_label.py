"""RLB: review-label.sh 貼／撤 `review-in-progress` label 的行為（issue #587）。

只有 gh 被換成有狀態的假檔：它把 repo label 與 PR label 存在 JSON 檔裡，讀寫都真的發生，
所以「回讀確認」是對真實狀態做的，而不是對寫死的回應做的。
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "review-label.sh"
LABEL = "review-in-progress"

FAKE_GH = f"""#!{sys.executable}
import json, os, sys

state_path = os.environ["FAKE_GH_STATE"]
with open(state_path, encoding="utf-8") as f:
    state = json.load(f)
args = sys.argv[1:]
state["calls"].append(args)

def save():
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)

def bail(message):
    save()
    print(message, file=sys.stderr)
    sys.exit(1)

if args[:2] == ["label", "list"]:
    if state.get("label_list_fail"):
        bail("label list unavailable")
    save()
    print(json.dumps([{{"name": n}} for n in state["repo_labels"]]))
elif args[:2] == ["pr", "view"]:
    if state.get("view_fail"):
        bail("API unavailable")
    save()
    print(json.dumps({{"labels": [{{"name": n}} for n in state["pr_labels"]]}}))
elif args[:2] == ["pr", "edit"]:
    if state.get("edit_fail"):
        bail("edit refused")
    if not state.get("edit_noop"):
        if "--add-label" in args:
            name = args[args.index("--add-label") + 1]
            if name not in state["pr_labels"]:
                state["pr_labels"].append(name)
        if "--remove-label" in args:
            name = args[args.index("--remove-label") + 1]
            state["pr_labels"] = [n for n in state["pr_labels"] if n != name]
    save()
else:
    sys.exit(99)
"""


@dataclass
class Case:
    state_path: Path
    env: dict[str, str]

    def configure(self, **changes: object) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state.update(changes)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def state(self) -> dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def edit_calls(self) -> list[list[str]]:
        return [c for c in self.state()["calls"] if c[:2] == ["pr", "edit"]]  # type: ignore[index]

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 B607
            ["bash", str(SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


@pytest.fixture
def case(tmp_path: Path) -> Case:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"repo_labels": [LABEL, "bug"], "pr_labels": ["harness"], "calls": []}),
        encoding="utf-8",
    )
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env["FAKE_GH_STATE"] = str(state_path)
    return Case(state_path, env)


def test_add_puts_label_on_pr_and_confirms(case: Case) -> None:
    """RLB-ST-001: add 後 PR 真的帶著 label，且保留既有 label。"""
    result = case.run("add", "7")
    assert result.returncode == 0, result.stderr
    assert case.state()["pr_labels"] == ["harness", LABEL]
    assert "[OK]" in result.stdout


def test_add_when_repo_lacks_label_warns_and_exits_10_without_editing(case: Case) -> None:
    """RLB-ST-002: 其他專案沒有這個 label：只 [WARN]、exit 10、完全不碰 PR。"""
    case.configure(repo_labels=["bug"])
    result = case.run("add", "7")
    assert result.returncode == 10, result.stderr
    assert "[WARN]" in result.stderr
    assert case.edit_calls() == []


def test_add_fails_when_readback_disagrees(case: Case) -> None:
    """RLB-EG-001: gh 回報成功但 label 沒上去（靜默失敗）必須 [FAIL]，不可當成功。"""
    case.configure(edit_noop=True)
    result = case.run("add", "7")
    assert result.returncode == 1
    assert "read-back mismatch" in result.stderr


@pytest.mark.parametrize("failing", ["edit_fail", "view_fail", "label_list_fail"])
def test_add_fails_loud_when_gh_fails(case: Case, failing: str) -> None:
    """RLB-EG-002: gh 任一呼叫失敗都是 exit 1，不退化成「沒有 label」的 exit 10。"""
    case.configure(**{failing: True})
    result = case.run("add", "7")
    assert result.returncode == 1
    assert "[FAIL]" in result.stderr


def test_remove_takes_label_off_and_confirms(case: Case) -> None:
    """RLB-ST-003: remove 後 PR 不再帶 label，其他 label 不受影響。"""
    case.configure(pr_labels=["harness", LABEL])
    result = case.run("remove", "7")
    assert result.returncode == 0, result.stderr
    assert case.state()["pr_labels"] == ["harness"]


def test_remove_when_already_absent_is_ok_and_does_not_edit(case: Case) -> None:
    """RLB-ST-004: 本來就沒有（含沒有此 label 的 repo）→ exit 0，且不呼叫 edit。"""
    case.configure(repo_labels=["bug"])
    result = case.run("remove", "7")
    assert result.returncode == 0, result.stderr
    assert case.edit_calls() == []


def test_remove_fails_when_label_still_there_after_edit(case: Case) -> None:
    """RLB-EG-003: 撤失敗（label 還在）必須 [FAIL]，讓呼叫端通知使用者手動移除。"""
    case.configure(pr_labels=[LABEL], edit_noop=True)
    result = case.run("remove", "7")
    assert result.returncode == 1
    assert "remove it by hand" in result.stderr


def test_remove_fails_loud_when_pr_unreadable(case: Case) -> None:
    """RLB-EG-004: 讀不到 PR 狀態不能當成「label 不在」。"""
    case.configure(view_fail=True)
    result = case.run("remove", "7")
    assert result.returncode == 1
    assert "cannot confirm label state" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("add",),
        ("add", "7", "extra"),
        ("toggle", "7"),
        ("add", "abc"),
        ("add", "0"),
        ("add", "-3"),
    ],
)
def test_usage_errors_exit_1_before_calling_gh(case: Case, args: tuple[str, ...]) -> None:
    """RLB-EG-005: 用法錯誤一律 exit 1，且不碰 gh。"""
    result = case.run(*args)
    assert result.returncode == 1
    assert case.state()["calls"] == []
