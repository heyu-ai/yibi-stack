---
name: warn-rglob-symlink
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.py$
  - field: new_text
    operator: regex_match
    pattern: \.rglob\(
action: warn
---

# Path.rglob() 不跟隨 symlink 子目錄

rule 02 已知 gotcha，第 4 次重現。

`pathlib.rglob()` 預設不進入 symlinked subdirectory，導致掃描結果靜默漏檔。
歷史事故：PR #18、#20、#104、#428。

**修法**：若目標目錄可能含 symlink，改用 `os.walk(followlinks=True)`：

```python
import os
for root, _dirs, files in os.walk(target_dir, followlinks=True):
    for name in files:
        if name.endswith(".jsonl"):
            path = Path(root) / name
```

或 Python 3.13+ `Path.glob(follow_symlinks=True)`。
