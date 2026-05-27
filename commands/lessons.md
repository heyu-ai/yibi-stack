---
name: lessons
description: 查詢、搜尋、寫入 typed lessons。取代 /recall。
---

# Lessons — 教訓查詢與寫入

查詢本 project 累積的 typed lessons、legacy handover 教訓，以及寫入新教訓。

所有操作透過 wrapper：`~/.agents/bin/lessons {add|show|search} [args]`
Wrapper 自動讀取 `~/.agents/config.json` 取得 skill_repo 路徑，並透過 `git rev-parse` 偵測當前 project。

**使用方式：**

- `/lessons` — 顯示最近 15 筆教訓（含 legacy）
- `/lessons <關鍵字>` — 隱式搜尋（等同 `/lessons find <關鍵字>`）
- `/lessons find <關鍵字>` — 明確搜尋，支援自然語意 filter 推斷

## Step 1 — 無 arguments（`/lessons`）

```bash
~/.agents/bin/lessons show --last 15 --include-legacy
```

## Step 2 — `/lessons find <keyword>` 或 `/lessons <keyword>`

1. 從 arguments 推斷 filter（自然語意映射）：
   - 含「雷」「pitfall」「踩過」→ 加 `--type pitfall`
   - 含「確認過」「可信」「trusted」→ 加 `--trusted-only`
   - 含「跨專案」「cross-project」→ 加 `--cross-project`

2. 執行搜尋（去掉 filter 關鍵字後的純搜尋詞）：

```bash
~/.agents/bin/lessons search <KEYWORD> --last 10 --include-legacy
```

可選 flag：`--type pitfall`、`--trusted-only`、`--cross-project`

## Step 3 — 寫入新教訓

Agent 直接組 `lessons add` 指令：

```bash
~/.agents/bin/lessons add \
  --type <type> \
  --key <key> \
  --insight "<教訓內文>" \
  --confidence <1-10> \
  --source <source>
```

| 欄位 | 選項 |
|------|------|
| type | pattern / pitfall / preference / architecture / tool / operational / investigation |
| key | 短識別 key（英數字、底線、連字號，如 `dedup-grain`） |
| insight | 教訓內文（至少 10 字元） |
| confidence | 1-10 的整數 |
| source | observed / user-stated / inferred / cross-model |

選填：`--skill <skill-name>`、`--files <path>`（可重複）

確認輸出的 id 和 trusted bit 後回報使用者。

## Step 4 — 呈現結果

- 若無結果，告知所用的 project 名稱並建議用 Step 3 寫入新教訓
- 若有結果，分群展示：**Typed lessons**（type 分類）和 **Legacy**（舊 handover 教訓）

## Skill integration contract（Phase B 以後實作）

以下 skills 將在對應時機自動呼叫 `lessons add`：

| Skill | 時機 | source | 額外參數 |
|-------|------|--------|---------|
| `/pr-retro` | AskUserQuestion 收集 type+confidence 後 | `user-stated` | `--skill pr-retro --retro-pr <N>` |
| `/handover` | session 結束時的 lessons_learned[] | `observed` | `--skill handover --handover-id <id>` |
| `/investigate` | DEBUG REPORT 後的 root-cause patterns | `observed` | `--skill investigate` |

這些整合點為 Phase B 工作範圍，`lessons add` CLI 介面在 Phase A 已穩定不變。
