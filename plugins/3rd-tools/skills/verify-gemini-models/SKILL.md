---
name: verify-gemini-models
type: exec
scope: global
description: >
  驗證 Gemini 模型在 Google AI Studio 與 GCP Vertex AI 上的**實際可用性**——
  不只是「列在文件上」，而是真正可呼叫並回傳有效輸出。支援 Gemini 3.x global 端點
  （gemini-3.1-pro-preview、gemini-3-flash-preview 等只在 global 端點可用）。
  當使用者詢問模型可用性、在寫入程式碼或設定前確認模型名稱是否有效、
  遇到 404/1011/model-not-found 錯誤、要在版本遷移前審查可用模型、
  或在不同 Gemini 版本間做選擇時使用此 skill。
  觸發關鍵字：模型是否存在、哪些模型可用、Vertex 找不到模型、
  AI Studio 模型測試、gemini 模型驗證、does model exist、which models actually work、
  gemini-3.1-pro-preview 不存在、global endpoint 404、Gemini 3 無法使用。
---

# verify-gemini-models

確認 Gemini 模型在 Google AI Studio 與 Vertex AI 上的**真實可用性**——
不只是文件說什麼。模型出現在 API listing 不代表它支援所有能力類型，
同一個模型名稱在不同平台上的行為可能完全不同。

## 為什麼需要三種獨立驗證

| 失效模式 | 症狀 | 意義 |
|---------|------|------|
| 模型不在此平台 | HTTP 404 | 模型在其他平台存在但此處沒有 |
| 列出但壞掉 | WebSocket 1011 | 列出但未真正部署 |
| 名稱格式錯誤 | HTTP 404 | 點換成橫線、缺少 `-preview` 後綴 |
| 音訊為空 | HTTP 200，0 bytes | 靜默失敗——比 404 更糟 |
| Thinking 模型 token 不足 | HTTP 200，無文字 | maxOutputTokens 太低，推理預算耗盡 |

## 能力類型

| 類型 | 方法 | 說明 |
|-----|------|------|
| **LLM** | `generateContent` REST | 文字輸出 |
| **TTS** | `generateContent` + `speechConfig` | 音訊輸出（PCM/L16 或 MP3） |
| **Live** | `BidiGenerateContent` WebSocket | 即時音訊；需要獨立 allowlist |

## 步驟

> **執行位置**：本 skill 可從任何 cwd 觸發，Step 3 腳本已透過
> `~/.agents/bin/resolve-skill-repo` 自動定位 yibi-stack repo，無需 `cd`。

### Step 1 — 環境確認

確認工具與憑證可用：

```bash
# Vertex AI -- Application Default Credentials
ls ~/.config/gcloud/application_default_credentials.json
test -n "$GCP_PROJECT_ID" && echo "GCP_PROJECT: SET" || echo "GCP_PROJECT: MISSING"
# 若缺少：gcloud auth application-default login && export GCP_PROJECT_ID=<project>

# Google AI Studio -- API key（絕不 echo key 值本身，只驗證存在性）
test -n "$GEMINI_API_KEY" && echo "GEMINI_KEY: SET" || echo "GEMINI_KEY: MISSING"
# 或從 yibi-stack repo 的 .env 確認 key 存在：
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
grep -q GEMINI_API_KEY "$SKILL_REPO/.env" 2>/dev/null && echo "ENV_KEY: PRESENT" || echo "ENV_KEY: ABSENT"
```

若憑證缺少，停下來告知使用者需要執行哪個指令，等待確認後再繼續。

### Step 2 — 設定確認

向使用者確認以下參數後執行：

- **要驗證的模型**：`{{model_names}}`（或「所有已知 Gemini 模型」）
- **平台**：`{{platforms}}`（vertex / aistudio / 兩者）
- **能力類型**：`{{capabilities}}`（llm / tts / live，預設全選）

### Step 3 — 執行驗證腳本

腳本有獨立的 `pyproject.toml`，從 skill 目錄執行：

```bash
if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
SKILL_DIR="$SKILL_REPO/skills/verify-gemini-models"

uv run --project "$SKILL_DIR" python "$SKILL_DIR/scripts/check_models.py" \
  --models "gemini-2.5-flash,gemini-2.5-pro,gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts,gemini-3.1-pro-preview,gemini-3-flash-preview,gemini-3.1-flash-lite-preview,gemini-3.1-flash-tts-preview,gemini-3.1-flash-image-preview,gemini-3-pro-image-preview,gemini-3.1-flash-live-preview,gemini-2.5-flash-native-audio-preview-12-2025" \
  --platforms vertex,aistudio \
  --capabilities llm,tts,live \
  --project "$GCP_PROJECT_ID" \
  --location us-central1
```

