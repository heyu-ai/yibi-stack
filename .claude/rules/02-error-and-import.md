# 錯誤處理 & Import 規範

## 例外類型選擇

| 情況 | 例外類型 |
|------|----------|
| 環境未設定、外部工具不可用、解密失敗、檔案遺失 | `RuntimeError` |
| 輸入格式錯誤、設定值不合法 | `ValueError` |
| Pydantic validator 內 | `ValueError`（Pydantic 會包成 ValidationError） |

## Exception Chaining

一律使用 `raise ... from e` 保留完整 traceback：

```python
try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    raise RuntimeError(f"設定檔格式錯誤：{config_path}") from e
```

## 重型 Import 延遲

下列第三方庫必須放在 function body 內，不可在 module 頂層 import：

- `pikepdf`, `pdfplumber`, `tabula`
- `cryptography.fernet`
- `playwright`
- `pytesseract`, `PIL`

```python
# 正確
def decrypt_pdf(path: Path, password: str) -> Path:
    from cryptography.fernet import Fernet
    ...

# 錯誤
from cryptography.fernet import Fernet  # module 頂層
```

標準庫（`pathlib`, `json`, `sqlite3`）及輕量套件（`click`, `pydantic`, `requests`）可在頂層 import。

## Subprocess 規範

```python
import subprocess  # nosec B404

result = subprocess.run(  # nosec B603
    ["uv", "run", "python", "-m", "tasks.gmail_scan", "status"],
    capture_output=True,
    text=True,
    timeout=60,
)
```

- 永遠用 list args（不用 `shell=True`）
- 永遠設定 `timeout`
- 加上 bandit nosec 註解：`# nosec B404`（import）、`# nosec B603`（呼叫）

## Filesystem 路徑存在性檢查

路徑存在性檢查優先用 `is_dir()` / `is_file()`，不用 `exists()`：

```python
# 違規：同名非目錄檔案時返回 True，後續 rglob() 拋 NotADirectoryError
if path.exists():
    for f in path.rglob("*.md"): ...

# 正確：直接排除非目錄
if path.is_dir():
    for f in path.rglob("*.md"): ...
```

`exists()` 只在「不區分型態、只需確認路徑存在」的場合使用（如 config 檔、log 檔）。
