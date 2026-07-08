# Sprint Health — ROAST reference

Guidance for the opt-in **ROAST** add-on: a styled, humorous HTML variant of the sprint-health report. The roast reuses the exact same `metrics.json` produced by the normal run — it changes the *voice and presentation*, never the numbers.

Rendered via [`scripts/render_roast.py`](../scripts/render_roast.py) + [`assets/roast-template.html`](../assets/roast-template.html). Reference example format: `sprint-health_ROAST_SCL_Sprint-56_2026-07-08.html`.

---

## Voice and rules

- **Tone:** "real data, zero mercy" — playful, sarcastic, emoji-heavy locker-room roast of the team's process (never a personal attack). Land the joke, then move on.
- **Numbers are sacred.** Every stat (SP, ticket counts, %, days, idle durations) MUST come from `metrics.json` (`metrics`, `deltas`, `bottleneck`, `themes`, `aging`). Never invent a number for a punchline. If a stat is not in the metrics, do not cite it.
- **Names:** roast the *situation*, and you may name a ticket's `assignee` when the metric ties to them (e.g. QA concentration, a regression), but keep it light and blame the process, not the person.
- **Always end constructive.** The final `.serious` block must give real, actionable advice — reuse the report's Top recommendations, with `[SCL-XXX]` browse links. The roast is motivation, not a hit piece.
- **English only**, same as the rest of the skill.
- **Escape** any user/summary text that contains `<`, `>`, or `&` when injecting into HTML.

---

## Required body structure (fills the `<!-- ROAST_BODY -->` marker, in order)

The `{{TITLE}}` (e.g. `🔥 THE A TEAM ROAST — {sprintName} 🔥`) and `{{SUBTITLE}}` (e.g. `Roast edition · {date} · Day {daysElapsed} of {sprintLength} working days · real data, zero mercy`) are supplied as `render_roast.py` args. The body fragment contains:

1. **Status pills** — one or two `<span class="pill">` quips summarizing overall + goal RAG.
2. **Intro `.banner`** — set the scene with the headline stat(s): SP done vs expected, burndown gap, and the biggest single embarrassment. Wrap key numbers in `<span class="stat">`.
3. **`🏆 Awards` (`<h2>`) + `.award` cards** — 3–5 cards. Each card: a `.title` with emoji + `<span class="who">` target, a one/two-sentence roast grounded in a metric, and a `.burn` italic kicker. See archetypes below.
4. **`😬 Scoreboard` table** — `Category | Reality | Roast`. Rows pull straight from metrics (see mapping). Use `td.c` + color helper classes (`.r`/`.o`/`.g`) on the Reality cell.
5. **`🧊 WIP, but make it honest` — `.wip` row of `.wipbox`** — the In-Progress-category split from `bottleneck`: dev-coding vs review vs QA, each a `.big` number with a color class.
6. **`.serious` block** — "Okay, seriously though" — bulleted real recommendations (from the report's Top recommendations) with `[SCL-XXX]` links, closing with a short encouraging line + days remaining.
7. **`.foot` footer** — one line noting it was generated from real Jira data (sprint id, board 231) and that it is all in good fun.

---

## Award archetypes → metric source

Pick the 3–5 that the data actually supports. Skip an award if its metric is empty (don't force it).

| Award | Emoji | Trigger metric | Roast angle |
|-------|-------|----------------|-------------|
| **The Houdini** | 🎩 | `deltas.regressed` / `deltas.sent_back` (+ `sp_regressed`/`sp_sent_back`) | A ticket that moved *backwards* — reopened or bounced from review/QA. |
| **Ghost Reviewers** | 👻 | `bottleneck.unassigned_in_review` (count + oldest `idle_since`) | In-Review tickets with no reviewer assigned, aging. |
| **The Atlas** | 🏋️ | top row of `bottleneck.qa_by_assignee` (name, sp, ticket count) | One person carrying a disproportionate QA load. |
| **Frozen In Time** | 🧊 | `bottleneck.stale_count` + longest `bottleneck.waiting` idle dates | Column that hasn't changed status in N business days. |
| **The Squirrel** | 🐿️ | `bottleneck` split: `in_progress_dev` vs `in_review` vs `qa` counts/SP | Lots started, little finished — "stop starting, start finishing." |
| **Flatliner** (optional) | 📉 | `deltas.sp_completed` = 0 over the window + `metrics.burndownDeltaPct` | Zero SP delivered while the burndown flatlines. |
| **The Optimist** (optional) | 🔮 | `aging` warning/critical + `metrics.unestimated` / mid-sprint SP changes | Estimates that aged badly, or 0-SP tickets distorting burndown. |

---

## Scoreboard row → metric source

| Row | Reality (from metrics) |
|-----|------------------------|
| Completed since {prevReportDate} | `deltas.sp_completed` SP |
| Burndown vs plan | `metrics.burndownDeltaPct` (behind/ahead), vs prior report if known |
| Sprint goal progress | goal roll-up % vs `expectedPct` (from `themes`/goal calc) |
| Actually being coded | `bottleneck.in_progress_dev.count` (out of `metrics.ipCount`) |
| Stuck in review/QA | `in_review.count + qa.count` |
| Unassigned reviews | `len(bottleneck.unassigned_in_review)` |

## WIP honest boxes → metric source

| Box | Value |
|-----|-------|
| actually coding | `bottleneck.in_progress_dev.count` (green) |
| begging for review | `bottleneck.in_review.count` (amber) |
| dumped on QA | `bottleneck.qa.count` (blue) |

---

## Output

- File name: `sprint-health_ROAST_SCL_{sprintName}_{YYYY-MM-DD}.html` (spaces in sprint name become `-`), written to the **workspace root** — mirrors the standard `.md` report name.
- Body fragment temp file: `.sprint_tmp/roast_body.html` (gitignored).
