# Sprint Health — Reference

Detailed JQL, changelog parsing, SP scale, burndown math, and report template.

---

## JQL snippets

**Prerequisite:** Resolve `activeSprintId` in Step 1 (active sprint on board 231). Use `sprint = <activeSprintId>` in all queries below — never bare `sprint in openSprints()` (project SCL has multiple concurrent active sprints on different boards).

**Backlog exclusion:** Board 231's saved filter includes `empty` (backlog) for grooming. Sprint-health metrics scope to the committed active sprint only; backlog items are excluded.

**Test exclusion (default):** Append `AND issuetype != Test` to all metric JQL below. Omit when the user requests **"include tests"**. Test issues are fetched separately for the exclusion summary (see SKILL.md Scope configuration).

### Active sprint issues (full pull — default scope)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
```

Include-tests variant:

```jql
project = SCL AND sprint = <activeSprintId>
```

### Test issues (exclusion summary only)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype = Test
```

### Recently changed (day-to-day delta)

Prefer `startOfDay(-1)` over bare `-1d` — the rolling 24h window misses completions from the previous calendar day.

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND status CHANGED AFTER startOfDay(-1)
```

If combined status/sprint change query fails, run separate queries. Sprint scope changes:

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test AND sprint CHANGED AFTER -1d
```

### In-progress issues (aging candidates)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND statusCategory = "In Progress"
```

### Completed in last day

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND status CHANGED TO Done AFTER -1d
```

### Scope added to sprint in last day

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test AND sprint CHANGED AFTER -1d
```

### Unestimated in-progress issues

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND statusCategory = "In Progress"
AND "Story Points" is EMPTY
```

Replace `"Story Points"` with `customfield_10200` if the named field is not indexed.

### Epic peer lookup (estimation calibration)

```jql
project = SCL AND parent = {epicKey} AND statusCategory = Done AND issuetype != Test ORDER BY updated DESC
```

Limit to ~20 results. Include peers from the current sprint and optionally the most recent closed sprint:

```jql
project = SCL AND parent = {epicKey} AND statusCategory = Done AND issuetype != Test AND sprint in closedSprints() ORDER BY updated DESC
```

---

## Story Points → expected duration

Official team scale (with ×1.1 multiplier for analysis/testing overhead):

| SP | Expected range | Midpoint (hours) | With ×1.1 |
|----|----------------|------------------|-----------|
| 1  | ≤ 1h           | 1h               | 1h        |
| 2  | 2–3h           | 2.5h             | ~3h       |
| 3  | 4–6h           | 5h               | ~5.5h     |
| 5  | 1–2 days       | 15h              | ~17h      |
| 8  | 3–4 days       | 30h              | ~33h      |
| 13 | 1 week         | 50h              | ~55h      |
| 21*| 1.5–2 weeks    | 87.5h            | ~96h      |

\*21 SP indicates the work item is too large and should be split into smaller issues.

For aging analysis, use the **×1.1 midpoint in hours**, converted to business days (8h/day) when comparing against calendar time in status.

**Unestimated issues (SP = 0/null):** assume 1 business day expected; flag if In Progress > 1 day.

---

## Cycle time calculation

Used for completed-ticket calibration (Step 5b.1).

1. Sort status-change histories chronologically.
2. **Cycle start** = timestamp of first transition where `toString` maps to In Progress category.
3. **Cycle end** = timestamp of first transition where `toString` maps to Done category.
4. `actualHours` = business hours between cycle start and cycle end (8h/day, skip weekends).

If no In Progress transition exists (ticket moved directly To Do → Done), use issue `created` as cycle start and note "no In Progress recorded".

If ticket re-opened after Done, use the most recent cycle (last In Progress → Done pair).

---

## Fibonacci re-estimate mapping

Team scale uses Fibonacci story points: **1, 2, 3, 5, 8, 13, 21** (21* = too large, split).

To convert projected hours to suggested SP:

