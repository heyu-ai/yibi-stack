## ADDED Requirements

### Requirement: Report-only remains the default code review path

The pr-review-cycle and pr-cycle-deep runbooks SHALL keep the report-only /code-review invocation as the default behavior of their code review step. The auto-apply cleanup path SHALL be documented as optional and SHALL run only on explicit user opt-in.

#### Scenario: Default run without opt-in

- **WHEN** a lifecycle run reaches the code review step and the user has not explicitly requested cleanup auto-apply
- **THEN** the agent runs /code-review in report-only mode and this step makes no working-tree modification

### Requirement: Opt-in auto-apply cleanups subsection

The pr-review-cycle and pr-cycle-deep runbooks SHALL each contain an "Auto-apply cleanups (optional)" subsection immediately after their report-only code review block. The subsection SHALL name both tools with their division of labor -- /code-review --fix detects correctness bugs and can auto-apply findings, while /simplify applies cleanup-only fixes (reuse, simplification, efficiency) without bug detection -- and SHALL state that any resulting working-tree changes MUST go through the existing diff-review and commit flow before push.

#### Scenario: User opts in to auto-apply

- **WHEN** the user explicitly requests auto-applied cleanups during the code review step
- **THEN** the agent invokes /code-review --fix or /simplify according to the documented division of labor and routes the resulting working-tree changes through the existing diff-review and commit flow before any push

#### Scenario: Tool division of labor stated

- **WHEN** a reader consults the subsection in either runbook
- **THEN** the subsection states that /code-review --fix detects correctness bugs and can auto-apply findings, and that /simplify applies cleanup-only fixes without bug detection

#### Scenario: Wording consistent across both runbooks

- **WHEN** the subsections in pr-review-cycle and pr-cycle-deep are compared
- **THEN** both state the same default (report-only), the same opt-in condition, and the same commit-flow requirement
