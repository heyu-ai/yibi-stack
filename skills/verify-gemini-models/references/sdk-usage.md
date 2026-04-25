# Gemini SDK 使用指引

> **實作前先驗證**：把你要用的 model ID 丟進 `verify-gemini-models` 跑一次，
> 確認 `✅ FUNCTIONAL` 後再把這份指引的範例碼貼進專案。

## TL;DR — 三件事

1. 用 `google-genai >= 1.51.0`（**不是** `google-cloud-aiplatform` 的 `vertexai.generative_models`，那已 deprecated）
2. Gemini 3.x preview 模型設 `GOOGLE_CLOUD_LOCATION=global`（2.5 系列繼續用 region）
3. Vertex AI URL host 是 `aiplatform.googleapis.com`，**不是** `global-aiplatform.googleapis.com`

---

## 新舊 SDK 對照

| | 推薦（新） | 舊版（廢棄） |
|---|---|---|
| Python 套件 | `google-genai` | `google-cloud-aiplatform` |
| import | `from google import genai` | `from vertexai.generative_models import ...` |
| 棄用時程 | — | deprecated 2025-06-24，**移除 2026-06-24** |
| Gemini 3.x 支援 | ✅ 完整 | ❌ 不支援新 API 特性 |
| 適用範圍 | Gemini API（Vertex + AI Studio） | Gemini API（已棄用）、其他 Vertex 功能仍沿用 |

> 其他 Vertex AI 平台功能（Agent Engine、Model Registry、Pipelines、Evaluation）仍使用
> `google-cloud-aiplatform`，僅生成式 AI 部分改用 `google-genai`。

---

## 環境設定

### Gemini 3.x（global 端點）

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global          # 3.x preview 只在 global 可用
export GOOGLE_GENAI_USE_VERTEXAI=True
```

### Gemini 2.5 系列（region 端點）

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1     # 或其他支援的 region
export GOOGLE_GENAI_USE_VERTEXAI=True
```

> **env var 命名差異（重要）**：
>
> | env var | 用途 |
> |---|---|
> | `GOOGLE_CLOUD_PROJECT` | `google-genai` SDK 讀取的 project ID |
> | `GOOGLE_CLOUD_LOCATION` | `google-genai` SDK 讀取的 location |
> | `GCP_PROJECT_ID` | `check_models.py` 腳本讀取的 project ID（`--project` 預設值） |
> | `VERTEX_AI_LOCATION` | `check_models.py` 腳本讀取的 location（`--location` 預設值） |
>
> 設定 `GOOGLE_CLOUD_LOCATION=global` **不會**影響 `check_models.py` 的 location 行為；
> 需改設 `VERTEX_AI_LOCATION=global` 或傳入 `--location global`。

### AI Studio（使用 API Key，無需 GCP 專案）

```bash
export GEMINI_API_KEY=your-api-key
# 不設 GOOGLE_GENAI_USE_VERTEXAI，SDK 自動使用 AI Studio 模式
```

---

## 認證

### 本機開發（ADC）

```bash
# 授權使用者帳號作為 ADC
gcloud auth application-default login
gcloud config set project your-project-id

# 確認 ADC 正常（能印出 token 代表 OK）
gcloud auth application-default print-access-token
```

### 最小 IAM 權限

```bash
gcloud projects add-iam-policy-binding your-project-id \
  --member="user:you@example.com" \
  --role="roles/aiplatform.user"
```

### Cloud Run / GCE / GKE

附加 Service Account 並授予 `roles/aiplatform.user`，程式碼不需任何改動，
SDK 自動使用 attached SA 的 ADC。

---

## Python 範例

### 安裝

```bash
pip install "google-genai>=1.51.0"
# 或 uv add "google-genai>=1.51.0"
```

### Vertex AI 模式（Gemini 3.1 Pro）

```python
import os
os.environ["GOOGLE_CLOUD_PROJECT"] = "your-project-id"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"   # Gemini 3.x 必填
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google import genai
from google.genai import types

# 讀取上述三個環境變數；也可改用顯式參數：
# client = genai.Client(vertexai=True, project="your-project-id", location="global")
client = genai.Client()

response = client.models.generate_content(
    model="gemini-3.1-pro-preview",
    contents="用一句話解釋量子糾纏。",
    config=types.GenerateContentConfig(
        # Gemini 3 預設 thinking_level=HIGH；LOW 降低延遲
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.LOW
        ),
        temperature=1.0,  # Gemini 3 強烈建議保留 1.0，不要調低
    ),
)
print(response.text)
```

### AI Studio 模式（使用 API Key）

```python
from google import genai
from google.genai import types

# 不設 GOOGLE_GENAI_USE_VERTEXAI，SDK 自動用 AI Studio 模式
client = genai.Client(api_key="your-api-key")

response = client.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents="Summarize this in one sentence.",
    config=types.GenerateContentConfig(temperature=1.0),
)
print(response.text)
```

### TTS（語音合成）

```python
import base64

response = client.models.generate_content(
    model="gemini-3.1-flash-tts-preview",
    contents="哈囉，你好！",
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
    ),
)
audio_bytes = base64.b64decode(
    response.candidates[0].content.parts[0].inline_data.data
)
with open("output.wav", "wb") as f:
    f.write(audio_bytes)
```

---

## Node.js / TypeScript 範例

### 安裝

```bash
npm install @google/genai
```

### Vertex AI 模式