依使用者需求調整 `--models`。

**選用旗標：**

- `--no-functional` — 跳過回應內容驗證，僅確認存在性（較快）；結果顯示 `🟡 REACHABLE` 而非 `✅ FUNCTIONAL`
- `--no-live-roundtrip` — Live 驗證：只確認 SETUP_COMPLETE，跳過音訊來回（較快）
- `--json` — 輸出原始 JSON，供腳本串接使用

### Step 4 — 結果報告

**狀態等級（越高越可信）：**

| 狀態 | 意義 |
|------|------|
| `✅ FUNCTIONAL` | HTTP 200 + 驗證有效輸出（文字內容 / 音訊 > 1 KB） |
| `🟡 REACHABLE` | HTTP 200 但輸出驗證失敗或無法確認 |
| `🔵 EXISTS` | HTTP 400/403 — 模型已部署，但此能力類型的參數不對 |
| `❌ NOT FOUND` | HTTP 404 — 模型不存在於此平台 |
| `✅ LIVE OK` | WebSocket SETUP_COMPLETE + 音訊來回確認 |
| `🟡 LIVE SETUP-ONLY` | WebSocket SETUP_COMPLETE，但音訊來回未確認 |
| `❌ LIVE WS-1011` | 模型有列出但未部署到 Live API |
| `❌ LIVE REFUSED` | WebSocket 連線完全無法建立（網路錯誤、1008 policy violation 等） |
| `⚠️  EMPTY OUTPUT` | HTTP 200 但模型回傳空內容——**靜默失敗，禁止使用** |
| `💥 ERROR` | 非預期錯誤（timeout、401 憑證過期、429 限流等） |

**決策規則：**

- `✅ FUNCTIONAL` / `✅ LIVE OK` → 可安全寫入程式碼或設定
- `🟡` 任何狀態 → 出貨前需先調查
- `⚠️ EMPTY OUTPUT` → 絕對不用，比 404 更危險
- `🔵 EXISTS` → 模型存在但你呼叫方式錯誤（例如用 LLM 方式呼叫 TTS 專用模型）
- `💥 ERROR` 含 401 → 憑證過期，需重新登入；含 429 → 被限流

**各平台常見模式說明：**

- **「模型只在 AI Studio，不在 Vertex」** → 改用 Vertex 確認可用的替代方案（如 LLM 用 `gemini-2.5-flash`）
- **「Live 模型在 Vertex 回傳 `❌ LIVE REFUSED`」** → GCP 專案缺少 Vertex Live API allowlist，改用 AI Studio endpoint
- **「Live 模型 REST 回傳 404」** → Live-only 模型（`*-live-preview`、`native-audio-preview-*`）**沒有 REST endpoint**，只能用 WebSocket
- **「TTS 回傳 EMPTY OUTPUT 但 HTTP 200」** → 確認請求格式有 `responseModalities: ["AUDIO"]` + `speechConfig`；音訊格式為 PCM/L16 或 MP3，依模型而定
- **「Thinking 模型（2.5 Pro）回傳空 parts」** → `maxOutputTokens` 太低，Thinking 模型在輸出前需消耗 token 做內部推理，至少設 256

以清楚的表格摘要並明確說明結論：「模型 X 在平台 Y 的 Z 能力**確認可用** / **不可用**。」

```text
模型                            | 平台       | LLM         | TTS         | Live
-------------------------------|------------|-------------|-------------|-----
gemini-2.5-flash               | Vertex     | ✅ text     | 🔵 no-audio | ❌
gemini-2.5-flash-preview-tts   | Vertex     | 🔵 tts-only | ✅ 44KB     | ❌
gemini-3.1-flash-live-preview  | AI Studio  | ❌ 404      | ❌ 404      | 🟡 setup-only
```

## 注意事項

- **Limited preview 模型**可能需要專案 allowlist —— 404 可能代表「你的專案未在 allowlist」而非「模型不存在」
- **Vertex Live** 需要獨立於一般 Vertex API 存取的 allowlist
- **WebSocket 上線晚於 REST** —— 模型可能 REST 可用數週後 Live 才穩定
- **模型可用性會改變** —— 每次重要部署前重新驗證，不要只驗一次
- **`-001` 後綴** = 固定版本；無後綴 = rolling latest（非 Live 場景可接受）

## 已知 Gemini 模型狀態（2026-04）

