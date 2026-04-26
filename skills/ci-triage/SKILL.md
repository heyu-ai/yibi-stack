---
name: ci-triage
type: know
description: 快速定位 CI 失敗原因的診斷順序，避免每次都等完整 make ci。觸發關鍵字：ci 失敗、lint 錯誤、mypy 錯誤、bandit、pre-commit 失敗、哪個 check 失敗
---

# CI 快速診斷

## 診斷順序（由快到慢）

依序執行，**失敗即停**，不要等全跑完再看：

| 順序 | 指令 | 時間估計 | 常見失敗原因 |
|------|------|----------|-------------|
| 1 | `make lint` | ~2s | import 順序、未使用變數、f-string 格式 |
| 2 | `make format` | ~2s | 縮排、引號、行長超過 100 |
| 3 | `make typecheck` | ~15s | 缺少型別標注、`None` 未處理、StrEnum 誤用 |
| 4 | `make test` | ~10s | 邏輯錯誤、assertion 失敗 |
| 5 | `make ci` | ~60s | 完整 pre-commit + bandit + pytest |

## 常見錯誤速查

### ruff E402 — import 順序錯誤

```python
# 錯誤：第三方 import 在 local import 之前
from tasks.foo import bar
import requests  # ← ruff 會標記這行

# 正確：標準庫 → 第三方 → local
import requests
from tasks.foo import bar
```

### mypy 嚴格模式常見錯誤

```python
# 錯誤：未標注回傳型別
def load_config(path):  # error: Function is missing a return type annotation

# 正確
def load_config(path: Path) -> FooConfig: ...
```

```python
# 錯誤：Optional 未處理
value = some_dict.get("key")
result = value.upper()  # error: Item "None" has no attribute "upper"

# 正確
value = some_dict.get("key")
if value is not None:
    result = value.upper()
```

### bandit 常見誤報

```python
# B404 / B603：subprocess 合法用法加 nosec 即可
import subprocess  # nosec B404
result = subprocess.run(["git", "status"], ...)  # nosec B603

# B608：動態 SQL WHERE 子句
where = f"WHERE {' AND '.join(conditions)}"  # nosec B608
```

## 本地只跑單一模組測試

```bash
uv run pytest tasks/<module>/tests/ -v
```

## pre-commit 只跑特定 hook

```bash
uv run pre-commit run ruff --all-files
uv run pre-commit run mypy --all-files
```
