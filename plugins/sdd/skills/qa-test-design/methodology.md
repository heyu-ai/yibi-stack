# QA Test Design Methodology

Single source of truth for QA test design techniques. Both `SKILL.md` (human entry) and
`plugins/sdd/agents/qa-test-designer.md` (programmatic entry) reference this document.
When updating methodology, update this file then sync the inline copy in `qa-test-designer.md`.

---

## Core Philosophy

> **Don't guess test cases by instinct — derive them with structured methods.**

AI can quickly generate large numbers of test cases, but tends to miss boundary conditions
and cross-logic scenarios.
The value of a senior QA engineer is: first build a "filter" using technique frameworks,
then compare against AI output — identifying what is covered and what critical paths were
never considered.

---

## Six Core Testing Techniques

### 1. Equivalence Partitioning

**Purpose**: Reduce test volume by avoiding repetitive testing of values with the same
characteristics.

**Steps**:

1. Identify all input fields and environmental conditions
2. Divide the value domain into groups by "valid / invalid"
3. Select one representative value from each group
4. Pay special attention: empty values, null, special characters, and extreme lengths
   are each their own equivalence class

**Output Format**:

```text
| Field | Category | Valid/Invalid | Value Range | Sample Value | Expected Result |
```

**Applicable Scenarios**: form validation, API parameters, data imports, search filters

---

### 2. Boundary Value Analysis

**Purpose**: Find "off-by-one" boundary bugs; usually used together with Equivalence
Partitioning.

**Fixed Test Points Formula**:

- `lower boundary - 1` (just invalid)
- `lower boundary` (just valid)
- `upper boundary` (just valid)
- `upper boundary + 1` (just invalid)
- If there is a midpoint constraint, also test `mid - 1`, `mid`, `mid + 1`

**Common Blind Spots**:

- Date boundaries: month-end/month-start, leap year 2/29, year-end crossover, timezone
- Quantity boundaries: 0 items, 1 item, exactly at capacity, exceeding the limit
- String boundaries: empty string, 1 character, max length, max length + 1
- Amount boundaries: 0, negative values, decimal precision (0.001 vs 0.01)
- Collection boundaries: empty list, single element, pagination threshold

**Output Format**:

```text
| Field | Test Point | Input Value | Expected Result |
```

**Applicable Scenarios**: numeric ranges, date intervals, character lengths, amount limits,
pagination

---

### 3. Decision Table Testing

**Purpose**: Multi-condition combination logic coverage — ensures every IF-AND combination
is tested.

**Steps**:

1. List all "conditions" that affect the result
2. List all possible "actions / results"
3. Enumerate condition combinations (N Y/N conditions -> at most 2^N combinations)
4. Merge columns with the same result (reduce redundancy)
5. Mark impossible combinations with `-`
6. Each valid column corresponds to one test case

**Output Format**:

```text
| Condition/Rule | R1  | R2  | R3  | R4  |
|----------------|-----|-----|-----|-----|
| Condition A    |  Y  |  Y  |  N  |  N  |
| Condition B    |  Y  |  N  |  Y  |  N  |
| **Action**     | Result1 | Result2 | Result3 | Result4 |
```

**Applicable Scenarios**: discount rules, permission control, promotion conditions,
complex business logic, approval rules

**Example**: High-Speed Rail Early-Bird Discount (conditions: advance days, quota, ticket type):

| Condition | R1 | R2 | R3 | R4 | R5 | R6 |
|-----------|:--:|:--:|:--:|:--:|:--:|:--:|
| >= 3 days in advance | Y | Y | Y | Y | N | N |
| Quota available | Y | Y | N | N | - | - |
| Full-price ticket | Y | N | Y | N | - | - |
| **Discount Result** | **30% off** | **20% off** | **No discount** | **No discount** | **No discount** | **No discount** |

---

### 4. State Transition Testing

**Purpose**: Test the validity and completeness of state transitions in an object's lifecycle.

**Steps**:

1. List all "states", including initial and terminal states
2. List all "events" that trigger transitions
3. Draw a state transition diagram or table
4. Test three aspects:
   - Valid transitions -- correct event triggers the correct next state
   - Invalid transitions -- transitions that should not occur are correctly blocked
   - Missing paths -- every state x every event cross-product is defined

**Output Format (State Transition Table)**:

```text
| Current State    | Event             | Next State   | Expected Result    |
|-----------------|-------------------|--------------|-------------------|
| Awaiting Payment | Payment succeeded | Paid         | Success            |
| Completed        | Re-order          | -            | Not allowed        |
```

**Applicable Scenarios**: order workflows, account status, approval flows, ticketing
systems, game character states

---

### 5. Pairwise / Combinatorial Testing

**Purpose**: When there are many parameters (>=3) each with multiple values, full
combinations grow explosively. Pairwise guarantees that every combination of any two
parameters appears at least once, achieving high coverage with minimal test cases.

**When to Use (instead of Decision Table)**:

- Decision Table: suited for few conditions (2-4 Y/N conditions) with explicit rules
- Pairwise: suited for many parameters (>=3) with multiple values and no clear rules
- Rule of thumb: if full combinations > 30, consider Pairwise

**Steps**:

1. List all parameters and their possible values
2. Build a parameter table
3. Use a Pairwise algorithm (e.g., OATS, AllPairs) to generate the minimum covering set
4. Sanity-check the generated result: are there any impossible combinations to exclude?

**Output Format**:

```text
| TC# | Param A | Param B | Param C | Param D | Expected Result |
```

**Applicable Scenarios**: cross-browser/device compatibility, configuration combinations,
environment combinations, multi-field filters

