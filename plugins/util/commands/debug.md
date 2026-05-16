# Debug Issue

Structured debugging methodology. Enforces root cause analysis before suggesting fixes.

## Autonomous Mode（預設行為）

收到 error log 或 failing test 時，自主完成以下流程，不要問問題：

1. 閱讀 failing test 和相關原始碼，理解預期行為
2. 追蹤錯誤路徑，定位 root cause
3. 實作最小修復
4. 跑測試完整驗證，失敗就迭代修復
5. 跑 lint 修正格式問題
6. 全部通過後，建立 PR，描述 root cause 和修復內容

遇到模糊的設計決策時，選較安全/簡單的方案，並在 PR description 中註記。

## Phase 1: Triage — Understand the Error

Before touching any code:

1. Ask for (or parse from context): the **exact error message**, **affected module/endpoint**, **stack trace**, and **when it started**.
2. Identify the error category by project type:

   **Web App（有 HTTP server）**：
   - **5xx** → server-side (backend, DB, migration, config)
   - **4xx** → auth/permission/routing issue
   - **CORS** → proxy, cold start, or missing header
   - **Build/type error** → frontend config, Tailwind, i18n, or TSC issue

   **Python / Automation（CLI、script、agent）**：
   - **Runtime error** → Python exception, missing dependency, config issue
   - **Browser automation** → Playwright timeout, selector change, page structure change
   - **Data parsing** → CSV/PDF format change, unexpected input, encoding issue
   - **Environment** → missing `.env` vars, auth token expired

## Phase 2: Environment & Config Check

```bash
# Check .env files
ls -la .env*

# Check recent changes that may have caused regression
git log --oneline -10
git diff HEAD~5
```

**Web App 額外檢查（Config Shadowing）**：

```bash
ls -la frontend/vite.config.*
ls -la backend/*.env* .env*
git diff HEAD~5 -- frontend/vite.config.ts backend/src/main.py
```

Common shadow issues:

- `vite.config.js` shadowing `vite.config.ts`
- `.env.local` overriding `.env` (not visible in git diff)
- Docker environment missing variables that work locally

## Phase 3: Database / Migration Check（Web App）

500 errors 最常見的 root cause 是 migration 沒跑。**在查 application code 之前先排除。**

```bash
# 依專案使用的 migration 工具調整：
# Alembic:  cd backend && uv run alembic current && uv run alembic heads
# Prisma:   cd backend && npx prisma migrate status
# Drizzle:  cd backend && npx drizzle-kit check
```

快速判斷：

- `column "X" does not exist` → migration 未跑
- `relation "X" does not exist` → table 的 migration 未跑
- 本地正常、deploy 後 500 → CI/CD 沒跑 migration

## Phase 4: Apply Fix

Only after identifying root cause:

1. Apply the **minimal** fix.
2. If it's a migration: write and run the migration.
3. If it's a config: update ALL locations consistently.
4. If it's a website change: update selectors/parsing logic.

## Phase 5: Verify — User-Facing Behavior (CRITICAL)

**Do NOT declare success based on error disappearance alone.**

- A 401 replacing a 500 is NOT a fix.
- Verify the actual user-facing behavior works end-to-end.

```bash
# Python 專案
uv run pytest

# Web App（依專案調整）
make test
curl -v http://localhost:8888/api/v1/<affected-endpoint>
```

Only report success after confirming the original problem is resolved.

## Phase 6: Prevent Recurrence

After fixing, note:

- What was the root cause?
- What check would have caught this earlier?
- Should a test be added to prevent regression?

如已在自主模式下完成修復，建立 PR：

- `git add` 修復相關檔案（排除 debug logs、.env 變更）
- 使用 conventional commit format：`fix(scope): 簡短描述`
- `gh pr create` 並在 body 中包含 root cause 分析和修復說明
