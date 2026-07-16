---
paths:
  - "tasks/**/config.py"
---
# Config Loading Pattern

## Config File Location

All JSON config files are stored in `.runtime/` (via `RUNTIME_DIR`), not committed to git:

```python
from tasks._paths import RUNTIME_DIR

DEFAULT_CONFIG_PATH = RUNTIME_DIR / "gmail_scan_profiles.json"
```

## Standard Function Set

Each `config.py` should include the following functions:

```python
def _load_env() -> None:
    """載入 .env 環境變數。"""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

def get_default_config_path() -> Path:
    return RUNTIME_DIR / "<name>.json"

def load_config(path: Path | None = None) -> XxxConfig:
    """載入設定，檔案不存在時 exit(1)。"""
    config_path = path or get_default_config_path()
    if not config_path.exists():
        click.echo(f"找不到設定檔：{config_path}")
        click.echo("請先執行：uv run python -m tasks.<module> setup")
        raise SystemExit(1)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return XxxConfig.model_validate(data)

def save_config(config: XxxConfig, path: Path | None = None) -> None:
    """儲存設定檔。"""
    config_path = path or get_default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")

def generate_default_config(path: Path | None = None) -> Path:
    """建立預設設定檔並回傳路徑。"""
    config = XxxConfig(...)
    config_path = path or get_default_config_path()
    save_config(config, config_path)
    return config_path
```

## Environment Variables

Load `.env` via `_load_env()`, then access values with `os.environ.get()`:

```python
_load_env()
token = os.environ.get("GMAIL_TOKEN")
if not token:
    raise RuntimeError("環境變數 GMAIL_TOKEN 未設定")
```

## Encrypted Passwords

Defer the encryption helper import to the function body (`cryptography` is a heavy import).
