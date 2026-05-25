# Allow-list 衛生（Allow-list Hygiene）

Claude Code 權限對話框出現「Yes, and don't ask again for: `<pattern>`」時，
選擇此選項會把 `<pattern>` 寫入 `~/.claude/settings.local.json` 永久放行。
本文件規範哪些 pattern **不應**永久放行（一律選 1 一次性同意），
以及如何撰寫安全的 allow-list pattern。

**來源**：Claude Code 官方權限文件
<https://code.claude.com/docs/en/permissions>（以下簡稱「官方文件」）。
本 rule 的所有 wildcard / wrapper / pattern 語意描述都對照官方文件原文，並非推測。

## 為什麼這件事重要

最容易被忽略的事實是 **`*` 在 Bash() pattern 內會跨越多個 argument**。官方文件原文：

> "A single `*` matches any sequence of characters including spaces, so one wildcard
> can span multiple arguments. `Bash(git *)` matches `git log --oneline --all`, and
> `Bash(git * main)` matches `git push origin main` as well as `git merge main`."

這代表你以為「動詞鎖在 `status`」的 `Bash(git -C * status)`，
**實際會 match `git -C /tmp push --force origin status`**——`*` 整段吃下 `<path> push --force origin`。

官方文件也明文警告引數約束本質脆弱：

> "Bash permission patterns that try to constrain command arguments are fragile.
> For example, `Bash(curl http://github.com/ *)` intends to restrict curl to GitHub URLs,
> but won't match variations like: Options before URL, Different protocol, Redirects, Variables, Extra spaces."

結論：**唯一可靠的限制方式是把指令動詞鎖在 pattern 的 prefix，並用 trailing wildcard 包尾**。

## Pattern 語意速查（官方文件對照）

| Pattern 形式 | 語意 | 範例 |
|------------|------|------|
| `Bash(verb)` | exact match | `Bash(make ci)` 只 match `make ci` |
| `Bash(verb *)` | verb 在 prefix，後接任意（trailing wildcard 強制 word boundary） | `Bash(npm run *)` match `npm run build`，**不**match `npm runtest` |
| `Bash(verb:*)` | 與 `Bash(verb *)` 等效（官方明文）| `Bash(git status:*)` ≡ `Bash(git status *)` |
| `Bash(verb*)` | 無 word boundary，`*` 直接接在 verb 後 | `Bash(ls*)` match `ls -la` **和** `lsof` |
| `Bash(* verb)` | 任意前綴 + verb 結尾 | `Bash(* install)` match `npm install` 與 `pip install` |
| `Bash(verb1 * verb2)` | **`*` 跨越多個 args**，中間部分完全不受約束 | `Bash(git * main)` match `git merge main` 也 match `git push origin main` |

`:*` 形式僅在 pattern 結尾識別為 trailing wildcard；中間出現的 `:` 是 literal。

## 永久放行的決策準則

按下「Yes, and don't ask again」前，先看 pattern 是否含以下任一項。**任一命中即選 1（一次性）**，不選永久放行。

### 紅旗 1：中間出現 wildcard（最危險）

```text
Bash(git -C * status)
Bash(verb1 * verb2)
Bash(curl https://example.com/*)
Bash(uv run --directory * pytest)
```

看起來像「動詞鎖死」，實際 `*` 會跨越任意數量的 args 與 flags。
`Bash(git -C * status)` 真的允許範圍包含 `git -C /any push --force origin status`、
`git -C /any reset --hard HEAD~5 status`（兩者末尾都以 `status` 結尾，符合 pattern）。
`Bash(uv run --directory * pytest)` 同樣是 `verb1 * verb2` 結構——`*` 不只展開到單一路徑，
還可吃下任意 `uv run` flag，例如 `uv run --directory /tmp --with malicious-package pytest`
（`*` 整段消化 `/tmp --with malicious-package`）。

**修法**：把 verb 移到 pattern 的 prefix，例如 `Bash(git status:*)` 或 `Bash(git status *)`。
若需要 `-C <path>` 或 `--directory <path>` 形式，要嘛寫每個 repo 的 exact pattern
（`Bash(git -C /Users/me/proj1 status)`、`Bash(uv run --directory /Users/me/proj1 pytest:*)`），
要嘛接受每次跳一次確認框——不要嘗試用 `*` 表達 path。

### 紅旗 2：指令動詞層 wildcard

```text
Bash(git *)
Bash(npm *)
Bash(rm *)
Bash(curl *)
```

涵蓋該 binary 的全部子命令。`Bash(git *)` 包含 commit / push / reset --hard / config / filter-branch。
即使你信任自己的 git 用法，agent 可能 propose `git config --global` 等動作而你不會察覺。

**修法**：拆成 per-verb pattern——`Bash(git status:*)`、`Bash(git log:*)`、`Bash(git diff:*)`、
`Bash(git rev-parse:*)` 等純讀子命令。`rm` 與 `curl` 永不應該 allow-list（理由見紅旗 4）。

