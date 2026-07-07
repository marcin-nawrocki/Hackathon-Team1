#!/usr/bin/env python3
"""Sprint Health metrics parser — versioned fallback for large sprint MCP dumps.

Usage:
  python sprint_metrics.py issues_page1.json [issues_page2.json ...] \\
    --start 2026-07-02 --end 2026-07-16 [--today 2026-07-07] \\
    [--tests tests.json] [--include-tests] [--format text|json]

Defaults: exclude issuetype Test (Zephyr). Pass --include-tests to count them in totals.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

# Windows/PowerShell: avoid UnicodeEncodeError on non-ASCII assignee names
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

IN_PROGRESS_STATUSES = frozenset(
    {
        "in progress",
        "in-progress",
        "in review",
        "in qa",
        "qa",
        "code review",
        "in development",
    }
)

DONE_STATUSES = frozenset(
    {
        "done",
        "closed",
        "resolved",
        "released",
        "accepted",
        "deployed",
    }
)

SP_EXPECTED_HOURS = {
    1: 1.0,
    2: 2.75,
    3: 5.5,
    5: 17.0,
    8: 33.0,
    13: 55.0,
    21: 96.0,
}


def sp_value(raw: Any) -> float:
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def parse_date(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def load_issues(paths: list[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        for issue in data.get("issues", []):
            key = issue.get("key")
            if key and key not in seen:
                seen.add(key)
                issues.append(issue)
    return issues


def issue_type_name(issue: dict[str, Any]) -> str:
    return (issue.get("fields", {}).get("issuetype") or {}).get("name", "")


def status_category(issue: dict[str, Any]) -> str:
    fields = issue.get("fields", {})
    status = fields.get("status") or {}
    cat = (status.get("statusCategory") or {}).get("name", "")
    if cat:
        return cat
    name = (status.get("name") or "").lower()
    if name in DONE_STATUSES:
        return "Done"
    if name in IN_PROGRESS_STATUSES:
        return "In Progress"
    return "To Do"


def parent_key(issue: dict[str, Any]) -> str | None:
    parent = issue.get("fields", {}).get("parent")
    return parent.get("key") if parent else None


def parent_summary(issue: dict[str, Any]) -> str:
    parent = issue.get("fields", {}).get("parent")
    if not parent:
        return ""
    return (parent.get("fields") or {}).get("summary", "")


def is_test(issue: dict[str, Any]) -> bool:
    return issue_type_name(issue) == "Test"


def filter_scope(
    issues: list[dict[str, Any]], include_tests: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tests = [i for i in issues if is_test(i)]
    if include_tests:
        return issues, tests
    scoped = [i for i in issues if not is_test(i)]
    return scoped, tests


def summarize_tests(tests: list[dict[str, Any]]) -> dict[str, Any]:
    total_sp = sum(sp_value(i["fields"].get("customfield_10200")) for i in tests)
    done = [i for i in tests if status_category(i) == "Done"]
    return {
        "count": len(tests),
        "sp": total_sp,
        "done_count": len(done),
        "done_sp": sum(sp_value(i["fields"].get("customfield_10200")) for i in done),
    }


def compute_metrics(
    scoped: list[dict[str, Any]],
    start: date,
    end: date,
    today: date,
) -> dict[str, Any]:
    total_sp = done_sp = ip_sp = todo_sp = 0.0
    unestimated = 0
    by_cat: dict[str, int] = defaultdict(int)

    for issue in scoped:
        s = sp_value(issue["fields"].get("customfield_10200"))
        if issue["fields"].get("customfield_10200") in (None, 0):
            unestimated += 1
        total_sp += s
        cat = status_category(issue)
        by_cat[cat] += 1
        if cat == "Done":
            done_sp += s
        elif cat == "In Progress":
            ip_sp += s
        else:
            todo_sp += s

    days_elapsed = max(0, (today - start).days)
    days_remaining = max(0, (end - today).days)
    sprint_length = days_elapsed + days_remaining

    actual_remaining = total_sp - done_sp
    ideal_remaining = (
        total_sp * (days_remaining / sprint_length) if sprint_length else 0.0
    )
    burndown_delta = actual_remaining - ideal_remaining
    burndown_delta_pct = (burndown_delta / total_sp * 100) if total_sp else 0.0
    expected_complete = (days_elapsed / sprint_length * 100) if sprint_length else 0.0
    actual_complete = (done_sp / total_sp * 100) if total_sp else 0.0
    completion_gap = expected_complete - actual_complete

    return {
        "issue_count": len(scoped),
        "total_sp": total_sp,
        "done_sp": done_sp,
        "in_progress_sp": ip_sp,
        "todo_sp": todo_sp,
        "unestimated": unestimated,
        "by_category": dict(by_cat),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "sprint_length": sprint_length,
        "actual_remaining": actual_remaining,
        "ideal_remaining": ideal_remaining,
        "burndown_delta": burndown_delta,
        "burndown_delta_pct": burndown_delta_pct,
        "expected_complete": expected_complete,
        "actual_complete": actual_complete,
        "completion_gap": completion_gap,
    }


def epic_rollup(scoped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    epics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"summary": "", "sp": 0.0, "done": 0.0, "ip": 0.0, "todo": 0.0, "count": 0}
    )
    for issue in scoped:
        ek = parent_key(issue) or "No Epic"
        s = sp_value(issue["fields"].get("customfield_10200"))
        epics[ek]["sp"] += s
        epics[ek]["count"] += 1
        ps = parent_summary(issue)
        if ps:
            epics[ek]["summary"] = ps
        cat = status_category(issue)
        if cat == "Done":
            epics[ek]["done"] += s
        elif cat == "In Progress":
            epics[ek]["ip"] += s
        else:
            epics[ek]["todo"] += s

    rows = []
    for key, v in epics.items():
        score = v["sp"] + v["ip"] * 2
        rows.append({"key": key, "score": score, **v})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def expected_hours(sp: float) -> float:
    if sp <= 0:
        return 8.0
    fib = [1, 2, 3, 5, 8, 13, 21]
    nearest = min(fib, key=lambda f: abs(f - sp))
    return SP_EXPECTED_HOURS.get(nearest, 17.0)


def parse_changelog_transitions(changelog: dict[str, Any]) -> list[tuple[datetime, str, str]]:
    transitions: list[tuple[datetime, str, str]] = []
    for history in changelog.get("histories", []):
        created = history.get("created", "")
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        for item in history.get("items", []):
            if item.get("field") == "status":
                transitions.append(
                    (ts, item.get("fromString", ""), item.get("toString", ""))
                )
    transitions.sort(key=lambda t: t[0])
    return transitions


def is_in_progress_status(name: str) -> bool:
    return name.lower() in IN_PROGRESS_STATUSES


def is_done_status(name: str) -> bool:
    return name.lower() in DONE_STATUSES


def business_hours_between(start: datetime, end: datetime) -> float:
    if end <= start:
        return 0.0
    hours = 0.0
    cur = start
    while cur < end:
        if cur.weekday() < 5:
            day_end = datetime.combine(cur.date(), time(23, 59, 59), tzinfo=cur.tzinfo)
            segment_end = min(end, day_end)
            hours += (segment_end - cur).total_seconds() / 3600.0
        cur = datetime.combine(cur.date(), time(0, 0), tzinfo=cur.tzinfo)
        from datetime import timedelta

        cur += timedelta(days=1)
    return min(hours, (end - start).total_seconds() / 3600.0 * 5 / 7 * 1.5)


def days_in_current_status(
    issue: dict[str, Any], changelog: dict[str, Any] | None, now: datetime
) -> float:
    if not changelog:
        return 0.0
    transitions = parse_changelog_transitions(changelog)
    if not transitions:
        return 0.0
    last_ts = transitions[-1][0]
    return max(0.0, (now - last_ts).total_seconds() / 86400.0)


def aging_flags(
    scoped: list[dict[str, Any]],
    changelogs: dict[str, dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for issue in scoped:
        if status_category(issue) != "In Progress":
            continue
        key = issue["key"]
        sp = sp_value(issue["fields"].get("customfield_10200"))
        summary = issue["fields"].get("summary", "")
        assignee = (issue["fields"].get("assignee") or {}).get("displayName", "Unassigned")
        status_name = (issue["fields"].get("status") or {}).get("name", "")
        cl = changelogs.get(key)
        days = days_in_current_status(issue, cl, now)
        exp_h = expected_hours(sp)
        exp_days = exp_h / 8.0
        actual_h = days * 8.0
        ratio = actual_h / exp_h if exp_h else 0.0

        flag = None
        if sp == 0 and days >= 1:
            flag = "Unestimated risk"
        elif ratio > 2.0:
            flag = "Critical"
        elif ratio > 1.5:
            flag = "Warning"
        elif days >= 2:
            flag = "Stale"

        if flag:
            flags.append(
                {
                    "key": key,
                    "summary": summary[:70],
                    "assignee": assignee,
                    "sp": sp,
                    "status": status_name,
                    "days_in_status": round(days, 1),
                    "expected_days": round(exp_days, 1),
                    "ratio": round(ratio, 2),
                    "flag": flag,
                }
            )
    flags.sort(key=lambda f: f["ratio"], reverse=True)
    return flags


def changelog_deltas(
    scoped_keys: set[str],
    changelogs: dict[str, dict[str, Any]],
    cutoff: datetime,
) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    started: list[dict[str, Any]] = []
    scope_added: list[dict[str, Any]] = []
    scope_removed: list[dict[str, Any]] = []
    sp_changes: list[dict[str, Any]] = []

    for key, changelog in changelogs.items():
        if key not in scoped_keys:
            continue
        for history in changelog.get("histories", []):
            created_str = history.get("created", "")
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created < cutoff:
                continue
            for item in history.get("items", []):
                field = item.get("field", "")
                if field == "status":
                    to_s = item.get("toString", "")
                    from_s = item.get("fromString", "")
                    entry = {
                        "key": key,
                        "from": from_s,
                        "to": to_s,
                        "when": created_str,
                        "author": (history.get("author") or {}).get("displayName", ""),
                    }
                    if is_done_status(to_s):
                        completed.append(entry)
                    elif is_in_progress_status(to_s) and not is_in_progress_status(from_s):
                        started.append(entry)
                elif field == "Sprint":
                    from_s = item.get("fromString") or ""
                    to_s = item.get("toString") or ""
                    if to_s and not from_s:
                        scope_added.append({"key": key, "when": created_str})
                    elif from_s and not to_s:
                        scope_removed.append({"key": key, "when": created_str})
                elif field in ("Story Points", "customfield_10200"):
                    sp_changes.append(
                        {
                            "key": key,
                            "from": item.get("fromString"),
                            "to": item.get("toString"),
                            "when": created_str,
                        }
                    )

    return {
        "completed": completed,
        "started": started,
        "scope_added": scope_added,
        "scope_removed": scope_removed,
        "sp_changes": sp_changes,
    }


def load_changelogs(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "changelogs" in data:
        return data["changelogs"]
    if isinstance(data, dict) and "key" in data:
        return {data["key"]: data.get("changelog", {})}
    return {}


def format_text(
    metrics: dict[str, Any],
    test_summary: dict[str, Any],
    epics: list[dict[str, Any]],
    aging: list[dict[str, Any]],
    deltas: dict[str, Any] | None,
    include_tests: bool,
) -> str:
    lines: list[str] = []
    scope = "Tests included" if include_tests else (
        f"Test issues excluded: {test_summary['count']} ticket(s), {test_summary['sp']} SP"
    )
    lines.append(f"SCOPE: {scope}")
    if not include_tests and test_summary["done_count"]:
        lines.append(
            f"TEST_QA_COVERAGE: {test_summary['done_count']} Test ticket(s) Done "
            f"({test_summary['done_sp']} SP, not in totals)"
        )
    lines.append("")
    lines.append(f"ISSUE_COUNT {metrics['issue_count']}")
    lines.append(f"TOTAL_SP {metrics['total_sp']}")
    lines.append(f"DONE_SP {metrics['done_sp']}")
    lines.append(f"IP_SP {metrics['in_progress_sp']}")
    lines.append(f"TODO_SP {metrics['todo_sp']}")
    lines.append(f"UNESTIMATED {metrics['unestimated']}")
    lines.append(f"BY_CAT {metrics['by_category']}")
    lines.append(f"DAYS_ELAPSED {metrics['days_elapsed']}")
    lines.append(f"DAYS_REMAINING {metrics['days_remaining']}")
    lines.append(f"ACTUAL_REMAINING {round(metrics['actual_remaining'], 1)}")
    lines.append(f"IDEAL_REMAINING {round(metrics['ideal_remaining'], 1)}")
    lines.append(f"BURNDOWN_DELTA {round(metrics['burndown_delta'], 1)}")
    lines.append(f"BURNDOWN_DELTA_PCT {round(metrics['burndown_delta_pct'], 1)}")
    lines.append(f"EXPECTED_COMPLETE {round(metrics['expected_complete'], 1)}")
    lines.append(f"ACTUAL_COMPLETE {round(metrics['actual_complete'], 1)}")
    lines.append(f"COMPLETION_GAP {round(metrics['completion_gap'], 1)}")
    lines.append("TOP_EPICS")
    for e in epics[:12]:
        lines.append(
            f"  {e['key']}|{e['summary'][:60]}|sp={e['sp']}|done={e['done']}|"
            f"ip={e['ip']}|todo={e['todo']}|count={e['count']}"
        )
    if aging:
        lines.append("AGING")
        for a in aging:
            lines.append(
                f"  {a['key']}|{a['summary']}|sp={a['sp']}|{a['assignee']}|"
                f"{a['days_in_status']}d|ratio={a['ratio']}x|{a['flag']}"
            )
    if deltas:
        lines.append("DELTAS_SINCE_CUTOFF")
        lines.append(f"  completed={len(deltas['completed'])} started={len(deltas['started'])}")
        lines.append(f"  scope_added={len(deltas['scope_added'])} scope_removed={len(deltas['scope_removed'])}")
        for c in deltas["completed"][:20]:
            lines.append(f"  DONE {c['key']} {c['from']} -> {c['to']}")
        for s in deltas["started"][:20]:
            lines.append(f"  START {s['key']} {s['from']} -> {s['to']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprint Health metrics from MCP JSON dumps")
    parser.add_argument("issue_files", nargs="+", type=Path, help="searchJiraIssuesUsingJql JSON dump(s)")
    parser.add_argument("--tests", type=Path, default=None, help="Optional separate Test-only issue dump")
    parser.add_argument("--changelogs", type=Path, default=None, help="Optional changelogs JSON map")
    parser.add_argument("--start", required=True, help="Sprint start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Sprint end date YYYY-MM-DD")
    parser.add_argument("--today", default=None, help="Report date YYYY-MM-DD (default: UTC today)")
    parser.add_argument("--cutoff", default=None, help="Day-to-day cutoff ISO datetime (default: yesterday 00:00 UTC)")
    parser.add_argument("--include-tests", action="store_true", help="Include Test issues in metric totals")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    today = parse_date(args.today) if args.today else datetime.now(timezone.utc).date()

    all_issues = load_issues(args.issue_files)
    if args.tests:
        all_issues.extend(load_issues([args.tests]))

    scoped, tests_from_main = filter_scope(all_issues, args.include_tests)
    if args.tests and not args.include_tests:
        extra_tests = load_issues([args.tests])
        test_keys = {i["key"] for i in tests_from_main}
        for t in extra_tests:
            if t["key"] not in test_keys:
                tests_from_main.append(t)

    test_summary = summarize_tests(tests_from_main if not args.include_tests else [])
    metrics = compute_metrics(scoped, start, end, today)
    epics = epic_rollup(scoped)

    changelogs = load_changelogs(args.changelogs)
    now = datetime.combine(today, time(12, 0), tzinfo=timezone.utc)
    aging = aging_flags(scoped, changelogs, now) if changelogs else []

    deltas = None
    if changelogs:
        if args.cutoff:
            cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
        else:
            from datetime import timedelta

            cutoff = datetime.combine(today, time(0, 0), tzinfo=timezone.utc) - timedelta(days=1)
        scoped_keys = {i["key"] for i in scoped}
        deltas = changelog_deltas(scoped_keys, changelogs, cutoff)

    result = {
        "scope": "include_tests" if args.include_tests else "exclude_tests",
        "test_summary": test_summary,
        "metrics": metrics,
        "top_epics": epics[:12],
        "aging": aging,
        "deltas": deltas,
    }

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_text(metrics, test_summary, epics, aging, deltas, args.include_tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
