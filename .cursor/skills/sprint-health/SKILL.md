---
name: sprint-health
description: >-
  Produces a daily sprint health report for the SCL JIRA board: auto-selects
  the active sprint, tracks progress toward the sprint goal, compares day-to-day
  changes via changelog, flags in-progress tasks running long vs estimate, and
  proposes re-estimates for wrong or drifting story points. By default excludes
  Zephyr Test issues from SP metrics (say "include tests" to override). Use when
  the user asks about sprint progress, sprint goal, burndown, daily standup,
  sprint health, SCL sprint, estimation accuracy, wrong estimate, re-estimate,
  story points, or whether the team will hit the sprint goal.
---

# Sprint Health

Generates a sprint health report for **board 231** (The A Team) using the Atlassian MCP server only. No local snapshot files — all history is reconstructed from the JIRA changelog.

## How to use (example prompts)

No configuration needed — copy one of the prompts below into chat. You get a single report with **RAG status**, sprint goal progress, burndown, what changed since yesterday, stuck tickets, and estimation proposals.

| You want… | Write this |
|-----------|------------|
| Full daily report | `Sprint health` |
| Changes since yesterday + goal | `Sprint health — what changed since yesterday and are we on track for the sprint goal?` |
| Sprint goal only | `Are we on track for the sprint goal?` |
| Stuck / aging tickets | `Which tickets are stuck or running long?` |
| Wrong estimates | `Which estimates are wrong? Propose re-estimates.` |
| Daily standup prep | `Prepare a daily standup summary` |
| Include Test tickets in SP | `Sprint health include tests` |
| Save report to file | Add: `Save the report to a file` |

