"""D11 scanner：Context / Token Economy（機械分 8）。

所有數字為字元估計（非精準 token 計量）。
"""

import contextlib
import os
import re
from collections import Counter
from pathlib import Path

from ..models import MechanicalFinding

D11_MAX = 8
_ALWAYS_ON_WARN_THRESHOLD = 20000
_ALWAYS_ON_OK_THRESHOLD = 5000
_PD_WARN_THRESHOLD = 0.3
_PD_OK_THRESHOLD = 0.5
_OVERLAP_WARN_COUNT = 3
_EFFORT_BODY_THRESHOLD = 2000
_MAX_OVERLAP_DISPLAY = 5

_STOPWORDS_EN = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "in",
        "of",
        "to",
        "is",
        "are",
        "be",
        "for",
        "on",
        "with",
        "this",
        "that",
        "it",
        "at",
        "as",
        "by",
        "from",
        "has",
        "have",
        "had",
        "not",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "if",
        "we",
        "they",
        "you",
        "he",
        "she",
        "its",
        "i",
        "was",
        "were",
        "been",
        "being",
        "into",
        "out",
        "up",
        "about",
        "than",
        "then",
        "but",
        "so",
        "their",
        "there",
        "when",
        "which",
        "who",
        "how",
        "can",
        "also",
        "use",
        "used",
    ]
)
_STOPWORDS_ZH = frozenset(
    [
        "的",
        "是",
        "在",
        "了",
        "有",
        "和",
        "不",
        "與",
        "為",
        "對",
        "到",
        "要",
        "可以",
        "如果",
        "就",
        "但",
        "也",
        "會",
        "這",
        "那",
        "個",
        "之",
        "以",
        "及",
    ]
)
_STOPWORDS = _STOPWORDS_EN | _STOPWORDS_ZH

_DISCLAIMER = "字元估計（非精準 token 計量）"


def _read_chars(path: Path) -> int:
    """安全讀取檔案字元數。"""
    try:
        return len(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _collect_always_on_chars(target_dir: Path) -> tuple[int, list[str]]:
    """計算 always-on context 字元數估計。

    來源：CLAUDE.md + .claude/rules/*.md + .claude/memory/*.md
    回傳 (char_count, detail_findings)。
    """
    findings: list[str] = []
    total = 0

    claude_md = target_dir / "CLAUDE.md"
    if claude_md.is_file():
        n = _read_chars(claude_md)
        total += n
        findings.append(f"CLAUDE.md: {n} chars")

    rules_dir = target_dir / ".claude" / "rules"
    if rules_dir.is_dir():
        rule_chars = 0
        rule_count = 0
        for f in rules_dir.iterdir():
            if f.suffix == ".md" and f.is_file():
                rule_chars += _read_chars(f)
                rule_count += 1
        if rule_count:
            total += rule_chars
            findings.append(f".claude/rules/ ({rule_count} files): {rule_chars} chars")

    memory_dir = target_dir / ".claude" / "memory"
    if memory_dir.is_dir():
        mem_chars = 0
        mem_count = 0
        for f in memory_dir.iterdir():
            if f.suffix == ".md" and f.is_file():
                mem_chars += _read_chars(f)
                mem_count += 1
        if mem_count:
            total += mem_chars
            findings.append(f".claude/memory/ ({mem_count} files): {mem_chars} chars")

    return total, findings


def _collect_on_demand_chars(target_dir: Path) -> tuple[int, list[str]]:
    """計算 on-demand（按需載入）字元數估計。

    來源：skills/ 或 .claude/skills/ 下所有 SKILL.md 的 body（frontmatter 之後）。
    回傳 (char_count, detail_findings)。
    """
    findings: list[str] = []
    total = 0

    skill_dirs = [target_dir / "skills", target_dir / ".claude" / "skills"]
    found_skills: list[Path] = []

    for skill_root in skill_dirs:
        if not skill_root.is_dir():
            continue
        for root, _, files in os.walk(skill_root, followlinks=True):
            if "SKILL.md" in files:
                found_skills.append(Path(root) / "SKILL.md")

    for skill_md in found_skills:
        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # body = content after second "---" separator (strip leading newline)
        parts = content.split("---", 2)
        body = parts[2].lstrip("\n") if len(parts) >= 3 else content
        total += len(body)

    if found_skills:
        findings.append(f"skills/ body ({len(found_skills)} SKILL.md files): {total} chars")

    return total, findings


def _tokenize(text: str) -> list[str]:
    """簡單分詞：英文小寫詞 + 中文字符片段，排除停用詞與短詞。"""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z_0-9-]{2,}|[一-鿿]{2,}", text)
    return [t.lower() if t.isascii() else t for t in tokens if t.lower() not in _STOPWORDS]


