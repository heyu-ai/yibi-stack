# Design：add-token-economy-harness

> 版本：v1.0 | 日期：2026-06-01

## 新增檔案

```text
tasks/harness_eval/scanners/token_economy.py   ← D11 scanner（新增）
```

## 修改檔案

```text
tasks/harness_eval/scanners/__init__.py       ← 匯出 scan_token_economy
tasks/harness_eval/service.py                 ← 加入 D11 _safe_scan 呼叫
tasks/harness_eval/tests/test_scanners.py     ← 新增 D11 測試
skills/harness-eval/SKILL.md                  ← Step 3 rubric 加入 D11 語意子項
```

---

## D11 Scanner 介面

```python
# tasks/harness_eval/scanners/token_economy.py

D11_MAX = 8  # 與 D1 同等重要性

def scan_token_economy(target_dir: Path) -> MechanicalFinding:
    """D11：Context / Token Economy 靜態 proxy 掃描。
    
    注意：所有數字為字元估計（非精準 token 計量）。
    """
    ...
```

回傳 `MechanicalFinding`（沿用現有 model，不修改 models.py）：

```python
MechanicalFinding(
    dimension="D11",
    label="Context / Token Economy",
    score=<0..8>,
    max_score=8,
    findings=[...],          # 含 WARN/OK 字串 + disclaimer
    semantic_targets=[...],  # SKILL.md 路徑供語意評分參考
    extra={
        "always_on_chars": ["12500"],        # list[str] → 供 testability
        "on_demand_chars": ["3200"],
        "total_chars": ["15700"],
        "overlap_words": ["git", "commit"],  # 重疊詞（≤5 個）
        "effort_missing_skills": ["rule-13", "bash-hygiene-audit"],
    },
)
```

---

## 計分邏輯

| 指標 | 條件 | 分數調整 |
|------|------|---------|
| always-on chars | ≤ 5000 | +3 |
| always-on chars | 5001–20000 | +1 |
| always-on chars | 20001–25000 | 0（扣 1）|
| always-on chars | 25001–30000 | 0（扣 2）|
| always-on chars | > 30000 | 0（扣 3）|
| progressive-disclosure ratio | ≥ 0.5 | +2 |
| progressive-disclosure ratio | 0.3–0.499 | +1 |
| progressive-disclosure ratio | < 0.3 | 0 |
| CLAUDE.md ↔ rules 無重疊 | < 3 個共同高頻詞 | +2 |
| CLAUDE.md ↔ rules 重疊 | ≥ 3 個共同高頻詞 | 0 |
| effort 相稱性 | 無長 skill 缺 effort | +1 |
| effort 相稱性 | 有長 skill 缺 effort | 0 |

**合計上限 = 8；score = max(0, sum)**

---

## always-on chars 定義（靜態 proxy）

```text
always_on_chars =
    CLAUDE.md 字元數（若存在）
  + settings.json 中 glob pattern 命中的 .claude/rules/*.md 字元數合計
  + .claude/memory/*.md 字元數合計（若目錄存在）
```

## on-demand chars 定義

```text
on_demand_chars =
    skills/ 下所有 SKILL.md 的 body 部分字元數合計
    （body = frontmatter 以外的內容，即 --- 第二個分隔符之後）
```

## 停用詞列表（詞頻重疊排除）

英文：`a, an, the, and, or, in, of, to, is, are, be, for, on, with, this, that, it`
中文：`的, 是, 在, 了, 有, 和, 不, 與, 為, 對, 到, 要, 可以, 如果`

---

## service.py 修改

```python
# 在 run_scan() 的 dimensions 清單最後加一行：
_safe_scan(scan_token_economy, target, "D11", "Context / Token Economy", 8),
```

---

## SKILL.md Step 3 語意 rubric 增補（D11）

```markdown
### D11 Context / Token Economy（語意 0–4 分）

| 子項 | 機械線索 | 滿分條件 |
|------|---------|---------|
| always-on 比例合理 | extra["always_on_chars"] | proxy < 20000 字元 + 2 分 |
| progressive-disclosure 活用 | extra["on_demand_chars"] | ratio ≥ 0.5 + 1 分 |
| 無 effort 相稱性問題 | extra["effort_missing_skills"] 為空 | + 1 分 |

> 注意：D11 語意分補充機械分不足的主觀判斷。機械分已含邊際遞減懲罰。
```

---

## 衝突偵測

- `openspec/specs/`：目前僅有 `d5-behavior-quality-rubric`，無路徑/命名衝突
- `scan_token_economy` 函數名稱與現有 scanners 無重複
- D11 dimension string 在現有 ScanOutput.dimensions 中未使用
- `MechanicalFinding.extra` 現有 schema `dict[str, list[str]]`——新增欄位
  `always_on_chars`, `on_demand_chars` 等均為 `list[str]`，型別相容，無 schema 衝突
- **Baseline：無需 openspec/specs/ 衝突檢查**（`d5-behavior-quality-rubric` 為完全不同 domain）
