---
name: sprint-health
description: >-
  Produces a changelog-backed sprint health report for the SCL JIRA board: auto-selects
  the active sprint, tracks progress toward the sprint goal, compares day-to-day changes
  via bulk changelog fetch, flags stuck tickets, and proposes re-estimates. Requires a
  Jira API token (jira-config.json). Zephyr Test issues are skipped by default (not fetched);
  say "show tests" for an exclusion summary or "include tests" to add them to SP metrics.
  Use when the user asks about sprint progress, sprint goal, burndown, daily standup,
  sprint health, SCL sprint, estimation accuracy, wrong estimate, re-estimate,
  story points, whether the team will hit the sprint goal, or posting sprint health
  to Microsoft Teams.
---

# Sprint Health

Generates a changelog-backed sprint health report for **board 231** (The A Team) using the Atlassian MCP server, bulk Jira REST changelog fetch, and the versioned parser [`scripts/sprint_metrics.py`](scripts/sprint_metrics.py).

**Requires** a Jira API token in [`jira-config.json`](jira-config.json) — see [Jira API token setup](#jira-api-token-setup-one-time). Without a valid token, stop and instruct the user to complete setup.

## How to use (example prompts)

Copy one of the prompts below into chat. Every prompt runs the **same full workflow** (changelog fetch + metrics + aging + estimation).

| You want… | Write this |
|-----------|------------|
| Daily standup / sprint health | `Sprint health` or `Prepare a daily standup summary` |
| Changes since yesterday + goal | `Sprint health — what changed since yesterday and are we on track for the sprint goal?` |
| Sprint goal only | `Are we on track for the sprint goal?` |
| Stuck / aging tickets | `Which tickets are stuck or running long?` |
| Wrong estimates (in-progress) | `Which estimates are wrong? Propose re-estimates.` |
| To Do re-estimates (Epic-calibrated) | `Propose re-estimates for To Do tickets` |
| Show Test exclusion summary | `Sprint health show tests` |
| Include Test tickets in SP | `Sprint health include tests` |
| Save report to file | Add: `Save the report to a file` |
| Generate a roast (HTML) | Add: `generate ROAST` or `also roast it` (styled HTML roast; opt-in add-on — see [Step 9](#step-9-roast-html-output-opt-in)) |
| Publish to Teams | Add: `Post the report to Teams` (single summary+toggle card; requires [Teams setup](#teams-publish-setup-one-time)) |
| Historical / point-in-time report | `Sprint health as of 2026-07-05` or `What did the sprint look like on Monday?` |

**Note:** By default, Zephyr **Test** issues are **not fetched** (saves one MCP round-trip). See [Scope configuration](#scope-configuration).

## Execution constraints

- **Always respond in English.** Produce the full report, all section text, and the Teams card content in English even when the user writes in another language.
- **Jira token required.** Before any Jira REST call, verify [`jira-config.json`](jira-config.json) exists and does not contain placeholder values (`YOUR-`). If missing, stop with setup instructions — do **not** fall back to MCP changelog fetch.
- **Always use the versioned parser.** After fetching MCP data and changelogs, run [`scripts/sprint_metrics.py`](scripts/sprint_metrics.py) **once** with `--changelogs` and `--out`. Read metrics from the output JSON file — do **not** compute metrics inline. Do **not** write one-off parsers per run.
- **Shell budget:** Each `Shell` invocation has ~20s fixed overhead. Run `sprint_report.py` in **one** shell call (replaces the former three-script chain). For historical reports, `fetch_sprints.py` remains a separate call (sprint id needed before MCP). Never re-run the parser to switch output format; use `--out` and read the file.
- **Never Read or Grep the full issue dump** in reasoning — let the parser consume it. Large MCP responses are written to agent-tools files automatically.
- **MCP payload:** Request only the named fields listed in Step 2. Set `responseContentFormat: "markdown"` to shrink descriptions. Never request `*all`. Use `maxResults: 100`, paginate with `nextPageToken`.
- **Resolve cloudId and active sprint once** in Step 1 and reuse for all subsequent MCP calls.
- **Scope strictly to board 231's active sprint** via `sprint = <activeSprintId>`. Never use bare `sprint in openSprints()` for metrics.

## Report sections (every run)

In this order: title + sub-line + dual RAG status, TL;DR, one-line verdict, **Top recommendations** (with role-based owners), Team roster line, What matters most, Sprint goal progress, Progress & burndown, Since yesterday (from parser `deltas`), Bottleneck (from parser `bottleneck` — In-Progress vs In-Review vs QA split, longest-waiting review/QA, QA load concentration), Estimation & method notes (unestimated, mid-sprint changes, calibration/in-progress re-estimates from aging, method notes), footer.

Recommendations lead the report (right after the verdict); detailed metrics follow. Owner suggestions come from `team-roster.json` (Step 0b). Use the report template in [references/reference.md](references/reference.md).

**To Do Epic-calibrated re-estimates (Step 5b.3)** run only when the user explicitly asks (e.g. "propose re-estimates for To Do", "Epic-calibrated estimates").

## Fixed configuration

| Setting | Value |
|---------|-------|
| Site | `inhabitiq.atlassian.net` |
| Project | `SCL` |
| Board | `231` |
| Story Points field | `customfield_10200` |
| Sprint field | `customfield_10115` |

**Cloud ID:** Resolve once via `getAccessibleAtlassianResources` for `inhabitiq.atlassian.net`, or pass `https://inhabitiq.atlassian.net` directly as `cloudId`.

## Scope configuration

**Default:** Exclude Zephyr **Test** issues (`issuetype = Test`) from metrics and **do not fetch** Test issues.

| Mode | Trigger | JQL filter | Test query | Scope line in report |
|------|---------|------------|------------|----------------------|
| **Skip** (default) | (none) | `AND issuetype != Test` | **Not run** | `Tests not fetched (skipped)` |
| **Show** | `show tests`, `exclude tests summary` | `AND issuetype != Test` | Lightweight fetch | `Test issues excluded — {count} ticket(s), {sp} SP` |
| **Include** | `include tests` | Omit `issuetype != Test` | Not needed | `Tests included in SP metrics` |

## Quick start

When invoked, detect **test mode** (skip vs show vs include), whether **To Do re-estimates** (5b.3) are requested, and whether a **ROAST** (Step 9, opt-in HTML add-on) is requested. Run the workflow below.

```
Task Progress:
- [ ] Step 0: Verify Jira API token (jira-config.json)
- [ ] Step 0b: Read team-roster.json (for role-based owner suggestions)
- [ ] Step 1: Resolve cloudId and active sprint
- [ ] Step 2: Pull all sprint issues (+ optional Test query if show mode)
- [ ] Step 3: Bulkfetch changelogs + run parser (one shell call)
- [ ] Step 4: Day-to-day delta (from parser deltas)
- [ ] Step 5: Aging analysis (from parser aging)
- [ ] Step 5a: Bottleneck breakdown (from parser bottleneck)
- [ ] Step 5b: Estimation accuracy (from parser + changelogs; 5b.3 opt-in)
- [ ] Step 6: Infer sprint goal and compute goal progress
- [ ] Step 7: Emit report with RAG status (recommendations first, role-based owners)
- [ ] Step 8: Publish to Teams (opt-in only)
- [ ] Step 9: Generate ROAST HTML (opt-in only)
```

---

## Step 0: Verify Jira API token

1. Read `.cursor/skills/sprint-health/jira-config.json`.
2. If the file is missing, tell the user to copy [`jira-config.example.json`](jira-config.example.json) to `jira-config.json` and complete [Jira API token setup](#jira-api-token-setup-one-time). **Stop.**
3. If `email` or `apiToken` is empty or contains `YOUR-`, **stop** with the same instructions.
4. Do **not** proceed without a valid token. Do **not** use MCP `getJiraIssue expand=changelog` as a fallback.

---

## Step 0b: Read team roster (for owner suggestions)

1. Read `.cursor/skills/sprint-health/team-roster.json`. If missing, fall back to [`team-roster.example.json`](team-roster.example.json); if neither exists, **omit** the "Suggested owners" column and the "Team roster used for suggestions" line (do not stop).
2. **Role resolution** for any person (Jira `assignee.displayName`):
   - name in `testers` → **Tester**
   - name in `frontend` → **Frontend**
   - otherwise → **`defaultRole`** (full-stack) — this covers every other dev without enumerating them.
3. Use roles to author the **Suggested owners (by role)** column in Top recommendations (Step 7): off-load QA from an overloaded tester to other testers; assign reviewers/dev work to full-stack devs; route frontend/CSS work to the frontend dev.
4. Render the **Team roster used for suggestions** line: list testers and frontend explicitly, describe full-stack as "all other contributors" (optionally naming the devs seen in the current sprint scope). A current assignee outside the roster (e.g. a non-team member) is treated as full-stack for suggestions but may be noted as "current assignee only".

---

## Step 1: Resolve cloudId and active sprint

1. Call `getAccessibleAtlassianResources` and select the resource for `inhabitiq.atlassian.net`.
2. Discovery query:

```
cloudId: <resolved>
jql: project = SCL AND sprint in openSprints()
maxResults: 1
fields: ["customfield_10115"]
```

3. Parse `customfield_10115`. Select the sprint where **`state === "active"` AND `boardId === 231`**.
4. Retain: **`activeSprintId`**, `name`, `startDate`, `endDate`, `goal`.

If no active sprint on board 231, stop: *No active sprint found for board 231 (The A Team).*

### Historical variant (point-in-time `--as-of`)

When the user requests a report **as of a specific date** (e.g. "Sprint health as of 2026-07-05"):

1. Run [`scripts/fetch_sprints.py`](scripts/fetch_sprints.py) with `--as-of <YYYY-MM-DD>` to select the sprint active on that date (may be **closed**).
2. Retain: `sprint_id`, `name`, `state`, `start`, `end`, `goal` from script output.
3. Use that sprint's date window for `--start` / `--end` in the parser (not the current active sprint).

---

## Step 2: Pull all sprint issues

Call `searchJiraIssuesUsingJql` with pagination until all issues are fetched. Pass the auto-written MCP output path to the parser — do not copy to `.sprint_tmp/`.

```
cloudId: <resolved>
jql: project = SCL AND sprint = <activeSprintId> AND issuetype != Test
maxResults: 100
responseContentFormat: "markdown"
fields: ["summary", "status", "statuscategory", "issuetype", "parent", "assignee", "customfield_10200", "customfield_10115", "priority", "labels", "resolutiondate"]
```

**Include-tests variant:** omit `issuetype != Test` when requested.

**Show-tests variant:** run the main pull plus the Test-only query from [Scope configuration](#scope-configuration).

**Historical variant:** use `sprint = <sprintId>` from `fetch_sprints.py --as-of` (cumulative JQL — returns tickets ever in that sprint). Parser membership gate replays changelog `Sprint` field to include only tickets that were in the sprint on the as-of date.

---

## Step 3: Bulkfetch changelogs and run parser (one shell call)

Run [`scripts/sprint_report.py`](scripts/sprint_report.py) in a **single** shell invocation. It fetches statuses (with 7-day cache) and changelogs **in parallel**, then runs the parser in-process:

```powershell
New-Item -ItemType Directory -Force -Path .sprint_tmp | Out-Null
python .cursor/skills/sprint-health/scripts/sprint_report.py `
  <path-to-MCP-issues-output.json> `
  [--path-to-MCP-issues-page2.json ...] `
  --out .sprint_tmp/metrics.json `
  --start <startDate YYYY-MM-DD> --end <endDate YYYY-MM-DD> `
  [--today <today YYYY-MM-DD>] `
  [--tests <tests-output.json>] [--include-tests] `
  [--theme "Sykes / release=sykes,SCL-3875"] `
  [--theme "Adyen R&D=adyen,pico,supercontrol pay"] `
  [--theme "VRBO=vrbo,SCL-12933"]
```

**Historical variant** — pass `--as-of` (implies `--full` changelog fetch):

```powershell
New-Item -ItemType Directory -Force -Path .sprint_tmp | Out-Null
python .cursor/skills/sprint-health/scripts/fetch_sprints.py --as-of <YYYY-MM-DD> --output .sprint_tmp/sprint.json
python .cursor/skills/sprint-health/scripts/sprint_report.py `
  <path-to-MCP-issues-output.json> `
  [--path-to-MCP-issues-page2.json ...] `
  --out .sprint_tmp/metrics.json `
  --start <sprintStart YYYY-MM-DD> --end <sprintEnd YYYY-MM-DD> `
  --as-of <YYYY-MM-DD> --sprint-id <sprintId> `
  --sprint-name "<sprintName>" --sprint-state <active|closed> `
  [--theme ...]
```

`--full` (or `--as-of`) fetches all changelog fields (required for Sprint/SP replay). Status mapping is cached for 7 days (`--status-max-age-days`, `--force-status` to refresh).

The runner prints `WROTE .sprint_tmp/metrics.json` and a one-line `SUMMARY`. **Read** `.sprint_tmp/metrics.json` for all metrics — do not re-run the parser.

**Fallback:** the individual scripts [`fetch_statuses.py`](scripts/fetch_statuses.py), [`fetch_changelogs.py`](scripts/fetch_changelogs.py), and [`sprint_metrics.py`](scripts/sprint_metrics.py) remain available for debugging or partial runs.

### Optional: To Do re-estimates (Step 5b.3)

Only when the user explicitly requests To Do / Epic-calibrated re-estimates:

1. From scoped issues, collect parent Epic keys for **To Do** tickets.
2. One batched JQL (limit ~50 peers):

```
project = SCL AND parent IN (<epicKey1>, <epicKey2>, ...) AND statusCategory = Done AND issuetype != Test ORDER BY updated DESC
```

3. Save peer issues JSON, run `fetch_changelogs.py` on it → `.sprint_tmp/peer_changelogs.json`.
4. Re-run parser (can chain with existing changelogs file):

```powershell
python .cursor/skills/sprint-health/scripts/sprint_metrics.py `
  <path-to-MCP-issues-output.json> `
  --changelogs .sprint_tmp/changelogs.json `
  --out .sprint_tmp/metrics.json `
  --start ... --end ... --today ... `
  --epic-peers <path-to-peer-issues.json> `
  --peer-changelogs .sprint_tmp/peer_changelogs.json `
  --todo-reestimates `
  [--theme ...]
```

Read `todo_reestimates` and `epic_median_ratios` from the JSON output.

### Parser JSON output

| Block | Contents |
|-------|----------|
| `metrics` | Total/Done/IP/To Do SP, burndown, days elapsed/remaining |
| `deltas` | Changelog-based since-yesterday: completed, started, sent_back, regressed, scope changes, SP changes |
| `themes` | Per-theme SP rollup when `--theme` passed |
| `top_epics` | Top 12 epics by score |
| `aging` | Stuck/over-running flags from changelogs |
| `bottleneck` | In-Progress-category status split: `in_progress_dev` / `in_review` / `qa` (count, sp, issue lists w/ assignee + `idle_since`), `waiting` (longest-idle review/QA, w/ `queue`), `qa_by_assignee`, `unassigned_in_review`, `stale_count`. Also mirrored as `in_progress_dev_count/sp`, `in_review_count/sp`, `qa_count/sp` in `metrics`. |
| `todo_reestimates` | Epic-calibrated To Do proposals (only with `--todo-reestimates`) |
| `as_of` | Point-in-time metadata (only with `--as-of`): date, sprint, membership counts |

See [references/reference.md](references/reference.md) for burndown math and RAG thresholds.

---

## Step 4: Day-to-day delta

Use parser `deltas` block (cutoff: yesterday 00:00 UTC).

| Category | Source |
|----------|--------|
| Completed | `deltas.completed` (+ `sp_completed`) |
| Moved forward | `deltas.started` |
| Sent back from review/QA | `deltas.sent_back` (+ `sp_sent_back`) |
| Moved backward / reopened | `deltas.regressed` (+ `sp_regressed`) |
| Scope added / removed | `deltas.scope_added` / `deltas.scope_removed` |
| SP changed mid-sprint | `deltas.sp_changes` |
| **Net flow** | `+{sp_completed} SP done vs ~{sp_sent_back} SP sent back vs ~{sp_regressed} SP regressed → {assessment}` |

See [references/reference.md](references/reference.md) for changelog parsing rules.

---

## Step 5: Aging analysis

Use parser `aging` block. For each flagged In Progress issue: key, summary, SP, status, idle duration, ratio, severity flag.

**Flag thresholds:** Warning >1.5×, Critical >2.0×, Stale ≥2 days idle, Unestimated risk (SP=0, >1 day).

Add a one-sentence bottleneck diagnosis (e.g. review/QA queue).

---

## Step 5a: Bottleneck breakdown

Use parser `bottleneck` block to render the "⛔ Bottleneck" section:

- Show the status split of the In-Progress category: `in_progress_dev.count` (dev coding) vs `in_review.count` vs `qa.count`.
- List the `in_progress_dev.issues` (key, SP, assignee).
- Build the **Longest-waiting review/QA** table from `bottleneck.waiting` (longest-idle first): key, summary, SP, `queue` (In-Review/QA), assignee, `idle_since` (format ISO date as "Mon D"). `stale_count` = how many have been idle ≥2 business days.
- Call out unassigned reviewers from `unassigned_in_review` and QA concentration from the top `qa_by_assignee` row (assignee holding a disproportionate SP share). Feed both into the Top recommendations (Step 7) with roster-based owners.

---

## Step 5b: Estimation accuracy and proposals

Reuse changelogs from Step 3. See [references/reference.md](references/reference.md) for cycle time rules and Fibonacci mapping.

### 5b.1 Completed tickets (calibration)

From changelogs: cycle start = first In Progress transition; cycle end = Done. Compare `actualHours / expectedHours`. Verdict: >1.5 underestimated, 0.5–1.5 accurate, <0.5 overestimated.

### 5b.2 In-progress tickets (re-estimate proposals)

Extend Step 5 `aging` data with suggested SP when ratio >1.3 or <0.6.

### 5b.3 To Do tickets (Epic-calibrated) — opt-in only

Run only when user explicitly requests. Use batched `parent IN (...)` JQL and parser `--todo-reestimates`. Read `todo_reestimates` from metrics JSON.

### 5b.4 Mid-sprint estimate changes

From `deltas.sp_changes` where change occurred after first In Progress transition.

### 5b.5 Sprint-level estimation summary

Aggregate underestimated %, `totalSuggestedSPDelta`, `estimatesChangedMidSprint`.

---

## Step 6: Infer sprint goal and compute goal progress

Same as before — use `themes` from parser when multi-part goal; per-theme RAG; goal roll-up = worst theme verdict.

See [references/reference.md](references/reference.md) for goal inference algorithm.

---

## Step 7: Report with RAG status

Determine **two independent RAG statuses** — overall sprint health and sprint goal. See [references/reference.md](references/reference.md) decision matrix.

| Status | Criteria (any triggers) |
|--------|-------------------------|
| **On track** | Burndown delta ≤ 10% AND no critical aging AND ≥ expected % complete |
| **At risk** | Burndown 10–25% behind OR 1+ warning aging OR scope grew >10% yesterday OR underestimation >50% with burndown behind |
| **Off track** | Burndown >25% behind OR 1+ critical aging OR 0 SP in 2 business days with >50% elapsed OR net suggested SP delta >15% of remaining |

**Always include (in this order — see the template in [references/reference.md](references/reference.md)):**

1. Title + sub-line (date · working days · sprint id) + dual RAG status line (for `--as-of`: prefix with **As of {date}** and show sprint state; include `as_of.membership_note` if present)
2. **TL;DR** narrative + **one-line verdict**
3. **Top recommendations** (max 5, priority-emoji ordered) with **Suggested owners (by role)** from the roster (Step 0b) — omit the owners column only if no roster
4. **Team roster used for suggestions** line
5. **What matters most** (3–6 bullets)
6. **Sprint goal progress** (themes table + roll-up)
7. **Progress & burndown** (combined Metric/Value/Note table)
8. **Since yesterday** (full `deltas` detail + net flow)
9. **Bottleneck** (from Step 5a: status split, In-Progress dev list, longest-waiting review/QA table, QA load concentration)
10. **Estimation & method notes** (unestimated, mid-sprint changes, progress basis, excluded tests, "In Progress" counts clarification, overall verdict; To Do proposals if 5b.3 ran)
11. Footer + closing offer — save file and/or post to Teams
12. **Jira key links** — render every ticket/epic key as a markdown browse link: `[SCL-XXX](https://inhabitiq.atlassian.net/browse/SCL-XXX)` (base URL from `jira-config.json` `site`)

Use the report template from [references/reference.md](references/reference.md).

---

## Jira API token setup (one-time)

**Required** for every sprint-health run.

1. Create a token at [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) (read access to Jira work items).
2. Copy the example config:

```powershell
Copy-Item .\.cursor\skills\sprint-health\jira-config.example.json .\.cursor\skills\sprint-health\jira-config.json
```

3. Edit `jira-config.json` (gitignored):

```json
{
  "site": "inhabitiq.atlassian.net",
  "email": "you@supercontrol.co.uk",
  "apiToken": "your-token-here"
}
```

4. Verify:

```powershell
python .\.cursor\skills\sprint-health\scripts\fetch_changelogs.py `
  <path-to-issues-json> `
  --output .\.sprint_tmp\changelogs.json
```

---

## Team roster setup (for owner suggestions)

The report's **Suggested owners (by role)** column and the **Team roster** line read `team-roster.json` (committed). List only testers and the frontend dev; everyone else resolves to `defaultRole` (full-stack) automatically:

```json
{
  "testers": ["Aleksandra Małolepsza", "Krystyna Fabianowska", "Izabela Wojtczak", "Szymon Bartylak"],
  "frontend": ["Bartłomiej Rzemieniewski"],
  "defaultRole": "full-stack"
}
```

Copy [`team-roster.example.json`](team-roster.example.json) to `team-roster.json` and edit as the team changes. If neither file exists, the skill still runs but omits named owners (Step 0b).

---

## Teams publish setup (one-time)

See existing workflow in this file (unchanged). Template: [`assets/teams-card.json`](assets/teams-card.json) — a single Adaptive Card with an always-visible summary and a **Show more data** toggle that reveals the detailed sections.

**Layout (v2 — structured):** the card uses **`ColumnSet` "tables"** (header row + one row per item), **`FactSet`** for key/value blocks (Progress & burndown, Since-yesterday counters), and **colored RAG `Container`s** for the dual status header. Native Adaptive `Table` elements are intentionally **not** used — they render blank on iOS/mobile Teams clients. Card version stays `1.5`.

---

## Step 8: Publish to Teams (opt-in)

Run only when the user asks to post/publish/send to Teams. There is **one** card: [`assets/teams-card.json`](assets/teams-card.json). It shows a summary (status, TL;DR/verdict, goal roll-up, what-matters, top 3 recommendations) always, plus an `Action.ToggleVisibility` button ("Show more data") that expands a hidden container holding the full detail (goal theme table, progress & burndown, since-yesterday, bottleneck split, longest-waiting, all recommendations).

**Structured-row rule:** the goal-theme table, longest-waiting table, and all-recommendations table are `ColumnSet` "tables" — a **header** `ColumnSet` followed by **one data `ColumnSet` per item**. The template ships with example rows (3 themes, 5 waiting, 5 recs); when building the payload, **add or delete `ColumnSet` rows** so the count matches the actual data. Do not leave unfilled placeholder rows in the posted card. Keep RAG/priority cells colored via `TextBlock` `color` (`Good`/`Warning`/`Attention`).

Substitute placeholders from the Step 7 report:

- **RAG header:** `{{ragEmoji}}`, `{{overallStatus}}`, `{{goalStatus}}`, plus `{{overallStyle}}`/`{{goalStyle}}` (Container style: `good`/`warning`/`attention`) and `{{overallColor}}`/`{{goalColor}}` (TextBlock color: `Good`/`Warning`/`Attention`).
- **Summary:** `{{sprintName}}`, `{{sprintStateSuffix}}` (e.g. " · sprint closed" or ""), `{{daysElapsed}}`, `{{sprintLength}}`, `{{daysRemaining}}`, `{{tldr}}`, `{{oneLineVerdict}}`, `{{goalDoneSP}}`/`{{goalTotalSP}}`/`{{goalPct}}`/`{{expectedPct}}`/`{{goalVerdictEmoji}}`, `{{whatMattersBody}}` (bulleted text), and top-3 recs `{{rec1Prio}}`/`{{rec1Text}}` … `{{rec3Text}}`.
- **Goal theme rows:** per theme `{{themeNName}}`, `{{themeNSP}}` (done/total), `{{themeNPct}}`, `{{themeNEmoji}}`, `{{themeNColor}}`.
- **Progress & burndown (FactSet):** `{{totalSP}}`, `{{issueCount}}`, `{{doneSP}}`, `{{pctComplete}}`, `{{doneCount}}`, `{{inProgressSP}}`, `{{ipPct}}`, `{{ipCount}}`, `{{wipWarning}}`, `{{toDoSP}}`, `{{todoPct}}`, `{{todoCount}}`, `{{actualRemaining}}`, `{{idealRemaining}}`, `{{burndownDeltaPct}}`, `{{unestimatedCount}}`, `{{testsLine}}`.
- **Since yesterday (FactSet + note):** `{{prevReportDate}}`, `{{completedCount}}`, `{{spCompleted}}`, `{{startedCount}}`, `{{sentBackCount}}`, `{{spSentBack}}`, `{{regressedCount}}`, `{{spRegressed}}`, `{{scopeLine}}`, `{{sinceYesterdayNotable}}` (notable keys).
- **Bottleneck:** `{{devCount}}`/`{{devSP}}`, `{{reviewCount}}`/`{{reviewSP}}`, `{{qaCount}}`/`{{qaSP}}`; longest-waiting rows `{{waitNKey}}`/`{{waitNQueue}}`/`{{waitNIdle}}`; `{{bottleneckNote}}` (unassigned reviewers + QA concentration).
- **All recommendations rows:** `{{recNPrio}}` (colored emoji) + `{{recNFull}}` (action with owners).
- **Footer:** `{{rosterLine}}`.

---

## Step 9: ROAST HTML output (opt-in)

Run only when the user asks to **roast** the sprint (e.g. "generate ROAST", "also roast it"). This is an **add-on** — it does not run its own data pull. It reuses the same `metrics.json` from Step 3, so complete Steps 1–6 first (a full report in Step 7 is not required, but the metrics must exist).

The roast is a styled, humorous HTML variant of the report. Read [`references/roast.md`](references/roast.md) for the voice, required body structure, and the award→metric mapping.

1. **Author the body fragment.** From `metrics.json` (`metrics`, `deltas`, `bottleneck`, `themes`, `aging`), write the roast body HTML — status pills, intro `.banner`, 3–5 `.award` cards, `😬` scoreboard table, `🧊` honest-WIP `.wipbox` row, a constructive `.serious` block (reuse the Top recommendations with `[SCL-XXX]` browse links), and a `.foot` footer. **Every number must come from the metrics** — never invent a stat for a punchline. Escape `<`, `>`, `&` in any injected text. Save the fragment to `.sprint_tmp/roast_body.html`.
2. **Render** the full HTML by wrapping the fragment in the shared shell:

```powershell
python .cursor/skills/sprint-health/scripts/render_roast.py `
  --title "🔥 THE A TEAM ROAST — <sprintName> 🔥" `
  --subtitle "Roast edition · <YYYY-MM-DD> · Day <daysElapsed> of <sprintLength> working days · real data, zero mercy" `
  --body .sprint_tmp/roast_body.html `
  --out "sprint-health_ROAST_SCL_<sprintName-with-dashes>_<YYYY-MM-DD>.html"
```

3. The script prints `WROTE <path>`. The output HTML is written to the **workspace root** (mirrors the standard `.md` report name). Tell the user where it landed and offer to open it.

**Rules:** Roast the *process/situation*, not people; always end constructive; English only.

---

## MCP tools used

| Tool | Purpose |
|------|---------|
| `getAccessibleAtlassianResources` | Resolve cloudId |
| `searchJiraIssuesUsingJql` | Fetch sprint issues (+ optional Epic peers for 5b.3) |

Local scripts:

| Script | Purpose |
|--------|---------|
| [`scripts/sprint_report.py`](scripts/sprint_report.py) | **Primary runner** — parallel status/changelog fetch + metrics (Step 3) |
| [`scripts/fetch_statuses.py`](scripts/fetch_statuses.py) | Fetch SCL statuses → `.sprint_tmp/jira-status-mapping.json` (cached; used by runner) |
| [`scripts/fetch_sprints.py`](scripts/fetch_sprints.py) | Resolve sprint for a date (`--as-of`) via Agile API |
| [`scripts/fetch_changelogs.py`](scripts/fetch_changelogs.py) | Bulk changelog via REST (used by runner; `--full` for `--as-of`) |
| [`scripts/sprint_metrics.py`](scripts/sprint_metrics.py) | Metrics parser (`build_result`); standalone fallback when changelogs already fetched |
| [`scripts/render_roast.py`](scripts/render_roast.py) | Wrap the agent-authored roast body in the styled HTML shell (Step 9, opt-in) |

## Additional resources

- JQL, changelog parsing, SP scale, burndown, report template: [references/reference.md](references/reference.md)
- ROAST voice, structure, and award→metric mapping: [references/roast.md](references/roast.md); template: [assets/roast-template.html](assets/roast-template.html)
- Teams card (single summary+toggle): [assets/teams-card.json](assets/teams-card.json)
- Config templates: [jira-config.example.json](jira-config.example.json), [teams-config.example.json](teams-config.example.json), [team-roster.example.json](team-roster.example.json)
- Team roster (committed): [team-roster.json](team-roster.json) — testers + frontend explicit, full-stack is the default role (Step 0b)
- Temp files: `.sprint_tmp/` (gitignored)
