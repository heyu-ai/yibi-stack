# 安全性規範

## 敏感檔案絕不 commit

以下目錄/檔案已在 `.gitignore`，永遠不要嘗試 commit：

- `.env` — API keys、密碼、加密金鑰
- `.runtime/` — JSON 設定檔（可能含加密密碼）、SQLite DB
- `output/` — 所有 skill 產出檔案

## 密碼加密

存入 `.runtime/` JSON 的密碼必須先用 Fernet 加密：

```python
# 正確：儲存加密後的值
config.pdf_password_encrypted = encrypt(password, key)

# 錯誤：明文密碼存 JSON
config.pdf_password = "my-secret-password"
```

加密金鑰從環境變數取得，不可硬編碼：

```python
key = os.environ["ENCRYPT_KEY"].encode()  # 從 .env 載入
```

## SQL 參數化查詢

SQL 查詢永遠使用 `?` 參數化，禁止 f-string 拼接：

```python
# 正確
cursor.execute("SELECT * FROM runs WHERE job_id = ?", (job_id,))

# 錯誤
cursor.execute(f"SELECT * FROM runs WHERE job_id = '{job_id}'")
```

動態 WHERE 子句（條件數量不固定）：

```python
conditions = []
params: list[object] = []
if status:
    conditions.append("status = ?")
    params.append(status)
where = f"WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
cursor.execute(f"SELECT * FROM runs {where}", params)  # nosec B608
```

## Protect-Push Hook

`.claude/hooks/protect-push.sh` 防止從 worktree branch 直推 origin/main。
不要繞過此 hook（不用 `--no-verify`）。
