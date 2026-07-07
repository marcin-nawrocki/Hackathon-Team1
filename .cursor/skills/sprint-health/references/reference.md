# Sprint Health — Reference

Detailed JQL, changelog parsing, SP scale, burndown math, and report template.

---

## JQL snippets

**Prerequisite:** Resolve `activeSprintId` in Step 1 (active sprint on board 231). Use `sprint = <activeSprintId>` in all queries below — never bare `sprint in openSprints()` (project SCL has multiple concurrent active sprints on different boards).

**Backlog exclusion:** Board 231's saved filter includes `empty` (backlog) for grooming. Sprint-health metrics scope to the committed active sprint only; backlog items are excluded.

**Test handling (three modes):**

| Mode | JQL | Separate Test query |
|------|-----|---------------------|
| **Skip** (default) | `AND issuetype != Test` on metric JQL | Not run |
| **Show** | `AND issuetype != Test` on metric JQL | Run Test-only query for exclusion summary |
| **Include** | Omit `issuetype != Test` | Not needed |

Append `AND issuetype != Test` to all metric JQL below unless the user requests **"include tests"**. Run the Test-only query only when the user requests **"show tests"** (see SKILL.md Scope configuration).

### Active sprint issues (full pull — default scope)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
```

Include-tests variant:

```jql
project = SCL AND sprint = <activeSprintId>
```

### Test issues (show mode only — opt-in)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype = Test
```

### Historical sprint issues (point-in-time `--as-of`)

Use `fetch_sprints.py --as-of <YYYY-MM-DD>` to resolve the sprint active on that date, then:

```jql
project = SCL AND sprint = <sprintId> AND issuetype != Test
```

Jira's `Sprint` field is **cumulative** — `sprint = S` returns tickets ever in sprint S (including carryover now in a later sprint). The parser replays changelog `Sprint` entries to filter membership at the as-of date.

**Residual gap:** tickets manually removed from sprint S to backlog after the as-of date are no longer returned by `sprint = S` and cannot be recovered.

### Day-to-day delta (changelog — parser `deltas`)

Changelogs are bulk-fetched via [`scripts/fetch_changelogs.py`](../scripts/fetch_changelogs.py). The parser `deltas` block classifies events since cutoff (yesterday 00:00 UTC):

- **Completed:** status transition to Done
- **Moved forward:** transition into In Progress category
- **Regressed:** Done → reopened, or In Progress → To Do/Open (hard demotion)
- **Sent back:** review/QA status → earlier pipeline (e.g. In-Review → In-Progress, QA → In-Progress)
- **Scope added/removed:** Sprint field changes
- **SP changes:** Story Points field changes

Do **not** use `sprint CHANGED AFTER` JQL — it is rejected by the Atlassian MCP endpoint. Scope changes come from changelog `Sprint` field entries.