def _detect_overlap_words(claude_md_path: Path, rules_dir: Path) -> list[str]:
    """偵測 CLAUDE.md 與 rules 之間的高頻詞重疊（TF-based，排除停用詞）。

    回傳重疊詞清單（≤ _MAX_OVERLAP_DISPLAY 個）。
    """
    try:
        claude_text = claude_md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    if not rules_dir.is_dir():
        return []

    rules_text_parts: list[str] = []
    for f in rules_dir.iterdir():
        if f.suffix == ".md" and f.is_file():
            with contextlib.suppress(OSError):
                rules_text_parts.append(f.read_text(encoding="utf-8", errors="replace"))

    if not rules_text_parts:
        return []

    rules_text = " ".join(rules_text_parts)
    claude_freq = Counter(_tokenize(claude_text))
    rules_freq = Counter(_tokenize(rules_text))

    # 高頻詞：在各自文本中出現 ≥ 3 次
    claude_high = {w for w, c in claude_freq.items() if c >= 3}
    rules_high = {w for w, c in rules_freq.items() if c >= 3}

    overlap = claude_high & rules_high
    # 依兩者出現次數之乘積排序（最顯著的重疊詞優先）
    sorted_overlap = sorted(overlap, key=lambda w: claude_freq[w] * rules_freq[w], reverse=True)
    return sorted_overlap[:_MAX_OVERLAP_DISPLAY]


def _get_skill_body_length(skill_md: Path) -> int:
    """回傳 SKILL.md body 部分字元數（frontmatter 之後，去除緊接的換行符）。"""
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    parts = content.split("---", 2)
    body = parts[2].lstrip("\n") if len(parts) >= 3 else content
    return len(body)


def _has_effort_frontmatter(skill_md: Path) -> bool:
    """判斷 SKILL.md frontmatter 是否含 effort: 欄位。"""
    try:
        lines: list[str] = []
        dash_count = 0
        with skill_md.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line)
                if line.strip() == "---":
                    dash_count += 1
                    if dash_count == 2:
                        break
    except OSError:
        return False
    if dash_count < 2:
        return False
    parts = "".join(lines).split("---", 2)
    if len(parts) < 3:
        return False
    return bool(re.search(r"^effort:", parts[1], re.MULTILINE))


def _check_effort_alignment(target_dir: Path) -> list[str]:
    """偵測 body > threshold 但缺 effort: frontmatter 的 SKILL.md。

    回傳缺失 effort 的 skill 名稱列表（kebab-case slug）。
    """
    missing: list[str] = []
    skill_dirs = [target_dir / "skills", target_dir / ".claude" / "skills"]

    for skill_root in skill_dirs:
        if not skill_root.is_dir():
            continue
        for root, _, files in os.walk(skill_root, followlinks=True):
            if "SKILL.md" not in files:
                continue
            skill_md = Path(root) / "SKILL.md"
            if _get_skill_body_length(
                skill_md
            ) > _EFFORT_BODY_THRESHOLD and not _has_effort_frontmatter(skill_md):
                missing.append(Path(root).name)

    return missing


def _always_on_score_adjustment(chars: int) -> int:
    """計算 always-on chars 對應的分數調整（邊際遞減懲罰）。"""
    if chars <= _ALWAYS_ON_OK_THRESHOLD:
        return 3
    if chars <= _ALWAYS_ON_WARN_THRESHOLD:
        return 1
    if chars <= 25000:
        return -1
    if chars <= 30000:
        return -2
    return -3


