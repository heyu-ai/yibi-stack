"""RLB: review-label.sh 貼／撤 `review-in-progress` label 的行為（issue #587）。

只有 gh 被換成有狀態的假檔：它把 repo label 與 PR label 存在 JSON 檔裡，讀寫都真的發生，
所以「回讀確認」是對真實狀態做的，而不是對寫死的回應做的。
"""

from __future__ import annotations

import json
import os
import shutil
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

def reject(message):
    save()
    print(message, file=sys.stderr)
    sys.exit(99)

def require_json():
    if "--json" not in args:
        reject("missing --json: " + " ".join(args))

def require_pr_number():
    if len(args) < 3 or args[2] != state["pr_number"]:
        reject("unexpected PR number: " + " ".join(args))

if args[:2] == ["label", "list"]:
    require_json()
    if state.get("label_list_fail"):
        bail("label list unavailable")
    save()
    if state.get("label_list_raw") is not None:
        print(state["label_list_raw"])
    else:
        print(json.dumps([{{"name": n}} for n in state["repo_labels"]]))
elif args[:2] == ["pr", "view"]:
    require_json()
    require_pr_number()
    if state.get("view_fail"):
        bail("API unavailable")
    save()
    if state.get("view_raw") is not None:
        print(state["view_raw"])
    else:
        print(json.dumps({{"labels": [{{"name": n}} for n in state["pr_labels"]]}}))
