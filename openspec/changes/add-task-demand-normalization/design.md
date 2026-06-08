# Design：add-task-demand-normalization

> 版本：v1.0 | 日期：2026-06-08

## 修改檔案

```text
tasks/harness_eval/models.py                  ← ScanOutput 加 d_repo / size_adjusted_score
tasks/harness_eval/service.py                 ← run_scan() 末段計算 D_repo 與調整分數
tasks/harness_eval/cli.py                     ← text 輸出顯示兩分數 + provisional 標示
tasks/harness_eval/tests/test_scanners.py     ← 新增 TDN 測試（或新 test_normalization.py）
skills/harness-eval/SKILL.md                  ← 報告格式段落說明 size_adjusted_score
```

不新增也不修改 `scanners/*.py`。

---

## D_repo 定義（provisional 啟發式）

```python
# tasks/harness_eval/service.py

import math

# provisional 係數；真正校準見 issue #143
_DREPO_SCALE = 50.0

def _compute_d_repo(target_dir: Path) -> tuple[float, list[str]]:
    """計算 repo 複雜度因子 D_repo（>= 1.0）與其組成清單。

    provisional：未經 outcome 校準，僅供相對規模調整。
    """
    loc = _count_source_loc(target_dir)        # tasks/ + scripts/ 的 .py 行數
    skills = _count_skills(target_dir)         # skills/*/SKILL.md 數
    hooks = _count_hooks(target_dir)           # settings.json hooks 條目數
    rules = _count_rules(target_dir)           # .claude/rules/*.md 數

    raw = loc + skills * 100 + hooks * 50 + rules * 80
    d_repo = 1.0 + math.log10(1.0 + raw / _DREPO_SCALE)
    components = [
        f"loc={loc}", f"skills={skills}", f"hooks={hooks}", f"rules={rules}",
    ]
    return round(d_repo, 3), components
```

設計理由：

- **log 縮放**：複雜度成長時 D_repo 平緩上升，避免大 repo 被線性過度懲罰。
- **`1.0 +`**：保證 `D_repo ≥ 1.0`（C1），最小 repo（raw=0）得 `log10(1)=0` → D_repo=1.0。
- **權重（100/50/80）**：provisional，反映「一個 skill/rule 的結構份量 ≈ 數十至上百行 source」的
  粗略直覺；校準前不可當絕對門檻（A1）。

---

## 聚合層整合

```python
# tasks/harness_eval/service.py，run_scan() 末段
d_repo, d_repo_components = _compute_d_repo(target_dir)
size_adjusted = round(total_mechanical / d_repo, 1)

return ScanOutput(
    ...,
    total_mechanical=total_mechanical,
    total_mechanical_max=total_mechanical_max,
    d_repo=d_repo,
    size_adjusted_score=size_adjusted,
    # d_repo_components 放入既有 extra 機制或 ScanOutput 的對應欄位
)
```

---

## models.py schema 變更

```python
class ScanOutput(BaseModel):
    version: str = "1.0"
    ...
    total_mechanical: int
    total_mechanical_max: int
    d_repo: float = 1.0                    # 新增：複雜度因子（>=1）
    size_adjusted_score: float = 0.0       # 新增：total / d_repo（provisional）
```

`d_repo_components` 以 list[str] 形式放入既有的 per-dimension `extra` 或 ScanOutput 層級欄位
（沿用 `MechanicalFinding.extra: dict[str, list[str]]` 的型別慣例，無 schema 衝突）。

---

## CLI 輸出（text）

```text
總機械分：62 / 69
規模調整分（size_adjusted）：12.4  [provisional：未校準，見 #143]
  D_repo = 5.01  (loc=4200, skills=18, hooks=6, rules=14)
```

json 輸出新增 `d_repo`、`size_adjusted_score` 兩鍵，並在 findings/meta 帶 provisional 字串。

---

## 衝突偵測

- `openspec/specs/` 既有 `d5-behavior-quality-rubric`、`token-economy-scanner`——
  `task-demand-normalization` 為不同 capability，無命名衝突。
- `ScanOutput` 新增欄位均有 default，向後相容（既有測試不破）。
- `_compute_d_repo` 與既有函數名無衝突。
