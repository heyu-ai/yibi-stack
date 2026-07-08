# Design：add-harness-eval-validation-protocol

> 版本：v1.0 | 日期：2026-06-08

## 新增檔案（rule 04 module 結構）

```text
tasks/harness_eval/validation/__init__.py        ← 一行中文 docstring
tasks/harness_eval/validation/__main__.py        ← 2 行：import cli + cli()
tasks/harness_eval/validation/cli.py             ← freeze / score / holdout 子命令
tasks/harness_eval/validation/models.py          ← Pydantic：ProtocolSnapshot / MetricResult / DataPoint
tasks/harness_eval/validation/service.py         ← 凍結、metric 計算、holdout 切分
tasks/harness_eval/validation/tests/__init__.py
tasks/harness_eval/validation/tests/test_validation.py
```

## 修改檔案

```text
skills/harness-eval/SKILL.md   ← 新增「驗證協定」段落（或拆 harness-eval-validate skill）
```

---

## 資料模型（models.py）

```python
from pydantic import BaseModel, Field

class ProtocolSnapshot(BaseModel):
    """凍結的評估協定快照。"""
    version: str = "1.0"
    protocol_hash: str                       # 內容雜湊（sha256，截短）
    dimension_weights: dict[str, int]        # 各維度 max_score
    d_repo_scale: float                       # 來自 #136 的 provisional 係數
    metric_definition: str = "r2+mae"

class DataPoint(BaseModel):
    repo_id: str
    score: float                              # harness-eval 分數（raw 或 size_adjusted）
    outcome: float                            # [0,1] 成功率 proxy（來自 #142）
    batch: str | None = None                  # holdout 切分用

class MetricResult(BaseModel):
    r2: float
    mae: float
    n: int
    protocol_hash: str
    holdout_batch: str | None = None
```

---

## 反 post-hoc guard（C1，機制強制）

```python
def _require_frozen_protocol(snapshot_path: Path) -> ProtocolSnapshot:
    """metric 計算前必須有有效 snapshot；否則拒絕（反 post-hoc）。"""
    if not snapshot_path.is_file():
        raise RuntimeError(
            "找不到協定快照，請先執行 freeze 凍結評估協定（防止事後挑參數）"
        )
    snap = ProtocolSnapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    # 重算 hash 確認 snapshot 未被竄改
    if _compute_protocol_hash(snap) != snap.protocol_hash:
        raise RuntimeError("協定快照雜湊不符，快照可能已被竄改")
    return snap
```

`score` 與 `holdout` 子命令一律先呼叫此函數；無 snapshot → 非零 exit（AC-004-1）。

---

## Metric 計算（service.py）

```python
def compute_metrics(points: list[DataPoint], protocol_hash: str,
                    holdout_batch: str | None = None) -> MetricResult:
    rows = [p for p in points if holdout_batch is None or p.batch == holdout_batch]
    if not rows:
        raise ValueError("holdout 批次無樣本，無法計算 metric")  # AC-003-3
    y = [p.outcome for p in rows]
    x = [p.score for p in rows]
    r2 = _r_squared(x, y)         # 1 - SS_res/SS_tot（以分數線性預測 outcome）
    mae = _mae(x, y)             # 視需要先做 min-max 對齊或線性 fit
    return MetricResult(r2=r2, mae=mae, n=len(rows),
                        protocol_hash=protocol_hash, holdout_batch=holdout_batch)
```

R²/MAE 以純 stdlib 實作（或輕量 numpy）；完美線性資料 → R²=1、MAE=0（AC-002-2）。

---

## CLI（rule 08）

```python
@cli.command()
def freeze() -> None:
    """凍結當前評估協定為版本化快照。"""

@cli.command()
@click.option("--dataset", required=True, type=click.Path(exists=True))
def score(dataset: str) -> None:
    """計算 harness-eval 分數對 outcome 的 R²/MAE。"""

@cli.command()
@click.option("--dataset", required=True, type=click.Path(exists=True))
@click.option("--holdout-batch", required=True)
def holdout(dataset: str, holdout_batch: str) -> None:
    """只在指定 holdout 批次上回報 metric（prospective holdout）。"""
```

執行：`uv run python -m tasks.harness_eval.validation <freeze|score|holdout> ...`

---

## 資料集 ingest

支援 CSV 與 JSONL，欄位 `repo_id, score, outcome[, batch]`。
JSONL 逐行解析，malformed 行 skip（`except ... continue  # nosec B112`，見 rule 09）。

---

## 前置依賴與分階段

- **可立即做**：protocol 凍結 + hash + guard、R²/MAE 計算、holdout 切分、CSV/JSONL ingest、
  以 fixture 資料集驗證全部邏輯。
- **待 #140 / #142**：真實 `(score, outcome)` 資料 wiring——`score`/`outcome` 由 trace/EFC 與
  outcome labels 餵入。apply 時此步驟標為 blocked-on（#140、#142），不阻擋邏輯層落地。

---

## 衝突偵測

- 新 capability `harness-eval-validation-protocol` 與既有 spec 無命名衝突。
- 新 module `tasks/harness_eval/validation/` 為子套件，與既有 scanners/service 無符號衝突。
- `make install` skip list 不受影響（此為 tasks/ 下模組，非 skills/ 目錄）。
