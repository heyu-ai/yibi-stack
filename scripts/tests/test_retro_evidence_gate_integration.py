"""retro-evidence-gate 的 runbook / CI wiring contract tests。

**這個檔案的教訓（PR #347 mob review）**：初版只斷言「ci.yml 這個字串檔裡有 `--base`」，
驗的是「我有沒有把這行字寫進去」，不是「這個介面存在嗎」——於是本機全綠、CI 紅。
修好那一版之後，mob review 又指出三個同族的殘餘破口，全部附 mutation 實跑證明：

1. `fetch-depth: 0` 用整檔字串比對，CI 拆成多 job 後另一個 job 就能滿足它，而 gate job
   失去 merge-base 歷史卻無人察覺。
2. 沒有任何斷言看 `if:` 條件——把它改成 `pull_request_target`（該 workflow 的 `on:` 沒有
   此事件）會讓 step 永久 skip、gate 什麼都不檢查，測試照樣 6 passed。
3. drift guard 只用 regex 抽 flag **名稱**，從不重建 workflow 實際產生的 argv——改成等號
   形式 `--base="${{ ... }}"` 後 guard 全綠，runtime 卻 `未知選項` exit 2。

所以下面改成**解析 YAML、綁到實際的 job / step / argv**。用 `yaml` 而非手刻字串比對：
PyYAML 在 `uv.lock` 內（pre-commit 的相依），CI 走同一個 `uv sync --all-groups` venv；
真的缺了會在 import 就大聲失敗，不會靜默略過。
"""

import shlex
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_rule_evidence  # noqa: E402

_CI_WORKFLOW = ".github/workflows/ci.yml"
_LINT_SCRIPT = "scripts/lint_rule_evidence.py"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_ci() -> dict[str, Any]:
    data = yaml.safe_load(_read(_CI_WORKFLOW))
    assert isinstance(data, dict), "ci.yml 解析結果不是 mapping"
    return data


def _evidence_lint_job() -> tuple[str, dict[str, Any]]:
    """回傳 (job 名稱, job 定義)——即實際跑 evidence lint 的那個 job。

    找不到就 [FAIL]：錨點失效時必須大聲失敗，不可讓後續斷言在空集合上空洞通過。
    """
    jobs = _load_ci().get("jobs") or {}
    hits = [
        (name, job)
        for name, job in jobs.items()
        if any(_LINT_SCRIPT in str(step.get("run", "")) for step in (job.get("steps") or []))
    ]
    assert len(hits) == 1, (
        f"預期恰好 1 個 job 跑 {_LINT_SCRIPT}，實際 {len(hits)} 個：{[h[0] for h in hits]}"
    )
    return hits[0]


def _evidence_lint_steps() -> list[dict[str, Any]]:
    _, job = _evidence_lint_job()
    steps = [s for s in (job.get("steps") or []) if _LINT_SCRIPT in str(s.get("run", ""))]
    assert steps, f"在 job 內找不到跑 {_LINT_SCRIPT} 的 step——錨點失效"
    return steps


def _argv_from_run(run: str) -> list[str]:
    """把 step 的 `run` scalar 還原成腳本實際收到的 argv（`${{ }}` 換成佔位 token）。

    這是關鍵：只比對 flag 名稱無法分辨 `--base <v>` 與 `--base=<v>`，而後者會讓
    `_parse_args` 走到 `arg.startswith("-")` 而 raise `未知選項`。
    """
    masked: list[str] = []
    rest = run
    while "${{" in rest:
        head, _, tail = rest.partition("${{")
        expr, _, tail = tail.partition("}}")
        assert expr, f"ci.yml 的 `${{{{` 沒有對應的 `}}}}`：{run!r}"
        masked.append(head)
        masked.append("PLACEHOLDER_SHA")
        rest = tail
    masked.append(rest)
    tokens = shlex.split("".join(masked))
    idx = next(
        (i for i, t in enumerate(tokens) if t.endswith(_LINT_SCRIPT)),
        None,
    )
    assert idx is not None, f"在 run 內找不到 {_LINT_SCRIPT}：{run!r}"
    return tokens[idx + 1 :]


def test_runbook_defers_typed_lesson_mutation_until_after_evidence_gate():
    skill = _read("plugins/pr-flow/skills/pr-retrospective/SKILL.md")

    preparation = skill.index("### Step 4b — 準備 typed-lessons 寫入")
    no_execute = skill.index("此處只準備 metadata 與 script，不得執行", preparation)
    evidence_gate = skill.index("#### Step 5.0 Evidence Gate", no_execute)
    promotion_gate = skill.index("#### Promotion Gate", evidence_gate)

    assert preparation < no_execute < evidence_gate < promotion_gate