1. Compute `rawSP = projectedHours / midpointHoursFor1SP` (1 SP midpoint = 1h × 1.1 = 1h).
2. Pick the nearest Fibonacci value from the table above.
3. If equidistant, round up.

| Projected hours | Nearest SP |
|-----------------|------------|
| ≤ 1.5h | 1 |
| 1.5 – 4h | 2 |
| 4 – 8h | 3 |
| 8 – 22h | 5 |
| 22 – 42h | 8 |
| 42 – 75h | 13 |
| > 75h | 21 |

For Epic-calibrated proposals: `suggestedSP = nearestFibonacci(currentSP × epicMedianRatio)`.

Only propose when `suggestedSP != currentSP`.

---

## Burndown math

Given:

- `totalSP` — sum of all story points in the sprint
- `doneSP` — sum of SP in Done status
- `daysElapsed` — calendar days since sprint start (including today)
- `daysRemaining` — calendar days until sprint end (minimum 0)
- `sprintLength` — `daysElapsed + daysRemaining`

```
actualRemaining   = totalSP - doneSP
idealRemaining    = totalSP * (daysRemaining / sprintLength)
burndownDelta     = actualRemaining - idealRemaining
burndownDeltaPct  = (burndownDelta / totalSP) * 100   # if totalSP > 0
expectedComplete  = (daysElapsed / sprintLength) * 100
actualComplete    = (doneSP / totalSP) * 100           # if totalSP > 0
completionGap     = expectedComplete - actualComplete
```

**Interpretation:**

| burndownDeltaPct | Meaning |
|------------------|---------|
| ≤ 0              | Ahead of ideal burndown |
| 0 – 10           | On track |
| 10 – 25          | Slightly behind |
| > 25             | Significantly behind |

When `totalSP = 0`, fall back to issue-count-based metrics (% issues Done vs total).

---

## Changelog parsing rules

### Structure

Each issue changelog contains `histories[]`. Each history has:

- `created` — ISO timestamp
- `author.displayName`
- `items[]` — each with `field`, `fieldtype`, `from`, `fromString`, `to`, `toString`

### Status transitions

Look for `items` where `field === "status"`:

```
fromString → toString  (at created, by author)
```

Map `toString` to status category using the issue's current status metadata or a known mapping:

| Status category | Typical status names |
|-----------------|---------------------|
| To Do | Open, To Do, Backlog, Selected for Development |
| In Progress | In Progress, In Review, In QA, Code Review |
| Done | Done, Closed, Resolved, Released |

When the mapping is ambiguous, use `statusCategory` from the issue fetch in Step 2 as the source of truth for the current status, and infer categories for historical statuses from `fromString`/`toString` context.

### Time-in-status calculation

1. Sort all status-change histories chronologically.
2. Initialize `currentStatus` = earliest known status (first `fromString` in earliest history, or issue creation status).
3. For each transition at time `T`:
   - If `currentStatus` is In Progress category, add `(T - lastTransitionTime)` to `inProgressDuration`.
   - Set `currentStatus` = `toString`, `lastTransitionTime` = `T`.
4. After all histories, if current status is In Progress, add `(now - lastTransitionTime)`.

Convert durations to business hours (8h per business day, skip weekends) for comparison against expected duration.

### Sprint scope changes

Look for `items` where `field === "Sprint"`:

| Pattern | Meaning |
|---------|---------|
| `from` empty, `to` set | Issue added to sprint |
| `from` set, `to` empty | Issue removed from sprint |
| `from` set A, `to` set B | Issue moved between sprints |

Record SP impact: use the issue's current SP value at the time of the change (from the same or nearest history entry).

### Story Points changes

Look for `field === "Story Points"` or `field === "customfield_10200"`:

```
fromString → toString  (e.g., "3" → "5")
```

### Blockers / impediments

Look for:

- `field === "Flagged"` with `toString === "Impediment"`
- `field === "labels"` where a new label contains `blocker`, `impediment`, or `blocked`

### Day-to-day cutoff

Default cutoff: **`startOfDay(-1)`** in JQL — start of previous calendar day in the user's local timezone. Filter changelogs: `history.created >= cutoffISO`.