```text
# Vertex AI — global 端點（Gemini 3.x preview，2026-04-25 實測 project=heyu-voice-lab）：
gemini-3.1-pro-preview          # LLM ✅ FUNCTIONAL（text: PONG）；TTS 🔵 需 audio allowlist
gemini-3-flash-preview          # LLM ✅ FUNCTIONAL（text: PONG）；TTS 🔵 需 audio allowlist
gemini-3.1-flash-lite-preview   # LLM ✅ FUNCTIONAL（text: PING）；TTS 🔵 不支援（invalid arg）
gemini-3.1-flash-image-preview  # LLM ✅ FUNCTIONAL（text: PONG）；TTS 🔵 需 audio allowlist
gemini-3-pro-image-preview      # LLM ✅ FUNCTIONAL（text: PONG）；TTS 🔵 需 audio allowlist
gemini-3.1-flash-tts-preview    # TTS ✅ FUNCTIONAL（53,760 audio bytes）；LLM 🔵 TTS-only 模型

# Vertex AI — region 端點（us-central1，Gemini 2.5 系列，2026-04-25 實測）：
gemini-2.5-flash                # LLM ✅ FUNCTIONAL；TTS 🔵 需 audio allowlist
gemini-2.5-pro                  # LLM ✅ FUNCTIONAL；TTS 🔵 需 audio allowlist
gemini-2.5-flash-preview-tts    # TTS ✅ FUNCTIONAL（42,766 audio bytes，PCM/L16）；LLM 🔵 TTS-only
gemini-2.5-pro-preview-tts      # TTS ✅（先前確認）
gemini-3.1-flash-tts-preview    # 見上（global 端點）

# Google AI Studio — 確認 FUNCTIONAL（先前驗證，本次 GEMINI_API_KEY 未設）：
gemini-2.5-flash              # LLM ✅
gemini-2.5-pro                # LLM ✅
gemini-2.5-pro-preview-tts    # TTS ✅
gemini-3.1-flash-tts-preview  # TTS ✅
gemini-3.1-flash-lite-preview # LLM ✅ (僅 AI Studio，Vertex global 亦 FUNCTIONAL)

# Live（Vertex us-central1，2026-04-25 實測 project=heyu-voice-lab）：
# gemini-live-* 前綴 = Live-only 模型；只走 WebSocket，REST 回 HTTP 400（正常）
gemini-live-2.5-flash-native-audio               # ✅ LIVE OK（11,114 audio bytes）；LLM 🔵（Live-only，無 REST）
gemini-live-2.5-flash-preview-native-audio-09-2025  # ✅ LIVE OK（11,114 audio bytes）；⚠️ 將於 2026-03-19 淘汰，改用上方

# Live（Vertex 需要 allowlist；下列模型在 heyu-voice-lab 1008 policy violation）：
gemini-3.1-flash-live-preview  # ❌ 1008 policy violation（heyu-voice-lab 未加入 allowlist）

# 已知無效 / 錯誤名稱：
gemini-3.1-pro                # ❌ 缺少 -preview 後綴（GA alias 不存在）
gemini-3-1-pro-preview        # ❌ 橫線取代小數點 — 永遠 404
gemini-3-pro-preview          # ⚠️  已於 2026-03-26 下架，請改用 gemini-3.1-pro-preview
gemini-3-1-flash-live         # ❌ 橫線版本 — 永遠 404
gemini-2.5-flash-001          # ❌ 固定版本號不在 AI Studio v1beta
gemini-2.5-flash-native-audio-preview-12-2025  # ❌ 非 gemini-live-* 前綴，Vertex 回 404
```

每次驗證後更新此區塊 —— 這是你的實際可用性真相來源。

## 常見問題

| 問題 | 解法 |
|------|------|
| `❌ Vertex ADC error` | 執行 `gcloud auth application-default login` 重新登入 |
| `💥 ERROR: HTTP 401` | ADC token 過期，重新執行 `gcloud auth application-default login` |
| `💥 ERROR: HTTP 429` | 被限流，稍候再試或減少同時驗證的模型數量 |
| `❌ LIVE REFUSED` on Vertex | GCP 專案缺少 Vertex Live API allowlist，改用 AI Studio |
| TTS 回傳 `⚠️ EMPTY OUTPUT` | 確認請求有 `responseModalities: ["AUDIO"]` + `speechConfig` |
| 模型名稱有 404 | 確認名稱格式（點 vs 橫線）、是否需要 `-preview` 後綴 |
| `websockets not installed` | 腳本依賴未安裝：在 skill 目錄執行 `uv sync` |
