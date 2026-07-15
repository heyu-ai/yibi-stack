#!/usr/bin/env python3
"""
verify-gemini-models: check_models.py

Two-tier verification of Gemini models on Google AI Studio and/or Vertex AI:

  Tier 1 — Existence:   does the model exist on this platform?  (HTTP status)
  Tier 2 — Functional:  does it produce valid output?           (response content)

For Live/WebSocket, a third gate is added: after SETUP_COMPLETE, send a real
text turn and verify that audio bytes come back.

Gemini 3.x preview 模型（gemini-3.1-pro-preview 等）只在 global 端點提供，
腳本會依 GLOBAL_ONLY_MODELS 白名單自動切換，不需手動指定 --location global。

Usage (from the skill directory):
    SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo") || exit 1
    SKILL_DIR="$SKILL_REPO/skills/verify-gemini-models"
    uv run --project "$SKILL_DIR" python "$SKILL_DIR/scripts/check_models.py" \\
        --models "gemini-2.5-flash,gemini-3.1-flash-tts-preview" \\
        --platforms vertex,aistudio \\
        --capabilities llm,tts,live \\
        --project my-gcp-project \\
        --location us-central1

Reads GEMINI_API_KEY from env for AI Studio probes.
Uses Application Default Credentials (ADC) for Vertex probes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Literal

import httpx

# ── Status levels (ordered: higher = more trustworthy) ───────────────────────
#
#  functional   ⭐⭐⭐  HTTP 200 + verified real output (text / audio bytes)
#  reachable    ⭐⭐   HTTP 200 but output was empty or couldn't be verified
#  exists       ⭐    HTTP 400/403 — model is deployed but capability params wrong
#  not_found    ✗    HTTP 404 — model doesn't exist on this platform
#  ws_functional ⭐⭐⭐  Live: SETUP_COMPLETE + audio round-trip succeeded
#  ws_connected  ⭐⭐   Live: SETUP_COMPLETE only (no audio round-trip attempted/succeeded)
#  ws_error      ✗    Live: WebSocket 1011 — listed but not truly deployed
#  ws_refused    ✗    Live: can't connect at all
#  empty_output  ✗    HTTP 200 but model returned empty / zero-byte content
#  skip          —    No credentials available
#  error         💥   Unexpected error (timeout, network, etc.)

Status = Literal[
    "functional",
    "reachable",
    "exists",
    "not_found",
    "ws_functional",
    "ws_connected",
    "ws_error",
    "ws_refused",
    "empty_output",
    "skip",
    "error",
]

STATUS_ICON: dict[str, str] = {
    "functional": "✅ FUNCTIONAL",
    "reachable": "🟡 REACHABLE",
    "exists": "🔵 EXISTS",
    "not_found": "❌ NOT FOUND",
    "ws_functional": "✅ LIVE OK",
    "ws_connected": "🟡 LIVE SETUP-ONLY",
    "ws_error": "❌ LIVE WS-1011",
    "ws_refused": "❌ LIVE REFUSED",
    "empty_output": "⚠️  EMPTY OUTPUT",
    "skip": "─  SKIP",
    "error": "💥 ERROR",
}

# Icon-only version for the compact matrix column
STATUS_SHORT: dict[str, str] = {
    "functional": "✅",
    "reachable": "🟡",
    "exists": "🔵",
    "not_found": "❌",
    "ws_functional": "✅",
    "ws_connected": "🟡",
    "ws_error": "❌",
    "ws_refused": "❌",
    "empty_output": "⚠️",
    "skip": "─",
    "error": "💥",
}

# Gemini 3.x preview 模型只在 global 端點提供（2026-04）
# Source: https://cloud.google.com/vertex-ai/generative-ai/docs/start/get-started-with-gemini-3
GLOBAL_ONLY_MODELS: frozenset[str] = frozenset(
    {
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
        "gemini-3-pro-preview",  # 已於 2026-03-26 下架，但 ID 仍會被 redirect 到 3.1
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-tts-preview",
    }
)


@dataclass
class ProbeResult:
    model: str
    platform: str
    capability: str
    status: Status
    http_code: int | None = None
    # Functional verification details
    output_bytes: int = 0  # audio bytes received (TTS/Live)
    output_text: str = ""  # text snippet (LLM)
    note: str = ""


@dataclass
class ProbeConfig:
    models: list[str]
    platforms: list[str]
    capabilities: list[str]
    project: str = ""
    location: str = "us-central1"
    api_key: str = ""
    timeout: float = 20.0
    # True = verify actual output content (default); False = existence-only
    functional: bool = True
    # For Live: True = send a real turn and wait for audio (slower but more thorough)
    live_audio_roundtrip: bool = True


# ── Endpoint resolver ────────────────────────────────────────────────────────


def _resolve_vertex_endpoint(model: str, requested_location: str) -> tuple[str, str]:
    """Return (effective_location, api_host) for a Vertex AI model.

    Gemini 3.x preview 模型強制使用 global 端點。
    URL host 為 'aiplatform.googleapis.com'（不是 'global-aiplatform.googleapis.com'）。
    其他 location 沿用 '{loc}-aiplatform.googleapis.com'。
    """
    if model in GLOBAL_ONLY_MODELS or requested_location == "global":
        return "global", "aiplatform.googleapis.com"
    return requested_location, f"{requested_location}-aiplatform.googleapis.com"


# ── Token helper ──────────────────────────────────────────────────────────────


def _get_vertex_token() -> str:
    """Get ADC access token for Vertex AI. Raises if not configured."""
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        req = google.auth.transport.requests.Request()
        creds.refresh(req)
        token = creds.token  # type: ignore[assignment]
        if not token:
            print("\n❌  Vertex ADC: credentials refreshed but token is None")
            print("    This can happen with AnonymousCredentials or a malformed refresh response.")
            print("    Run: gcloud auth application-default login")
            raise SystemExit(1)
        return token
    except ImportError as exc:
        print(f"\n❌  google-auth 套件未安裝：{exc}")
        print("    修正：uv add google-auth google-auth-httplib2 requests")
        raise SystemExit(1) from exc
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\n❌  Vertex ADC error ({type(exc).__name__}): {exc}")
        print("    Run: gcloud auth application-default login")
        print("    Then: export GCP_PROJECT_ID=<your-project>")
        raise SystemExit(1) from exc


# ── Request bodies ────────────────────────────────────────────────────────────

# LLM: ask for a short reply; use 256 tokens because thinking models (2.5 Pro)
# consume tokens for internal reasoning before producing output text.
# With only 8 tokens, 2.5 Pro exhausts the budget on thinking and returns empty parts.
_LLM_BODY = {
    "contents": [{"role": "user", "parts": [{"text": "Reply with exactly one word: PONG"}]}],
    "generationConfig": {"maxOutputTokens": 256, "temperature": 0.0},
}

# TTS: short text; response audio is base64-decoded and checked for size > 1024 bytes.
# The API may return PCM/L16 or MP3 — we accept any codec; no header check is performed.
_TTS_BODY = {
    "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
    "generationConfig": {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
    },
}

# Live: text turn to send after SETUP_COMPLETE
_LIVE_TURN_MSG = json.dumps(
    {
        "clientContent": {
            "turns": [{"role": "user", "parts": [{"text": "Say the word hello"}]}],
            "turnComplete": True,
        }
    }
)


# ── Content verification helpers ─────────────────────────────────────────────


def _verify_llm_response(body: dict) -> tuple[bool, str]:
    """
    Return (ok, snippet) where ok=True if the response contains non-empty text.

    Gemini response shape: candidates[0].content.parts[N].text
    For thinking models (2.5 Pro), some parts have thought=True and no text;
    we skip those and look for the first part that has actual text content.
    """
    try:
        candidates = body.get("candidates", [])
        if not candidates:
            return False, "no candidates in response"
        finish = candidates[0].get("finishReason", "")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return False, f"no parts (finishReason={finish})"
        # Skip thinking parts (thought=True) — only look at output text parts
        for part in parts:
            if part.get("thought"):
                continue
            text = part.get("text", "")
            if text.strip():
                return True, text.strip()[:40]
        return False, f"all {len(parts)} parts are thinking/empty (finishReason={finish})"
    except Exception as exc:
        print(f"[warn] LLM response parse error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return False, f"parse error: {exc}"


def _verify_tts_response(body: dict) -> tuple[bool, int]:
    """
    Return (ok, byte_count) where ok=True if audio bytes exist and are non-trivially large.

    Gemini TTS response: candidates[0].content.parts[0].inlineData.data (base64)
    The mimeType can be audio/L16 (PCM), audio/mpeg (MP3), audio/wav, etc.
    We accept ANY non-empty audio regardless of encoding — the model decides the format.
    We use byte count (>1024) as a proxy for "real audio" vs a stub/error response.
    """
    try:
        candidates = body.get("candidates", [])
        if not candidates:
            return False, 0
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return False, 0
        inline = parts[0].get("inlineData", {})
        b64 = inline.get("data", "")
        if not b64:
            return False, 0
        audio = base64.b64decode(b64)
        if len(audio) < 1024:
            return False, len(audio)
        # Any non-trivially-sized audio is valid regardless of codec (PCM/L16, MP3, WAV, etc.)
        return True, len(audio)
    except Exception as exc:
        print(f"[warn] TTS parse error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return False, -1  # sentinel: parse error, distinguishable from empty response (0)


# ── REST probes ───────────────────────────────────────────────────────────────


def _extract_error_note(resp: httpx.Response, platform: str) -> str:
    """Extract the error message from a non-200 API response body.

    Falls back to raw text if the body is not JSON (e.g. HTML 502 gateway page).
    """
    try:
        return resp.json().get("error", {}).get("message", "")[:80]
    except Exception as exc:
        print(f"[warn] {platform} error body parse failed: {exc}", file=sys.stderr)
        return resp.text[:80] if resp.text else ""


def _base_status_from_http(code: int) -> tuple[Status, str]:
    """Map HTTP status code to (status, hint) for display in the note field."""
    if code == 200:
        return "reachable", ""  # will be upgraded to "functional" if content checks pass
    if code == 400:
        return "exists", "HTTP 400 — capability params rejected"
    if code == 401:
        return "error", "HTTP 401 Unauthorized — credentials expired or invalid"
    if code == 403:
        return "error", "HTTP 403 Forbidden — check IAM (roles/aiplatform.user) or billing"
    if code == 404:
        return "not_found", ""
    if code == 429:
        return "error", "HTTP 429 Too Many Requests — rate limited"
    if code >= 500:
        return "error", f"HTTP {code} server error"
    return "error", f"HTTP {code}"


async def _probe_vertex_rest(
    model: str,
    capability: str,
    config: ProbeConfig,
    token: str,
) -> ProbeResult:
    """POST to Vertex AI generateContent; verify content if functional=True."""
    effective_loc, api_host = _resolve_vertex_endpoint(model, config.location)
    if effective_loc != config.location:
        print(
            f"    [info] {model}: 自動切換到 global 端點（Gemini 3.x preview 僅在 global 可用）",
            file=sys.stderr,
        )
    url = (
        f"https://{api_host}/v1/projects/{config.project}"
        f"/locations/{effective_loc}/publishers/google/models/{model}:generateContent"
    )
    body = _TTS_BODY if capability == "tts" else _LLM_BODY
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        try:
            resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException:
            return ProbeResult(model, "vertex", capability, "error", note="timeout")
        except Exception as exc:
            return ProbeResult(model, "vertex", capability, "error", note=str(exc)[:60])

    status, hint = _base_status_from_http(resp.status_code)
    note = ""

    # Extract error message for non-200
    if status != "reachable":
        api_note = _extract_error_note(resp, "vertex")
        note = f"{hint} — {api_note}" if (hint and api_note) else (api_note or hint)
        return ProbeResult(model, "vertex", capability, status, resp.status_code, note=note)

    # HTTP 200 — now verify the actual output content
    if not config.functional:
        return ProbeResult(model, "vertex", capability, "reachable", resp.status_code)

    try:
        resp_body = resp.json()
    except Exception as exc:
        print(
            f"[warn] vertex {capability}: HTTP 200 response not valid JSON "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return ProbeResult(
            model,
            "vertex",
            capability,
            "reachable",
            resp.status_code,
            note="could not parse JSON response",
        )

    if capability == "tts":
        ok, byte_count = _verify_tts_response(resp_body)
        if ok:
            return ProbeResult(
                model,
                "vertex",
                capability,
                "functional",
                resp.status_code,
                output_bytes=byte_count,
                note=f"{byte_count:,} audio bytes verified",
            )
        if byte_count == -1:  # parse error sentinel
            return ProbeResult(
                model,
                "vertex",
                capability,
                "error",
                resp.status_code,
                note="TTS response parse error (check stderr for details)",
            )
        return ProbeResult(
            model,
            "vertex",
            capability,
            "empty_output",
            resp.status_code,
            note=f"TTS failed: {byte_count} bytes (need >1024)",
        )
    else:  # llm
        ok, snippet = _verify_llm_response(resp_body)
        if ok:
            return ProbeResult(
                model,
                "vertex",
                capability,
                "functional",
                resp.status_code,
                output_text=snippet,
                note=f'text: "{snippet}"',
            )
        return ProbeResult(
            model, "vertex", capability, "empty_output", resp.status_code, note=snippet
        )


async def _probe_aistudio_rest(
    model: str,
    capability: str,
    config: ProbeConfig,
) -> ProbeResult:
    """POST to Google AI Studio generateContent; verify content if functional=True."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.api_key}"
    )
    body = _TTS_BODY if capability == "tts" else _LLM_BODY

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        try:
            resp = await client.post(url, json=body)
        except httpx.TimeoutException:
            return ProbeResult(model, "aistudio", capability, "error", note="timeout")
        except Exception as exc:
            return ProbeResult(model, "aistudio", capability, "error", note=str(exc)[:60])

    status, hint = _base_status_from_http(resp.status_code)
    note = ""

    if status != "reachable":
        api_note = _extract_error_note(resp, "aistudio")
        note = f"{hint} — {api_note}" if (hint and api_note) else (api_note or hint)
        return ProbeResult(model, "aistudio", capability, status, resp.status_code, note=note)

    if not config.functional:
        return ProbeResult(model, "aistudio", capability, "reachable", resp.status_code)

    try:
        resp_body = resp.json()
    except Exception as exc:
        print(
            f"[warn] aistudio {capability}: HTTP 200 response not valid JSON "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return ProbeResult(
            model,
            "aistudio",
            capability,
            "reachable",
            resp.status_code,
            note="could not parse JSON response",
        )

    if capability == "tts":
        ok, byte_count = _verify_tts_response(resp_body)
        if ok:
            return ProbeResult(
                model,
                "aistudio",
                capability,
                "functional",
                resp.status_code,
                output_bytes=byte_count,
                note=f"{byte_count:,} audio bytes verified",
            )
        if byte_count == -1:  # parse error sentinel
            return ProbeResult(
                model,
                "aistudio",
                capability,
                "error",
                resp.status_code,
                note="TTS response parse error (check stderr for details)",
            )
        return ProbeResult(
            model,
            "aistudio",
            capability,
            "empty_output",
            resp.status_code,
            note=f"TTS failed: {byte_count} bytes (need >1024)",
        )
    else:
        ok, snippet = _verify_llm_response(resp_body)
        if ok:
            return ProbeResult(
                model,
                "aistudio",
                capability,
                "functional",
                resp.status_code,
                output_text=snippet,
                note=f'text: "{snippet}"',
            )
        return ProbeResult(
            model, "aistudio", capability, "empty_output", resp.status_code, note=snippet
        )


# ── WebSocket Live probes ─────────────────────────────────────────────────────


def _classify_ws_exc(exc_str: str) -> tuple[Status, str]:
    """Classify a WebSocket exception into a Status + short note.

    Auth failures (401/429) get explicit branches so they don't fall through to ws_refused.
    The 1011 check is intentionally before auth checks because 1011 is the most common
    failure mode and its error message never contains auth-related strings.
    """
    # 1011 = model listed but not deployed; must check before "server error" substring
    if "1011" in exc_str:
        return "ws_error", "1011 server error (model listed but not deployed for Live)"
    # Auth failures — check before generic "server error" to avoid misclassification
    if "Unauthorized" in exc_str or "HTTP 401" in exc_str:
        return "error", "HTTP 401 Unauthorized — credentials expired or invalid"
    if "HTTP 429" in exc_str or "Too Many Requests" in exc_str:
        return "error", "HTTP 429 Too Many Requests — rate limited"
    if "server error" in exc_str.lower():
        return "ws_error", exc_str[:80]
    if "404" in exc_str or "Not Found" in exc_str:
        return "not_found", exc_str[:80]
    if "403" in exc_str or "Forbidden" in exc_str:
        return "exists", "403 Forbidden — project may lack Live access"
    if "TimeoutError" in exc_str or "timed out" in exc_str.lower():
        return "error", f"timeout: {exc_str[:80]}"
    return "ws_refused", exc_str[:80]


async def _recv_live_audio(ws: object, timeout: float) -> tuple[bool, int]:
    """
    Drain WebSocket messages until we receive audio bytes or timeout.

    Returns (found_audio, byte_count).
    We skip serverContent messages that only contain text (those are thinking turns),
    and we stop at turnComplete.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while (now := loop.time()) < deadline:
        remaining = deadline - now
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))  # type: ignore[attr-defined]
        except TimeoutError:
            break
        try:
            msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            frame_type = "str" if isinstance(raw, str) else f"bytes[{len(raw)}]"  # type: ignore[arg-type]
            print(f"[warn] live recv: non-JSON {frame_type} frame, skipping", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"[warn] live recv frame error ({type(exc).__name__}): {exc}", file=sys.stderr)
            break

        sc = msg.get("serverContent", {})

        # Check for audio parts in modelTurn
        for part in sc.get("modelTurn", {}).get("parts", []):
            b64 = part.get("inlineData", {}).get("data", "")
            if b64:
                try:
                    audio = base64.b64decode(b64)
                    if len(audio) > 0:
                        return True, len(audio)
                except Exception as exc:
                    print(f"[warn] base64 decode failed for audio part: {exc}", file=sys.stderr)

        # If turn is complete and we haven't received audio, give up
        if sc.get("turnComplete"):
            break

    return False, 0


async def _probe_vertex_live(
    model: str,
    config: ProbeConfig,
    token: str,
) -> ProbeResult:
    """
    Vertex AI BidiGenerateContent WebSocket probe.

    Gate 1: WebSocket connects + SETUP_COMPLETE received  → ws_connected
    Gate 2: Send a text turn, receive audio bytes back     → ws_functional
    """
    try:
        import websockets
    except ImportError:
        return ProbeResult(model, "vertex", "live", "skip", note="websockets not installed")

    effective_loc, api_host = _resolve_vertex_endpoint(model, config.location)
    model_path = (
        f"projects/{config.project}/locations/{effective_loc}/publishers/google/models/{model}"
    )
    ws_url = (
        f"wss://{api_host}/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"
    )
    setup_msg = json.dumps(
        {
            "setup": {
                "model": model_path,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
                },
            }
        }
    )

    try:
        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {token}"},
            open_timeout=10,
            close_timeout=5,
        ) as ws:
            # Gate 1: setup handshake
            try:
                await asyncio.wait_for(ws.send(setup_msg), timeout=10.0)
            except TimeoutError:
                return ProbeResult(
                    model, "vertex", "live", "error", note="setup send timeout (10s)"
                )
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except TimeoutError:
                return ProbeResult(
                    model, "vertex", "live", "error", note="setup recv timeout (10s)"
                )

            try:
                msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return ProbeResult(
                    model, "vertex", "live", "error", note=f"setup response not valid JSON: {exc}"
                )

            if "setupComplete" not in msg:
                return ProbeResult(
                    model,
                    "vertex",
                    "live",
                    "ws_connected",
                    note=f"unexpected setup reply: {list(msg.keys())}",
                )

            if not config.live_audio_roundtrip:
                return ProbeResult(
                    model,
                    "vertex",
                    "live",
                    "ws_connected",
                    note="SETUP_COMPLETE (audio round-trip skipped)",
                )

            # Gate 2: send a text turn and wait for audio
            await asyncio.wait_for(ws.send(_LIVE_TURN_MSG), timeout=10.0)
            found_audio, byte_count = await _recv_live_audio(ws, timeout=15.0)

            if found_audio:
                return ProbeResult(
                    model,
                    "vertex",
                    "live",
                    "ws_functional",
                    output_bytes=byte_count,
                    note=f"SETUP_COMPLETE + {byte_count:,} audio bytes received",
                )
            return ProbeResult(
                model,
                "vertex",
                "live",
                "ws_connected",
                note="SETUP_COMPLETE but no audio bytes returned in time",
            )

    except Exception as exc:
        status, note = _classify_ws_exc(str(exc))
        return ProbeResult(model, "vertex", "live", status, note=note)


async def _probe_aistudio_live(
    model: str,
    config: ProbeConfig,
) -> ProbeResult:
    """Google AI Studio BidiGenerateContent WebSocket probe."""
    try:
        import websockets
    except ImportError:
        return ProbeResult(model, "aistudio", "live", "skip", note="websockets not installed")

    ws_url = (
        f"wss://generativelanguage.googleapis.com/ws/"
        f"google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
        f"?key={config.api_key}"
    )
    setup_msg = json.dumps(
        {
            "setup": {
                "model": f"models/{model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
                },
            }
        }
    )

    try:
        async with websockets.connect(ws_url, open_timeout=10, close_timeout=5) as ws:
            try:
                await asyncio.wait_for(ws.send(setup_msg), timeout=10.0)
            except TimeoutError:
                return ProbeResult(
                    model, "aistudio", "live", "error", note="setup send timeout (10s)"
                )
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except TimeoutError:
                return ProbeResult(
                    model, "aistudio", "live", "error", note="setup recv timeout (10s)"
                )

            try:
                msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return ProbeResult(
                    model, "aistudio", "live", "error", note=f"setup response not valid JSON: {exc}"
                )

            if "setupComplete" not in msg:
                return ProbeResult(
                    model,
                    "aistudio",
                    "live",
                    "ws_connected",
                    note=f"unexpected setup reply: {list(msg.keys())}",
                )

            if not config.live_audio_roundtrip:
                return ProbeResult(
                    model,
                    "aistudio",
                    "live",
                    "ws_connected",
                    note="SETUP_COMPLETE (audio round-trip skipped)",
                )

            await asyncio.wait_for(ws.send(_LIVE_TURN_MSG), timeout=10.0)
            found_audio, byte_count = await _recv_live_audio(ws, timeout=15.0)

            if found_audio:
                return ProbeResult(
                    model,
                    "aistudio",
                    "live",
                    "ws_functional",
                    output_bytes=byte_count,
                    note=f"SETUP_COMPLETE + {byte_count:,} audio bytes received",
                )
            return ProbeResult(
                model,
                "aistudio",
                "live",
                "ws_connected",
                note="SETUP_COMPLETE but no audio bytes returned in time",
            )

    except Exception as exc:
        status, note = _classify_ws_exc(str(exc))
        return ProbeResult(model, "aistudio", "live", status, note=note)


# ── Orchestration ─────────────────────────────────────────────────────────────


async def run_probes(config: ProbeConfig) -> list[ProbeResult]:
    results: list[ProbeResult] = []

    vertex_token: str | None = None
    if "vertex" in config.platforms:
        if not config.project:
            print("❌  --project required for Vertex probes")
            raise SystemExit(1)
        print("🔑  Fetching Vertex AI ADC token...")
        vertex_token = _get_vertex_token()
        print("    ✅ Token acquired\n")

    if "aistudio" in config.platforms and not config.api_key:
        print("⚠️   No GEMINI_API_KEY found — AI Studio probes will be skipped")

    async def _tracked(coro: object, model: str, platform: str, cap: str) -> ProbeResult:
        """Wrap a probe coroutine to attach model/platform/capability to any uncaught error.

        Without this, asyncio.gather would surface an exception as a generic ProbeResult
        with unknown fields, losing the context needed to report which probe failed.
        SystemExit and KeyboardInterrupt are re-raised so they terminate the process normally.
        """
        try:
            return await coro  # type: ignore[misc]
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            return ProbeResult(
                model, platform, cap, "error", note=f"{type(exc).__name__}: {str(exc)[:60]}"
            )

    tasks = []
    for model in config.models:
        for platform in config.platforms:
            for cap in config.capabilities:
                if cap == "live":
                    if platform == "vertex" and vertex_token:
                        tasks.append(
                            _tracked(
                                _probe_vertex_live(model, config, vertex_token),
                                model,
                                platform,
                                cap,
                            )
                        )
                    elif platform == "aistudio" and config.api_key:
                        tasks.append(
                            _tracked(_probe_aistudio_live(model, config), model, platform, cap)
                        )
                    else:
                        results.append(
                            ProbeResult(model, platform, cap, "skip", note="no credentials")
                        )
                elif cap in ("llm", "tts"):
                    if platform == "vertex" and vertex_token:
                        tasks.append(
                            _tracked(
                                _probe_vertex_rest(model, cap, config, vertex_token),
                                model,
                                platform,
                                cap,
                            )
                        )
                    elif platform == "aistudio" and config.api_key:
                        tasks.append(
                            _tracked(_probe_aistudio_rest(model, cap, config), model, platform, cap)
                        )
                    else:
                        results.append(
                            ProbeResult(model, platform, cap, "skip", note="no credentials")
                        )

    print(
        f"🔍  Running {len(tasks)} probes (functional={config.functional}, "
        f"live_roundtrip={config.live_audio_roundtrip})...\n"
    )
    probe_results = await asyncio.gather(*tasks)
    results.extend(probe_results)

    return results


# ── Output formatting ─────────────────────────────────────────────────────────


def print_matrix(results: list[ProbeResult]) -> None:
    print("\n" + "=" * 100)
    print("  RESULTS MATRIX")
    print("=" * 100)
    print(f"\n  {'MODEL':<48} {'PLATFORM':<10} {'CAP':<6}  STATUS              DETAIL")
    print("  " + "-" * 96)

    results_sorted = sorted(results, key=lambda r: (r.model, r.platform, r.capability))
    for r in results_sorted:
        icon = STATUS_ICON.get(r.status, "?")
        detail = r.note[:50] if r.note else ""
        print(f"  {r.model:<48} {r.platform:<10} {r.capability:<6}  {icon:<20}  {detail}")

    print("\n" + "=" * 100)
    print("\n  STATUS LEGEND")
    print("  " + "-" * 60)
    legend = [
        ("functional", "✅", "HTTP 200 + valid text/audio output verified"),
        ("reachable", "🟡", "HTTP 200 but output could not be verified"),
        ("exists", "🔵", "HTTP 400 — model is deployed, capability params wrong"),
        ("not_found", "❌", "HTTP 404 — model does NOT exist on this platform"),
        ("ws_functional", "✅", "Live: SETUP_COMPLETE + real audio round-trip confirmed"),
        ("ws_connected", "🟡", "Live: SETUP_COMPLETE only, no audio round-trip"),
        ("ws_error", "❌", "Live: WebSocket 1011 — listed but not deployed for Live"),
        ("ws_refused", "❌", "Live: WebSocket could not connect"),
        ("empty_output", "⚠️", "HTTP 200 but model returned empty content"),
        ("skip", "─", "Skipped — missing credentials"),
        ("error", "💥", "Unexpected error (timeout, network issue)"),
    ]
    for status, _short, desc in legend:
        icon = STATUS_ICON.get(status, "?")
        print(f"  {icon:<22}  {desc}")
    print()


def print_recommendations(results: list[ProbeResult]) -> None:
    print("=" * 100)
    print("  RECOMMENDATIONS")
    print("=" * 100)

    issues: list[ProbeResult] = [
        r
        for r in results
        if r.status
        in (
            "not_found",
            "ws_error",
            "ws_refused",
            "ws_connected",
            "empty_output",
            "exists",
            "error",
        )
    ]

    if not issues:
        print("\n  ✅  All probed models/capabilities are FUNCTIONAL.")
        print("      You can safely use these models in your configuration.\n")
        return

    for r in issues:
        print(f"\n  ⚠️  {r.model}  [{r.platform}/{r.capability}]  →  {STATUS_ICON.get(r.status)}")
        if r.note:
            print(f"      Detail: {r.note}")

        if r.status == "not_found":
            if r.platform == "vertex":
                print("      Fix: this model doesn't exist on Vertex. Try:")
                print("        LLM → gemini-2.5-flash or gemini-2.5-flash-001")
                print("        TTS → gemini-2.5-flash-preview-tts or gemini-3.1-flash-tts-preview")
            else:
                print("      Fix: this model doesn't exist on Google AI Studio.")

        elif r.status == "ws_error":
            print(
                "      Fix: Live WebSocket returns 1011 — model is not truly deployed for Live API."
            )
            print("        → Use gemini-2.5-flash-native-audio-preview-12-2025 (verify separately)")
            print("        → Or wait for this model to exit limited preview / check allowlist.")

        elif r.status == "exists":
            print(
                "      Note: model is deployed (HTTP 400) but this capability may be unsupported."
            )
            print("        Check the model's supported generation methods in the API docs.")

        elif r.status == "empty_output":
            print("      Warning: model responded HTTP 200 but returned empty content.")
            print("        This is worse than a 404 — silent failure in production.")
            print("        → Do NOT use this model/capability combination.")

        elif r.status == "ws_connected":
            print(
                "      Note: Live handshake succeeded (SETUP_COMPLETE) but no audio was returned."
            )
            print("        → Confirm with a manual test before using in production.")

    print()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Two-tier Gemini model verification: existence + functional output check"
    )
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated model names, e.g. gemini-2.5-flash,gemini-3.1-flash-tts-preview",
    )
    parser.add_argument(
        "--platforms",
        default="vertex,aistudio",
        help="Comma-separated: vertex, aistudio  (default: both)",
    )
    parser.add_argument(
        "--capabilities",
        default="llm,tts,live",
        help="Comma-separated: llm, tts, live  (default: all)",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT_ID", ""),
        help="GCP project ID (or set GCP_PROJECT_ID env var)",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("VERTEX_AI_LOCATION", "us-central1"),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GEMINI_API_KEY", ""),
        help="Google AI Studio API key (or set GEMINI_API_KEY env var)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-probe HTTP/WS timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--no-functional",
        action="store_true",
        help="Skip response content verification — existence check only (faster)",
    )
    parser.add_argument(
        "--no-live-roundtrip",
        action="store_true",
        help="For Live probes: only verify SETUP_COMPLETE, skip audio round-trip (faster)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    config = ProbeConfig(
        models=[m.strip() for m in args.models.split(",") if m.strip()],
        platforms=[p.strip() for p in args.platforms.split(",") if p.strip()],
        capabilities=[c.strip() for c in args.capabilities.split(",") if c.strip()],
        project=args.project,
        location=args.location,
        api_key=args.api_key,
        timeout=args.timeout,
        functional=not args.no_functional,
        live_audio_roundtrip=not args.no_live_roundtrip,
    )

    print("\n🚀  verify-gemini-models  (two-tier: existence + functional)")
    print(f"    Models:         {', '.join(config.models)}")
    print(f"    Platforms:      {', '.join(config.platforms)}")
    print(f"    Capabilities:   {', '.join(config.capabilities)}")
    print(f"    Project:        {config.project or '(not set)'}")
    print(f"    Location:       {config.location}")
    print(f"    Functional:     {config.functional}")
    print(f"    Live roundtrip: {config.live_audio_roundtrip}\n")

    results = await run_probes(config)

    if args.json:
        import dataclasses

        print(json.dumps([dataclasses.asdict(r) for r in results], indent=2))
        return

    print_matrix(results)
    print_recommendations(results)


if __name__ == "__main__":
    asyncio.run(main())