Do not use bare `-1d` alone for discovery; it is a rolling 24h window and misses earlier completions from the previous day.

For "since last standup" requests, use 24h rolling window (`-1d` in JQL) only when the user explicitly asks for it.

---

## Sprint goal inference and progress algorithm

### Goal statement (Step 6a)

```
1. IF sprint.goal is non-empty → use as primaryGoal
2. GROUP issues by parent Epic key
3. FOR each Epic: sumSP = sum(storyPoints), countDone, countInProgress
4. dominantEpic = Epic with highest (sumSP * 1.0 + countInProgress * 2)
5. topIssues = top 3 by (storyPoints * priorityWeight)
   priorityWeight: Highest=4, High=3, Medium=2, Low=1, default=2
6. IF primaryGoal exists → report it
   ELSE → "(inferred) Deliver {dominantEpic.summary} ({dominantEpic.key}, {sumSP} SP) and {topIssues summaries}"
```

### Goal progress (Step 6b — mandatory in report)

**Single-goal sprint:**

```
1. goalIssues = issues linked to primaryGoal (keyword match) OR dominantEpic + topIssues
2. goalTotalSP = sum(storyPoints) of goalIssues
3. goalDoneSP = sum(storyPoints) of goalIssues where statusCategory = Done
4. goalPctComplete = goalDoneSP / goalTotalSP * 100
5. expectedPct = daysElapsed / sprintLength * 100
6. IF goalPctComplete >= expectedPct → 🟢 On track for goal
   ELIF goalPctComplete >= expectedPct - 10 → 🟡 At risk for goal
   ELSE → 🔴 Off track for goal
```

**Multi-part goal** (when `sprint.goal` contains multiple lines or bullet items):

```
1. SPLIT goal text into themes (one per line/bullet)
2. FOR each theme:
   a. Map to Epics/issues by keyword match (e.g. "Sykes" → Epic SCL-3875, "Adyen" → SCL-13248/SCL-12058, "VRBO" → SCL-12933)
   b. Sum themeTotalSP, themeDoneSP from mapped scoped issues
   c. themePct = themeDoneSP / themeTotalSP * 100
   d. themeVerdict = same thresholds as step 6 above (with emoji)
3. Goal roll-up: sum all theme SP → goalTotalSP, goalDoneSP → goalPctComplete
4. Overall goal verdict = worst theme verdict (🔴 > 🟡 > 🟢)
5. Render per-theme table + one-line Goal roll-up comparing goal % vs expected %
```

---

## RAG status decision matrix

Evaluate all criteria; the **worst** matching status wins.

**Emoji legend (use in header, goal table, and verdict rows):**

| Emoji | Status |
|-------|--------|
| 🟢 | On track |
| 🟡 | At risk |
| 🔴 | Off track |

Apply emoji RAG **per row** in the goal-theme table and in the dual-status header (`Overall status` and `Sprint goal` are independent).

| Check | On track | At risk | Off track |
|-------|----------|---------|-----------|
| burndownDeltaPct | ≤ 10 | 10–25 | > 25 |
| completionGap | ≤ 10 | 10–20 | > 20 |
| Critical aging issues | 0 | 0 | ≥ 1 |
| Warning aging issues | 0 | ≥ 1 | — |
| SP completed in last 2 business days | > 0 | — | 0 (when > 50% elapsed) |
| Scope growth yesterday | ≤ 10% of totalSP | > 10% | > 20% |
| Underestimated done tickets | ≤ 50% | > 50% (with burndown behind) | — |
| Net suggested SP delta | ≤ 15% of remaining SP | — | > 15% of remaining SP |

---

## Full report template

This is the **only** report format. Follow it exactly for every sprint-health run.

