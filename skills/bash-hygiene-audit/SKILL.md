---
name: bash-hygiene-audit
type: exec
scope: global
description: bash-hygiene hook audit log 管理：啟用/停用記錄、查看近期 hook 攔截事件、統計違規比例與熱點 pattern。觸發關鍵字：audit log、hook 記錄、bash-hygiene 統計、啟用 audit、停用 audit、查看 block 記錄
---

# bash-hygiene-audit

`bash-hygiene` hooks 的 audit log 管理工具。
記錄每次 hook 執行的 allow / block 結果，用於分析違規熱點與測量 hook 效能。

**Log 位置**（per-project）：`.runtime/logs/bash-hygiene-audit.jsonl`
**Toggle config**（user-level）：`~/.agents/bash-hygiene.json`，欄位 `audit_enabled`，預設 `false`

## 執行步驟

### Step 1 — 環境確認

```bash
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then exit 1; fi
```

### Step 2 — 查看目前狀態

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit status
```

輸出範例：

```text
audit log：[OFF]
config 路徑：/Users/foo/.agents/bash-hygiene.json
log 路徑：（尚無記錄）
```

### Step 3 — 啟用 / 停用 audit log

啟用：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit enable
```

停用：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit disable
```

啟用後，每次 `bash-hygiene` hook 執行都會在當前 git repo 的
`.runtime/logs/bash-hygiene-audit.jsonl` 追加一筆 JSONL 記錄。

### Step 4 — 查看近期記錄

顯示最近 20 筆（預設）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit show
```

只看 block 記錄：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit show --verdict block
```

只看特定 hook：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit show --hook ap1
```

指定筆數：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit show --last 50
```

### Step 5 — 統計分析

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit stats
```

輸出範例：

```text
總計：42 筆  block：8（19.0%）  allow：34
平均耗時：3.2ms
--- by hook ---
  ap1: 25
  ap2: 12
  smart-fix: 5
--- by block_reason ---
  python-c-multiline: 5
  ap2-unicode: 2
  grep-bre-doublequote: 1
```

## 與內建 `/less-permission-prompts` 的分工

Claude Code 2.1.111 起有內建 `/less-permission-prompts` skill，兩者功能不同，**互補而非替代**：

| | `bash-hygiene-audit` | `/less-permission-prompts` |
|-|---------------------|--------------------------|
| **目的** | 記錄 hook 攔截事件，分析哪些指令被 block | 掃描 transcript，建議哪些指令可加入 allowlist |
| **資料來源** | `.runtime/logs/bash-hygiene-audit.jsonl` | 當前 session transcript |
| **輸出** | block 記錄、違規熱點統計 | allowlist pattern 建議清單 |
| **用途** | 診斷「hook 攔了什麼 / 有多頻繁」 | 減少重複出現的確認框 |

**搭配使用流程**：先跑 `bash-hygiene-audit stats` 確認哪些 hook 最常攔截、違規熱點 pattern 為何 →
再用 `/less-permission-prompts` 取得 allowlist 建議 → **照 rule 16 紅旗準則複查後**才套用。

> 注意：`/less-permission-prompts` 依執行頻率產生建議，可能包含 `Bash(git *)` 等動詞層
> wildcard（rule 16 紅旗 2）。**不可無腦接受**，必須手動改寫成 per-verb 精確 pattern。

### Step 6 — 重複攔截分析（audit log）

從 audit log 找出「同一 session 同一指令被 block >= 2 次」的重複攔截事件：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit repeats
```

顯示前 10 名熱點：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit repeats --top 10
```

自訂 token 浪費估算（每次額外 block 的 token 預設 1500）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit repeats --token-estimate 2000
```

輸出範例：

```text
總 block 次數：42
重複攔截次數：8（19.0%）
重複事件組數：3
累積浪費時間：45.3 秒
累積浪費 token：~7,500 tokens
--- top 重複攔截熱點 ---
  1. [3x] ap2-unicode  +32.1s  ~3,000tk
     cmd: echo "test — em dash here"
  2. [2x] ap1-block  +8.7s  ~1,500tk
     cmd: for f in a.py b.py; do grep -n "pattern" "$f" | head -5; done
  3. [2x] unknown  +4.5s  ~1,500tk
     cmd: gh pr merge 8 --squash --delete-branch 2>&1
--- by block_reason ---
  ap2-unicode: 3
  ap1-block: 2
  unknown: 3
```

### Step 7 — 回溯 transcript 分析（歷史資料）

從 Claude Code session transcript 回溯 parse hook block 事件（不需要先啟用 audit log）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit replay-transcripts
```

指定回溯天數（預設 14 天）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.bash_hygiene_audit replay-transcripts --since-days 7
```

**注意**：`replay-transcripts` 用 Claude Code 自己的 session transcript 回溯，識別精準度比 audit log 低。`audit log` 路徑（Step 6）是精準資料，`replay-transcripts` 是歷史 baseline。

## JSONL 記錄 Schema

| 欄位 | 型別 | 說明 |
|------|------|------|
| `ts` | string | ISO 8601 timestamp |
| `hook` | string | `ap1` / `ap2` / `smart-fix` |
| `hook_version` | string | 目前固定 `"1"` |
| `exit_code` | int | `0`=allow、`2`=block |
| `verdict` | string | `allow` / `block` / `error` |
| `block_reason` | string\|null | block 原因 slug（見下方） |
| `command_preview` | string | 指令前 200 字元 |
| `command_hash` | string | SHA-256 前 16 chars |
| `session_id` | string\|null | `$CLAUDE_SESSION_ID` |
| `duration_ms` | int\|null | hook 執行耗時（ms） |

### block_reason slug 對照

| slug | 觸發情境 |
|------|---------|
| `python-c-multiline` | `python -c` 含換行（AP1 Detection 1） |
| `osascript-heredoc` | `osascript` heredoc（AP1 Detection 2） |
| `grep-bre-doublequote` | `grep "...\|..."` 雙引號 BRE（AP1 Detection 3） |
| `nested-subshell` | `$(outer "$(inner)")` 反向巢狀（AP1 Detection 4） |
| `jq-singlequote-filter` | `$(jq 'filter')` 單引號（AP1 Detection 5） |
| `rg-bre-misuse` | `rg` BRE alternation 誤用（AP1 Detection 6） |
| `ap2-unicode` | em/en dash、emoji、零寬空白（AP2） |
| `rule2-doublequote` | `"$(cmd)"` 外層雙引號包 subshell（Rule 2） |

## 常見問題

| 問題 | 解法 |
|------|------|
| `status` 顯示「尚無記錄」 | 先執行 `enable`，再觸發幾次 bash hook，記錄才會出現 |
| `stats` 顯示「無記錄」 | log 檔不存在或在其他 git repo；確認 cwd 在目標 repo 內 |
| `jq` 未安裝導致 bash hook 無法寫入 | `brew install jq`，bash hook（ap1）依賴 jq 進行 JSON 序列化 |
| Python hooks 的 audit 仍不寫入 | 確認 `~/.agents/bash-hygiene.json` 存在且 `audit_enabled` 為 `true` |
| `command_preview` 含 inline secret 的疑慮 | `curl -H "Authorization: Bearer token"` 等指令的前 200 字元會以明文儲存於 `.runtime/logs/`。log 已 gitignore 不會 commit，但長期留存於磁碟。建議只在無 inline secret 的 repo 啟用 audit，或配合 `.runtime/` 定期清理策略使用 |