elif args[:2] == ["pr", "edit"]:
    require_pr_number()
    if state.get("edit_fail"):
        bail("edit refused")
    if not state.get("edit_noop"):
        # GitHub 的 label 名稱不分大小寫，假檔也照這個語意增刪。
        if "--add-label" in args:
            name = args[args.index("--add-label") + 1]
            if name.lower() not in [n.lower() for n in state["pr_labels"]]:
                state["pr_labels"].append(name)
        if "--remove-label" in args:
            name = args[args.index("--remove-label") + 1]
            state["pr_labels"] = [n for n in state["pr_labels"] if n.lower() != name.lower()]
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

    def pr_numbers_seen(self) -> set[str]:
        """gh 實際收到的 PR 號（pr view / pr edit 的第三個參數）。"""
        return {c[2] for c in self.state()["calls"] if c[:2] in (["pr", "view"], ["pr", "edit"])}  # type: ignore[index]

    def run_with_path(self, path: str, *args: str) -> subprocess.CompletedProcess[str]:
        """只給指定 PATH 執行（用絕對路徑的 bash，PATH 裡缺什麼工具就是缺什麼）。"""
        return subprocess.run(  # nosec B603
            ["/bin/bash", str(SCRIPT), *args],
            env={**self.env, "PATH": path},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

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
        json.dumps(
            {
                "pr_number": "7",
                "repo_labels": [LABEL, "bug"],
                "pr_labels": ["harness"],
                "calls": [],
            }
        ),
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


def test_add_targets_exactly_the_given_pr(case: Case) -> None:
    """RLB-ST-005: gh 只收到被指定的 PR 號，edit 恰好一次且參數完全符合。"""
    result = case.run("add", "7")
    assert result.returncode == 0, result.stderr
    assert case.edit_calls() == [["pr", "edit", "7", "--add-label", LABEL]]
    assert case.pr_numbers_seen() == {"7"}


def test_remove_targets_exactly_the_given_pr(case: Case) -> None:
    """RLB-ST-006: remove 同理，edit 恰好一次、參數完全符合。"""
    case.configure(pr_labels=["harness", LABEL])
    result = case.run("remove", "7")
    assert result.returncode == 0, result.stderr
    assert case.edit_calls() == [["pr", "edit", "7", "--remove-label", LABEL]]
    assert case.pr_numbers_seen() == {"7"}


def test_add_is_idempotent_when_pr_already_labelled(case: Case) -> None:
    """RLB-ST-007: 已經帶著 label 時再 add 仍 exit 0，PR 上只有一個該 label。"""
    case.configure(pr_labels=["harness", LABEL])
    result = case.run("add", "7")
    assert result.returncode == 0, result.stderr
    assert case.state()["pr_labels"].count(LABEL) == 1  # type: ignore[attr-defined]


def test_add_matches_repo_label_case_insensitively(case: Case) -> None:
    """RLB-ST-008: repo 的 label 叫 `Review-In-Progress`（GitHub 不分大小寫）仍視為存在。"""
    case.configure(repo_labels=["Review-In-Progress"])
    result = case.run("add", "7")
    assert result.returncode == 0, result.stderr
    assert case.edit_calls() == [["pr", "edit", "7", "--add-label", LABEL]]


def test_remove_matches_pr_label_case_insensitively(case: Case) -> None:
    """RLB-ST-009: PR 上掛的是大小寫不同的同名 label，remove 仍要撤掉。"""
    case.configure(pr_labels=["harness", "Review-In-Progress"])
    result = case.run("remove", "7")
    assert result.returncode == 0, result.stderr
    assert case.state()["pr_labels"] == ["harness"]


def test_add_requires_whole_name_not_substring(case: Case) -> None:
    """RLB-ST-010: repo 只有 `review-in-progress-old` 不算有此 label（整字相等，非 contains）。"""
    case.configure(repo_labels=[f"{LABEL}-old", "bug"])
    result = case.run("add", "7")
    assert result.returncode == 10, result.stderr
    assert case.edit_calls() == []


def test_remove_ignores_label_that_only_contains_the_name(case: Case) -> None:
    """RLB-ST-011: PR 上只有 `review-in-progress-old` 時 remove 不呼叫 edit、exit 0。"""
    case.configure(pr_labels=["harness", f"{LABEL}-old"])
    result = case.run("remove", "7")
    assert result.returncode == 0, result.stderr
    assert case.edit_calls() == []
    assert case.state()["pr_labels"] == ["harness", f"{LABEL}-old"]


def test_add_when_repo_lacks_label_warns_and_exits_10_without_editing(case: Case) -> None:
    """RLB-ST-002: 其他專案沒有這個 label：只 [WARN]、exit 10、不呼叫 pr edit。"""
    case.configure(repo_labels=["bug"])
    result = case.run("add", "7")
    assert result.returncode == 10, result.stderr
    assert "[WARN]" in result.stderr
    assert case.edit_calls() == []
    assert case.pr_numbers_seen() == set()


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


@pytest.mark.parametrize("raw", ["{}", '{"labels": null}'])
@pytest.mark.parametrize("action", ["add", "remove"])
def test_malformed_pr_label_metadata_fails_loud(case: Case, raw: str, action: str) -> None:
    """RLB-EG-006: pr view 回傳的 labels 不是陣列，不能當成「沒有 label」。"""
    case.configure(view_raw=raw, pr_labels=[LABEL])
    result = case.run(action, "7")
    assert result.returncode == 1
    assert "malformed label metadata" in result.stderr


@pytest.mark.parametrize("raw", ['{"name": "x"}', "null", '"oops"'])
def test_add_fails_when_label_list_is_not_an_array(case: Case, raw: str) -> None:
    """RLB-EG-007: label list 回傳非陣列必須 [FAIL]，不可誤報成 exit 10（repo 沒有 label）。"""
    case.configure(label_list_raw=raw)
    result = case.run("add", "7")
    assert result.returncode == 1
    assert "malformed metadata" in result.stderr
    assert case.edit_calls() == []


def test_remove_fails_loud_when_edit_refused(case: Case) -> None:
    """RLB-EG-008: 撤 label 時 gh pr edit 被拒，必須 [FAIL] 並提示手動移除。"""
    case.configure(pr_labels=[LABEL], edit_fail=True)
    result = case.run("remove", "7")
    assert result.returncode == 1
    assert "remove it by hand" in result.stderr


@pytest.mark.parametrize("missing", ["gh", "jq"])
def test_missing_required_tool_fails_before_any_call(
    case: Case, tmp_path: Path, missing: str
) -> None:
    """RLB-EG-009: PATH 上缺 gh 或 jq 是 exit 1 與明確訊息，不是 command not found 的亂碼。"""
    only = tmp_path / "only"
    only.mkdir()
    if missing == "jq":  # 有 gh、沒有 jq
        shutil.copy2(tmp_path / "bin" / "gh", only / "gh")
    result = case.run_with_path(str(only), "add", "7")
    assert result.returncode == 1
    assert f"Required tool unavailable: {missing}" in result.stderr


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
