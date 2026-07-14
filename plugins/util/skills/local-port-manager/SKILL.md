---
name: local-port-manager
type: exec
scope: global
description: 本地開發 Port 分配登錄。查詢/登記/釋放各專案服務的 port，避免多專案衝突。觸發關鍵字：port 衝突、幫我登記 port、哪個 port 可用、port 被佔用、reserve port、列出 port 分配
---

# Local Port Manager

機器層 port 分配登錄系統，管理 `~/.agents/ports.json`。
支援多專案同時開發，預防 postgres/redis/backend 等服務 port 衝突。

## 執行步驟

### Step 1 — 環境確認

```bash
# 定位 yibi-stack repo（在任何 cwd 都能跑）
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
cd "$SKILL_REPO"

uv --version          # 確認 uv 可用
ls ~/.agents/ports.json 2>/dev/null && echo "exists" || echo "需要初始化"
```

若 ports.json 不存在：

```bash
uv run python -m tasks.local_port_manager init
```

### Step 2 — 查詢現有登記

列出所有 port 分配：

```bash
uv run python -m tasks.local_port_manager list
```

過濾特定專案：

```bash
uv run python -m tasks.local_port_manager list --project {{project}}
```

查詢特定服務 port：

```bash
uv run python -m tasks.local_port_manager get {{project}} {{service}}
```

查詢某 port 被誰佔用：

```bash
uv run python -m tasks.local_port_manager check {{port}}
```

### Step 3 — 登記新 Port（三步驟）

**3-1. 查詢建議 port（不寫入）：**

```bash
uv run python -m tasks.local_port_manager suggest {{project}} {{service}}
```

**3-2. 告知使用者建議 port 與衝突原因，等使用者確認。**

**3-3. 確認後寫入登記：**

```bash
uv run python -m tasks.local_port_manager reserve {{project}} {{service}} --port {{port}}
```

### Step 4 — 移除登記

```bash
uv run python -m tasks.local_port_manager release {{project}} {{service}}
```

## 常見問題

| 問題 | 解法 |
|------|------|
| `Registry 不存在` | 執行 `init` 指令建立 bootstrap 資料 |
| `port 已被佔用` | 先執行 `suggest` 取得可用 port，再 `reserve` |
| Makefile 整合 | `REDIS_PORT := $(shell uv run python -m tasks.local_port_manager get $(PROJECT) redis)` |
