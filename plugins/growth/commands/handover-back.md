---
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

# Handover Back — 讀取上次工作進度

回到上次工作時執行此命令，自動偵測當前專案並讀取對應的 handover 記錄。

## Step 1 — 偵測當前專案並讀取交班

git repo 根目錄名稱作為 project name（與 `detect_project()` 行為一致），或 fallback 為 `pwd` 的 basename。

> **執行注意**：script 內含多個 `"$VAR"` expansion，直接內嵌會觸發 CC parser `simple_expansion` 確認框，故提取為獨立 script（rule 13 Quoting Rule 5-B）。
> **路徑說明**：用 `~/.agents/bin/resolve-skill-repo`（`make install` 建立）解析 SKILL_REPO 的絕對路徑，
> 確保從任何專案目錄呼叫都能找到 script（全域 slash command 不能假設 cwd 在 yibi-stack）。
> 不要改回讀 `~/.agents/config.json` 的 `skill_repo`：該 key 由多個 repo 的 `make install` 共寫，
> 會被最後一個安裝者覆寫而指向錯 repo（見 rule 11）。
> **直接呼叫 script，不要重新內嵌 bash logic。**

```bash
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
bash "$SKILL_REPO/commands/scripts/handover-read.sh"
```

若查無記錄，明確告知使用者所用的 project name，方便確認是否有誤：

> 「以 project='$PROJECT' 過濾，查無記錄。
> 若 project 名稱有誤，可改用不帶 --project 的指令查詢全部記錄。」

不帶 `--project` 顯示所有記錄（跨專案）：

```bash
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
bash "$SKILL_REPO/commands/scripts/handover-read.sh" --no-project
```

## Step 2 — 呈現重點

根據讀取結果，整理並呈現：

1. **上次工作主題**：`topic`
2. **完成了什麼**：`completed`
3. **卡住的事項**：`blocked`（若有）
4. **下一步優先事項**：`next_priorities`
5. **關鍵決策**：`decisions`

## Step 3 — 建議行動

根據 `next_priorities` 提示使用者：

> 「根據上次 {{project}} 的交班，建議從以下開始：...」

若有 `blocked` 項目，也一併提醒。
