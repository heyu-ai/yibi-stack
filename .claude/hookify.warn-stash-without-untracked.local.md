---
name: warn-stash-without-untracked
enabled: true
event: bash
pattern: \bgit(?:\s+-[cC]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+stash(?:\s+(?:push|save)\b|(?=\s+-)|(?=\s*(?:[;&|)\n]|$)))(?![^;&|\n]*\s(?:-[a-zA-Z]*[ua][a-zA-Z]*|--include-untracked|--all)(?=[\s;&|)]|$))
action: warn
---

# `git stash` 沒帶 `-u`：untracked 檔不會被存進去

這個 `git stash`（或 `stash push` / `stash save`）沒有 `-u` / `--include-untracked` / `-a` / `--all`。

**untracked 檔不會被 stash，也不會被移走**——它們留在工作區，stash 裡完全沒有它們。
最容易出事的是 rename / archive（例如 `spectra archive` 把 change 目錄搬進 `archive/`）：
新位置的檔案是 untracked，所以 stash 只記到「舊檔被刪除」那一半，形成一筆只有刪除的 stash。
之後若以為「內容都在 stash 裡」而清掉工作區，新檔就沒了。

實測（git 2.56.0）：把追蹤中的目錄 `mv` 到 `archive/` 後 `git stash push`，
`stash show` 只列出 `D old/spec.md`，`stash^3`（untracked parent）不存在，新舊兩份檔案都還留在磁碟上。

**建議**：

- 要連 untracked 一起存：`git stash push -u -m "<唯一的標記>"`
- 確實只想存 tracked 改動（沒有 untracked 檔，或刻意不存）：照原樣執行即可，這只是提醒
- 共用 stash stack 時，記下 `git stash list --format='%H %gs'` 的 SHA，之後用 `git stash apply <sha>` 還原

來源：PR #540 的 stash 稽核（一筆 stash 只剩 untracked、另一筆只剩刪除），
lesson `git-stash-no-u-drops-untracked-half`。
