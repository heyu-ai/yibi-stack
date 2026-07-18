---
name: lessons
description: 查詢、搜尋、寫入 typed lessons。取代 /recall。
---

# Lessons — 教訓查詢與寫入

查詢累積的 typed lessons、legacy handover 教訓，以及寫入新教訓。

所有操作透過 wrapper：`~/.agents/bin/lessons {add|show|search|delete|retire} [args]`
Wrapper 透過 `~/.agents/bin/resolve-skill-repo` 取得 skill_repo 路徑。

**`--project` 注入策略（刻意為之）**：

| 指令 | wrapper 行為 | 結果 |
| --- | --- | --- |
| `show` / `search`（讀取） | **不注入** `--project` | 預設回傳**全部 project**，與 CLI 文件一致；要限縮請自行加 `--project <name>` |
| `delete` / `retire`（id-targeted） | **不注入** `--project` | 以精確 `--id` 操作單一 lesson；CLI 不定義 `--project`，注入會讓 click exit 2（issue #242） |
| `add`（寫入） | 注入 `git rev-parse` 偵測到的 project | 教訓記到當前 repo（issue #243 的防線） |

讀取之所以不注入：CLI 對 `show` / `search` 的 `--project` 預設就是「顯示全部 project」，
wrapper 若注入會靜默覆寫該預設——呼叫端以為拿到跨 project 結果、實際只拿到 cwd 那個 repo
的，且無任何訊號。

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

## Step 3b — 退場：delete 與 retire（issue #242）

lessons 表原本只進不出，錯寫只能直接動 SQLite。兩條退場路徑語意不同：

**`delete`（誤寫修正）** — 「這筆根本不該存在」。刪除前自動寫入 `lessons_deleted`
tombstone（含完整 snapshot + `deleted_at`）保留 audit trail：

```bash
~/.agents/bin/lessons delete --id <uuid> --dry-run   # 先看會刪什麼
~/.agents/bin/lessons delete --id <uuid>             # 實際刪除，印出剩餘筆數
```

- 只接受精確 `--id`，不支援條件式批次刪除
- `--id` 指向不存在教訓時 fail loud（exit 1），非靜默 no-op

**`retire`（教訓過期）** — 「它曾經對，現在被推翻了」。保留內容但退出流通：

```bash
~/.agents/bin/lessons retire --id <uuid> --reason "被 PR #NNN 推翻：<新事實>" --superseded-by <key>
```

- 寫入 `retired_at` / `retired_reason` / `superseded_by`
- `--reason` 必填（「為何被推翻」常是下一條教訓）；重複 retire 會 fail loud（不覆寫原始退場記錄）
- `show` / `search` 預設排除 retired 的 **typed** 教訓，加 `--include-retired` 才顯示（標 `[RETIRED]`，並顯示 `superseded_by`）
- distill 聚合（`python -m tasks.mycelium distill run`）與 tier 升降級自動排除 retired，不再稀釋 cluster

## Step 4 — 呈現結果

- 若無結果，說明查詢範圍為全部 project（除非呼叫端明確加了 `--project`），並建議用 Step 3 寫入新教訓
- 若有結果，分群展示：**Typed lessons**（type 分類）和 **Legacy**（舊 handover 教訓）

## Skill integration contract（Phase B 以後實作）

以下 skills 將在對應時機自動呼叫 `lessons add`：

| Skill | 時機 | source | 額外參數 |
|-------|------|--------|---------|
| `/pr-retro` | AskUserQuestion 收集 type+confidence 後 | `user-stated` | `--skill pr-retro --retro-pr <N>` |
| `/handover` | session 結束時的 lessons_learned[] | `observed` | `--skill handover --handover-id <id>` |
| `/investigate` | DEBUG REPORT 後的 root-cause patterns | `observed` | `--skill investigate` |

這些整合點為 Phase B 工作範圍，`lessons add` CLI 介面在 Phase A 已穩定不變。
