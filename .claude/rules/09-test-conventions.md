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
