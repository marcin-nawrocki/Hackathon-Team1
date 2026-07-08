# Sprint Health skill

Generates a changelog-backed sprint health report for the SCL JIRA board (**board 231 — The A Team**) using the Atlassian MCP server, bulk Jira REST changelog fetch, and a versioned local parser. The report leads with a TL;DR and prioritized, role-based recommendations, then covers sprint goal progress, day-to-day deltas, a bottleneck breakdown (In-Progress vs In-Review vs QA, longest-waiting queue, QA load concentration), and estimation calibration.

For workflow and prompts, see [`SKILL.md`](SKILL.md). JQL, burndown math, and the report template: [`references/reference.md`](references/reference.md).

## Requirements

| Requirement | Needed for | Notes |
|-------------|-----------|-------|
| **Python 3.9+** (3.11+ recommended) | Always | Runs `scripts/sprint_metrics.py`, `scripts/fetch_changelogs.py`, and `scripts/fetch_statuses.py`. Standard library only — **no pip packages**. |
| **Atlassian MCP server** | Always | `getAccessibleAtlassianResources` and `searchJiraIssuesUsingJql`. Must be connected in Cursor. |
| **Jira API token** (`jira-config.json`) | **Required** | Bulk changelog fetch. Copy from `jira-config.example.json`. Without it, the skill stops with setup instructions. |
| **Team roster** (`team-roster.json`) | Owner suggestions | Committed. Maps people to roles (testers + frontend explicit; everyone else is full-stack). Copy from `team-roster.example.json`. If absent, owner suggestions are omitted. |
| **Teams webhook** (`teams-config.json`) | Teams publish only | Opt-in. Copy from `teams-config.example.json`. |

```powershell
python --version   # expect 3.9+
Copy-Item .\jira-config.example.json .\jira-config.json   # then add token + email
```

## Quick start

In Cursor chat:

- `Sprint health` — full report (standup, burndown, aging, since-yesterday)
- `Sprint health — what changed since yesterday and are we on track for the sprint goal?`
- `Which tickets are stuck or running long?`
- `Propose re-estimates for To Do tickets` — adds Epic-calibrated To Do proposals (opt-in)
- `Sprint health, also generate a ROAST` — styled, data-driven HTML roast (opt-in add-on)

See [`SKILL.md`](SKILL.md#how-to-use-example-prompts) for show/include tests, save to file, post to Teams.

## Files

Standard [Agent Skills](https://cursor.com/docs/skills) layout: `SKILL.md`, `scripts/`, `references/`, `assets/`.

| File | Purpose | Committed? |
|------|---------|-----------|
| `SKILL.md` | Agent workflow | Yes |
| `references/reference.md` | JQL, burndown, report template | Yes |
| `scripts/fetch_statuses.py` | Fetch Jira statuses → `.sprint_tmp/jira-status-mapping.json` | Yes |
| `scripts/fetch_changelogs.py` | Bulk changelog via Jira REST | Yes |
| `scripts/sprint_metrics.py` | Metrics, deltas, themes, aging, bottleneck (requires `--changelogs`) | Yes |
| `scripts/render_roast.py` | Wrap the agent-authored roast body in the styled HTML shell (opt-in ROAST) | Yes |
| `references/roast.md` | ROAST voice, structure, award→metric mapping | Yes |
| `assets/roast-template.html` | Styled HTML shell for the ROAST output (CSS + tokens) | Yes |
| `assets/teams-card.json` | Single Teams Adaptive Card (summary + "Show more data" toggle) | Yes |
| `jira-config.example.json` | Jira token template | Yes |
| `team-roster.example.json` | Team roster template | Yes |
| `team-roster.json` | Team roster (roles for owner suggestions) | Yes |
| `teams-config.example.json` | Teams webhook template | Yes |
| `jira-config.json` | Your Jira credentials | **gitignored** |
| `teams-config.json` | Your Teams webhook | **gitignored** |

## Jira API token setup (required)

1. Create a token at <https://id.atlassian.com/manage-profile/security/api-tokens> (read access).
2. `Copy-Item .\jira-config.example.json .\jira-config.json` and fill in `email` + `apiToken`.
3. Verify: `python .\scripts\fetch_changelogs.py <issues.json> --output .sprint_tmp\changelogs.json`

## Team roster (owner suggestions)

`Copy-Item .\team-roster.example.json .\team-roster.json` (already committed). List testers and the frontend dev; everyone else is treated as full-stack. Used for the report's per-role owner suggestions. See [Team roster setup](SKILL.md#team-roster-setup-for-owner-suggestions) in `SKILL.md`.

## Teams publishing (optional)

`Copy-Item .\teams-config.example.json .\teams-config.json` and add your Power Automate webhook URL. Posts a single Adaptive Card with a summary and a "Show more data" toggle. See [Teams setup](SKILL.md#teams-publish-setup-one-time) in `SKILL.md`.
