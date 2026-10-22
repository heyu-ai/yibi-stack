---
model: sonnet
---

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
> **分兩次 Bash 呼叫，不要寫成 `SKILL_REPO=$(...)`**：有些 repo 的 PreToolUse hook 會擋下指令字串裡的
> command substitution（例如 yibi-mvp 的 `protect-bash-cd.py`），在這類 repo 每次執行本指令都會被擋。
> shell 變數也不會跨 Bash 呼叫保留，所以第二步要由 agent 把第一步的輸出直接寫進指令。

第一步，解析 skill repo 路徑（成功時 stdout 只有一行絕對路徑）：

```bash
~/.agents/bin/resolve-skill-repo
```

exit code 非 0 時停止執行，告知使用者在 yibi-stack 目錄執行 `make install`。resolver 能執行但解析失敗時，exit code 為 1，stderr 會有 `[FAIL]` 原因；resolver 本身不存在時（從未執行 `make install`），exit code 為 127，shell 只會回報找不到檔案，沒有 `[FAIL]` 字樣，處理方式相同。

第二步，把第一步輸出的絕對路徑代入 `<SKILL_REPO>` 後執行。保留雙引號，路徑含空白時才不會被拆開：

```bash
bash "<SKILL_REPO>/commands/scripts/handover-read.sh"
```

exit code 非 0 時停止，回報 `[FAIL] handover-read 執行失敗` 並附上 stderr 原文，不要當成「查無記錄」處理。常見原因：`<SKILL_REPO>` 沒有換成第一步的輸出（找不到檔案）、`uv` 不存在、mycelium DB 讀取失敗。

若查無記錄，明確告知使用者所用的 project name，方便確認是否有誤：

> 「以 project='$PROJECT' 過濾，查無記錄。
> 若 project 名稱有誤，可改用不帶 --project 的指令查詢全部記錄。」

不帶 `--project` 顯示所有記錄（跨專案）。`<SKILL_REPO>` 沿用第一步的輸出；手上沒有這個路徑時，先重跑第一步：

```bash
bash "<SKILL_REPO>/commands/scripts/handover-read.sh" --no-project
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
