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
  story points, whether the team will hit the sprint goal, or posting sprint health
  to Microsoft Teams.
---

# Sprint Health

Generates a sprint health report for **board 231** (The A Team) using the Atlassian MCP server only. No local snapshot files — all history is reconstructed from the JIRA changelog.

## How to use (example prompts)

No configuration needed — copy one of the prompts below into chat. You get a single report with **dual RAG status** (overall + sprint goal), per-theme goal progress, burndown, since-yesterday flow (including backward/reopened + Net flow), stuck tickets (idle since), estimation notes, and prioritized recommendations.

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
| Publish to Teams | Add: `Post the report to Teams` (requires [Teams setup](#teams-publish-setup-one-time)) |

**Note:** By default, Zephyr **Test** issues are excluded from story-point metrics (they often duplicate parent Stories). See [Scope configuration](#scope-configuration). Say **"include tests"** to include them.

## Execution constraints

- **Always respond in English.** Produce the full report, all section text, and the Teams card content in English even when the user writes in another language.
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

When invoked, run the full workflow below and output the report in chat. Optionally offer to save as `sprint-health_SCL_<sprintName>_<YYYY-MM-DD>.md` and/or publish to Teams (Step 8).

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
- [ ] Step 8: Publish summary card to Teams (opt-in only)
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
jql: project = SCL AND sprint = <activeSprintId> AND issuetype != Test AND status CHANGED AFTER startOfDay(-1)
maxResults: 50
fields: ["summary", "status", "customfield_10200", "issuetype"]
```

Use `startOfDay(-1)` (not bare `-1d`) — the rolling 24h window misses completions from the previous calendar day.

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

Use the cutoff: **`startOfDay(-1)`** in JQL (aligns with start of previous calendar day 00:00 local). Do not use bare `-1d` alone — it misses earlier completions from the previous day. For changelog filtering, use the same cutoff: `history.created >= cutoffISO`.

For each `changelog.histories` entry where `created >= cutoff`:

| Change type | Field | What to record |
|-------------|-------|----------------|
| Status transition | `status` | `{key, from, to, when, author}` |
| SP completed | `status` → Done | SP value of the issue |
| Moved forward | `status` | To Do → In Progress, or forward in workflow (e.g. → In-Review, → QA) |
| Moved backward / reopened | `status` | In Progress → To Do/Open, Review/QA → Open, Done → reopened |
| Scope added | `Sprint` | Issue added to sprint (from empty or different sprint) |
| Scope removed | `Sprint` | Issue removed from sprint |
| SP changed | `Story Points` / `customfield_10200` | Old → new value |
| Blocker added | `Flagged` / `labels` | New blocker or impediment label |

Summarize into (all required in report — see [reference.md](reference.md) template):

- **✅ Completed:** keys that transitioned to Done (+ SP sum)
- **▶ Moved forward:** keys that advanced in workflow (started, → review, → QA)
- **◀ Moved backward / reopened:** keys that regressed (In-Progress→Open, QA→Open, Done→reopened) (+ SP sum regressed)
- **➕ Scope added / ➖ Scope removed:** keys added/removed from sprint (+ SP impact)
- **Net flow:** one-line summary — `+{spCompleted} SP done vs ~{spRegressed} SP regressed → {assessment}`

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

List flagged issues with: key, summary, SP, status, **idle since** (date of last status change or `updated` if no changelog). Add a one-sentence bottleneck diagnosis (e.g. review/QA queue). Ratio/assignee are optional — prefer the idle-since table from [reference.md](reference.md).

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

Always quantify progress toward the sprint goal. Use emoji RAG (🟢/🟡/🔴) per theme and for overall goal verdict.

**When `sprint.goal` has multiple lines or bullets** (multi-part goal):

1. Split goal text into **themes** (one per line/bullet).
2. For each theme, map to Epics/issues by keyword match (e.g. "Sykes" → Epic SCL-3875, "Adyen" → SCL-13248/SCL-12058, "VRBO" → SCL-12933).
3. Per theme: sum `themeTotalSP`, `themeDoneSP`, compute `themePct`, assign theme verdict (same thresholds below).
4. Render the **per-theme table** from [reference.md](reference.md).
5. **Goal roll-up:** aggregate all theme SP → overall `goalPctComplete` vs `expectedPct`; overall goal verdict = worst theme verdict.

**Single-goal or inferred goal:**

1. **Identify goal-linked issues** — keyword match to explicit goal, or dominant Epic + top high-priority issues from 6a. Use the **scoped** issue set (Test excluded by default).
2. **Sum goal SP** — total SP of goal-linked scoped issues in the sprint.
3. **Sum goal Done SP** — SP of goal-linked scoped issues with status category = Done.
4. **Goal % complete** = `goalDoneSP / goalTotalSP × 100` (if goalTotalSP = 0, use issue count).
5. **Goal verdict** — compare goal % complete vs expected % complete (`daysElapsed / sprintLength × 100`):
   - Goal % ≥ expected % → 🟢 *On track for goal*
   - Goal % within 10 pp of expected → 🟡 *At risk for goal*
   - Goal % > 10 pp behind expected → 🔴 *Off track for goal*

Report: goal statement (bulleted if multi-part), per-theme table when applicable, Goal roll-up line, and overall goal RAG in the header.

---

## Step 7: Report with RAG status

Determine **two independent RAG statuses** — overall sprint health and sprint goal — each with emoji (🟢 On track / 🟡 At risk / 🔴 Off track). See [reference.md](reference.md) decision matrix.

| Status | Criteria (any triggers the status) |
|--------|-------------------------------------|
| **On track** | Burndown delta ≤ 10% of total SP AND no critical aging issues AND ≥ expected % complete for elapsed time |
| **At risk** | Burndown delta 10–25% behind OR 1+ warning aging issues OR scope grew > 10% yesterday OR underestimatedCount/doneCount > 50% with burndown behind |
| **Off track** | Burndown delta > 25% behind OR 1+ critical aging issues OR 0 SP completed in last 2 business days with > 50% sprint elapsed OR net suggested SP delta > 15% of remaining SP |

**Expected % complete** = `(Days elapsed / Sprint length) × 100`

**Estimation RAG modifiers** (upgrade status if triggered):

- `underestimatedCount / doneCount > 50%` AND burndown behind → upgrade to **At risk** with note "systematic underestimation detected"
- `totalSuggestedSPDelta > 15%` of remaining SP → prioritize re-estimation in recommendations

Use the report template from [reference.md](reference.md) — it is the **only** output format. Always include:

1. **Dual RAG header** — `Overall status` and `Sprint goal` (independent) with one-line `>` justification
2. Sprint name, dates, days remaining/elapsed, and **scope line**: `Test (Zephyr) issues excluded — {count} ticket(s), {sp} SP` (or "Tests included" when override active)
3. **Sprint Goal & Progress** — bulleted goal + per-theme table when multi-part goal + Goal roll-up line (Step 6b)
4. **Progress Summary** — SP by category (flag WIP >40%), burndown, test exclusion
5. **Since Yesterday** — ✅ Completed, ▶ Moved forward, ◀ Moved backward/reopened, ➕/➖ scope, **Net flow** (Step 4)
6. **Aging / Stuck Tickets** — idle-since table + bottleneck diagnosis sentence
7. **Estimation Notes** — unestimated count, mid-sprint changes, calibration summary or offer
8. **Recommendations** — max 5, prioritized (review queue, WIP, goal rescue, estimation)
9. **Closing offer** — ask to save `sprint-health_SCL_<sprintName>_<YYYY-MM-DD>.md`, publish to Teams (Step 8), and/or run full estimation calibration

### Output

- **Default:** render the report in chat using the template exactly.
- **On request:** save to `sprint-health_SCL_<sprintName>_<YYYY-MM-DD>.md` in the workspace root.
- **On request:** publish a summary Adaptive Card to Teams (Step 8).

---

## Teams publish setup (one-time)

Perform this setup once per target Teams chat. The agent does **not** create the workflow — the user configures it in Teams or Power Automate.

### 1. Create the workflow

1. In **Microsoft Teams**, open the **Workflows** app (or go to [make.powerautomate.com](https://make.powerautomate.com) → **Create** → **Instant cloud flow**).
2. Choose the template **"Post to a chat when a webhook request is received"**.
   - Uses the free Teams **webhook** trigger — not the Premium **When an HTTP request is received** trigger.
3. In the **Post adaptive card in a chat or channel** action:
   - **Post as:** Flow bot (or your user account, if preferred).
   - **Post in:** **Chat**.
   - **Chat:** select the dedicated sprint-health chat (group or 1:1).
   - **Adaptive Card:** bind to the incoming webhook body (the template usually maps `triggerBody()` or the full request body).
4. **Save** the flow and copy the **HTTP POST URL** from the trigger step.

### 2. Store the webhook URL locally

Copy the example config and paste your webhook URL:

```powershell
Copy-Item .\.cursor\skills\sprint-health\teams-config.example.json .\.cursor\skills\sprint-health\teams-config.json
```

Edit [teams-config.json](teams-config.json) (gitignored — not committed):

```json
{
  "webhookUrl": "https://..."
}
```

The committed template is [teams-config.example.json](teams-config.example.json). Each developer clones the repo, copies the example to `teams-config.json`, and adds their own webhook URL.

### 3. Verify the webhook

Send a test payload matching the expected body shape:

```powershell
$config = Get-Content .\.cursor\skills\sprint-health\teams-config.json -Raw | ConvertFrom-Json
$body = Get-Content .\.cursor\skills\sprint-health\templates\teams-card.json -Raw
Invoke-RestMethod -Uri $config.webhookUrl -Method Post -ContentType 'application/json' -Body $body
```

Replace `{{placeholders}}` in the template with sample values before testing, or post the raw template to confirm the flow receives JSON.

### Expected request body

The workflow expects a Teams message envelope with an Adaptive Card attachment:

```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": []
      }
    }
  ]
}
```

---

## Step 8: Publish to Teams (opt-in)

Run **only** when the user asks to post/publish/send the report to Teams (e.g. "Post the report to Teams"). Do not publish automatically after Step 7.

### 8a. Resolve webhook URL

1. Read `.cursor/skills/sprint-health/teams-config.json` and parse `webhookUrl`.
2. If the file is missing, tell the user to copy [teams-config.example.json](teams-config.example.json) to `teams-config.json` and complete [Teams publish setup](#teams-publish-setup-one-time). Do not guess or hardcode a URL.
3. If `webhookUrl` is empty or still contains the placeholder `YOUR-POWER-AUTOMATE-WEBHOOK-URL-HERE`, stop and ask the user to paste the real URL.

### 8b. Build the summary Adaptive Card

Load [`templates/teams-card.json`](templates/teams-card.json) and substitute placeholders from the Step 7 report metrics.

**Goal theme rows:** The template contains one example goal-row `ColumnSet` (the second `ColumnSet` after the header row). Before substitution, **clone that `ColumnSet` once per goal theme** from Step 6b so each theme gets its own row. Replace per-row placeholders (`{{themeName}}`, `{{themeDoneSP}}`, `{{themeTotalSP}}`, `{{themePct}}`, `{{themeVerdictEmoji}}`) with that theme's values. Remove the template row after cloning if you built all rows from scratch, or substitute the single template row when there is exactly one theme.

| Placeholder | Source |
|-------------|--------|
| `{{ragEmoji}}` | Overall RAG emoji from Step 7 (🟢 / 🟡 / 🔴) |
| `{{sprintName}}` | Active sprint name from Step 1 |
| `{{overallStatus}}` | Overall status label (On track / At risk / Off track) |
| `{{goalStatus}}` | Sprint goal status label (On track / At risk / Off track) |
| `{{daysElapsed}}` | Days elapsed from Step 3 |
| `{{sprintLength}}` | Sprint length from Step 3 |
| `{{daysRemaining}}` | Days remaining from Step 3 |
| `{{ragJustification}}` | One-line RAG justification from Step 7 header |
| `{{themeName}}` | Goal theme name (per row, from Step 6b) |
| `{{themeDoneSP}}` | Done SP for theme (per row) |
| `{{themeTotalSP}}` | Total SP for theme (per row) |
| `{{themePct}}` | Theme % complete, rounded (per row) |
| `{{themeVerdictEmoji}}` | Theme RAG emoji (per row) |
| `{{goalDoneSP}}` | Goal roll-up done SP |
| `{{goalTotalSP}}` | Goal roll-up total SP |
| `{{goalPct}}` | Goal roll-up % complete |
| `{{expectedPct}}` | Expected % complete for elapsed time |
| `{{goalVerdictEmoji}}` | Overall goal RAG emoji |
| `{{totalSP}}` | Total SP from Step 3 |
| `{{doneSP}}` | Done SP from Step 3 |
| `{{pctComplete}}` | % complete, rounded to whole number |
| `{{inProgressSP}}` | In Progress SP from Step 3 |
| `{{ipPct}}` | In Progress SP as % of total |
| `{{wipWarning}}` | ` ⚠️ WIP high` when In Progress SP > 40% of total; otherwise empty string |
| `{{toDoSP}}` | To Do SP from Step 3 |
| `{{todoPct}}` | To Do SP as % of total |
| `{{issueCount}}` | Scoped issue count |
| `{{doneCount}}` | Done issue count |
| `{{ipCount}}` | In Progress issue count |
| `{{todoCount}}` | To Do issue count |
| `{{unestimatedCount}}` | Unestimated issue count |
| `{{testExcludedCount}}` | Excluded Test ticket count |
| `{{testExcludedSP}}` | Excluded Test SP sum |
| `{{idealRemaining}}` | Ideal remaining SP (rounded) |
| `{{actualRemaining}}` | Actual remaining SP (rounded) |
| `{{burndownDelta}}` | Signed burndown delta SP (e.g. `+29`, `-2`, `0`) |
| `{{burndownDeltaPct}}` | Burndown delta as % of total SP (rounded) |
| `{{expectedComplete}}` | Expected % complete (rounded) |
| `{{actualComplete}}` | Actual % complete (rounded) |

**Scope (summary version):** header + justification, per-theme goal SP table, goal roll-up, Progress Summary, and Burndown. Do **not** add Since Yesterday, Aging, Estimation, Recommendations, or action buttons yet — those come in a later card iteration.

Perform substitution **inline** in the agent response (string replace on the JSON). Do not write a one-off script or temp file for substitution unless the user explicitly requests a saved card file.

### 8c. POST to Teams

```powershell
$config = Get-Content .\.cursor\skills\sprint-health\teams-config.json -Raw | ConvertFrom-Json
$body = '<substituted JSON from 8b>'
Invoke-RestMethod -Uri $config.webhookUrl -Method Post -ContentType 'application/json' -Body $body
```

### 8d. Confirm to user

After a successful POST, confirm in chat: *Posted sprint health card to Teams.* On failure, report the HTTP status/error and suggest re-running the [verify step](#3-verify-the-webhook).

### Notes

- Publishing is **opt-in** — normal report runs are unaffected.
- The card is **static/informational**; interactive buttons (`Action.Submit`, `Action.Execute`) require a bot or response-waiting flow and are out of scope for this step.
- Since Yesterday, Aging, Estimation, Recommendations, and JIRA board link buttons are deferred to a follow-up card iteration.

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
- Teams Adaptive Card template (summary): [templates/teams-card.json](templates/teams-card.json)
- Teams webhook config template: [teams-config.example.json](teams-config.example.json) → copy to `teams-config.json` (gitignored)