```typescript
// index.ts (Node 18+)
import { GoogleGenAI } from "@google/genai";

// 讀取環境變數（GOOGLE_CLOUD_PROJECT、GOOGLE_CLOUD_LOCATION=global、
// GOOGLE_GENAI_USE_VERTEXAI=true）
const ai = new GoogleGenAI({});
// 或顯式指定：
// const ai = new GoogleGenAI({
//   vertexai: true,
//   project: process.env.GOOGLE_CLOUD_PROJECT,
//   location: "global",
// });

const response = await ai.models.generateContent({
  model: "gemini-3.1-pro-preview",
  contents: "Explain quantum entanglement in one sentence.",
  config: {
    thinkingConfig: { thinkingLevel: "low" },
    temperature: 1.0,
  },
});
console.log(response.text);
```

### AI Studio 模式

```typescript
import { GoogleGenAI } from "@google/genai";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

const response = await ai.models.generateContent({
  model: "gemini-3.1-flash-lite-preview",
  contents: "Hello!",
});
console.log(response.text);
```

---

## OpenAI 相容層（可選）

若既有程式以 OpenAI SDK 為主，可用 Vertex AI 的 OpenAI-compatible 端點：

```python
from google.auth import default
from google.auth.transport.requests import Request
import openai

PROJECT_ID = "your-project-id"

credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
credentials.refresh(Request())

client = openai.OpenAI(
    base_url=(
        f"https://aiplatform.googleapis.com/v1/projects/{PROJECT_ID}"
        "/locations/global/endpoints/openapi"
    ),
    api_key=credentials.token,
)

resp = client.chat.completions.create(
    model="google/gemini-3.1-pro-preview",
    messages=[{"role": "user", "content": "Hello"}],
    reasoning_effort="medium",  # 對應 thinking_level=medium
)
print(resp.choices[0].message.content)
```

> Token 有效期約 1 小時，正式環境需實作自動 refresh。

---

## Model ID 命名規則

| 規則 | 正確 | 錯誤 |
|---|---|---|
| Gemini 3.1 用小數點 | `gemini-3.1-pro-preview` | `gemini-3-1-pro-preview` |
| Preview 必須加後綴 | `gemini-3.1-pro-preview` | `gemini-3.1-pro`（不存在）|
| 3.x 無三位數版本 | `gemini-3.1-pro-preview` | `gemini-3.1-pro-001`（不存在）|
| 3.x 無 auto-updated alias | 一律 pin ID 字串 | `gemini-3.1-pro-latest`（不存在）|
| 已下架 ID | 改用 `gemini-3.1-pro-preview` | `gemini-3-pro-preview`（2026-03-26 退役）|

---

## Pinning 最佳實務

1. **一律 pin 完整 ID**，不要用 `*-latest` 別名（Vertex AI 的 Gemini 3.x 沒有這類別名）
2. **把 model ID 存在環境變數或設定檔**，升版時不需改程式碼
3. **訂閱 Vertex AI release notes RSS** 監控 Preview 模型下架通知
4. **Preview 模型沒有 SLA**；上線前用 `verify-gemini-models` 實測一遍

---

## Region 限制速查

| 模型系列 | Vertex AI location | 說明 |
|---|---|---|
| Gemini 3.x preview（`gemini-3.*`） | `global` 限定 | 區域端點回傳 404 |
| Gemini 2.5 stable（`gemini-2.5-flash` 等） | 任意支援 region | `us-central1`、`europe-west4` 等 |
| Gemini 2.5 TTS preview（`gemini-2.5-*-preview-tts`） | 任意支援 region | 同上 |
| Gemini 3.1 TTS（`gemini-3.1-flash-tts-preview`） | `global` 限定 | 同 3.x 規則 |
| Live API（Vertex） | `global` + 需 allowlist | WebSocket 端點 |

**Vertex AI REST URL 規則**：

- global：`https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global/...`
- region：`https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/us-central1/...`

> `https://global-aiplatform.googleapis.com` 不存在，會直接 DNS 失敗。

---

## 常見錯誤排除

| `verify-gemini-models` 看到的錯誤 | 根因 | SDK 端修正 |
|---|---|---|
| `❌ NOT FOUND`（Vertex，3.x 模型） | SDK `GOOGLE_CLOUD_LOCATION` 非 `global`，或腳本 `VERTEX_AI_LOCATION` 非 `global` | SDK：`os.environ["GOOGLE_CLOUD_LOCATION"] = "global"`；腳本：`export VERTEX_AI_LOCATION=global` |
| `❌ NOT FOUND`（任何模型） | Model ID 拼錯（橫線 vs 小數點、缺 `-preview`） | 核對命名規則表格 |
| `💥 ERROR: HTTP 401` | ADC token 過期 | `gcloud auth application-default login` |
| `💥 ERROR: HTTP 403` | 缺少 `roles/aiplatform.user` 或未啟用計費 | 授予 IAM 角色、啟用計費帳號 |
| `💥 ERROR: HTTP 429` | 超過 quota | 實作指數退避；申請提升 quota |
| `⚠️ EMPTY OUTPUT`（TTS） | 缺少 `responseModalities: ["AUDIO"]` | 加 `response_modalities=["AUDIO"]` 到 `GenerateContentConfig` |
| `⚠️ EMPTY OUTPUT`（LLM 思考模型） | `maxOutputTokens` 太低 | 設 `max_output_tokens` 至少 256（Thinking 需要預算） |
| `❌ LIVE REFUSED`（Vertex） | 專案未加入 Live API allowlist | 改用 AI Studio endpoint |
| SDK 版本錯誤導致 400 | `google-genai < 1.51.0` | `pip install "google-genai>=1.51.0"` |
