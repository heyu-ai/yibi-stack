"""Artifact 草稿生成器：透過 Claude Code CLI 為 friction cluster 生成預防性規則。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
import uuid

from .models import (
    FRICTION_TO_ARTIFACT,
    ArtifactProposal,
    ArtifactType,
    FrictionCluster,
    NightlyAgentConfig,
)

# 單次草擬的 subprocess 逾時（秒）；多個 cluster 串行呼叫，須遠低於 job timeout。
_DRAFT_TIMEOUT_SECONDS = 180

# ---------------------------------------------------------------------------
# System prompts per artifact type
# ---------------------------------------------------------------------------

_HOOKIFY_SYSTEM = """\
You are a Claude Code automation expert. Your task is to write a Python PreToolUse hook script
that prevents a specific class of bash command errors. The hook must:
1. Read JSON from stdin (Claude Code hook payload format)
2. Check for the problematic pattern in tool_input.command
3. If found: print a clear error message to stderr and exit with code 2
4. If not found: exit with code 0 (allow)

Output ONLY a valid Python script. No markdown fences, no explanation.
The script must:
- Handle invalid JSON gracefully (exit 0 on parse error)
- Be focused and specific (not a general catch-all)
- Include a clear, actionable error message with a fix suggestion
"""

_CLAUDE_MD_SYSTEM = """\
You are a documentation expert for Claude Code project workflows. Your task is to write a
Gotcha entry for a CLAUDE.md file that prevents a specific class of recurring errors.

Format: A bullet point entry using this template:
- **<Concise title>**: <One sentence describing the problem and when it occurs>.
  Fix: <Concrete action to avoid it>.

Rules:
- Be specific, not generic (name the exact command, file, or pattern involved)
- Include a concrete fix, not vague advice
- Keep under 3 sentences total
- Output ONLY the bullet point, nothing else
"""

_SKILL_UPDATE_SYSTEM = """\
You are a technical writer for Claude Code skill documentation. Your task is to write a
new section (2-4 bullet points) to add to an existing SKILL.md runbook that addresses
a recurring friction pattern.

Format:
## Common Pitfall: <Title>

- **Symptom**: <what the user/agent sees>
- **Cause**: <why it happens>
- **Fix**: `<concrete command or action>`