**Note:** By default, Zephyr **Test** issues are excluded from story-point metrics (they often duplicate parent Stories). See [Scope configuration](#scope-configuration). Say **"include tests"** to include them.

## Execution constraints

- **No ad-hoc scripts or temp files.** Do NOT create one-off Python scripts, `.sprint_tmp` directories, or parser output files in the workspace. For **small sprints** (≤ 60 issues, MCP response stays inline), compute metrics **inline** in reasoning from MCP JSON.
- **Large-sprint fallback:** When the sprint has **> 60 issues** or an MCP search response is **> ~200 KB** (e.g. written to an agent-tools file), run the versioned parser [`scripts/sprint_metrics.py`](scripts/sprint_metrics.py) on the saved JSON dump(s). Never write a new parser per run.
- **Minimize MCP payload:** Request only the fields listed in Step 2 — never request `description` or `*all`. Use `maxResults: 50`, paginate with `nextPageToken`, and prefer `responseContentFormat: markdown` when supported.
- **Scope strictly to board 231's active sprint** via `sprint = <activeSprintId>` (resolved in Step 1). Never use bare `sprint in openSprints()` for metrics — project SCL has multiple concurrent active sprints on different boards.

## Fixed configuration

| Setting | Value |
|---------|-------|
| Site | `inhabitiq.atlassian.net` |
| Project | `SCL` |
| Board | `231` |
| Story Points field | `customfield_10200` |
| Sprint field | `customfield_10115` |

**Cloud ID:** Resolve once per session via `getAccessibleAtlassianResources` and pick the resource for `inhabitiq.atlassian.net`. Alternatively pass `https://inhabitiq.atlassian.net` directly as `cloudId`. Do **not** use the PropertyBrands cloud ID from other skills.

## Scope configuration

**Default:** Exclude Zephyr **Test** issues (`issuetype = Test`) from all metric calculations — Total/Done/In Progress/To Do SP, burndown, goal progress, aging, estimation, and day-to-day deltas.

| Setting | Default | Override |
|---------|---------|----------|
| Exclude Test issues | **Yes** | User says **"include tests"** |
| JQL filter (default) | `AND issuetype != Test` | Omit when including tests |
| Metrics scope | Story, Bug, Task, Epic-linked work, etc. | All issue types when including tests |

**Why:** Test tickets (Zephyr) often duplicate parent Stories with inflated SP (e.g. SCL-13273 Test 5 SP vs SCL-13211 Story 2 SP), skewing burndown and goal progress.

**Always report excluded tests separately:**
- `Test issues excluded: {count} ticket(s), {sp} SP`
- Optional **Test/QA coverage** line: count of excluded Test issues in Done status (informational only — not added to SP totals)

When excluding tests, still fetch Test issues in a **separate lightweight query** (keys + status + SP only) to populate the exclusion summary and QA coverage line:

```
jql: project = SCL AND sprint = <activeSprintId> AND issuetype = Test
maxResults: 50
fields: ["summary", "status", "customfield_10200"]
```

## Quick start

When invoked, run the full workflow below and output the report in chat. Optionally offer to save as `sprint-health_SCL_<sprintName>_<YYYY-MM-DD>.md`.

```
Task Progress:
- [ ] Step 1: Resolve cloudId and active sprint
- [ ] Step 2: Pull all sprint issues
- [ ] Step 3: Compute sprint metrics and burndown
- [ ] Step 4: Day-to-day delta from changelog
- [ ] Step 5: Aging analysis (time-in-status vs estimate)
- [ ] Step 5b: Estimation accuracy and proposals
- [ ] Step 6: Infer sprint goal and compute goal progress
- [ ] Step 7: Emit report with RAG status
```

---

## Step 1: Resolve cloudId and active sprint

1. Call `getAccessibleAtlassianResources` and select the resource whose URL contains `inhabitiq.atlassian.net`.
2. Call `searchJiraIssuesUsingJql` (discovery only):

```
cloudId: <resolved>
jql: project = SCL AND sprint in openSprints()
maxResults: 1
fields: ["customfield_10115"]
```

3. Parse `customfield_10115` from the first issue. It is an array of sprint objects. Select the sprint where **`state === "active"` AND `boardId === 231`**. Do not fall back to other boards — project SCL has multiple concurrent active sprints (e.g. Panda Labs on board 1423).
4. Extract and retain for all subsequent steps: **`activeSprintId`** (`id`, numeric), `name`, `state`, `startDate`, `endDate`, `goal` (may be empty).

If no active sprint with `boardId === 231` is found, stop and report: *No active sprint found for board 231 (The A Team).*

**Board filter note:** Board 231's saved filter is `project = SCL AND sprint IN ("The A Team", empty) ORDER BY priority DESC, Rank ASC`. The `empty` clause includes backlog items for grooming. Sprint-health metrics use only the committed active sprint (`sprint = <activeSprintId>`); backlog items are excluded from SP totals and burndown.

---

## Step 2: Pull all sprint issues

Call `searchJiraIssuesUsingJql` with pagination (`nextPageToken`) until all issues are fetched.

**Default JQL** (Test issues excluded):

```
jql: project = SCL AND sprint = <activeSprintId> AND issuetype != Test
maxResults: 50
fields: ["summary", "status", "statuscategory", "issuetype", "parent", "assignee", "customfield_10200", "customfield_10115", "priority", "labels"]
```

**Include-tests variant** (omit `issuetype != Test` when user requests it).

Do **not** request `description` or `*all` — these inflate responses and force ad-hoc parsing.

For each issue, extract:

| Field | Source |
|-------|--------|
| Key | `key` |
| Summary | `fields.summary` |
| Status | `fields.status.name` |
| Status category | `fields.status.statusCategory.name` (To Do / In Progress / Done) |
| Type | `fields.issuetype.name` |
| Parent Epic | `fields.parent.key` + `fields.parent.fields.summary` (if present) |
| Assignee | `fields.assignee.displayName` |
| Story Points | `fields.customfield_10200` (treat null as 0, flag as unestimated) |
| Priority | `fields.priority.name` |
| Labels | `fields.labels` |

All metrics below apply to the **scoped issue list** (Test issues excluded by default). Sub-tasks returned by JQL are included unless the team convention says otherwise.

---

## Step 3: Sprint metrics and burndown

Compute from the scoped issue list (Step 2; Test issues excluded by default):

| Metric | Calculation |
|--------|-------------|
| Total SP | Sum of `customfield_10200` for scoped issues |
| Done SP | Sum where status category = Done |
| In Progress SP | Sum where status category = In Progress |
| To Do SP | Sum where status category = To Do |
| % complete | `Done SP / Total SP × 100` (if Total SP = 0, use issue count) |
| Unestimated count | Scoped issues where `customfield_10200` is null or 0 |
| Test issues excluded | Count and SP sum from the separate Test query (Scope configuration) |
| Test/QA coverage | Count of excluded Test issues with status category = Done (informational) |
| Days elapsed | Calendar days from `startDate` to today |
| Days remaining | Calendar days from today to `endDate` (min 0) |
| Sprint length | Days elapsed + days remaining |

**Burndown:**

- **Ideal remaining SP** = `Total SP × (Days remaining / Sprint length)`
- **Actual remaining SP** = `Total SP − Done SP`
- **Burndown delta** = `Actual remaining − Ideal remaining` (positive = behind)

See [reference.md](reference.md) for burndown math and RAG thresholds.

---

## Step 4: Day-to-day delta (changelog-based)

No local storage. Reconstruct "since yesterday" from JIRA changelog.

### 4a. Find recently changed issues

```
jql: project = SCL AND sprint = <activeSprintId> AND issuetype != Test AND status CHANGED AFTER -1d
maxResults: 50
fields: ["summary", "status", "customfield_10200", "issuetype"]
```

If the combined `status CHANGED OR sprint CHANGED` query fails, split into separate queries (status-only, sprint-only). Omit `issuetype != Test` when user requested include tests.

Paginate if needed.

### 4b. Fetch changelogs

For each issue from 4a (and any In Progress or Done issue from Steps 2/5/5b needing changelog), call:

```
getJiraIssue
  cloudId: <resolved>
  issueIdOrKey: <key>
  expand: "changelog"
  fields: ["summary", "status", "customfield_10200"]
```

### 4c. Parse changelog entries since previous working day

Use the cutoff: **start of previous calendar day** (00:00 local) or last business day if the user specifies.

For each `changelog.histories` entry where `created >= cutoff`:

| Change type | Field | What to record |
|-------------|-------|----------------|
| Status transition | `status` | `{key, from, to, when, author}` |
| SP completed | `status` → Done | SP value of the issue |
| Scope added | `Sprint` | Issue added to sprint (from empty or different sprint) |
| Scope removed | `Sprint` | Issue removed from sprint |
| SP changed | `Story Points` / `customfield_10200` | Old → new value |
| Blocker added | `Flagged` / `labels` | New blocker or impediment label |

Summarize into:

- **Completed yesterday:** list of keys that transitioned to Done (+ SP)
- **Started yesterday:** keys that moved from To Do → In Progress
- **Scope changes:** keys added/removed from sprint (+ SP impact)
- **SP completed yesterday:** sum of SP for issues moved to Done
- **Net SP change:** scope added SP − scope removed SP − SP completed

See [reference.md](reference.md) for detailed changelog parsing rules.

---

## Step 5: Aging analysis (time-in-status vs estimate)

For each **scoped** issue (Test excluded by default) with status category **In Progress**:

1. Fetch changelog (`expand=changelog`) if not already fetched.
2. Walk changelog chronologically. For each status transition, accumulate time spent in "In Progress" category statuses.
3. Add time from last transition to now for the current status (if In Progress).
4. Derive **expected duration** from Story Points using the team scale (see [reference.md](reference.md)).
5. Compute **ratio** = `actual hours in progress / expected hours`.

**Flag as stuck/over-running when:**

| Condition | Severity |
|-----------|----------|
| Ratio > 1.5× expected | Warning |
| Ratio > 2.0× expected | Critical |
| No status change for ≥ 2 business days while In Progress | Stale |
| Story Points = 0/null and In Progress > 1 business day | Unestimated risk |

List flagged issues with: key, summary, assignee, SP, days in current status, expected duration, ratio, recommendation.

---

## Step 5b: Estimation accuracy and proposals

Reuse changelogs already fetched in Steps 4 and 5. See [reference.md](reference.md) for cycle time rules, Fibonacci mapping, and Epic peer JQL.

### 5b.1 Completed tickets (calibration)

For each **Done** scoped issue in the sprint (Test excluded by default):

1. From changelog: **cycle start** = first transition into In Progress category; **cycle end** = transition to Done.
2. `actualHours` = business hours between start and end.
3. `expectedHours` = SP midpoint × 1.1 from the team scale.
4. `ratio = actualHours / expectedHours`.

| Ratio | Verdict |
|-------|---------|
| > 1.5 | Underestimated |
| 0.5 – 1.5 | Accurate |
| < 0.5 | Overestimated |

List each Done issue with: key, SP, expected, actual, ratio, verdict.

### 5b.2 In-progress tickets (re-estimate proposals)

Extend Step 5 aging data with a **suggested SP**:

```
expectedDays = expectedHours / 8
projectedHours = actualHoursInProgress / (daysInProgress / expectedDays)
suggestedSP = nearestFibonacci(projectedHours / midpointHoursFor1SP)
```

Only propose when `suggestedSP != currentSP` and ratio > 1.3 or ratio < 0.6.

Nearest Fibonacci: 1, 2, 3, 5, 8, 13, 21 (21* = too large, should be split).

Example: 5 SP ticket at 1.8× ratio → suggest **8 SP**.

### 5b.3 To Do tickets (Epic-calibrated proposals)

For each **To Do** issue with a parent Epic:

1. Fetch completed peers via JQL (current sprint + last closed sprint, limit ~20):

```
project = SCL AND parent = {epicKey} AND statusCategory = Done AND issuetype != Test ORDER BY updated DESC
```

Omit `issuetype != Test` when user requested include tests.

2. Compute `epicMedianRatio = median(actualHours / expectedHours)` from peer changelogs.
3. If `epicMedianRatio > 1.3`: propose `suggestedSP = nearestFibonacci(currentSP × epicMedianRatio)`.
4. Confidence: **High** (≥ 3 peers), **Low** (1–2 peers). Skip if no Epic or no peers.

### 5b.4 Mid-sprint estimate changes

From changelogs, detect tickets where Story Points (`customfield_10200`) changed **after** the first In Progress transition. Reuse SP change data from Step 4c.

Record: key, original SP, new SP, when changed.

### 5b.5 Sprint-level estimation summary

Aggregate:

- `underestimatedCount / doneCount` (% underestimated)
- `totalSuggestedSPDelta` — net SP change if all proposals accepted
- `estimatesChangedMidSprint` — count of mid-flight SP edits

---

## Step 6: Infer sprint goal and compute goal progress

Sprint goals are **not** marked with labels — infer from available data when the `goal` field is empty.

### 6a. Determine goal statement

**Priority order:**

1. **Sprint goal field** — if `goal` from Step 1 is non-empty, use it as the primary goal.
2. **Epic clustering** — group issues by parent Epic; the Epic with the highest total SP (especially Done + In Progress) is the dominant theme.
3. **High-SP / high-priority tickets** — top 3 issues by SP × priority weight.
4. **Inferred summary** — one sentence synthesizing the above. Prefix with *(inferred)* if no explicit goal field.

Example inference:

> *(inferred)* Deliver payment gateway integration (Epic SCL-450, 21 SP) and fix critical booking flow bugs (SCL-512, SCL-518).

### 6b. Compute goal progress (mandatory)

Always quantify progress toward the sprint goal:

1. **Identify goal-linked issues** — if an explicit goal exists, map it to Epics/issues by keyword match or dominant Epic from 6a; otherwise use the dominant Epic + top high-priority issues from 6a. Use the **scoped** issue set (Test excluded by default).
2. **Sum goal SP** — total SP of goal-linked scoped issues in the sprint.
3. **Sum goal Done SP** — SP of goal-linked scoped issues with status category = Done.
4. **Goal % complete** = `goalDoneSP / goalTotalSP × 100` (if goalTotalSP = 0, use issue count).
5. **Goal verdict** — one line: compare goal % complete vs expected % complete (`daysElapsed / sprintLength × 100`):
   - Goal % ≥ expected % → *On track for goal*
   - Goal % within 10 pp of expected → *At risk for goal*
   - Goal % > 10 pp behind expected → *Off track for goal*

Report: goal statement, goal-linked Epic/issues, goal Done/total SP, goal %, and verdict.

---

## Step 7: Report with RAG status

Determine overall **RAG status**:

| Status | Criteria (any triggers the status) |
|--------|-------------------------------------|
| **On track** | Burndown delta ≤ 10% of total SP AND no critical aging issues AND ≥ expected % complete for elapsed time |
| **At risk** | Burndown delta 10–25% behind OR 1+ warning aging issues OR scope grew > 10% yesterday OR underestimatedCount/doneCount > 50% with burndown behind |
| **Off track** | Burndown delta > 25% behind OR 1+ critical aging issues OR 0 SP completed in last 2 business days with > 50% sprint elapsed OR net suggested SP delta > 15% of remaining SP |

**Expected % complete** = `(Days elapsed / Sprint length) × 100`

**Estimation RAG modifiers** (upgrade status if triggered):

- `underestimatedCount / doneCount > 50%` AND burndown behind → upgrade to **At risk** with note "systematic underestimation detected"
- `totalSuggestedSPDelta > 15%` of remaining SP → prioritize re-estimation in recommendations

Use the report template from [reference.md](reference.md). Always include:

1. RAG status with one-line justification
2. Sprint name, dates, days remaining, and **scope line**: `Test (Zephyr) issues excluded — {count} ticket(s), {sp} SP` (or "Tests included" when override active)
3. **Sprint goal** (explicit or inferred) **and Goal Progress** (goal-linked issues, Done/total SP, goal %, on-track verdict from Step 6b)
4. Metrics table (SP by category, % complete, burndown, test exclusion summary, optional Test/QA coverage)
5. Since-yesterday section (completed, started, scope changes)
6. Aging / stuck tickets table
7. Estimation accuracy section (summary, re-estimate proposals, completed calibration)
8. Actionable recommendations (max 5, prioritized; include estimation actions when proposals exist, e.g. "Re-estimate SCL-512 from 5→8 SP"; include goal actions when off track, e.g. "Prioritize SCL-512 to unblock goal")

### Output

- **Default:** render the report in chat.
- **Optional:** ask the user if they want the report saved to `sprint-health_SCL_<sprintName>_<YYYY-MM-DD>.md` in the workspace root.

---

## MCP tools used

| Tool | Purpose |
|------|---------|
| `getAccessibleAtlassianResources` | Resolve cloudId for inhabitiq.atlassian.net |
| `searchJiraIssuesUsingJql` | Fetch sprint issues, find recently changed issues |
| `getJiraIssue` (expand=changelog) | Status history, aging, day-to-day delta |

## Additional resources

- JQL snippets, changelog parsing, SP-to-time scale, burndown math, full report template: [reference.md](reference.md)
- Large-sprint metrics parser (fallback): [scripts/sprint_metrics.py](scripts/sprint_metrics.py)
