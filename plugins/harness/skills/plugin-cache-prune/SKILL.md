---
name: plugin-cache-prune
type: exec
scope: global
description: >
  掃描 ~/.claude/plugins/cache/ 下所有 marketplace 的 plugin 版本快取，找出未被
  installed_plugins.json 參照的舊版本目錄並回報可回收空間，經確認後可實際刪除。
  觸發情境：「plugin cache 太大」「清 plugin 快取」「清理舊版本 plugin」
  「plugin cache prune」「~/.claude 佔用空間」「清理 Claude Code 快取」。
---

# Plugin Cache Prune

Claude Code 更新 marketplace plugin 時，只會在
`~/.claude/plugins/cache/<marketplace>/<plugin>/` 下新增一個版本目錄，從不刪除舊版本——
`installed_plugins.json` 對每個 `<plugin>@<marketplace>` 只記錄一筆目前釘選的
`installPath`，其餘版本目錄不會再被讀取，純粹是磁碟累積。長期使用下，常更新的 plugin
（例如本 repo 自己發布的 pack）可能各累積十幾個舊版本目錄。

這個 skill 讀取本機安裝清單，比對所有 marketplace 的 cache 目錄，列出（dry-run）
或刪除（`--apply`）未被目前安裝版本參照的舊版本目錄。

## 用法

```bash
python3 ~/.claude/skills/plugin-cache-prune/scripts/prune_plugin_cache.py           # dry-run，只列出
python3 ~/.claude/skills/plugin-cache-prune/scripts/prune_plugin_cache.py --apply   # 實際刪除
```

或若透過 plugin cache 安裝：`claude plugin install harness@yibi-stack` 後，路徑會在
plugin 自己的 cache 目錄下，直接呼叫本檔同目錄的 `scripts/prune_plugin_cache.py` 即可。

## 輸出範例

```text
[DRY-RUN] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.10.0  (432 KB)
[DRY-RUN] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.11.0  (462 KB)

共 140 個未被參照的舊版本目錄，合計約 46.9 MB
此為 dry-run，未實際刪除任何檔案。加上 --apply 才會真的刪除。
```

**預設為 dry-run，不會自動刪除任何檔案**——必須明確加上 `--apply` 才會實際執行刪除。

## 已知限制

- **不驗證版本目錄是否正被其他行程使用**。若在 `--apply` 執行的瞬間，另一個 Claude Code
  session 正在把某個「即將被判定為孤兒」的路徑更新成新的釘選版本，理論上有極小的
  time-of-check-to-time-of-use 競態；此工具設計為手動、偶爾執行的維運指令，非常駐服務，
  這個風險可接受但值得知道。
- **只掃 `~/.claude/plugins/cache/`，不掃 `~/.claude/jobs/*/tmp/`**。背景 job 的暫存目錄
  是另一套生命週期（job 結束自動清理），不屬於這個工具的範疇。
- **無法回收透過 `make install` symlink 安裝的 skill**。那類 skill 不寫入
  `installed_plugins.json`，本來就不會出現在 `~/.claude/plugins/cache/`。

## FAQ

| 問題 | 處理方式 |
|------|---------|
| 執行後說找不到 `installed_plugins.json` | 確認你至少透過 `claude plugin install` 裝過一個 plugin；純 symlink 安裝（`make install`）不會產生這份檔案 |
| dry-run 列出的目錄看起來是我還在用的版本 | 檢查 `~/.claude/plugins/installed_plugins.json` 裡對應 plugin 的 `installPath`；若版本不符，代表你可能需要先 `claude plugin update` 讓安裝清單指向新版本，而不是這個工具判斷錯誤 |
| 想確認會刪多少空間但不想跑兩次 | 先跑不帶 `--apply` 的版本，確認清單與總量後再重跑一次帶 `--apply` 的版本；兩次都是完整重新掃描，結果一致 |