def test_runbook_uses_executable_park_and_reassessment_contract():
    skill = _read("plugins/pr-flow/skills/pr-retrospective/SKILL.md")

    assert "mycelium lessons add --park" in skill
    assert "status=parked recurrence=<n>" in skill
    assert "status=reassess recurrence=<n>" in skill
    assert "只重套 parked、不再次 bump recurrence" in skill
    assert "--tag parked" not in skill


def test_evidence_lint_job_checkout_has_full_history():
    """`fetch-depth: 0` 必須掛在**跑 evidence lint 的那個 job** 的 checkout 上。

    整檔字串比對不夠：CI 日後拆成多 job 時，別的 job 帶著 `fetch-depth: 0` 就能滿足檔案層級
    的斷言，而 gate job 失去 merge-base 歷史、range diff 解不開——正是本 PR 要防的形狀。
    """
    job_name, job = _evidence_lint_job()
    checkouts = [
        s for s in (job.get("steps") or []) if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts, f"job '{job_name}' 沒有 actions/checkout step"
    for step in checkouts:
        with_ = step.get("with") or {}
        assert with_.get("fetch-depth") == 0, (
            f"job '{job_name}' 的 checkout 缺 `fetch-depth: 0`；shallow checkout 會讓 "
            f"`base...head` 解不開"
        )


def test_evidence_lint_steps_run_on_the_events_they_claim():
    """AC-3 要求「實際執行、不是 skip」——決定執不執行的是 `if:`，必須被斷言。

    mutation 實證（mob review 提供）：把 PR step 的 `if:` 改成 `pull_request_target`
    （本 workflow 的 `on:` 只有 push / pull_request），該 step 從此永久 skip、gate 什麼都不
    檢查，而改版前的測試照樣全綠。
    """
    triggers = _load_ci().get("on") or _load_ci().get(True)  # YAML 1.1 會把裸 `on` 解析成 True
    assert isinstance(triggers, dict), f"無法解析 ci.yml 的 on: 區塊（得到 {type(triggers)}）"
    assert "pull_request" in triggers, (
        "workflow 未在 pull_request 事件觸發，PR range step 永遠不會跑"
    )
    assert "push" in triggers, "workflow 未在 push 事件觸發，push range step 永遠不會跑"

    conditions = [str(s.get("if", "")) for s in _evidence_lint_steps()]
    pr_steps = [c for c in conditions if "pull_request" in c and "pull_request_target" not in c]
    push_steps = [c for c in conditions if "'push'" in c or '"push"' in c]

    assert pr_steps, (
        f"沒有任何 evidence-lint step 的 if: 綁在 pull_request 上，實際條件：{conditions}"
    )
    assert push_steps, f"沒有任何 evidence-lint step 的 if: 綁在 push 上，實際條件：{conditions}"
    for cond in pr_steps:
        assert "github.event_name == 'pull_request'" in cond, (
            f"PR step 的 if: 不是綁在 pull_request 事件上：{cond!r}"
        )


def test_workflow_argv_is_accepted_by_the_scripts_own_parser():
    """把 workflow 實際產生的 argv 餵給 `_parse_args`——呼叫端與實作端任一改動都會紅。

    比對 argv 而非 flag 名稱是關鍵：`--base=<v>` 與 `--base <v>` 的 flag 名稱相同，但前者會讓
    `_parse_args` 走到 `arg.startswith("-")` 而 raise `未知選項` → CI exit 2。
    """
    steps = _evidence_lint_steps()
    assert len(steps) == 2, f"預期 PR 與 push 各一個 evidence-lint step，實際 {len(steps)} 個"

    for step in steps:
        argv = _argv_from_run(str(step["run"]))
        assert argv, (
            f"step '{step.get('name')}' 沒有傳任何引數給 lint（等同 staged 模式，CI 上恆為空 diff）"
        )
        base, head, diff_file = lint_rule_evidence._parse_args(argv)
        assert base and head, f"step '{step.get('name')}' 未同時提供 --base/--head：{argv}"
        assert diff_file is None, f"step '{step.get('name')}' 不應同時給 diff 檔：{argv}"


def test_argv_extractor_rejects_the_equals_form_that_broke_ci():
    """正向對照：等號形式必須被抓出來，否則上面那條沒有資訊量。

    這正是 mob review 提出的存活突變——舊 guard 只抽 flag 名稱，等號形式照樣通過。
    """
    argv = _argv_from_run(
        f"uv run python {_LINT_SCRIPT} --base=PLACEHOLDER_SHA --head=PLACEHOLDER_SHA"
    )
    with pytest.raises(ValueError, match="未知選項"):
        lint_rule_evidence._parse_args(argv)


def test_drift_guard_itself_rejects_an_unknown_flag():
    """正向對照：parser 必須對不認得的 flag 真的抛錯。"""
    with pytest.raises(ValueError, match="未知選項"):
        lint_rule_evidence._parse_args(["--not-a-real-flag", "x"])
