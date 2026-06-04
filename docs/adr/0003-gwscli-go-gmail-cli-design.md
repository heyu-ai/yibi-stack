# gwscli — Go Native Gmail CLI 設計

## 背景

現有 `tasks/gmail_scan/` 透過 `gws` CLI（`@anthropic-ai/gws`）存取 Gmail API，但該套件在 npm registry 中不存在，無法安裝。使用者需要掃描兩個不同 Gmail 帳號（公司 + 個人），且想要零依賴、高效能的解決方案。

**決策：** 用 Go 寫一個原生 binary `gwscli`，作為 Gmail API 的 thin wrapper。Python 側的 `service.py` 改為呼叫 `gwscli`（與原本呼叫 `gws` 的模式相同，改動最小）。未來可漸進擴展到其他 Google Workspace 服務。

## 範圍

### Phase 1（本次實作）

- OAuth 2.0 認證：多帳號支援（`--account` / `--token-file`）
- Gmail 郵件搜尋（messages search）
- Gmail 郵件詳情（messages get）
- 附件下載（attachments download）
- Python `service.py` 改為呼叫 `gwscli`

### 不在範圍

- PDF 解析 / 解密（維持 Python pikepdf）
- Profile 管理 / SQLite DB（維持 Python）
- Drive、Calendar 等其他 Google Workspace 服務（未來再擴展）

## CLI 介面

所有命令的 stdout 輸出 JSON，stderr 輸出錯誤訊息。

### 認證

```bash
# 開瀏覽器走 OAuth flow，token 存到 ~/.gwscli/tokens/<account>.json
gwscli auth login --account <name>

# 檢查 token 是否有效
gwscli auth status --account <name>

# 列出所有已認證帳號
gwscli auth list
```

### 郵件搜尋

```bash
gwscli messages search --account <name> --query "subject:帳單 has:attachment" \
    [--after 2024/01/01] [--before 2024/12/31] [--max-results 100]
```

輸出：

```json
{
  "messages": [
    {"id": "abc123", "threadId": "thread456"}
  ],
  "resultSizeEstimate": 42
}
```

### 郵件詳情

```bash
gwscli messages get --account <name> --id <message_id> [--format full|minimal|metadata]
```

輸出：Gmail API 原始回應 JSON。

### 附件下載

```bash
gwscli attachments download --account <name> \
    --message-id <mid> --attachment-id <aid> --output <filepath>
```

輸出：

```json
{"path": "/absolute/path/to/saved/file", "size": 12345}
```

### 版本

```bash
gwscli --version    # 輸出版本號，如 "gwscli v0.1.0"
```

### 全域旗標

| 旗標 | 說明 |
|------|------|
| `--account <name>` | 帳號名稱，對應 `~/.gwscli/tokens/<name>.json` |
| `--token-file <path>` | 直接指定 token 檔路徑（覆寫 --account） |
| `--client-secret <path>` | OAuth client secret 路徑（預設 `~/.gwscli/client_secret.json`） |
| `--quiet` | 抑制 stderr 的 info 訊息 |

## Token 管理

```text
~/.gwscli/
├── client_secret.json          # OAuth client secret（使用者從 GCP Console 下載）
└── tokens/
    ├── work.json               # --account work 的 OAuth token
    └── personal.json           # --account personal 的 OAuth token
```

- OAuth Client ID 可複用現有 GCP 專案（例如 Gemini CLI 的同一專案）
- gwscli 請求的 scope：`https://www.googleapis.com/auth/gmail.readonly`
- Token 包含 refresh_token，過期時自動 refresh
- `auth login` 啟動本地 HTTP server（localhost:PORT）接收 OAuth callback

## Go 專案結構

```text
cmd/gwscli/
├── main.go
├── cmd/
│   ├── root.go                 # cobra root command + 全域旗標
│   ├── auth.go                 # auth login/status/list
│   ├── messages.go             # messages search/get
│   └── attachments.go          # attachments download
├── internal/
│   ├── auth/
│   │   ├── oauth.go            # OAuth flow（local server callback）
│   │   └── token.go            # Token 載入/儲存/refresh
│   └── gmail/
│       └── client.go           # Gmail API service wrapper
├── go.mod
└── go.sum
```

## Go 依賴

| 套件 | 用途 |
|------|------|
| `github.com/spf13/cobra` | CLI framework |
| `golang.org/x/oauth2/google` | OAuth 2.0 |
| `google.golang.org/api/gmail/v1` | Gmail API client |

編譯後預估 ~15MB static binary（darwin/arm64）。

## Python 整合

`tasks/gmail_scan/service.py` 改動：

```python
# 舊
GWS_CMD = "gws"
cmd = [GWS_CMD, "gmail", "users", "messages", "list", "--params", json.dumps({...})]

# 新
GWSCLI_CMD = "gwscli"
cmd = [GWSCLI_CMD, "messages", "search", "--account", account_name, "--query", query]
```

Python `ScanProfile` model 新增 `account_name: str` 欄位，對應 gwscli 的 `--account`。

### 函式對應表

| Python 函式 | 舊 gws 命令 | 新 gwscli 命令 |
|-------------|------------|---------------|
| `check_cli_available()` | `gws --version` | `gwscli --version` |
| `check_auth_status()` | `gws auth status` | `gwscli auth status --account <name>` |
| `search_messages(query)` | `gws gmail users messages list --params {...}` | `gwscli messages search --account <name> --query <q>` |
| `get_message_detail(id)` | `gws gmail users messages get --params {...}` | `gwscli messages get --account <name> --id <id>` |
| `download_attachment(...)` | `gws gmail users messages attachments get --params {...}` | `gwscli attachments download --account <name> --message-id <mid> --attachment-id <aid> --output <path>` |

## 錯誤處理

- exit code 0 = 成功（JSON 在 stdout）
- exit code 1 = 一般錯誤（錯誤訊息在 stderr）
- exit code 2 = 認證錯誤（token 過期或不存在）

Python 側可根據 exit code 給出適當的中文錯誤提示。

## Build & Install

```bash
# 在專案 Makefile 加入
# build-gwscli:
cd cmd/gwscli && go build -o ../../bin/gwscli .

# install-gwscli:
cp bin/gwscli /usr/local/bin/gwscli
```

## 驗證方式

1. `go build` 成功，產出 binary
2. `gwscli auth login --account test` — 開瀏覽器完成 OAuth
3. `gwscli auth status --account test` — 回傳 JSON 確認有效
4. `gwscli messages search --account test --query "is:unread" --max-results 5` — 回傳搜尋結果 JSON
5. Python 側 `make check` 通過（service.py 呼叫 gwscli 正確）

## 使用者前置作業

1. 確認 GCP 專案已啟用 Gmail API（console.cloud.google.com → APIs & Services → Enable Gmail API）
2. 下載 OAuth Client ID JSON（Desktop app 類型）到 `~/.gwscli/client_secret.json`
3. `gwscli auth login --account work` 和 `gwscli auth login --account personal` 分別授權兩個帳號
