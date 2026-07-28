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
`installed_plugins.json` 對每個 `<plugin>@<marketplace>` 記錄一份或多份安裝（user／local
scope 各一筆），每筆帶自己的 `installPath`；未被任何一筆參照的版本目錄不會再被讀取，
純粹是磁碟累積。長期使用下，常更新的 plugin（例如本 repo 自己發布的 pack）可能各累積
十幾個舊版本目錄。

這個 skill 讀取本機安裝清單，比對所有 marketplace 的 cache 目錄，列出（dry-run）
或刪除（`--apply`）未被目前安裝版本參照的舊版本目錄。

## 用法

```bash
python3 ~/.claude/skills/plugin-cache-prune/scripts/prune_plugin_cache.py           # dry-run，只列出
python3 ~/.claude/skills/plugin-cache-prune/scripts/prune_plugin_cache.py --apply   # 實際刪除
python3 ~/.claude/skills/plugin-cache-prune/scripts/prune_plugin_cache.py --help    # 說明
```

`--apply` 是唯一支援的旗標。**任何未知參數都會被 argparse 拒絕並以 exit 2 結束**——
這是刻意的：像 `--apply --marketplace yibi-stack` 這種看起來會限縮範圍、實際不存在的
旗標，必須明確報錯，而不是被靜默忽略後跑一次全域刪除。

或若透過 plugin cache 安裝：`claude plugin install harness@yibi-stack` 後，路徑會在
plugin 自己的 cache 目錄下，直接呼叫本檔同目錄的 `scripts/prune_plugin_cache.py` 即可。

## 輸出範例

dry-run（預設）：

```text
[DRY-RUN] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.10.0  (432 KB)
[DRY-RUN] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.11.0  (462 KB)

共 140 個未被參照的舊版本目錄，合計約 46.9 MB
此為 dry-run，未實際刪除任何檔案。加上 --apply 才會真的刪除。
```

`--apply`（`[SKIP]` 與 `[FAIL]` 走 stderr）：

```text
[REMOVE] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.10.0  (432 KB)
[SKIP] /Users/x/.claude/plugins/cache/yibi-stack/pr-flow/1.11.0 -- 掃描後已被重新釘選，跳過

實際刪除 139 個目錄，回收約 46.5 MB
另有 1 個目錄因刪除前重新確認而跳過
```

**預設為 dry-run，不會自動刪除任何檔案**——必須明確加上 `--apply` 才會實際執行刪除。

## 安全設計

這支工具會呼叫 `shutil.rmtree`，所以每個守衛的預設方向都是「不刪」：

- **無法確認安裝清單時拒絕動作**。清單缺檔、格式錯誤、結構非預期、任一筆缺
  `installPath`、或推導不出任何 `installPath` 時，一律 `[FAIL]` 退出（exit 1），
  絕不把「讀不出有效安裝」誤當成「整個 cache 都是孤兒」。這是刻意的 tri-state 設計：
  「確認為孤兒」與「無法確認」必須分開，見
  [`.claude/rules/15-irreversible-operations.md`](../../../../.claude/rules/15-irreversible-operations.md)
  的「A Boolean Safety Gate Must Distinguish 'Confirmed Safe' From 'Couldn't Check'」。
- **刪除前重新確認，不依賴掃描時的快照**。每次 `rmtree` 前重讀 `installed_plugins.json`；
  若該目錄在掃描後已被其他 session 重新釘選，或當下讀不到清單，都跳過該筆並回報
  `[SKIP]`，不會依舊快照刪除。
- **不跟隨 symlink**。marketplace／plugin／version 三層皆拒絕 symlink，並斷言每個刪除
  候選解析後仍位於 cache root 內，避免刪到 cache 之外的真實目錄；被排除者以 `[SKIP]` 回報。
- **先刪成功才回報**。`[REMOVE]` 只在 `rmtree` 成功後印出；單一目錄刪除失敗會記
  `[FAIL]` 並繼續處理其餘目錄，最後以非零退出碼結束，不會讓整批中斷在一半且不留摘要。

## 已知限制

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
| `[FAIL] ... 可解析但推導不出任何 installPath` | 安裝清單存在但沒有任何有效安裝紀錄。這是刻意拒絕，不是誤判——此時每個版本目錄都會「看起來像」孤兒，照刪會清空整個 cache。若你確實要清空，請自行刪除 `~/.claude/plugins/cache/` |
| `[FAIL] ... 有一筆安裝缺少 installPath` | 該筆安裝無法確認釘選哪個目錄，工具中止以免誤刪。先 `claude plugin update` 或重裝該 plugin 讓清單完整，再重跑 |
| `[SKIP] ... symlink 或位於 cache root 之外` | cache 內有 symlink（例如本機 plugin 開發把 checkout 連進來）。工具刻意不跟隨，以免刪到 cache 之外的真實目錄；該目錄需自行處理 |
| `--apply` 跑完退出碼非零 | 有目錄刪除失敗（權限、唯讀檔等），詳見 stderr 的 `[FAIL]` 行。其餘目錄仍已正常處理，摘要列出實際回收量 |