```markdown
# Sprint Health Report — {sprintName}

| | |
|-|-|
| **Date** | {YYYY-MM-DD} |
| **Project / Board** | SCL / 231 (The A Team) |
| **Sprint** | {sprintName} ({startDate} → {endDate}) |
| **Days remaining** | {daysRemaining} (day {daysElapsed} of {sprintLength}) |
| **Scope** | Test (Zephyr) issues excluded — {testExcludedCount} tickets, {testExcludedSP} SP (say "include tests" to add them back) |
| **Overall status** | {🟢 On track / 🟡 At risk / 🔴 Off track} |
| **Sprint goal** | {🟢 On track / 🟡 At risk / 🔴 Off track} **for goal** |

> {one-line RAG justification — burndown gap, WIP concentration, flow blockers, goal themes off track}

---

## Sprint Goal & Progress

{explicit goal as numbered/bulleted list OR inferred goal prefixed with *(inferred)*}

| Goal theme | Linked work | Total SP | Done SP | % done | Verdict |
|-----------|-------------|----------|---------|--------|---------|
| {theme1} | {Epic key or issue keys} | {themeTotalSP} | {themeDoneSP} | {themePct}% | {🟢/🟡/🔴 short note} |
| {theme2} | ... | ... | ... | ... | ... |

**Goal roll-up:** {goalDoneSP} of {goalTotalSP} SP done ≈ **{goalPctComplete}%** vs **{expectedPct}%** expected for elapsed time → **{🟢/🟡/🔴 overall goal verdict}**. {one sentence on which themes are dragging.}

---

## Progress Summary

| Metric | Value |
|--------|-------|
| Total SP | {totalSP} |
| Done SP | {doneSP} ({pctComplete}%) |
| In Progress SP | {inProgressSP} ({ipPct}%){flag if >40%: ⚠️} |
| To Do SP | {toDoSP} ({todoPct}%) |
| Issues | {issueCount} (Done {doneCount} / In Progress {ipCount} / To Do {todoCount}) |
| Unestimated issues | {unestimatedCount} |
| Tests excluded | {testExcludedCount} tickets, {testExcludedSP} SP ({testDoneCount} Done, informational) |

### Burndown

| | SP |
|-|-----|
| Ideal remaining | {idealRemaining} |
| Actual remaining | {actualRemaining} |
| Delta (actual − ideal) | {burndownDelta} ({burndownDeltaPct}% behind/ahead) |
| Expected completion | {expectedComplete}% |
| Actual completion | {actualComplete}% |
| Completion gap | {completionGap}% |

---

## Since Yesterday

{opening sentence: net assessment of the day — flat, forward, or regressive}

| Category | Details |
|----------|---------|
| ✅ Completed ({count}, {spCompleted} SP) | {SCL-XXX: summary (SP), ...} |
| ▶ Moved forward | {SCL-XXX: summary — e.g. → QA, → In-Review, started (SP)} |
| ◀ Moved backward / reopened | {SCL-XXX: summary — e.g. In-Progress→Open, QA→Open, Done→reopened (SP)} |
| ➕ Scope added to sprint | {SCL-XXX: summary (+SP), ... or "None"} |
| ➖ Scope removed | {SCL-XXX: summary (−SP), ... or "None"} |
| **Net flow** | +{spCompleted} SP done vs ~{spRegressed} SP regressed → {net assessment} |

---

## Aging / Stuck Tickets

{one-sentence bottleneck diagnosis — e.g. "N of M In-Progress items idle ≥2 business days, mostly in In-Review/QA since sprint start."}

| Key | Summary | SP | Status | Idle since |
|-----|---------|-----|--------|-----------|
| SCL-XXX | {summary truncated} | {sp or —} | {status name} | {date or "Jul 2"} |

{if no flagged issues: "No aging issues detected."}

---

## Estimation Notes

- **Unestimated:** {unestimatedCount} issues in committed scope — list keys if ≤5, else count + examples.
- **Mid-sprint changes:** {midSprintChanges count and keys, or "None"}.
- **Calibration:** {doneCount analyzed, under/over counts — or "Full cycle-time calibration not run; offer if user wants it."}
{if proposals exist: include Re-estimate Proposals sub-table from Step 5b}

---

## Recommendations

1. {Highest priority — usually clear review/QA queue or rescue off-track goal theme}
2. {Second — WIP limits, goal rescue, estimation}
3. {Third}
4. {Fourth}
5. {Fifth — max 5 total}

---

*Generated by the sprint-health skill via Atlassian MCP (board 231, active sprint id {activeSprintId}). Tests excluded by default.*

Want me to **save this to a file** (`sprint-health_SCL_{sprintName}_{YYYY-MM-DD}.md`), or **run the full estimation calibration** on completed tickets?
```

