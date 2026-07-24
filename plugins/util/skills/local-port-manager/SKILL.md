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

`portman` 由 yibi-stack CLI 提供，**不需要 clone 本 repo**，在任何 cwd 都能跑。

```bash
if ! command -v portman >/dev/null 2>&1; then
  echo '[FAIL] 找不到 portman 指令。請先安裝：' >&2
  echo '       uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"' >&2
  exit 1
fi
if ! portman --version; then
  echo '[FAIL] portman 安裝損毀（--version 非零退出）。請重裝：' >&2
  echo '       uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"' >&2
  exit 1
fi
if [ -f ~/.agents/ports.json ]; then echo "exists"; else echo "需要初始化"; fi
```

> **為何沒有最低版本比對**：唯一支援的安裝路徑已固定到 recorded release tag `v1.11.0`。
> `command -v portman` 驗證 console script 存在，`portman --version` 驗證 entry point 可啟動；
> 若行為與本文件不同，重裝同一個 recorded tag 並回報，不改追蹤未記錄版本。
>
> 因此 `--version` 在這裡的定位是**診斷**（人看的、貼 bug report 用的），不是閘門；閘門是
> 上面兩道 fail-loud：指令存在、安裝未損毀。
>
> ADR-0004 現行文字要求「能力／**版本**檢查」，與此實作有**已知歧異**——該要求的可行性正由
> issue #256 追蹤裁決（是否改為 capability/protocol revision 或行為 probe）。在裁決前不預先
> 加一道恆真的比較：`portman` 只存在於 >= 1.9.0，故 `command -v portman` 成功就已蘊含版本
> 下限，再比一次 `MIN_VERSION="1.9.0"` 守不到任何東西。

若 ports.json 不存在：

```bash
portman init
```

### Step 2 — 查詢現有登記

列出目標專案的 port 分配：

```bash
portman list --project {{project}}
```

過濾特定專案：

```bash
portman list --project {{project}}
```

查詢特定服務 port：

```bash
portman get {{project}} {{service}}
```

查詢某 port 被誰佔用：

```bash
portman check {{port}}
```

### Step 3 — 登記新 Port（三步驟）

**3-1. 查詢建議 port（不寫入）：**

```bash
portman suggest {{project}} {{service}}
```

**3-2. 告知使用者建議 port 與衝突原因，等使用者確認。**

**3-3. 確認後寫入登記：**

```bash
portman reserve {{project}} {{service}} --port {{port}}
```

### Step 4 — 移除登記

```bash
portman release {{project}} {{service}}
```

## Makefile 整合

`get` 在查無登記時 **exit 1 且 stdout 全空**（刻意設計，見 LPM-DT-021/022）。但
**GNU Make 的 `$(shell ...)` 會丟棄 exit status**——實測 `X := $(shell exit 1)` 只是把 `X`
綁成空字串，make 照常繼續、exit 0。所以裸寫法會**靜默**綁到空 port：

```makefile
# 不要這樣：get 失敗時 REDIS_PORT 靜默變成空字串
REDIS_PORT := $(shell portman get $(PROJECT) redis)
```

要讓它大聲失敗，必須自己檢查——`$(or ...)` 搭 `$(error ...)` 會在 **parse 階段**就中止：

```makefile
REDIS_PORT := $(or $(shell portman get $(PROJECT) redis),$(error [FAIL] $(PROJECT)/redis 尚未登記 port，請先執行 portman reserve))
```

（`:=` 是立即賦值，故 `$(error)` 在讀 Makefile 時就觸發，不必等到用到該變數的 target。）

## 常見問題

| 問題 | 解法 |
|------|------|
| `找不到 portman 指令` | `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"` |
| `portman --version` 非零退出（安裝損毀） | `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"` |
| `portman` 行為與本文件不符（疑似版本落差） | 重裝 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"`，若仍不符則回報 |
| `Registry 不存在` | 執行 `portman init` 建立**空** registry（不含任何預載專案），再用 `reserve` 登記 |
| `port 已被佔用` | 先執行 `suggest` 取得可用 port，再 `reserve` |
| Makefile 整合 | 見下方「Makefile 整合」——**不要**直接用裸的 `$(shell ...)`，它會吞掉失敗 |