Output ONLY the markdown section, nothing else.
"""

_SYSTEM_PROMPTS: dict[ArtifactType, str] = {
    ArtifactType.HOOKIFY_RULE: _HOOKIFY_SYSTEM,
    ArtifactType.CLAUDE_MD_GOTCHA: _CLAUDE_MD_SYSTEM,
    ArtifactType.SKILL_UPDATE: _SKILL_UPDATE_SYSTEM,
}

# ---------------------------------------------------------------------------
# Target file mapping
# ---------------------------------------------------------------------------

_TARGET_FILES: dict[ArtifactType, str] = {
    ArtifactType.HOOKIFY_RULE: ".claude/hooks/nightly/{slug}.py",
    ArtifactType.CLAUDE_MD_GOTCHA: "CLAUDE.md",
    ArtifactType.SKILL_UPDATE: "skills/{skill}/SKILL.md",
}


def _cluster_user_prompt(cluster: FrictionCluster) -> str:
    snippets = "\n\n".join(
        f"Event {i + 1} [{e.timestamp[:19]}]:\n"
        f"  Description: {e.description}\n  Snippet: {e.raw_text[:300]}"
        for i, e in enumerate(cluster.events[:5])
    )
    return (
        f"Friction type: {cluster.friction_type}\n"
        f"Occurrences: {cluster.count}\n"
        f"Common keywords: {', '.join(cluster.common_keywords[:8])}\n\n"
        f"Example friction events:\n{snippets}"
    )


def _make_slug(cluster: FrictionCluster) -> str:
    """Generate a filesystem-safe slug from cluster keywords."""
    kws = cluster.common_keywords[:3]
    slug = "-".join(re.sub(r"[^a-z0-9]", "", k.lower()) for k in kws if k)
    return slug or cluster.friction_type.replace("_", "-")


def _resolve_target_file(artifact_type: ArtifactType, cluster: FrictionCluster) -> str:
    template = _TARGET_FILES[artifact_type]
    slug = _make_slug(cluster)
    # For skill updates, try to guess the relevant skill from keywords
    skill = "nightly-agent"
    if "worktree" in cluster.common_keywords:
        skill = "newjob"
    elif "bash" in cluster.common_keywords or "ap2" in cluster.common_keywords:
        skill = "bash-hygiene-audit"
    return template.format(slug=slug, skill=skill)


class ArtifactDrafter:
    """透過 Claude Code CLI（headless）草擬預防性 artifacts，使用本機訂閱。"""

    def __init__(self, config: NightlyAgentConfig) -> None:
        self.config = config

    def _resolve_claude_bin(self) -> str:
        """解析 claude CLI 路徑；launchd PATH 精簡，不能假設它在 PATH。"""
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        if not os.path.isfile(claude_bin):
            raise RuntimeError(
                f"找不到 claude CLI（{claude_bin}）；nightly-agent 草擬需要 Claude Code（訂閱）"
            )
        return claude_bin

    def draft(self, cluster: FrictionCluster) -> ArtifactProposal:
        """為單一 cluster 草擬 ArtifactProposal。"""
        artifact_type = FRICTION_TO_ARTIFACT.get(
            cluster.friction_type, ArtifactType.CLAUDE_MD_GOTCHA
        )
        system_prompt = _SYSTEM_PROMPTS[artifact_type]
        user_prompt = _cluster_user_prompt(cluster)

        try:
            content = self._call_api(system_prompt, user_prompt)
        except Exception as e:
            raise RuntimeError(f"草擬 artifact 失敗（cluster {cluster.id}）：{e}") from e

        target_file = _resolve_target_file(artifact_type, cluster)
        title = self._extract_title(content, artifact_type, cluster)

        return ArtifactProposal(
            id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            target_file=target_file,
            source_session_ids=cluster.source_session_ids,
            friction_descriptions=[e.description for e in cluster.events],
        )

    def _call_api(self, system: str, user: str) -> str:
        """以 Claude Code CLI（headless `--print`）草擬，使用訂閱而非 ANTHROPIC_API_KEY。"""
        claude_bin = self._resolve_claude_bin()
        try:
            result = subprocess.run(  # nosec B603
                [
                    claude_bin,
                    "--print",
                    "--model",
                    self.config.draft_model,
                    "--system-prompt",
                    system,
                    user,
                ],
                capture_output=True,
                text=True,
                timeout=_DRAFT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI 草擬逾時（{_DRAFT_TIMEOUT_SECONDS}s）") from e
        except OSError as e:
            raise RuntimeError(f"claude CLI 執行失敗：{e}") from e
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI 回傳非零（exit {result.returncode}）：{result.stderr.strip()[:300]}"
            )
        content = result.stdout.strip()
        if not content:
            raise RuntimeError("claude CLI 回傳空 stdout")
        return content

    def _extract_title(
        self, content: str, artifact_type: ArtifactType, cluster: FrictionCluster
    ) -> str:
        if artifact_type == ArtifactType.CLAUDE_MD_GOTCHA:
            # Extract bold title from "- **Title**: ..."
            m = re.search(r"\*\*([^*]+)\*\*", content)
            if m:
                return m.group(1)
        elif artifact_type == ArtifactType.SKILL_UPDATE:
            m = re.search(r"##\s+Common Pitfall:\s*(.+)", content)
            if m:
                return m.group(1).strip()
        elif artifact_type == ArtifactType.HOOKIFY_RULE:
            # Use friction type + slug as title
            slug = _make_slug(cluster)
            return f"hookify-rule: {cluster.friction_type} ({slug})"
        kws = " ".join(cluster.common_keywords[:3])
        return f"{cluster.friction_type}: {kws}"
