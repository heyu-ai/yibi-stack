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
    """把 step 的 `run` scalar 還原成腳本實際收到的 argv。

    每個 `${{ expr }}` 換成**可辨識**的 `EXPR:<expr>` 佔位，而不是同一個匿名 token。
    這一點是關鍵：折成同一個 token 只驗得出「有兩個 flag、值是某個東西」，驗不出
    `--base` 拿到的是 `base.sha` 還是 `head.sha`——把 `--base` 換成 head 側會讓 range 變成
    `head...head`、diff 恆空、gate exit 0 印 `[OK]`，正是 AC-3「不是讀到空 diff」要擋的假綠。
    （PR #347 re-review 以 mutation 實證該假綠存活。）

    保留 argv 形式（而非只比對原文）也是必要的：`--base <v>` 與 `--base=<v>` 的 flag 名稱
    相同，但後者會讓 `_parse_args` 走到 `arg.startswith("-")` 而 raise `未知選項`。
    """
    masked: list[str] = []
    rest = run
    while "${{" in rest:
        head, _, tail = rest.partition("${{")
        expr, _, tail = tail.partition("}}")
        assert expr, f"ci.yml 的 `${{{{` 沒有對應的 `}}}}`：{run!r}"
        masked.append(head)
        masked.append(f"EXPR:{expr.strip()}")
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
    skill = _read("plugins/growth/skills/pr-retrospective/SKILL.md")

    preparation = skill.index("### Step 4b — 準備 typed-lessons 寫入")
    no_execute = skill.index("此處只準備 metadata 與 script，不得執行", preparation)
    evidence_gate = skill.index("#### Step 5.0 Evidence Gate", no_execute)
    promotion_gate = skill.index("#### Promotion Gate", evidence_gate)

    assert preparation < no_execute < evidence_gate < promotion_gate


def test_runbook_uses_executable_park_and_reassessment_contract():
    skill = _read("plugins/growth/skills/pr-retrospective/SKILL.md")

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
    ci = _load_ci()
    triggers = ci.get("on") or ci.get(True)  # YAML 1.1 會把裸 `on` 解析成 True
    assert isinstance(triggers, dict), f"無法解析 ci.yml 的 on: 區塊（得到 {type(triggers)}）"
    assert "pull_request" in triggers, (
        "workflow 未在 pull_request 事件觸發，PR range step 永遠不會跑"
    )
    assert "push" in triggers, "workflow 未在 push 事件觸發，push range step 永遠不會跑"

    # **完全比對**，不是子字串比對。子字串比對對「條件後面接了什麼」完全不看，於是加一個
    # 收窄的合取（現實中的形狀是 `&& github.event.pull_request.draft == false`，不是
    # `&& false`）就讓 gate 在某些 PR 上永久 skip，而測試照樣全綠。
    # （PR #347 re-review 以 mutation 實證該假綠存活。）
    # 代價是改條件時必須連本測試一起改——那正是它存在的目的。
    conditions = {str(s.get("if", "")) for s in _evidence_lint_steps()}
    expected = {
        "github.event_name == 'pull_request'",
        "github.event_name == 'push' && github.event.before != "
        "'0000000000000000000000000000000000000000'",
    }
    assert conditions == expected, (
        f"evidence-lint step 的 if: 條件與預期不完全相符。\n實際：{sorted(conditions)}\n"
        f"預期：{sorted(expected)}\n"
        "任何額外合取都會讓 gate 在某些事件上靜默 skip；若這是刻意的，請同步更新本測試。"
    )


def test_workflow_argv_is_accepted_by_the_scripts_own_parser():
    """把 workflow 實際產生的 argv 餵給 `_parse_args`——呼叫端與實作端任一改動都會紅。

    比對 argv 而非 flag 名稱是關鍵：`--base=<v>` 與 `--base <v>` 的 flag 名稱相同，但前者會讓
    `_parse_args` 走到 `arg.startswith("-")` 而 raise `未知選項` → CI exit 2。
    """
    steps = _evidence_lint_steps()
    assert len(steps) == 2, f"預期 PR 與 push 各一個 evidence-lint step，實際 {len(steps)} 個"

    seen: dict[str, str] = {}
    for step in steps:
        argv = _argv_from_run(str(step["run"]))
        assert argv, (
            f"step '{step.get('name')}' 沒有傳任何引數給 lint（等同 staged 模式，CI 上恆為空 diff）"
        )
        base, head, diff_file = lint_rule_evidence._parse_args(argv)
        assert base and head, f"step '{step.get('name')}' 未同時提供 --base/--head：{argv}"
        assert diff_file is None, f"step '{step.get('name')}' 不應同時給 diff 檔：{argv}"
        assert base != head, (
            f"step '{step.get('name')}' 的 --base 與 --head 是同一個表達式 "
            f"（{base}）——range 會退化成 `X...X`、diff 恆空、gate 印 [OK] 卻什麼都沒檢查"
        )
        seen[str(step.get("if", ""))] = f"{base} {head}"

    # 逐一釘住「哪個 SHA 餵給哪個 flag」。只驗「有兩個 flag、值是某個 token」擋不住把
    # `--base` 換成 head 側——那會讓 range 變成 `head...head` 而 gate 恆綠。
    pr_key = "github.event_name == 'pull_request'"
    assert pr_key in seen, f"找不到 pull_request step 的 if: 條件，實際：{sorted(seen)}"
    push_key = next((k for k in seen if k.startswith("github.event_name == 'push'")), None)
    assert push_key is not None, f"找不到 push step 的 if: 條件，實際：{sorted(seen)}"
    assert seen[pr_key] == (
        "EXPR:github.event.pull_request.base.sha EXPR:github.event.pull_request.head.sha"
    ), f"PR step 的 base/head 表達式配對錯誤：{seen[pr_key]}"
    assert seen[push_key] == "EXPR:github.event.before EXPR:github.sha", (
        f"push step 的 base/head 表達式配對錯誤：{seen[push_key]}"
    )


def test_argv_extractor_detects_a_degenerate_same_sha_range():
    """正向對照：把 --base 換成 head 側時，上面那條必須紅。

    這是 re-review 實證存活的假綠形狀——`head...head` 的 diff 恆空，gate exit 0 印 `[OK]`。
    """
    argv = _argv_from_run(
        f"uv run python {_LINT_SCRIPT} "
        '--base "${{ github.event.pull_request.head.sha }}" '
        '--head "${{ github.event.pull_request.head.sha }}"'
    )
    base, head, _ = lint_rule_evidence._parse_args(argv)
    assert base == head, "佔位 token 折疊了表達式差異——本對照失去偵測能力"


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