---

### 6. Risk-Based Testing

**Purpose**: When resources are limited, prioritize testing by risk level to ensure the
most critical areas are covered first.
This is not a standalone technique for generating test cases, but a method to rank the
output of other techniques by priority.

**Steps**:

1. List all feature areas or test items
2. Evaluate two dimensions:
   - **Impact**: how severe is the failure? (data loss > UI misalignment)
   - **Likelihood**: how likely is failure? (new feature > stable module,
     complex logic > simple CRUD)
3. Calculate risk score = Impact x Likelihood
4. Sort by risk score; determine testing depth:
   - High risk: full testing (multiple technique combinations)
   - Medium risk: focused testing (Equivalence Partitioning + Boundary Value)
   - Low risk: basic smoke testing

**Output Format (Risk Matrix)**:

```text
| Feature Area | Impact (1-5) | Likelihood (1-5) | Risk Score | Priority | Recommended Depth |
```

**Applicable Scenarios**: testing strategy planning, Sprint scope decisions,
trade-offs under time pressure

---

## Technique Selection Decision Logic

When a requirement arrives, judge in this order — techniques are usually combined:

```text
Requirement arrives
  |
  +-- Ask: Is there a "state -> event -> new state" lifecycle?
  |   +-- Yes -> State Transition (backbone); then examine details within each state
  |
  +-- Ask: Do multiple conditions cross-determine the result?
  |   +-- <= 4 conditions, mostly Y/N -> Decision Table
  |   +-- >= 3 parameters, multiple values -> Pairwise
  |
  +-- Ask: Are there input fields that need validation?
  |   +-- Yes -> Equivalence Partitioning + Boundary Value (almost always used together)
  |
  +-- Ask: Is test time limited and prioritization needed?
      +-- Yes -> Risk matrix first; then decide testing depth per area
```

**Combination Example**: E-commerce order system

- State Transition: order lifecycle (Create -> Pay -> Ship -> Complete -> Return)
- Decision Table: return condition logic (over time limit? opened? special category?)
- Equivalence Partitioning + Boundary Value: amount field, quantity field
- Pairwise: checkout environment combinations (Browser x Payment x Delivery x Device)
- Risk-Based: prioritize payment and returns (high risk); UI tweaks go last

---

## Common Blind Spots Checklist

After designing test cases, run through this checklist to confirm nothing is missed:

**Data**:

- Empty value / null / undefined handling
- Special characters (emoji, CJK, RTL text, SQL injection strings)
- Extremely long input, very large files
- Duplicate data, duplicate submissions
- Concurrent operations (two users modifying simultaneously)

**Process**:

- Cancel / go back / page refresh mid-flow
- Recovery after network disconnection
- Operations when session has expired
- Error handling when permission is insufficient

**Environment**:

- Timezone differences
- Language switching (especially layout after switching between Chinese and English)
- Different screen sizes / mobile devices

**Business**:

- Are there default values? Are the defaults reasonable?
- Upstream and downstream system cascade effects
- Historical data compatibility

---

## AI-Generated Case Review Workflow

```text
Step 1: Receive the requirement (document, User Story, AC, or verbal description)
   |
Step 2: Requirement clarification -- actively ask for:
   - Input field list and value range constraints for each
   - Business rules and condition combinations
   - Object state flow (if any)
   - Known high-risk areas
   |
Step 3: Select technique combination (refer to decision logic above)
   |
Step 4: Build "expected coverage list" using technique frameworks
   - This is the "answer key" -- must be built BEFORE seeing AI output
   |
Step 5: Generate test cases (produce yourself or review user-provided AI output)
   |
Step 6: Gap Analysis -- check against coverage list item by item:
   [covered]   -- mark the corresponding case
   [partial]   -- identify what is missing
   [missing]   -- add the missing case
   [redundant] -- mark cases that can be merged or deleted
   |
Step 7: Apply the blind spots checklist for one more sweep
   |
Step 8: Output final Test Suite + Coverage Report
```

### Gap Analysis Output Format

```text
## Coverage Analysis

### Covered
| Expected Coverage Item | Corresponding TC ID | Notes |

### Partially Covered
| Expected Coverage Item | Missing Aspect | Recommended Addition |

### Completely Missing
| Expected Coverage Item | Description | Recommended New Test Case |

### Redundant Items
| Test Case ID | Duplicate of which case | Recommended Action |
```

---

## Test Case Output Standard

### Required Fields

Each test case must include:

| Field | Description |
|-------|-------------|
| TC-ID | Numbering convention: `[Feature-Abbrev]-[Technique-Abbrev]-[Seq]`, e.g. `LOGIN-BVA-001` |
| Test Purpose | One sentence describing what is being verified |
| Technique Used | Mark which testing design technique this case comes from |
| Risk Level | High / Medium / Low |
| Precondition | What state the system must be in before the test begins |
| Test Steps | Concrete executable steps (not vague descriptions) |
| Test Data | Explicit input values (don't write "enter a valid value" -- write "enter `test@example.com`") |
| Expected Result | Concrete verifiable result (don't write "shows success" -- write "shows green toast: 'Saved successfully', disappears after 3 seconds") |

### Output Template

```text
| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|-------------|-------|-----------|----------------|
```

### Quality Check

Before finalizing output, confirm:

- Every case's test data is a concrete value, not an abstract description
- Expected results are verifiable (another person can tell what "pass" looks like)
- Steps are specific enough for a newcomer to follow
- Each case is marked with the testing technique used, for traceability

---

## Quick Reference

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