### In-progress issues (aging candidates)

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND statusCategory = "In Progress"
```

### Unestimated in-progress issues

```jql
project = SCL AND sprint = <activeSprintId> AND issuetype != Test
AND statusCategory = "In Progress"
AND "Story Points" is EMPTY
```

Replace `"Story Points"` with `customfield_10200` if the named field is not indexed.

### Epic peer lookup (batched — Step 5b.3, opt-in)

Collect Epic keys from **To Do** scoped issues, then one query (limit ~50):

```jql
project = SCL AND parent IN (<epicKey1>, <epicKey2>, ...) AND statusCategory = Done AND issuetype != Test ORDER BY updated DESC
```

Omit `issuetype != Test` when user requested include tests. Fetch peer changelogs with `fetch_changelogs.py`, then pass `--epic-peers` and `--peer-changelogs --todo-reestimates` to the parser.

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
- `daysElapsed` — **business days** (Mon-Fri) since sprint start through today (weekends excluded)
- `daysRemaining` — business days from today through sprint end
- `sprintLength` — business days from sprint start through sprint end (~10 for a 2-week sprint)

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

Map `toString` / `fromString` using `.sprint_tmp/jira-status-mapping.json` (fetched by `fetch_statuses.py` at the start of Step 3). Each SCL status has:

| Field | Meaning |
|-------|---------|
| `statusCategory` | Jira native category (To Do / In Progress / Done) |
| `sprintHealthBucket` | Parser bucket: `todo`, `in_progress`, `review_qa`, `done` |

**SCL buckets (25 statuses):**

| Bucket | Statuses |
|--------|----------|
| `todo` | Open, Groomed, Epic Concept, Epic Scoping, Initiative Approved, Initiative Ideation |
| `in_progress` | In-Progress, Blocked, Dev Done, Epic Definition/Development/Grooming/Scheduling, Initiative Committed |
| `review_qa` | In-Review, QA, User Acceptance Testing, Epic Testing |
| `done` | Done, Accepted, Deployed, Closed, Archive, Epic Complete, Initiative Closed |

Changelog deltas use buckets: **completed** → `done`; **started** → enter `in_progress` or `review_qa`; **sent back** → leave `review_qa` without reaching `done`; **regressed** → leave `done` or active work.

When the mapping file is missing a historical status name, the parser falls back to keyword heuristics (`review`, `qa`, `test`, etc.).

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

**Jira key links:** Render every Jira key as a markdown link: `[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX)`. Base URL derives from the configured `site` in `jira-config.json` (`inhabitiq.atlassian.net`).

```markdown
# Sprint Health Report — {sprintName}

| | |
|-|-|
| **Date** | {YYYY-MM-DD} |
| **Project / Board** | SCL / 231 (The A Team) |
| **Sprint** | {sprintName} ({startDate} → {endDate}) |
| **Days remaining** | {daysRemaining} (day {daysElapsed} of {sprintLength}) |
| **Scope** | {scope line — see below} |
| **Overall status** | {🟢 On track / 🟡 At risk / 🔴 Off track} |
| **Sprint goal** | {🟢 On track / 🟡 At risk / 🔴 Off track} **for goal** |

> {one-line RAG justification — burndown gap, WIP concentration, flow blockers, goal themes off track}

**Scope line variants:**

| Test mode | Scope line text |
|-----------|-----------------|
| Skip (default) | `Tests not fetched (skipped)` |
| Show | `Test issues excluded — {testExcludedCount} tickets, {testExcludedSP} SP` |
| Include | `Tests included in SP metrics` |

---

## Sprint Goal & Progress

{explicit goal as numbered/bulleted list OR inferred goal prefixed with *(inferred)*}

| Goal theme | Linked work | Total SP | Done SP | % done | Verdict |
|-----------|-------------|----------|---------|--------|---------|
| {theme1} | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX), ...} | {themeTotalSP} | {themeDoneSP} | {themePct}% | {🟢/🟡/🔴 short note} |
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
| Tests | {scope line or show-mode: {testExcludedCount} tickets, {testExcludedSP} SP ({testDoneCount} Done, informational)} |

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
| ✅ Completed ({count}, {spCompleted} SP) | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX): summary (SP), ...} |
| ▶ Moved forward | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX): summary — e.g. → QA, → In-Review, started (SP)} |
| ↩ Sent back from review/QA | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX) + SP from deltas.sent_back, or "None"} |
| ◀ Moved backward / reopened | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX) + SP from deltas.regressed, or "None"} |
| ➕ Scope added to sprint | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX): summary (+SP), ... or "None"} |
| ➖ Scope removed | {[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX) + SP from deltas.scope_removed, or "None"} |
| **Net flow** | +{spCompleted} SP done vs ~{spSentBack} SP sent back vs ~{spRegressed} SP regressed → {assessment} |

---

## Aging / Stuck Tickets

{one-sentence bottleneck diagnosis — e.g. "N of M In-Progress items idle ≥2 business days, mostly in In-Review/QA since sprint start."}

