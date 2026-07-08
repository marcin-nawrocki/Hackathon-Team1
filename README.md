# Hackathon Team1 — Cursor Agent Skills

A repository of [Cursor Agent](https://cursor.com/docs/skills) skills for the team. Skills extend the agent with ready-made workflows — copy the `.cursor/skills/` directory into your project or use this repo as the source.

## Requirements

- [Cursor](https://cursor.com/) with Agent enabled
- For **sprint-health**:
  - Atlassian (JIRA) connection via MCP — Atlassian plugin in Cursor
  - **Python 3.9+** (3.11+ recommended) — standard library only, no pip install
  - **Jira API token** (`jira-config.json`) — **required** for bulk changelog fetch
  - *(optional)* Microsoft Teams / Power Automate webhook — only for publishing to Teams

See [`.cursor/skills/sprint-health/README.md`](.cursor/skills/sprint-health/README.md) for the full per-skill requirements and setup.

## Installation

Clone this repository or copy the contents of `.cursor/skills/` into your project root:

```
your-project/
└── .cursor/
    └── skills/
        └── sprint-health/
```

Cursor automatically discovers skills from `.cursor/skills/`.

## Available skills

### sprint-health

Daily sprint health report for JIRA board **SCL / board 231** (The A Team).

**What it does:**

- selects the active sprint on board 231
- tracks progress toward the sprint goal (dual RAG: overall health + goal)
- reports day-to-day changes from JIRA changelogs (bulk REST fetch)
- flags tickets stuck in In Progress and proposes re-estimates when story points drift
- excludes Zephyr **Test** issues from SP metrics by default (say `include tests` to include them)
- *(optional)* publishes a summary or full Adaptive Card to Microsoft Teams

**Requires** a Jira API token in `jira-config.json` — see the skill README for setup.

**Example prompts:**

| Goal | Prompt |
|------|--------|
| Sprint health / standup | `Sprint health` |
| Changes since yesterday + goal | `Sprint health — what changed since yesterday and are we on track for the sprint goal?` |
| Stuck tickets | `Which tickets are stuck or running long?` |
| Wrong estimates | `Which estimates are wrong? Propose re-estimates.` |
| To Do re-estimates | `Propose re-estimates for To Do tickets` |
| Post to Teams | add `Post the report to Teams` |

Full workflow: [`.cursor/skills/sprint-health/SKILL.md`](.cursor/skills/sprint-health/SKILL.md) and [reference.md](.cursor/skills/sprint-health/references/reference.md).

**Pipeline:** `fetch_statuses.py` + `fetch_changelogs.py` + `sprint_metrics.py` (one chained shell run) → `.sprint_tmp/metrics.json`.

## Repository structure

Following the standard [Agent Skills](https://cursor.com/docs/skills) layout (`scripts/`, `references/`, `assets/`):

```
.cursor/skills/
└── sprint-health/
    ├── SKILL.md                    # main agent instructions
    ├── README.md                   # skill overview, requirements, setup
    ├── jira-config.example.json    # template for Jira API token (required)
    ├── team-roster.example.json    # template for team roster (owner suggestions)
    ├── team-roster.json            # team roster: roles for owner suggestions (committed)
    ├── teams-config.example.json   # template for Teams webhook (publishing)
    ├── scripts/
    │   ├── sprint_metrics.py       # metrics parser (requires changelogs)
    │   ├── fetch_changelogs.py     # bulk changelog fetch (required)
    │   └── fetch_statuses.py       # Jira status mapping (every run)
    ├── references/
    │   └── reference.md            # JQL, burndown, report template (on-demand)
    └── assets/
        └── teams-card.json         # Teams Adaptive Card (summary + "Show more data" toggle)
```

Local config files `jira-config.json` and `teams-config.json` are created from the `*.example.json` templates and are **gitignored** (never committed). `team-roster.json` is committed.

## Contributing

Add new skills as subdirectories under `.cursor/skills/<skill-name>/` with a `SKILL.md` file (YAML frontmatter: `name`, `description`) following the [Cursor Skills documentation](https://cursor.com/docs/skills).
