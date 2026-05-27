---
name: qa-test-design
type: know
scope: global
description: >
  Senior QA test design techniques using structured methods to produce high-quality test cases.
  Trigger contexts: user mentions "design test cases", "write test cases", "analyze test scope",
  "review AI-generated cases", "QA test design", "how to test this feature".
  Applies six core techniques: Equivalence Partitioning, Boundary Value Analysis, Decision Table,
  State Transition, Pairwise / Combinatorial Testing, and Risk-Based Testing.
  Produces structured test case tables and coverage analysis.
  Also triggers when user says "help me think through how to test this",
  "what should I watch out for in this feature", "testing strategy",
  "help me review these test cases".
  Must trigger when user pastes a requirements spec, User Story, AC, or API doc
  and asks for test scope analysis.
---

# QA Test Design Skill

## Human Entry Point

This skill is the human-facing interface for QA test design.
For programmatic invocation by spectra-amplifier Step 2a, use the `sdd:qa-test-designer`
Task subagent instead.

**Full methodology**: Read `plugins/sdd/skills/qa-test-design/methodology.md` for the
complete six-technique guide, technique selection decision logic, blind spots checklist,
AI-generated case review workflow, and test case output standard.

---

## Quick Start

1. Read `plugins/sdd/skills/qa-test-design/methodology.md`
2. Receive the requirement (User Story, AC, Gherkin scenarios, or verbal description)
3. Select technique combination using the decision logic in methodology.md
4. Build "expected coverage list" BEFORE generating test cases
5. Generate TC table + Coverage Analysis (formats in methodology.md)

---

## Technique Quick Reference

| Scenario | Recommended Technique |
|----------|-----------------------|
| Single field with a defined valid range | Equivalence Partitioning + Boundary Value |
| Multi-condition rules (discounts, permissions, approvals) | Decision Table |
| Objects with state (orders, accounts, tickets) | State Transition |
| Cross-browser/environment/configuration compatibility | Pairwise / Combinatorial Testing |
| Limited time, prioritization needed | Risk-Based + other techniques |
| Complex business system (all of the above apply) | Risk-Based first, then combine techniques per area |
| AI-generated cases need review | Build coverage list first, then Gap Analysis |
| User provides User Story / AC | Extract conditions from ACs, select techniques, produce cases |

---

## TC-ID Convention

Format: `[Feature-Abbrev]-[Technique-Abbrev]-[Seq]`, e.g. `LOGIN-BVA-001`

Technique abbreviations: EP / BVA / DT / ST / PW / RB

> **Note**: `ST` here means State Transition (ISTQB standard). In spectra-amplifier,
> smoke tests use `SMK-NNN` (not `ST-NNN`) to avoid this collision.