---

## MCP call examples

### Resolve cloudId

```
Tool: getAccessibleAtlassianResources
→ pick resource where url contains "inhabitiq.atlassian.net"
```

### Search sprint issues

```
Tool: searchJiraIssuesUsingJql
Arguments:
  cloudId: "https://inhabitiq.atlassian.net"
  jql: "project = SCL AND sprint = <activeSprintId> AND issuetype != Test"
  maxResults: 50
  fields: ["summary", "status", "statuscategory", "issuetype", "parent", "assignee", "customfield_10200", "customfield_10115", "priority", "labels"]
```

Do not request `description` or `*all`. Paginate with `nextPageToken`.

### Fetch changelog for aging

```
Tool: getJiraIssue
Arguments:
  cloudId: "https://inhabitiq.atlassian.net"
  issueIdOrKey: "SCL-123"
  expand: "changelog"
  fields: ["summary", "status", "customfield_10200"]
```

### Large-sprint parser fallback

When inline parsing is impractical (> 60 issues or > ~200 KB MCP response), run the versioned parser on saved JSON dumps:

```bash
python .cursor/skills/sprint-health/scripts/sprint_metrics.py \
  path/to/issues_page1.json path/to/issues_page2.json \
  --tests path/to/tests.json \
  --start 2026-07-02 --end 2026-07-16 --today 2026-07-07 \
  --format text
```

Options:
- `--include-tests` — count Test issues in SP totals (default: excluded)
- `--changelogs path/to/changelogs.json` — optional map `{ "SCL-123": { histories: [...] } }` for aging and day-to-day deltas
- `--format json` — machine-readable output

Paste the text output into the report; do not write ad-hoc parsers.

---

## Edge cases

| Scenario | Handling |
|----------|----------|
| No active sprint on board 231 | Stop; report clearly |
| totalSP = 0 | Use issue-count metrics; flag estimation gap |
| Multiple open sprints in project | Scope to board 231 only via `sprint = <activeSprintId>`; never use bare `openSprints()` |
| Backlog items (`empty` sprint) | Excluded from metrics; board filter includes them for grooming only |
| Sprint goal empty | Infer from Epics (mark as inferred); still compute Goal Progress with per-theme table if multiple inferred themes |
| Multi-part sprint goal | Split into themes; per-theme table + Goal roll-up (Step 6b) |
| Changelog too large | Process most recent 100 histories; note truncation |
| Issue without parent Epic | Group under "No Epic" |
| Test (Zephyr) issues | **Excluded by default** from all SP/metric totals; reported separately. Story+Test pairs double-count if included — e.g. SCL-13211 (Story 2 SP) + SCL-13273 (Test 5 SP) |
| User says "include tests" | Omit `issuetype != Test` from JQL; scope line shows "Tests included" |
| Sub-tasks with SP | Include in scoped totals (default); note if excluded |
| Weekend/holiday | Aging uses business days; burndown uses calendar days |
| No In Progress transition | Use `created` as cycle start; note in calibration table |
| Ticket re-opened after Done | Use most recent In Progress → Done cycle |
| No changelog history | Skip calibration for that issue; note "insufficient history" |
| Sub-task vs story | Include both in calibration; note issue type in proposals |
| No Epic peers for To Do | Skip Epic-calibrated proposal for that issue |
| SP = 0 on Done ticket | Classify as "Unestimated"; exclude from ratio averages |
| Equidistant Fibonacci | Round up to next Fibonacci value |
