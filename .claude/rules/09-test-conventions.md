---
globs: tasks/**/tests/**
---
# 測試慣例

## 命名規範

```text
tasks/<module>/tests/
├── __init__.py
├── test_models.py
├── test_service.py
├── test_cli.py
└── test_parsers.py    # 如有 parsers/
```

Class 命名：`class TestXxx:`（無繼承）
Method 命名：`test_<scenario>` 或帶結構 ID：`test_gbill_dt_001_cathay_cc_parser`

## 結構化 Test ID

在 docstring 內標記 ID，格式：`<MODULE>-<CATEGORY>-<NUMBER>`

| 縮寫 | 用途 |
|------|------|
| DT | Decision Table（分支覆蓋） |
| ST | Service Test（整合流程） |
| EG | Edge Case（邊界條件） |
| CV | Conversion（格式轉換） |
| VL | Validation（驗證規則） |

```python
def test_gscan_dt_001_scan_days_controls_after_date(self) -> None:
    """GSCAN-DT-001: scan_days 控制 after_date 計算"""
    ...
```

## Helper Factory Functions

用 module-level helper functions 建立測試資料，不用 conftest.py：

```python
def make_scan_profile(**kwargs: object) -> ScanProfile:
    defaults = {"name": "test", "labels": ["INBOX"], "scan_days": 7}
    return ScanProfile(**{**defaults, **kwargs})

class TestScanProfile:
    def test_default_values(self) -> None:
        profile = make_scan_profile()
        assert profile.scan_days == 7
```

## Mocking

```python
SCAN_SVC = "tasks.gmail_scan.service"

class TestRunScan:
    @patch(f"{SCAN_SVC}.build_gmail_service")
    def test_builds_service(self, mock_build: MagicMock) -> None:
        ...
```

## 資源處理

- SQLite：傳入 `":memory:"`
- Filesystem：用 pytest 內建 `tmp_path` fixture
- 不建立 conftest.py，不自訂 pytest fixtures

## Import 語法

測試內一律用絕對路徑 import：

```python
from tasks.gmail_scan.models import ScanProfile
from tasks.gmail_scan.service import run_scan
```

## Test Fixture Schema 必須對照真實工具 Schema

Fixture 的資料結構必須與被測工具的**真實** schema 一致，不可自創。
測試通過只驗證「邏輯在測試資料下能跑」，不驗證「在真實環境下能跑」。

反例（PR #20 hooks.py）：fixture 用 `{"run": ".sh"}` 但 Claude Code 真實 schema 是
`{"hooks": [{"type": "command", "command": ".sh"}]}`——59 tests 全過，但生產環境
ghost hook 偵測永遠無效，直到 mob review 對照真實 `.claude/settings.json` 才發現。

正確做法：寫 fixture 前先讀真實工具的 schema 文件，或對照真實設定檔（如 `.claude/settings.json`）。

## Assertion 語意精確性

Findings / output 驗證避免過寬的 substring match——目標字串若同時出現在多個合理路徑，
assertion 就失去保護力，fallback 邏輯失效時靜默通過。

```python
# 違規：".claude/skills/" 也含 "skills/"，fallback 失效時仍通過
assert any("skills/" in f for f in result.findings)

# 正確：用語意唯一的字串鎖定預期分支
assert any("源碼 repo 模式" in f for f in result.findings)
```

適用場景：任何驗證「走了哪條邏輯分支」的 assertion。

## Bandit `# nosec` 使用慣例

測試中不應無腦加 `# nosec`；但下列兩類場景是合理例外：

**B112（try_except_continue）— 串流解析跳過格式錯誤行**

```python
try:
    obj = json.loads(raw)
except Exception:  # nosec B112
    continue
```

適用場景：逐行解析 JSONL / log 檔時，格式錯誤的行應跳過而非中止整個解析流程。`continue` 是刻意設計，不是疏忽。

**F841（unused variable）— 徹底刪除，不用 `# noqa`**

ruff F841「local variable assigned but never used」需**同時刪除賦值行與初始化行**；只刪其中一行，另一行仍會觸發。

```python
# 違規：刪了 loop 內的賦值，但保留了函式開頭的初始化
prev_output_tokens = 0      # <-- 這行也要刪
...
# prev_output_tokens = last_output_tokens  # 已刪，但上面那行仍是 F841

# 正確：兩行都刪除
```