def scan_token_economy(target_dir: Path) -> MechanicalFinding:
    """D11：Context / Token Economy 靜態 proxy 掃描。

    注意：所有數字為字元估計（非精準 token 計量）。
    """
    findings: list[str] = []
    extra: dict[str, list[str]] = {}
    score = 0

    # --- always-on chars ---
    always_on_chars, always_on_detail = _collect_always_on_chars(target_dir)
    score_adj = _always_on_score_adjustment(always_on_chars)
    score += score_adj

    if always_on_chars <= _ALWAYS_ON_OK_THRESHOLD:
        findings.append(f"OK always-on context: {always_on_chars} chars（{_DISCLAIMER}）")
    elif always_on_chars < _ALWAYS_ON_WARN_THRESHOLD:
        findings.append(
            f"always-on context: {always_on_chars} chars "
            f"（{_ALWAYS_ON_OK_THRESHOLD}–{_ALWAYS_ON_WARN_THRESHOLD} 範圍，{_DISCLAIMER}）"
        )
    else:
        findings.append(
            f"WARN always-on context: {always_on_chars} chars "
            f"（上閾值 {_ALWAYS_ON_WARN_THRESHOLD}，{_DISCLAIMER}）"
        )
    findings.extend(always_on_detail)

    extra["always_on_chars"] = [str(always_on_chars)]

    # --- on-demand chars + progressive-disclosure ratio ---
    on_demand_chars, on_demand_detail = _collect_on_demand_chars(target_dir)
    total_chars = always_on_chars + on_demand_chars
    extra["on_demand_chars"] = [str(on_demand_chars)]
    extra["total_chars"] = [str(total_chars)]

    ratio = on_demand_chars / total_chars if total_chars > 0 else 0.0

    if ratio >= _PD_OK_THRESHOLD:
        score += 2
        findings.append(f"OK progressive-disclosure: on-demand 比例 {ratio:.0%}（≥50%）")
    elif ratio >= _PD_WARN_THRESHOLD:
        score += 1
        findings.append(f"progressive-disclosure 比例 {ratio:.0%}（30–49%，建議提升至 ≥50%）")
    else:
        findings.append(
            f"WARN progressive-disclosure 比例過低: {ratio:.0%}"
            "（< 30%，建議將更多內容移為 on-demand skill body）"
        )

    findings.extend(on_demand_detail)

    # --- CLAUDE.md ↔ rules overlap ---
    claude_md = target_dir / "CLAUDE.md"
    rules_dir = target_dir / ".claude" / "rules"
    overlap_words = _detect_overlap_words(claude_md, rules_dir)
    extra["overlap_words"] = overlap_words

    if len(overlap_words) >= _OVERLAP_WARN_COUNT:
        findings.append(
            f"WARN CLAUDE.md↔rules 重疊: 共同高頻詞 {overlap_words}（建議整併冗餘內容）"
        )
    else:
        score += 2
        findings.append("OK no CLAUDE.md↔rules redundancy detected")

    # --- effort alignment ---
    missing_effort = _check_effort_alignment(target_dir)
    extra["effort_missing_skills"] = missing_effort

    if missing_effort:
        for skill_name in missing_effort[:3]:
            findings.append(
                f"WARN effort 未設定: skill '{skill_name}' body > {_EFFORT_BODY_THRESHOLD} chars，"
                f"建議設定 effort: frontmatter"
            )
        if len(missing_effort) > 3:
            findings.append(f"（另有 {len(missing_effort) - 3} 個 skill 同樣缺少 effort:）")
    else:
        score += 1
        findings.append("OK effort alignment: 所有長 skill 均已設定 effort: frontmatter")

    # clamp to [0, D11_MAX]
    score = max(0, min(score, D11_MAX))

    return MechanicalFinding(
        dimension="D11",
        label="Context / Token Economy",
        score=score,
        max_score=D11_MAX,
        findings=findings,
        extra=extra,
    )