| Key | Summary | SP | Status | Idle since |
|-----|---------|-----|--------|-----------|
| [SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX) | {summary truncated} | {sp or —} | {status name} | {date or "Jul 2"} |

{if no flagged issues: "No aging issues detected."}

---

## Estimation Notes

- **Unestimated:** {unestimatedCount} issues in committed scope — list linked keys (`[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX)`) if ≤5, else count + examples.
- **Mid-sprint changes:** {midSprintChanges count and linked keys, or "None"}.
- **Calibration:** {doneCount analyzed, under/over counts}
{if To Do re-estimates requested: include proposals from parser todo_reestimates}

---

## Recommendations

1. {Highest priority — usually clear review/QA queue or rescue off-track goal theme}
2. {Second — WIP limits, goal rescue, estimation}
3. {Third}
4. {Fourth}
5. {Fifth — max 5 total}

---

*Generated by the sprint-health skill via Atlassian MCP + Jira bulk changelog (board 231, active sprint id {activeSprintId}). Tests skipped unless requested.*

Want me to **save this to a file** (`sprint-health_SCL_{sprintName}_{YYYY-MM-DD}.md`) or **post to Teams**?
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
  maxResults: 100
  responseContentFormat: "markdown"
  fields: ["summary", "status", "statuscategory", "issuetype", "parent", "assignee", "customfield_10200", "customfield_10115", "priority", "labels", "resolutiondate"]
```

Pass the auto-written output file path to `fetch_changelogs.py` and the parser. Temp JSON (status mapping, changelogs, metrics) goes to `.sprint_tmp/`.

### Fetch statuses (cached by runner)

```bash
python .cursor/skills/sprint-health/scripts/fetch_statuses.py \
  --config .cursor/skills/sprint-health/jira-config.json \
  --output .sprint_tmp/jira-status-mapping.json \
  [--max-age-days 7] [--force]
```

Standalone default (`--max-age-days 0`) always fetches. The runner uses `--max-age-days 7` by default.

### Fetch changelogs (required — bulkfetch)

```bash
python .cursor/skills/sprint-health/scripts/fetch_changelogs.py \
  <path-to-issues-json> \
  --config .cursor/skills/sprint-health/jira-config.json \
  --output .sprint_tmp/changelogs.json
```

Requires Jira API token in `jira-config.json`. One HTTP call for all sprint issues (up to 1000).

Use `--full` to omit the `fieldIds` filter (required for point-in-time `--as-of` replay of Sprint and Story Points).

### Resolve sprint for a date (historical)

```bash
python .cursor/skills/sprint-health/scripts/fetch_sprints.py \
  --as-of 2026-06-25 \
  --output .sprint_tmp/sprint.json
```

Prints `SPRINT_ID`, `START`, `END`, `GOAL`, and suggested JQL to stdout.

### Sprint report runner (preferred — one process, parallel I/O)

```bash
python .cursor/skills/sprint-health/scripts/sprint_report.py \
  <path-to-issues-json> [issues_page2.json ...] \
  --out .sprint_tmp/metrics.json \
  --start 2026-07-02 --end 2026-07-16 \
  [--today 2026-07-07] \
  [--as-of 2026-06-25 --sprint-id 14379 --sprint-name "SCL Sprint 55" --sprint-state closed] \
  [--tests <tests-json>] \
  [--theme "Sykes / release=sykes,SCL-3875"]
```

Options:
- `--status-max-age-days` — reuse cached status mapping (default 7; runner only)
- `--force-status` — ignore status cache
- `--full` — all changelog fields (auto-enabled with `--as-of`)
- `--include-tests` — count Test issues in SP totals
- `--theme LABEL=kw1,kw2` — goal theme rollup (repeatable)

### Sprint metrics parser (fallback — changelogs already on disk)

```bash
python .cursor/skills/sprint-health/scripts/sprint_metrics.py \
  <path-to-issues-json> \
  --changelogs .sprint_tmp/changelogs.json \
  --out .sprint_tmp/metrics.json \
  --start 2026-07-02 --end 2026-07-16 --today 2026-07-07 \
  [--tests <tests-json>] \
  [--theme "Sykes / release=sykes,SCL-3875"]
