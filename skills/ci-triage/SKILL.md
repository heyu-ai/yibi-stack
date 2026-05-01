---
name: ci-triage
type: know
scope: global
description: 快速定位 CI 失敗原因的通用診斷漏斗（Lint → Format → Type check → Tests），適用 Python/JS/Go 等技術棧。Security scanner 誤報處理見速查章節。觸發關鍵字：ci 失敗、lint 錯誤、type error、security scanner、pre-commit 失敗、哪個 check 失敗
---

# CI 快速診斷

## 診斷漏斗（由快到慢）

依序執行，**失敗即停**，不要等全跑完再看：

| 順序 | 階段 | 常見工具 | 時間估計 |
|------|------|---------|----------|
| 1 | **Lint** | ruff / eslint / golangci-lint | ~2s |
| 2 | **Format** | ruff format / prettier / gofmt | ~2s |
| 3 | **Type check** | mypy / tsc / go vet | ~15s |
| 4 | **Tests** | pytest / jest / go test | ~10–30s |
| 5 | **Full CI** | `make ci` / `npm run ci` / pre-commit | ~60s |

先讀專案根目錄找實際指令：

```bash
grep -E "^lint:|^format:|^typecheck:|^test:|^ci:" Makefile 2>/dev/null | head -10
cat package.json 2>/dev/null | python3 -c "import json,sys; [print(k,':',v) for k,v in json.load(sys.stdin).get('scripts',{}).items()]"
```

---

## 常見錯誤速查

### Lint — Import 順序 / 未使用變數

**Python（ruff I001 — import 順序；F401 — 未使用 import）**：

```python
# 錯誤：local import 在第三方之前
from tasks.foo import bar
import requests           # ruff 標記 I001

# 修法：標準庫 → 第三方 → local
import requests
from tasks.foo import bar
```

自動修：`ruff check --fix` / `eslint --fix` / `goimports -w .`

---

### Type check — 缺少標注 / None 未處理

**Python（mypy）**：

```python
# 錯誤：缺少回傳型別
def load_config(path):  # error: missing return type annotation

# 正確
def load_config(path: Path) -> FooConfig: ...
```

```python
# 錯誤：Optional 未判斷
value = some_dict.get("key")
result = value.upper()  # error: Item "None" has no attribute "upper"

# 修法：先 guard
if value is not None:
    result = value.upper()
```

**TypeScript（tsc）**：`noImplicitAny` 通常需明確標注。untyped 第三方套件加 `@types/<pkg>` 或在 `tsconfig.json` 加 `skipLibCheck`。

**Go（go vet）**：`go vet ./...` 後根據訊息修正；型別不符通常是介面實作不完整。

---

### Security scanner — 誤報處理

**Python（bandit）**：

```python
import subprocess  # nosec B404
result = subprocess.run(["git", "status"], ...)  # nosec B603

# 動態 SQL WHERE（僅限參數化查詢場景）
where = f"WHERE {' AND '.join(conditions)}"  # nosec B608
```

**Node.js（npm audit）**：`npm audit fix` 先自動升版；高危依賴考慮 `npm audit fix --force` 或 override。

**Go（gosec）**：`//nolint:gosec // 原因` 加到對應行。

---

### Tests — 失敗診斷

只跑單一模組加速迭代：

| 技術棧 | 指令 |
|--------|------|
| Python | `pytest tasks/<module>/tests/ -v` 或 `uv run pytest ... -v` |
| Node.js | `jest src/<module> --watch` |
| Go | `go test ./internal/<pkg>/...` |

只跑特定 hook（Python pre-commit 環境）：

```bash
uv run pre-commit run ruff --all-files
uv run pre-commit run mypy --all-files
```

---

## 環境差異排查

CI 通過但本地失敗（或反之）：

1. 比對工具版本：`ruff --version` / `node --version` / `go version`
2. 比對環境變數：CI 常有 `CI=true` 影響部分工具行為
3. 比對快取：清除 `.mypy_cache` / `node_modules` 後重跑
4. 以本地工具輸出為準：修到本地乾淨，再推 CI 觀察