### 紅旗 3：變數展開或變數賦值 prefix

```text
Bash(* "$VAR" *)
Bash(PATH="..." git *)
Bash(* ${HOME}/* )
```

兩種子模式：

- **Pattern 含 `"$VAR"`**：實際匹配範圍依執行時 VAR 值，不可靜態 review
- **Variable assignment prefix**：`PATH="..." git ...` 的第一個 token 是 `PATH=...` 不是 `git`，
  所以 `Bash(git *)` 不 match（pattern 第一個 literal token 必須與 command 第一個 token 一致）

**注意：variable assignment prefix `PATH=...` 不是「exec wrapper」**——它是 shell 賦值，
與官方文件中 stripped wrapper（`timeout` / `time` / `nice` / `nohup` / `stdbuf`，以及 bare
`xargs`，即無 flag 的 `xargs cmd`）或 always-prompt wrapper（`watch` / `setsid` / `ionice`
/ `flock`）是不同機制。

**修法**：絕對路徑或 explicit binary 形式，例如 `Bash(/Users/<you>/.asdf/shims/git status:*)`，
而非靠 `PATH=` 拼湊 shim 解析。allow-list 寫的是當下執行時看到的 token，
不要靠變數展開製造抽象層。

### 紅旗 4：網路工具與 URL 約束

官方文件對 `Bash(curl URL ...)` 形式給出**明文警告**：

> "Bash permission patterns that try to constrain command arguments are fragile. ...
> For more reliable URL filtering, consider:
>
> - **Restrict Bash network tools**: use deny rules to block `curl`, `wget`, and similar
>   commands, then use the WebFetch tool with `WebFetch(domain:github.com)` permission for
>   allowed domains
> - **Use PreToolUse hooks**: implement a hook that validates URLs in Bash commands
> - **Add CLAUDE.md guidance**: describe your allowed curl patterns in CLAUDE.md"

`Bash(curl https://known.host/specific-path)` 看似精確，**仍然脆弱**——
agent 加 `-X GET`、改 `http://`→`https://`、用 redirect、變數展開 URL 都會繞過。

**修法**：採官方推薦組合

- `deny`: `Bash(curl *)`、`Bash(wget *)`、`Bash(* | sh)`、`Bash(* | bash)`
- `allow`: `WebFetch(domain:known.host)` 為網路請求專用 tool
- 或寫 PreToolUse hook 做 runtime URL 檢查

### 紅旗 5：含 redirection 或 pipeline wildcard

```text
Bash(* >> *)
Bash(* > *)
Bash(* | sh)
Bash(* | bash)
```

`*` 涵蓋 redirection 目標或 pipeline 下游，等於開放任意檔案寫入或任意指令執行。

**修法**：不放行此類 pattern。需要寫檔的場景改用 Edit/Write tool（受 Edit/Read rules 約束）；
需要 pipeline 的場景把整段 pipeline 寫成 script 後 allow-list 該 script 路徑。

## 安全 pattern 範例

通用準則：**動詞固定在 prefix，wildcard 只在尾端，純讀或完整 script 路徑**。

| Pattern | 為什麼安全 |
|---------|-----------|
| `Bash(make ci)` | exact match，固定指令 |
| `Bash(make test)` | exact |
| `Bash(uv run pytest)` | exact |
| `Bash(git status:*)` | 動詞 `git status` 鎖在 prefix，trailing `:*` 強制 word boundary |
| `Bash(git log:*)` | 同上，純讀 |
| `Bash(git diff:*)` | 同上，純讀（差分不修改檔案系統） |
| `Bash(git rev-parse:*)` | 同上，純讀 |
| `Bash(git fetch:*)` | 只讀遠端，不改 working tree |
| `Bash(npm run *)` | npm subcommand 鎖在 `run` |
| `Bash(bash /Users/<you>/.agents/skills/foo/scripts/setup.sh)` | 完整絕對路徑 exact match；等於審核一次 script 永久信任 |

**重點**：

1. `Bash(verb)` 與 `Bash(verb:*)` 是兩種完整且唯一可靠的形式；中間 wildcard 一律不要用
2. `~` 在 Bash() pattern 內**不展開**（官方文件對 Bash rule 沒有 `~` 語意，只有 Read/Edit 有）。
   `Bash(bash ~/foo.sh)` 不會 match runtime 的 `bash /Users/me/foo.sh`；要用絕對路徑
3. `Bash(rm *)` / `Bash(curl *)` / `Bash(wget *)` 永遠不應 allow-list，改走 deny + 其他 tool

## 與 Fat command 反模式的關聯

allow-list 衛生問題與 rule 13 AP1 共生：

- agent 寫 fat command（多步驟 `&&` 鏈）→ token 結構打破標準形式
- → settings.json 的 `Bash(cmd *)` pattern 因動詞不在 prefix 而無法精確匹配
- → 回退到 manual confirm
- → 使用者被誘導選「don't ask again」
- → 永久放行的 pattern 含中間 wildcard 或變數展開（紅旗 1 / 紅旗 3）