```

Options:
- `--changelogs` — **required**; map from `fetch_changelogs.py`
- `--status-mapping` — defaults to `.sprint_tmp/jira-status-mapping.json` from `fetch_statuses.py`
- `--out` — write JSON to file; stdout prints path + summary line
- `--tests` — show-mode Test dump
- `--include-tests` — count Test issues in SP totals
- `--theme LABEL=kw1,kw2` — goal theme rollup (repeatable)
- `--epic-peers` / `--peer-changelogs` / `--todo-reestimates` — To Do Epic calibration (opt-in)
- `--as-of YYYY-MM-DD` / `--sprint-id` / `--sprint-name` / `--sprint-state` — point-in-time report (requires `--full` changelogs)
- `--cutoff-end` — upper bound for deltas window (default: end of as-of day)

Read `.sprint_tmp/metrics.json`; do not re-run the parser for a different format.

---

## Point-in-time replay (`snapshot_at`)

When `--as-of` is set, the parser reconstructs each ticket's state at end-of-day UTC:

| Field | Replay source |
|-------|---------------|
| Status | Last `status` changelog entry with `created <= as_of`; if none, `fromString` of first future entry or current field |
| Story Points | Last `Story Points` / `customfield_10200` entry `<= as_of` |
| Sprint membership | Last `Sprint` / `customfield_10115` entry `<= as_of` (`to` field = cumulative sprint IDs) |

**Membership gate:** only tickets whose replayed `sprint_ids` contains `--sprint-id` are included in metrics. Excludes tickets added to the sprint after the as-of date and tickets not yet in the sprint on that date.

**Deltas window:** lower bound = previous day 00:00 UTC; upper bound = as-of day 23:59:59 UTC (`--cutoff-end`).

**Aging:** `now` = as-of day 12:00 UTC; days-in-status measured to last status transition `<= as_of`.

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
| Test (Zephyr) issues | **Skipped by default** (not fetched). Show mode: excluded from metrics but summarized. Include mode: in SP totals. Story+Test pairs double-count if included |
| User says "show tests" | Run Test-only query; scope line shows exclusion summary + QA coverage |
| User says "include tests" | Omit `issuetype != Test` from JQL; scope line shows "Tests included" |
| No Jira API token | Stop; instruct user to configure jira-config.json |
| Lite vs full mode | Removed — single changelog-backed flow only |
| `sprint CHANGED` JQL | Rejected by Atlassian MCP — use changelog `Sprint` field |
| MCP `fields` param | Additive only; baseline set (incl. `description`) always returned; never use `*all` |
| Shell budget | One parser run per report; ~20s overhead per Shell call in typical environments |
| Sub-tasks with SP | Include in scoped totals (default); note if excluded |
| Weekend/holiday | Aging uses business hours; burndown/expected % use business days (Mon-Fri, no holiday calendar) |
| No In Progress transition | Use `created` as cycle start; note in calibration table |
| Ticket re-opened after Done | Use most recent In Progress → Done cycle |
| No changelog history | Skip calibration for that issue; note "insufficient history" |
| Sub-task vs story | Include both in calibration; note issue type in proposals |
| No Epic peers for To Do | Skip Epic-calibrated proposal for that issue |
| SP = 0 on Done ticket | Classify as "Unestimated"; exclude from ratio averages |
| Equidistant Fibonacci | Round up to next Fibonacci value |
| Point-in-time `--as-of` | Use `fetch_sprints.py` + `sprint = <id>` JQL + parser `--as-of --sprint-id`; `--full` changelogs required |
| Ticket removed to backlog after as-of | Not returned by `sprint =` JQL; note in `as_of.membership_note` |
