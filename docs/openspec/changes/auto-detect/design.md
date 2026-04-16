# Design：auto-detect

> 版本：v1.0 | 日期：2026-04-16

## Layer 3 — 資料模型

### Entity：AccountRecord（_registry/accounts.json 的陣列元素）

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `email` | string | NOT NULL | 帳號 email |
| `agent_type` | string | NOT NULL, enum: claude/gemini/codex | 對應的 Agent 類型 |
| `registered_at` | string | NOT NULL, ISO 8601 | 首次偵測並註冊的時間 |
| `hash` | string \| null | 僅 claude 有值 | `~/.claude/.claude.json` 的 userID SHA256 hash |
| `device_id` | string \| null | optional | 哪台機器的記錄 |

**索引**：以 `(email, agent_type)` 組合唯一（dedup key）

**完整 JSON 範例**：

```json
[
  {
    "email": "howie@gmail.com",
    "agent_type": "gemini",
    "registered_at": "2026-04-16T10:00:00+08:00",
    "hash": null,
    "device_id": "MacBook-Pro"
  },
  {
    "email": "howie@gmail.com",
    "agent_type": "claude",
    "registered_at": "2026-04-16T10:01:00+08:00",
    "hash": "a3b4c5d6e7f8...",
    "device_id": "MacBook-Pro"
  }
]
```

---

### Entity：AgentsConfig（~/.agents/config.json，已有，無需修改）

現有 schema 不變：

```python
class AgentsConfig(BaseModel):
    version: str = "1.0"
    device_id: str
    default_account: str | None = None   # fallback 層 3 使用
    default_agent: str = "claude"
    operator: str = "howie"
```

---

## Layer 3 — API Schema（內部 Python 介面）

### AccountAdapter 抽象介面

```python
from abc import ABC, abstractmethod

class AccountAdapter(ABC):
    """帳號偵測 adapter 的抽象介面。"""

    agent_type: str = ""  # 子類設定

    @abstractmethod
    def detect(self) -> str | None:
        """偵測帳號 email。無法偵測時回傳 None，不拋例外。"""
        ...
```

### GeminiAccountAdapter

```python
class GeminiAccountAdapter(AccountAdapter):
    agent_type = "gemini"

    # 讀取路徑：Path.home() / ".gemini" / "google_accounts.json"
    # 回傳：data["active"] 或 None
```

### CodexAccountAdapter

```python
class CodexAccountAdapter(AccountAdapter):
    agent_type = "codex"

    # 讀取路徑：Path.home() / ".codex" / "auth.json"
    # 處理：base64url decode tokens.id_token 的 payload 部分
    # 回傳：payload["email"] 或 None
```

### ClaudeAccountAdapter

```python
class ClaudeAccountAdapter(AccountAdapter):
    agent_type = "claude"

    # 讀取路徑：Path.home() / ".claude" / ".claude.json"
    # 查表：REGISTRY_DIR / "accounts.json" 中 agent_type == "claude" 且 hash == userID
    # 回傳：對應 email 或 None
```

### detect_account() 更新後簽章

```python
def detect_account(
    agent_type: str = "claude",
    warn: bool = True,
) -> str:
    """四層 fallback：env var → adapter → config.json → "unknown"。"""
    ...
```

### detect_agent_type() 更新後簽章

```python
def detect_agent_type(
    caller: str | None = None,
    default: str = "claude",
) -> str:
    """四層 fallback：env var → caller → config.json → default。"""
    ...
```

### AccountRegistry

```python
class AccountRegistry:
    """~/.agents/_registry/accounts.json 的讀寫介面。"""

    def auto_register(
        self,
        email: str,
        agent_type: str,
        extra: dict | None = None,
    ) -> bool:
        """首次偵測到新帳號時自動寫入。回傳 True 代表新增，False 代表已存在（冪等）。"""
        ...

    def find_by_hash(self, hash_value: str) -> str | None:
        """以 Claude userID hash 查詢對應 email。"""
        ...
```

---

## 衝突偵測結果

**前置確認**：`docs/openspec/specs/` 目前不存在，這是第一份規格。標註：**baseline，無需衝突檢查**。

受影響的現有程式碼（需更新呼叫方式）：

| 檔案 | 受影響函式 | 需要修改 |
|------|----------|----------|
| `tasks/session_memory/insight_hook.py` | `detect_account()` | 新增 `agent_type="claude"` 參數（維持向後相容，預設值不變）|
| `tasks/session_memory/handover_service.py` | `detect_account()` | 同上，或由呼叫端傳入 `agent_type` |
| `tasks/session_memory/cli.py` | `detect_account()` | 同上 |