**根治**：把 fat command 抽成 `scripts/foo.sh`，allow-list 只需 `Bash(bash /abs/path/scripts/foo.sh)`
（完整絕對路徑 + script 已 review），符合本 rule「安全 pattern 範例」末項。

詳細抽 script 指引見 rule 13「AP1 自動修復觸發條件」與 CLAUDE.md「Slash command 的
bash code block 被 agent 重寫」gotcha。

## 既有不安全 pattern 的修正流程

若 `~/.claude/settings.local.json` 已包含上述紅旗 pattern：

1. 打開 `~/.claude/settings.local.json`，找出 `permissions.allow` 內的紅旗 pattern
2. 對應每個 pattern，找出「實際想放行的單一指令動詞」
3. 把 wildcard pattern 改寫成「動詞固定在 prefix + 純讀」或「完整絕對路徑 + script」
4. 重啟 Claude Code session 套用

通用示例（`<abs-path-to-git>` 用 `which git` 確認，常見值如 `/opt/homebrew/bin/git`、
`/usr/bin/git`、`/Users/<you>/.asdf/shims/git`）：

```diff
 "permissions": {
   "allow": [
-    "Bash(PATH=\"/Users/me/.asdf/shims:$PATH\" git *)",
+    "Bash(<abs-path-to-git> status:*)",
+    "Bash(<abs-path-to-git> log:*)",
+    "Bash(<abs-path-to-git> diff:*)",
+    "Bash(<abs-path-to-git> rev-parse:*)",
+    "Bash(<abs-path-to-git> fetch:*)",
+    "Bash(bash /Users/<you>/.agents/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh)"
   ]
 }
```

說明：

- 用絕對路徑取代 `PATH=` prefix wrapper，讓 pattern 第一個 token 即為 binary 自身
- 把 `git *` 拆成 per-verb 純讀子命令；每個都 trailing `:*` 鎖 word boundary
- script 路徑展開到絕對位置（`~` 不展開），且因 script 內容固定不變，等於審核一次
- 不放行 `git commit:*` / `git push:*` / `git reset:*` 等寫入子命令（保留每次跳確認框作為安全網）

## Rule 13 vs Rule 16 互補關係

- rule 13 規範 agent **如何寫** bash command（不要 fat command、不要 wrapper 同型引號衝突）
- rule 14 規範 **shell 引號 / 變數展開衛生**（含 `$?` 特殊案例：用 `if ! cmd; then` 取代）
- rule 16 規範 使用者 / agent **如何配置** allow-list pattern（不要中間 wildcard、不要 variable prefix）

三條規則一起運作：rule 13 + rule 14 讓 agent 寫出 allow-list 可精確匹配的 bash；rule 16 讓
allow-list pattern 不會比使用者預期更寬。任一單獨運作都會留下漏洞——只有 rule 13 / 14 但
allow-list 過寬，agent 還是能執行未預期指令；只有 rule 16 但 bash 都是 fat command，
pattern 永遠 match 不到，使用者被無止盡的確認框疲勞轟炸。

## 內建 `/less-permission-prompts` 的使用警告

Claude Code 2.1.111 起內建 `/less-permission-prompts` skill，會掃描當前 transcript 中常見的
唯讀 Bash／MCP 呼叫，**自動產生一份排序過的 allowlist 建議**。使用前必須了解以下限制：

### 自動建議常見的紅旗 pattern

`/less-permission-prompts` 依執行頻率排序，因此高頻指令（如 `git`、`npm`、`uv`）容易產生：

```json
"Bash(git *)",
"Bash(npm *)",
"Bash(uv *)"
```

這些全部是**紅旗 2（指令動詞層 wildcard）**——覆蓋該 binary 的全部子命令，包含破壞性操作。

### 正確使用流程

1. 執行 `/less-permission-prompts` 取得建議清單
2. **逐一用本 rule 的紅旗準則（1–5）複查每個 pattern**
3. 通過檢查的 pattern 才 approve；不通過的**手動改寫**後再加入

改寫範例：

| 自動建議（紅旗） | 安全改寫 |
|----------------|---------|
| `Bash(git *)` | `Bash(git status:*)` / `Bash(git log:*)` / `Bash(git diff:*)` |
| `Bash(npm *)` | `Bash(npm run:*)` / `Bash(npm ls:*)` |
| `Bash(uv *)` | `Bash(uv run pytest:*)` / `Bash(uv sync)` |

### 絕對不要做

**不可無腦「Yes, and don't ask again」接受 `/less-permission-prompts` 的全部建議。**
工具嘗試過濾唯讀呼叫，但過濾不完整：`git reset *`、`curl *` 等語意模糊的命令仍可能出現。
更關鍵的是：即使只列出「確實是唯讀」的呼叫，產生的 pattern 也可能是 `Bash(git *)`——
動詞層 wildcard，覆蓋整個 binary 的全部子命令，包含破壞性操作。**頻率統計無法保證 pattern 安全。**
