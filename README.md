# Hackathon Team1 — Cursor Agent Skills

A repository of [Cursor Agent](https://cursor.com/docs/agent/skills) skills for the team. Skills extend the agent with ready-made workflows — copy the `.cursor/skills/` directory into your project or use this repo as the source.

## Requirements

- [Cursor](https://cursor.com/) with Agent enabled
- For **sprint-health**: Atlassian (JIRA) connection via MCP — Atlassian plugin in Cursor

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
- tracks progress toward the sprint goal (RAG status)
- compares day-to-day changes via the JIRA changelog
- flags tickets stuck in In Progress
- proposes re-estimates when story points drift from reality
- excludes Zephyr **Test** issues from SP metrics by default (say `include tests` to include them)

**Example prompts:**

| Goal | Prompt |
|------|--------|
| Full report | `Sprint health` |
| Changes since yesterday | `Sprint health — what changed since yesterday and are we on track for the sprint goal?` |
| Daily standup | `Prepare a daily standup summary` |
| Wrong estimates | `Which estimates are wrong? Propose re-estimates.` |

Full workflow, JQL, and report template: [`.cursor/skills/sprint-health/SKILL.md`](.cursor/skills/sprint-health/SKILL.md) and [reference.md](.cursor/skills/sprint-health/reference.md).

**Large-sprint parser** (> 60 tickets): [`scripts/sprint_metrics.py`](.cursor/skills/sprint-health/scripts/sprint_metrics.py) — used only as a fallback when the MCP response is too large.

## Repository structure

```
.cursor/skills/
└── sprint-health/
    ├── SKILL.md              # main agent instructions
    ├── reference.md          # JQL, burndown, report template
    └── scripts/
        └── sprint_metrics.py # metrics parser (large sprints)
```

## Contributing

Add new skills as subdirectories under `.cursor/skills/<skill-name>/` with a `SKILL.md` file (YAML frontmatter: `name`, `description`) following the [Cursor Skills documentation](https://cursor.com/docs/agent/skills).
