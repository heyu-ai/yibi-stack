## Context

使用者要求處理 #390 與 #530。本 change 在獨立 worktree 實作，保留既有 fresh fetch
與輸出契約，不改 PR-state gates、red-first、模型選型或其他 agy skills。

## Goals / Non-Goals

In scope：agy R1/R2 的 HEAD snapshot 與 OS 防寫；Step 2 的 fresh diff admission；
log、timeout、signal cleanup 與有效回歸證據。

Out of scope：修改內建 code-review；替上游 agy 新增 permissions.allow；宣稱 sandbox 能阻止
惡意遠端服務／IPC 代理代寫；#487/#527 等 PR-state 改善。#390 建議 4 仍是外部能力依賴，
本地隔離不依賴它，也不以本 change 自動關閉那個驗收項目。

## Decisions

1. Snapshot 不用 linked worktree：不可把 source .git、hardlink 或 index 暴露為可寫共用狀態。
   只讀 committed HEAD 的完整 tracked 內容，不複製 untracked secret；不能因 export-ignore
   靜默漏掉 tracked 檔案。tracked 修改／衝突時失敗，要求先完成 review 基準。
2. macOS 使用 sandbox-exec，Linux 使用 bwrap；不支援或不可用時 fail-closed，不退回 unrestricted。
   OS 防護覆蓋 reviewer descendants；snapshot 原始碼、原工作樹與 Git common dir 不可寫。
   只有 helper-owned scratch/home/log 可寫，保留 auth/network 與 command lookup。
3. 外部 child 用獨立 process group。成功、失敗、timeout、SIGINT/SIGTERM 均先停止 group，
   再收回 log／清理目錄；保留原 artifact 名稱與原始 worktree PRE/POST 比對。
4. setup-review-dir 仍唯一擁有 upstream/origin 與 FETCH_HEAD 決策；產生 version/base/head/
   changed_paths manifest。檔名來源使用 NUL 分隔，不能把本機 main 當 base。
5. Step 2 只允許 report-only code-review，明確帶 PR 號。lead 保留 raw 結果，轉為既有
   ReviewFindings envelope 的 file 欄位；filter 不猜模糊路徑，不造 finding，不丟 evidence。
   接受 repo-relative 或 repo 內 absolute path；拒絕越界、traversal、帶行號而無法匹配者。
6. filter 產出 filtered JSON 與 scope audit，final 的 owned marker 區塊可重複更新且不刪掉
   amplifier findings。錯誤或 HEAD 變動先失效舊結果。空 findings 是有效的無問題結果。
7. 有 cleanup 授權時也不允許內建 --fix 在 filter 前寫入。simplify 的產物需重新 review／
   重新捕捉 scope。Step 5 保留 audit；Step 6 不可從 raw Step 2 結果修復。

## Implementation Contract

### Isolation interface

R1/R2 shell wrappers 把 prompt、model、budget 與 agy log 目的地交給同一個隔離 helper。
helper 解析 cwd 的 repo，建立 snapshot，啟動 OS-protected agy，將 stdout/stderr/log
回交原有 review artifacts。helper-owned 路徑不存進永久 findings 的 file 身分。

成功：既有 agy_validate 與 timeout classifier 仍能消費產物。
失敗：診斷寫 stderr、非零退出、無 unrestricted fallback；原檔 bytes 與 Git metadata 不變。
驗收：AC-1/2/3，由真實 OS sandbox 下的寫入探針與 shell 端到端測試證明，而非字串測試。

### Scope interface

setup 發布 review-scope.json：version=1、base/head SHA、changed_paths 字串陣列。
review_scope.py 的 filter 子命令接受 --input，讀取 .pr-review 的當輪 manifest，發布
code-review-filtered.json 與 code-review-scope.md；final 已存在時只更新
code-review-scope:start/end marker 之間的區塊。

成功：只有 canonical changed path 對應的 findings 被接受，其餘欄位原樣保留。
拒絕：保留原 item 與原因，明列 N 個 out-of-scope dropped，不進 Step 6。
錯誤：malformed envelope／無 manifest／HEAD 變動均非零；先清掉舊 admission artifacts。
驗收：AC-4/5/6/7，由 tmp git remote 的 stale/fresh main 對照與 CLI filter smoke 證明。

## Risks / Trade-offs

- 新增 OS backend 前提；沒有可用 containment 的平台會少一個 agy voice，而非冒險寫 source。
- 私有 home 只複製必要 agy auth/settings 狀態，不複製整份 cache／transcript；異常認證需 loud fail。
- 本機 main 警告是診斷，不作 base；現有 remote 名稱啟發式風險沿用已接受契約。
- finding 的 file 正規化由 lead 提供明確資料，不用脆弱 Markdown path regex 代替結構化輸入。
- Git submodule/gitlink 目前明確拒絕，避免提供不完整 snapshot；不靜默略過。
- macOS 的回收邊界是 owned process group；刻意脫離 group 的惡意 daemon 不屬本契約。
  Linux 另以 PID namespace 約束子程序。這不是機密讀取或網路隔離。

## Migration Plan

更新兩個 agy wrappers 與 Step 2/3/5/6 runbook，移除舊 direct-worktree 呼叫及 pre-filter --fix
路徑。私有 HOME 不再需要刪除共用 scratch；其他 session 的輸入必須保留。
退役受影響的 source-string／固定 SKILL 行數測試，不重設任意行數上限來製造綠燈；
以可觀察的寫入防護、scope admission 與生命週期測試驗證新增行為。

## Verification

- review scripts 全套：629 passed（包含 scope 與真實 macOS sandbox 寫入探針）。
- timeout cleanup 壓力驗證：6 個並行 worker、12 次皆通過。先前錯誤已由 traceback 定位為
  timeout 後重複 killpg；改為回收前只終止一次，未吞掉 EPERM。
- 真實 CLI：agy 1.3.3 於 OS sandbox 下完成認證，讀回未放進 prompt 的 committed nonce，
  與原檔逐字相同；第一次 60 秒 smoke 逾時，後續 150 秒上限的 smoke 於約 26 秒完成。
  產品的既有預設時間預算沒有提高。
- Scope CLI：本機 main 落後 1 commit、PR branch 無 upstream；只接受 pr-only.txt，
  排除 base-only.txt，audit 記錄 1 筆，原 amplifier 報告未被覆蓋。
- Changed-file pre-commit 通過；trace checker 對其他 change 與 trigger overlap 的 advisory WARN
  已如實保留，未為這次工作抑制。
- Linux bwrap 未在此 macOS 主機執行；內建 code-review 的模型決策未實跑，
  scope filter 本身已透過真實 CLI 驗證，不宣稱上游 base 解析方式已被修改或證明。
