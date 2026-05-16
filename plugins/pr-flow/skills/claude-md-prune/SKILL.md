---
name: claude-md-prune
type: tool
scope: global
description: >
  審查並精簡 CLAUDE.md 文件：把累積的 gotcha / 規則段落路由到對應的 .claude/rules/ 子檔，
  刪除過期內容，維持 CLAUDE.md 在 Anthropic 建議的 200 行軟上限內。
  觸發關鍵字：CLAUDE.md 太大、精簡 CLAUDE.md、CLAUDE.md 太多規則、migrate gotcha to rules、
  CLAUDE.md bloat、清理 CLAUDE.md、整理 CLAUDE.md、prune CLAUDE.md、
  CLAUDE.md 行數、revise CLAUDE.md、rules 遷移
---

# CLAUDE.md Prune -- 精簡與規則遷移

## 適用情境

- CLAUDE.md 行數接近或超過 200 行（Anthropic 建議的 adherence 軟上限）
- `/pr-retro` 的 `[WARN]` 提示觸發後想做完整審查
- 定期維護：把累積的「臨時 gotcha」升級為正式的 path-scoped rule

## 不適用

| 情境 | 應使用 |
|------|--------|
| 新增規則到 CLAUDE.md | `/claude-md-management:revise-claude-md` |
| PR 收尾學習記錄 | `/pr-retro` |
| 週度工程回顧 | `/retro` |

---

## 步驟

### Step 1 -- 確認目標與行數

確認要審查的 CLAUDE.md（可同時審查兩個）：

```bash
wc -l ~/.claude/CLAUDE.md
```

```bash
wc -l CLAUDE.md
```

向使用者確認目標（user-level / project-level / 兩者）後繼續。

---

### Step 2 -- 分段分類

讀取目標 CLAUDE.md，對每個段落按下表分類：

| 段落特徵 | 分類 | 目的地 |
|---------|------|--------|
| Bash anti-pattern / AP1/AP2/AP3 細節 | bash | `.claude/rules/13-bash-anti-patterns.md` |
| Shell quoting / simple_expansion | quoting | `.claude/rules/14-shell-quoting-hygiene.md` |
| SKILL.md 格式 / frontmatter / placeholder | skill-authoring | `.claude/rules/11-skill-authoring.md` |
| 不可逆操作 / 危險指令邊界 | irreversible | `.claude/rules/15-irreversible-operations.md` |
| 安全性 / injection / sanitize | security | `.claude/rules/03-security.md` |
| Python / task module 慣例（Pydantic、CLI、DB、tests、module structure、error handling、language rules）| python-task | `.claude/rules/` 對應子檔（rule 01-10；依主題對應，同 pr-retro Lesson Classifier）|
| Repo 架構 / 目錄說明 / make targets | metadata | 保留在 `<repo>/CLAUDE.md` |
| 個人工具偏好 / 跨專案操作習慣 | preference | 保留在 `~/.claude/CLAUDE.md` |
| 過期 / 已解決的問題 / 只發生一次 | stale | **刪除** |
| 與現有 rule 重複（rule 是正本）| duplicate | **刪除** CLAUDE.md 中的副本 |

---

### Step 3 -- 產出 diff plan

輸出審查結果，格式如下：

```text
## CLAUDE.md Prune Plan

目標：~/.claude/CLAUDE.md（<N> 行）[user]
      CLAUDE.md（<M> 行）[project]

### 遷移（移到 rules/）
- [user] L12-15「for loop body 含 pipe」
  -> .claude/rules/13-bash-anti-patterns.md（AP1 Sub-type 段落後 append）
  草稿：<具體文字>

- [project] L28-30「${CLAUDE_EFFORT} 在 SKILL.md 不展開」
  -> .claude/rules/11-skill-authoring.md（新增條目）
  草稿：<具體文字>

### 刪除（過期 / 一次性 / 與 rule 重複）
- [user] L40-42「某次環境 debug 筆記」-> 刪除（已解決，無重現性）
- [project] L55-58「AP1 multi-line 判斷」-> 刪除（與 rule 13 重複，rule 是正本）

### 保留
- [user] L1-11「## CLI Tools」-> 保留（工具偏好，user CLAUDE.md 正本）
- [project] L44-60「## 專案架構」-> 保留（repo metadata）

預計結果：~/.claude/CLAUDE.md <N> 行 -> <P> 行 / CLAUDE.md <M> 行 -> <Q> 行
```

---

### Step 4 -- 使用者確認

呈現 diff plan 後等待使用者確認：

| 使用者回應 | Agent 動作 |
|---|---|
| `OK` / `全部執行` | 進入 Step 5 |
| `只做遷移，不刪除` | 跳過刪除部分 |
| `修改 L12 的分類` | 重新分類該段落 |
| `cancel` | 中止，不做任何變更 |

---

### Step 5 -- 執行遷移與刪除

**遷移（append 到 rules 檔）**：

對每個遷移項目，用 Edit 工具直接 append 到對應 rule 檔：

- 目標檔：`.claude/rules/XX.md`（Step 3 plan 中已標註對應 rule）
- append 位置：插入到最相關段落之後；不確定就 append 到檔尾
- 草稿文字：Step 3 plan 中的草稿

**刪除**：

用 Edit 工具從 CLAUDE.md 移除對應段落。

---

### Step 6 -- 確認結果

```bash
wc -l ~/.claude/CLAUDE.md
```

```bash
wc -l CLAUDE.md
```

輸出最終行數，確認精簡成功。建議在結果提示：「下次遷移目標可用 `/claude-md-prune` 再次觸發。」

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| 不確定某段落歸哪個 rule | 看「動詞 / 操作對象」：bash 指令相關一律 rule 13/14；SKILL.md 格式 rule 11；危險操作 rule 15 |
| 已有相同內容在 rules/ | 直接刪除 CLAUDE.md 的重複段落（rule 是正本，不需保留副本）|
| 遷移後 rules/ 太長 | rules/ 沒有 200 行限制（path-scoped，不是全域載入），不需擔心 |
| 想同時 prune 兩個 CLAUDE.md | Step 2-5 對兩個檔案分別執行一次 |
| 在其他 repo 執行，整個 `.claude/rules/` 目錄不存在 | 跳過所有「遷移到 rules/」項目；若屬個人偏好類別，仍路由到 `~/.claude/CLAUDE.md`（此檔永遠可用）；其餘改走「保留 or 刪除」或寫入 `<repo>/CLAUDE.md` |
| 找不到對應的 .claude/rules/ 分類 | 若沒有對應 rule 類別，保留在 CLAUDE.md 即可（metadata / preference 本就屬於此處）|
