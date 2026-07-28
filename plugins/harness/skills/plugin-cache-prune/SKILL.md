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
另有 1 個目錄在刪除前確認為已重新釘選而跳過
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
- **刪除前重新確認，不依賴掃描時的快照**。每次 `rmtree` 前重讀 `installed_plugins.json`。
  兩種結果刻意分開回報：該目錄若已被其他 session 重新釘選，屬良性，回報 `[SKIP]` 且
  不影響退出碼；若當下讀不到清單，屬「無法確認」，回報 `[FAIL]`、中止本次刪除並以
  非零退出碼結束（同一份壞掉的清單，不該因為壞在初次載入還是刪除當下而給出相反答案）。
- **不跟隨 symlink**。marketplace／plugin／version 三層皆拒絕 symlink，並斷言每個刪除
  候選解析後仍位於 cache root 內，避免刪到 cache 之外的真實目錄；被排除者以 `[SKIP]` 回報。
- **近期有異動的目錄一律不碰，且時間在刪除當下重新量測**。安裝流程會先建立並填充版本
  目錄、之後才把 `installPath` 寫進 `installed_plugins.json`；在那段窗口內該目錄在
  **任何一次 manifest 重讀**下都長得像孤兒。因此加一道時間門檻：mtime 在 300 秒內的
  未參照目錄視為「可能正在安裝」而跳過。門檻取 300 秒有量測依據——實測機器上 50 個版本
  目錄中，5 分鐘內有異動的是 0 個、1 小時內是 21 個。
  這道門檻在**掃描時與刪除前各量一次**：只在掃描時量會留下一個同時繞過兩道防線的缺口
  ——一個掃描當下是孤兒、掃描後才被重新安裝（re-install／降版回既有版本）的目錄，
  manifest 重讀看不到它，掃描期的 mtime 又已是舊快照。
  讀不到 mtime、或 mtime 落在未來（備份還原、`cp -p`、時鐘校正皆會造成）時，都屬
  「無法用時間判斷」，回報 `[FAIL]` 並計入非零退出碼——刻意不歸類為「近期有異動」，
  因為負數的 age 永遠滿足門檻，會讓該目錄被永久跳過還附上與事實相反的訊息。
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
| 想確認會刪多少空間但不想跑兩次 | 先跑不帶 `--apply` 的版本確認清單與總量，再重跑一次帶 `--apply` 的版本。兩次都是完整重新掃描，但**結果不保證一致**——期間若有 plugin 被安裝／更新，第二次的清單就會不同；`--apply` 一律以刪除當下的安裝清單為準，被重新釘選者以 `[SKIP]` 回報 |
| `[FAIL] ... 可解析但推導不出任何 installPath` | 安裝清單存在但沒有任何有效安裝紀錄。這是刻意拒絕，不是誤判——此時每個版本目錄都會「看起來像」孤兒，照刪會清空整個 cache。若你確實要清空，請自行刪除 `~/.claude/plugins/cache/` |
| `[FAIL] ... 有一筆安裝缺少 installPath` | 該筆安裝無法確認釘選哪個目錄，工具中止以免誤刪。先 `claude plugin update` 或重裝該 plugin 讓清單完整，再重跑 |
| `[SKIP] ... symlink，不跟隨以免刪到 cache root 之外` | cache 內有 symlink（例如本機 plugin 開發把 checkout 連進來）。工具刻意不跟隨，以免刪到 cache 之外的真實目錄；該目錄需自行處理 |
| `[SKIP] ... 可能是安裝中的目錄` / `[SKIP] ... 刪除前重新確認時發現近期異動` | 該目錄 mtime 在 300 秒內。可能正好有 `claude plugin install/update`（含背景 autoUpdate）在寫入它。等幾分鐘後重跑即可；若確定沒有安裝在跑，該目錄下次執行就會被回收 |
| `[SKIP] ... 非目錄，不列入版本目錄候選` | cache 樹裡有雜項檔案（macOS 的 `.DS_Store` 最常見）。工具只處理目錄，回報後略過；不需處理，也可自行刪除該檔 |
| `[SKIP] ... 解析後位於 cache root 之外` | 該候選解析後不在 cache root 內。這是 symlink 拒絕之外的第二道邊界防線，正常情況不會出現；若出現代表 cache 結構被外部改動過，請人工檢查 |
| `[FAIL] ... mtime 在未來` | 該目錄的時間戳晚於現在（備份還原、`cp -p`、時鐘校正皆會造成）。時間門檻無法判斷它是否安裝中，工具拒絕刪除並以非零退出碼提示。用 `touch` 修正時間戳後重跑即可 |
| `[FAIL] ... 無法讀取 mtime` | 掃描後該目錄消失或無法存取。屬「無法確認」，不刪並計入非零退出碼；重跑一次通常即消失 |
| `--apply` 跑完退出碼非零 | 兩種情況會回非零：有目錄刪除失敗（權限、唯讀檔等），或有目錄在刪除前**無法重新確認**安裝清單。兩者都在 stderr 留 `[FAIL]` 行。其餘目錄仍已正常處理，摘要列出實際回收量。「確認後發現已被重新釘選」屬良性結果，走 `[SKIP]` 且不影響退出碼 |
