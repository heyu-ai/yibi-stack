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
config.pdf_secret_fernet = encrypt(secret, key)

# 錯誤：明文存 JSON（絕對不要這樣做）
config.pdf_secret = "<明文值>"
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
不要繞過此 hook，也不要使用任何 bypass 旗標停用 git hook 驗證。

## Scanner Gate 設計原則

Security scanner 的「前置條件 gate」（如 `gitignore_ok`）只應控制 score 累積，
不應以 early return 阻斷 findings 輸出——使用者在 gate 失敗時仍需看到所有偵測結果。

```python
# 正確：gate 只影響 score，findings 無條件執行
if not gitignore_ok:
    pass  # score 不累積，但繼續往下掃描
findings.append(check_dangerous_commands())

# 錯誤：gate 失敗就 early return，使用者看不到後續偵測結果
if not gitignore_ok:
    return MechanicalFinding(score=0, findings=["WARN: no .gitignore"])
```
