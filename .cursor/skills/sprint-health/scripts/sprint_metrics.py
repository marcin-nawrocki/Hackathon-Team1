#!/usr/bin/env python3
"""Sprint Health metrics parser — changelog-backed sprint metrics from MCP dumps.

Usage:
  python sprint_metrics.py issues_page1.json [issues_page2.json ...] \\
    --start 2026-07-02 --end 2026-07-16 [--today 2026-07-07] \\
    [--as-of 2026-07-05 --sprint-id 15019 --sprint-name "SCL Sprint 56"] \\
    --changelogs changelogs.json \\
    [--out .sprint_tmp/metrics.json] \\
    [--tests tests.json] [--include-tests] \\
    [--theme "Sykes=sykes,SCL-3875"] \\
    [--epic-peers peers.json --peer-changelogs peers_cl.json --todo-reestimates] \\
    [--format text|json]

Requires --changelogs (bulkfetch output). Defaults: exclude issuetype Test (Zephyr).
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

# Windows/PowerShell: avoid UnicodeEncodeError on non-ASCII assignee names
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REVIEW_QA_KEYWORDS = ("review", "qa", "test", "uat", "verify", "validation")

_FALLBACK_DONE = frozenset(
    {"done", "closed", "resolved", "released", "accepted", "deployed"}
)
_FALLBACK_IN_PROGRESS = frozenset(
    {"in progress", "in-progress", "in development", "blocked", "dev done"}
)

_STATUS_MAPPING: "StatusMapping | None" = None
_SNAPSHOTS: dict[str, "IssueSnapshot"] | None = None
_DERIVED: dict[str, tuple[float, str, str]] = {}
_PARSED_CL: dict[str, "ParsedChangelog"] = {}


@dataclass
class ParsedChangelog:
    """Pre-parsed changelog fields for a single issue (sorted by timestamp)."""

    status: list[tuple[datetime, str, str, str, str]] = field(default_factory=list)
    sp: list[tuple[datetime, Any, Any, str]] = field(default_factory=list)
    sprint: list[tuple[datetime, Any, Any, str]] = field(default_factory=list)
    histories: list[tuple[datetime, str, str, list[dict[str, Any]]]] = field(default_factory=list)


class IssueSnapshot:
    """Point-in-time issue state reconstructed from changelog."""

    __slots__ = ("status_name", "sp", "sprint_ids")

    def __init__(self, status_name: str, sp: float, sprint_ids: set[int]):
        self.status_name = status_name
        self.sp = sp
        self.sprint_ids = sprint_ids


def set_snapshots(snapshots: dict[str, IssueSnapshot] | None) -> None:
    global _SNAPSHOTS
    _SNAPSHOTS = snapshots


def get_snapshot(key: str) -> IssueSnapshot | None:
    return _SNAPSHOTS.get(key) if _SNAPSHOTS else None


def clear_caches() -> None:
    global _DERIVED, _PARSED_CL
    _DERIVED = {}
    _PARSED_CL = {}


def parse_changelog_entry(changelog: dict[str, Any]) -> ParsedChangelog:
    parsed = ParsedChangelog()
    for history in changelog.get("histories", []):
        created = parse_datetime(history.get("created"))
        if created is None:
            continue
        created_iso = created.isoformat()
        author = (history.get("author") or {}).get("displayName", "")
        items = history.get("items", [])
        parsed.histories.append((created, created_iso, author, items))
        for item in items:
            fld = item.get("field", "")
            if fld == "status":
                parsed.status.append(
                    (
                        created,
                        item.get("fromString", ""),
                        item.get("toString", ""),
                        author,
                        created_iso,
                    )
                )
            elif fld in ("Story Points", "customfield_10200"):
                parsed.sp.append(
                    (created, item.get("fromString"), item.get("toString"), created_iso)
                )
            elif fld in ("Sprint", "customfield_10115"):
                parsed.sprint.append(
                    (created, item.get("from"), item.get("to"), created_iso)
                )
    parsed.status.sort(key=lambda row: row[0])
    parsed.sp.sort(key=lambda row: row[0])
    parsed.sprint.sort(key=lambda row: row[0])
    parsed.histories.sort(key=lambda row: row[0])
    return parsed


def precompute_changelogs(changelogs: dict[str, dict[str, Any]]) -> None:
    global _PARSED_CL
    _PARSED_CL = {key: parse_changelog_entry(cl) for key, cl in changelogs.items()}


def get_parsed(key: str, changelog: dict[str, Any] | None) -> ParsedChangelog:
    if key in _PARSED_CL:
        return _PARSED_CL[key]
    return parse_changelog_entry(changelog or {})


def _bisect_last_before(
    events: list[tuple[datetime, ...]], as_of: datetime
) -> int | None:
    if not events:
        return None
    timestamps = [e[0] for e in events]
    idx = bisect.bisect_right(timestamps, as_of) - 1
    return idx if idx >= 0 else None


def _bisect_first_after(events: list[tuple[datetime, ...]], as_of: datetime) -> int | None:
    if not events:
        return None
    timestamps = [e[0] for e in events]
    idx = bisect.bisect_right(timestamps, as_of)
    return idx if idx < len(events) else None


def precompute_derived(issues: list[dict[str, Any]]) -> None:
    global _DERIVED
    derived: dict[str, tuple[float, str, str]] = {}
    for issue in issues:
        key = issue["key"]
        snap = get_snapshot(key)
        if snap is not None:
            sp = snap.sp
            status_name = snap.status_name
            category = status_category_from_name(status_name)
        else:
            sp = sp_value(issue["fields"].get("customfield_10200"))
            fields = issue.get("fields", {})
            status = fields.get("status") or {}
            cat = (status.get("statusCategory") or {}).get("name", "")
            status_name = status.get("name") or ""
            if cat:
                category = cat
            else:
                category = status_category_from_name(status_name)
        derived[key] = (sp, category, status_name)
    _DERIVED = derived


class StatusMapping:
    """Jira status name -> sprint-health buckets (from jira-status-mapping.json)."""

    def __init__(self, data: dict[str, Any]):
        self._by_lower: dict[str, dict[str, Any]] = {}
        for row in data.get("statuses", []):
            self._by_lower[row["name"].lower()] = row

    @classmethod
    def load(cls, path: Path) -> StatusMapping:
        with path.open(encoding="utf-8") as f:
            return cls(json.load(f))

    def entry(self, name: str) -> dict[str, Any] | None:
        return self._by_lower.get(name.lower())

    def bucket(self, name: str) -> str | None:
        row = self.entry(name)
        return row.get("sprintHealthBucket") if row else None

    def jira_category(self, name: str) -> str | None:
        row = self.entry(name)
        return row.get("statusCategory") if row else None

    def is_done(self, name: str) -> bool:
        bucket = self.bucket(name)
        if bucket:
            return bucket == "done"
        return name.lower() in _FALLBACK_DONE

    def is_review_qa(self, name: str) -> bool:
        bucket = self.bucket(name)
        if bucket:
            return bucket == "review_qa"
        lower = name.lower()
        return any(k in lower for k in REVIEW_QA_KEYWORDS)

    def is_in_progress(self, name: str) -> bool:
        bucket = self.bucket(name)
        if bucket:
            return bucket in ("in_progress", "review_qa")
        lower = name.lower()
        return lower in _FALLBACK_IN_PROGRESS or any(k in lower for k in REVIEW_QA_KEYWORDS)


def init_status_mapping(path: Path) -> StatusMapping:
    global _STATUS_MAPPING
    _STATUS_MAPPING = StatusMapping.load(path)
    return _STATUS_MAPPING


def status_mapping() -> StatusMapping | None:
    return _STATUS_MAPPING

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


def business_days(start: date, end: date) -> int:
    """Count weekdays (Mon-Fri) in [start, end)."""
    if end <= start:
        return 0
    count = 0
    cur = start
    while cur < end:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


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


def parse_sprint_ids(raw: Any) -> set[int]:
    """Parse sprint IDs from changelog from/to or issue sprint field."""
    if raw is None:
        return set()
    if isinstance(raw, list):
        ids: set[int] = set()
        for item in raw:
            if isinstance(item, dict) and item.get("id") is not None:
                ids.add(int(item["id"]))
        return ids
    s = str(raw).strip()
    if not s:
        return set()
    ids = set()
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def sprint_ids_from_issue_fields(issue: dict[str, Any]) -> set[int]:
    return parse_sprint_ids(issue.get("fields", {}).get("customfield_10115"))


def snapshot_at(
    issue: dict[str, Any],
    changelog: dict[str, Any] | None,
    as_of: datetime,
) -> IssueSnapshot:
    """Reconstruct status, SP, and sprint membership at a point in time."""
    key = issue["key"]
    fields = issue.get("fields", {})
    current_status = (fields.get("status") or {}).get("name", "")
    current_sp = sp_value(fields.get("customfield_10200"))
    current_sprints = sprint_ids_from_issue_fields(issue)

    parsed = get_parsed(key, changelog)

    past_idx = _bisect_last_before(parsed.status, as_of)
    if past_idx is not None:
        status_name = parsed.status[past_idx][2]
    else:
        future_idx = _bisect_first_after(parsed.status, as_of)
        status_name = parsed.status[future_idx][1] if future_idx is not None else current_status

    past_idx = _bisect_last_before(parsed.sp, as_of)
    if past_idx is not None:
        sp = sp_value(parsed.sp[past_idx][2])
    else:
        future_idx = _bisect_first_after(parsed.sp, as_of)
        sp = sp_value(parsed.sp[future_idx][1]) if future_idx is not None else current_sp

    past_idx = _bisect_last_before(parsed.sprint, as_of)
    if past_idx is not None:
        sprint_ids = parse_sprint_ids(parsed.sprint[past_idx][2])
    else:
        future_idx = _bisect_first_after(parsed.sprint, as_of)
        if future_idx is not None:
            sprint_ids = parse_sprint_ids(parsed.sprint[future_idx][1])
        else:
            sprint_ids = current_sprints

    return IssueSnapshot(status_name=status_name, sp=sp, sprint_ids=sprint_ids)


def status_category_from_name(name: str) -> str:
    mapping = status_mapping()
    if mapping:
        mapped = mapping.jira_category(name)
        if mapped:
            return mapped
        bucket = mapping.bucket(name)
        if bucket == "done":
            return "Done"
        if bucket in ("in_progress", "review_qa"):
            return "In Progress"
        if bucket == "todo":
            return "To Do"
    lower = name.lower()
    if lower in _FALLBACK_DONE:
        return "Done"
    if lower in _FALLBACK_IN_PROGRESS or any(k in lower for k in REVIEW_QA_KEYWORDS):
        return "In Progress"
    return "To Do"


def issue_sp(issue: dict[str, Any]) -> float:
    key = issue["key"]
    if key in _DERIVED:
        return _DERIVED[key][0]
    snap = get_snapshot(key)
    if snap is not None:
        return snap.sp
    return sp_value(issue["fields"].get("customfield_10200"))


def issue_status_name(issue: dict[str, Any]) -> str:
    key = issue["key"]
    if key in _DERIVED:
        return _DERIVED[key][2]
    snap = get_snapshot(key)
    if snap is not None:
        return snap.status_name
    return (issue.get("fields", {}).get("status") or {}).get("name", "")


def status_category(issue: dict[str, Any]) -> str:
    key = issue["key"]
    if key in _DERIVED:
        return _DERIVED[key][1]
    snap = get_snapshot(key)
    if snap is not None:
        return status_category_from_name(snap.status_name)
    fields = issue.get("fields", {})
    status = fields.get("status") or {}
    cat = (status.get("statusCategory") or {}).get("name", "")
    if cat:
        return cat
    name = status.get("name") or ""
    mapping = status_mapping()
    if mapping:
        mapped = mapping.jira_category(name)
        if mapped:
            return mapped
        bucket = mapping.bucket(name)
        if bucket == "done":
            return "Done"
        if bucket in ("in_progress", "review_qa"):
            return "In Progress"
        if bucket == "todo":
            return "To Do"
    lower = name.lower()
    if lower in _FALLBACK_DONE:
        return "Done"
    if lower in _FALLBACK_IN_PROGRESS or any(k in lower for k in REVIEW_QA_KEYWORDS):
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


def issue_summary(issue: dict[str, Any]) -> str:
    return issue.get("fields", {}).get("summary", "")


def parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def status_category_changed_at(issue: dict[str, Any]) -> datetime | None:
    return parse_datetime(issue.get("fields", {}).get("statuscategorychangedate"))


def parse_theme_arg(raw: str) -> tuple[str, list[str]]:
    if "=" not in raw:
        raise ValueError(f"Invalid --theme {raw!r}; expected Label=kw1,kw2")
    label, keywords = raw.split("=", 1)
    kws = [k.strip() for k in keywords.split(",") if k.strip()]
    if not label.strip() or not kws:
        raise ValueError(f"Invalid --theme {raw!r}; label and keywords required")
    return label.strip(), kws


def issue_matches_theme(issue: dict[str, Any], keywords: list[str]) -> bool:
    haystack = f"{issue_summary(issue)} {parent_summary(issue)} {parent_key(issue) or ''}".lower()
    return any(kw.lower() in haystack for kw in keywords)


def theme_rollup(
    scoped: list[dict[str, Any]], themes: list[tuple[str, list[str]]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, keywords in themes:
        matched: list[dict[str, Any]] = []
        total_sp = done_sp = ip_sp = todo_sp = 0.0
        for issue in scoped:
            if not issue_matches_theme(issue, keywords):
                continue
            s = issue_sp(issue)
            cat = status_category(issue)
            matched.append(
                {
                    "key": issue["key"],
                    "summary": issue_summary(issue),
                    "sp": s,
                    "status_category": cat,
                }
            )
            total_sp += s
            if cat == "Done":
                done_sp += s
            elif cat == "In Progress":
                ip_sp += s
            else:
                todo_sp += s
        pct = (done_sp / total_sp * 100) if total_sp else 0.0
        rows.append(
            {
                "name": label,
                "keywords": keywords,
                "keys": [m["key"] for m in matched],
                "total_sp": total_sp,
                "done_sp": done_sp,
                "in_progress_sp": ip_sp,
                "todo_sp": todo_sp,
                "pct": pct,
                "issues": matched,
            }
        )
    return rows


FIBONACCI_SP = (1, 2, 3, 5, 8, 13, 21)


def nearest_fibonacci(value: float) -> int:
    if value <= 0:
        return 1
    return min(FIBONACCI_SP, key=lambda f: (abs(f - value), f))


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
    total_sp = sum(issue_sp(i) for i in tests)
    done = [i for i in tests if status_category(i) == "Done"]
    return {
        "count": len(tests),
        "sp": total_sp,
        "done_count": len(done),
        "done_sp": sum(issue_sp(i) for i in done),
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
    dev_count = review_count = qa_count = 0
    dev_sp = review_sp = qa_sp = 0.0

    for issue in scoped:
        s = issue_sp(issue)
        raw_sp = issue["fields"].get("customfield_10200")
        snap = get_snapshot(issue["key"])
        if snap is not None:
            if snap.sp in (0, 0.0) and raw_sp in (None, 0):
                unestimated += 1
        elif raw_sp in (None, 0):
            unestimated += 1
        total_sp += s
        cat = status_category(issue)
        by_cat[cat] += 1
        if cat == "Done":
            done_sp += s
        elif cat == "In Progress":
            ip_sp += s
            status_name = issue_status_name(issue)
            if is_review_qa_status(status_name):
                if review_qa_subtype(status_name) == "In-Review":
                    review_count += 1
                    review_sp += s
                else:
                    qa_count += 1
                    qa_sp += s
            else:
                dev_count += 1
                dev_sp += s
        else:
            todo_sp += s

    days_elapsed = business_days(start, today)
    days_remaining = business_days(today, end)
    sprint_length = business_days(start, end)

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
        "in_progress_dev_count": dev_count,
        "in_progress_dev_sp": dev_sp,
        "in_review_count": review_count,
        "in_review_sp": review_sp,
        "qa_count": qa_count,
        "qa_sp": qa_sp,
        "unestimated": unestimated,
        "by_category": dict(by_cat),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "sprint_length": sprint_length,
        "day_basis": "business",
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
        s = issue_sp(issue)
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


def parse_changelog_transitions(changelog: dict[str, Any], key: str | None = None) -> list[tuple[datetime, str, str]]:
    if key and key in _PARSED_CL:
        return [(ts, frm, to) for ts, frm, to, _author, _iso in _PARSED_CL[key].status]
    parsed = parse_changelog_entry(changelog)
    return [(ts, frm, to) for ts, frm, to, _author, _iso in parsed.status]


def is_in_progress_status(name: str) -> bool:
    mapping = status_mapping()
    if mapping:
        return mapping.is_in_progress(name)
    lower = name.lower()
    return lower in _FALLBACK_IN_PROGRESS or any(k in lower for k in REVIEW_QA_KEYWORDS)


def is_review_qa_status(name: str) -> bool:
    mapping = status_mapping()
    if mapping:
        return mapping.is_review_qa(name)
    return any(k in name.lower() for k in REVIEW_QA_KEYWORDS)


def is_done_status(name: str) -> bool:
    mapping = status_mapping()
    if mapping:
        return mapping.is_done(name)
    return name.lower() in _FALLBACK_DONE


def review_qa_subtype(name: str) -> str:
    """Split the review_qa bucket into a human queue label: In-Review vs QA."""
    lower = name.lower()
    if "review" in lower:
        return "In-Review"
    if any(k in lower for k in ("qa", "test", "uat", "verify", "validation", "accept")):
        return "QA"
    return "QA"


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
        cur += timedelta(days=1)
    return min(hours, (end - start).total_seconds() / 3600.0 * 5 / 7 * 1.5)


def days_in_current_status(
    issue: dict[str, Any], changelog: dict[str, Any] | None, now: datetime
) -> float:
    key = issue["key"]
    if changelog or key in _PARSED_CL:
        parsed = get_parsed(key, changelog)
        if parsed.status:
            past_idx = _bisect_last_before(parsed.status, now)
            if past_idx is not None:
                last_ts = parsed.status[past_idx][0]
                return max(0.0, (now - last_ts).total_seconds() / 86400.0)
            return max(0.0, (now - parsed.status[0][0]).total_seconds() / 86400.0)
    changed = status_category_changed_at(issue)
    if changed:
        return max(0.0, (now - changed).total_seconds() / 86400.0)
    return 0.0


def status_change_ts(
    issue: dict[str, Any], changelog: dict[str, Any] | None, now: datetime
) -> datetime | None:
    """Timestamp of the last status transition at/before `now` (idle-since anchor)."""
    key = issue["key"]
    if changelog or key in _PARSED_CL:
        parsed = get_parsed(key, changelog)
        if parsed.status:
            past_idx = _bisect_last_before(parsed.status, now)
            if past_idx is not None:
                return parsed.status[past_idx][0]
            return parsed.status[0][0]
    return status_category_changed_at(issue)


def bottleneck_breakdown(
    scoped: list[dict[str, Any]],
    changelogs: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Split the 'In Progress' status category into real dev In-Progress vs In-Review vs QA.

    Surfaces where work is actually parked: the review/QA queue, unassigned reviewers,
    and QA-load concentration on a single assignee.
    """
    dev: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    qa: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    qa_by_assignee: dict[str, dict[str, Any]] = {}
    unassigned_in_review: list[str] = []
    stale_count = 0
    today = now.date()

    for issue in scoped:
        if status_category(issue) != "In Progress":
            continue
        key = issue["key"]
        sp = issue_sp(issue)
        summary = issue_summary(issue)
        assignee = (issue["fields"].get("assignee") or {}).get("displayName") or "Unassigned"
        unassigned = assignee == "Unassigned"
        status_name = issue_status_name(issue)
        cl = changelogs.get(key) if changelogs else None
        ts = status_change_ts(issue, cl, now)
        idle_since = ts.date().isoformat() if ts else None
        idle_business_days = business_days(ts.date(), today) if ts else 0

        base = {
            "key": key,
            "summary": summary,
            "sp": sp,
            "assignee": assignee,
            "unassigned": unassigned,
            "status": status_name,
            "idle_since": idle_since,
            "idle_business_days": idle_business_days,
        }

        if is_review_qa_status(status_name):
            queue = review_qa_subtype(status_name)
            entry = {**base, "queue": queue}
            waiting.append(entry)
            if queue == "In-Review":
                review.append(entry)
                if unassigned:
                    unassigned_in_review.append(key)
            else:
                qa.append(entry)
                if not unassigned:
                    row = qa_by_assignee.setdefault(
                        assignee, {"assignee": assignee, "count": 0, "sp": 0.0, "keys": []}
                    )
                    row["count"] += 1
                    row["sp"] += sp
                    row["keys"].append(key)
            if idle_business_days >= 2:
                stale_count += 1
        else:
            dev.append(base)

    # Longest-waiting first: oldest idle date, then largest SP.
    waiting.sort(key=lambda e: (e["idle_since"] or "9999", -e["sp"]))
    qa_rows = sorted(qa_by_assignee.values(), key=lambda r: r["sp"], reverse=True)

    return {
        "in_progress_dev": {
            "count": len(dev),
            "sp": sum(e["sp"] for e in dev),
            "issues": dev,
        },
        "in_review": {
            "count": len(review),
            "sp": sum(e["sp"] for e in review),
            "issues": review,
        },
        "qa": {
            "count": len(qa),
            "sp": sum(e["sp"] for e in qa),
            "issues": qa,
        },
        "waiting": waiting,
        "qa_by_assignee": qa_rows,
        "unassigned_in_review": unassigned_in_review,
        "stale_count": stale_count,
    }


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
        sp = issue_sp(issue)
        summary = issue_summary(issue)
        assignee = (issue["fields"].get("assignee") or {}).get("displayName", "Unassigned")
        status_name = issue_status_name(issue)
        cl = changelogs.get(key) if changelogs else None
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
    scoped_by_key: dict[str, dict[str, Any]],
    changelogs: dict[str, dict[str, Any]],
    cutoff: datetime,
    cutoff_end: datetime | None = None,
) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    started: list[dict[str, Any]] = []
    sent_back: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    scope_added: list[dict[str, Any]] = []
    scope_removed: list[dict[str, Any]] = []
    sp_changes: list[dict[str, Any]] = []

    for key in scoped_keys:
        changelog = changelogs.get(key, {})
        parsed = get_parsed(key, changelog)
        issue = scoped_by_key.get(key, {})
        issue_sp_val = issue_sp(issue) if issue else 0.0
        for created, created_iso, author, items in parsed.histories:
            if created < cutoff:
                continue
            if cutoff_end is not None and created > cutoff_end:
                continue
            for item in items:
                field = item.get("field", "")
                if field == "status":
                    to_s = item.get("toString", "")
                    from_s = item.get("fromString", "")
                    entry = {
                        "key": key,
                        "from": from_s,
                        "to": to_s,
                        "when": created_iso,
                        "author": author,
                        "sp": issue_sp_val,
                    }
                    if is_done_status(to_s):
                        completed.append(entry)
                    elif is_done_status(from_s) and not is_done_status(to_s):
                        regressed.append(entry)
                    elif is_in_progress_status(to_s) and not is_in_progress_status(from_s):
                        started.append(entry)
                    elif (
                        is_review_qa_status(from_s)
                        and not is_review_qa_status(to_s)
                        and not is_done_status(to_s)
                    ):
                        sent_back.append(entry)
                    elif is_in_progress_status(from_s) and not is_in_progress_status(to_s):
                        regressed.append(entry)
                elif field == "Sprint":
                    from_s = item.get("fromString") or ""
                    to_s = item.get("toString") or ""
                    if to_s and not from_s:
                        scope_added.append({"key": key, "when": created_iso, "sp": issue_sp_val})
                    elif from_s and not to_s:
                        scope_removed.append({"key": key, "when": created_iso, "sp": issue_sp_val})
                elif field in ("Story Points", "customfield_10200"):
                    sp_changes.append(
                        {
                            "key": key,
                            "from": item.get("fromString"),
                            "to": item.get("toString"),
                            "when": created_iso,
                        }
                    )

    sp_completed = sum(e["sp"] for e in completed)
    sp_sent_back = sum(e["sp"] for e in sent_back)
    sp_regressed = sum(e["sp"] for e in regressed)

    return {
        "completed": completed,
        "started": started,
        "sent_back": sent_back,
        "regressed": regressed,
        "scope_added": scope_added,
        "scope_removed": scope_removed,
        "sp_changes": sp_changes,
        "sp_completed": sp_completed,
        "sp_sent_back": sp_sent_back,
        "sp_regressed": sp_regressed,
        "completed_count": len(completed),
        "started_count": len(started),
        "sent_back_count": len(sent_back),
        "regressed_count": len(regressed),
    }


def cycle_times_from_changelog(
    changelog: dict[str, Any], key: str | None = None
) -> tuple[datetime | None, datetime | None]:
    cycle_start: datetime | None = None
    cycle_end: datetime | None = None
    for ts, _from_s, to_s in parse_changelog_transitions(changelog, key):
        if cycle_start is None and is_in_progress_status(to_s):
            cycle_start = ts
        if is_done_status(to_s):
            cycle_end = ts
            break
    return cycle_start, cycle_end


def calibration_ratio_for_issue(
    issue: dict[str, Any], changelog: dict[str, Any] | None
) -> float | None:
    if not changelog:
        return None
    sp = issue_sp(issue)
    if sp <= 0:
        return None
    start, end = cycle_times_from_changelog(changelog, issue["key"])
    if not start or not end or end <= start:
        return None
    actual = business_hours_between(start, end)
    expected = expected_hours(sp)
    if expected <= 0:
        return None
    return actual / expected


def compute_epic_median_ratios(
    peer_issues: list[dict[str, Any]],
    peer_changelogs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_epic: dict[str, list[float]] = defaultdict(list)
    for issue in peer_issues:
        if status_category(issue) != "Done":
            continue
        ek = parent_key(issue)
        if not ek:
            continue
        ratio = calibration_ratio_for_issue(issue, peer_changelogs.get(issue["key"]))
        if ratio is not None:
            by_epic[ek].append(ratio)

    result: dict[str, dict[str, Any]] = {}
    for ek, ratios in by_epic.items():
        ratios_sorted = sorted(ratios)
        mid = len(ratios_sorted) // 2
        if len(ratios_sorted) % 2:
            median = ratios_sorted[mid]
        else:
            median = (ratios_sorted[mid - 1] + ratios_sorted[mid]) / 2.0
        result[ek] = {"median_ratio": round(median, 2), "peer_count": len(ratios_sorted)}
    return result


def todo_reestimate_proposals(
    scoped: list[dict[str, Any]],
    epic_medians: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for issue in scoped:
        if status_category(issue) != "To Do":
            continue
        ek = parent_key(issue)
        if not ek or ek not in epic_medians:
            continue
        info = epic_medians[ek]
        median_ratio = info["median_ratio"]
        if median_ratio <= 1.3:
            continue
        current_sp = issue_sp(issue)
        if current_sp <= 0:
            continue
        suggested = nearest_fibonacci(current_sp * median_ratio)
        if suggested == current_sp:
            continue
        peer_count = info["peer_count"]
        confidence = "High" if peer_count >= 3 else "Low"
        proposals.append(
            {
                "key": issue["key"],
                "summary": issue_summary(issue)[:70],
                "epic": ek,
                "current_sp": current_sp,
                "suggested_sp": suggested,
                "epic_median_ratio": median_ratio,
                "peer_count": peer_count,
                "confidence": confidence,
            }
        )
    return proposals


def load_changelogs(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "changelogs" in data:
        return data["changelogs"]
    if isinstance(data, dict) and "key" in data:
        return {data["key"]: data.get("changelog", {})}
    if isinstance(data, dict) and data:
        first_val = next(iter(data.values()))
        if isinstance(first_val, dict) and "histories" in first_val:
            return data
    return {}


def format_text(
    metrics: dict[str, Any],
    test_summary: dict[str, Any],
    top_epics: list[dict[str, Any]],
    aging: list[dict[str, Any]],
    deltas: dict[str, Any] | None,
    themes: list[dict[str, Any]] | None,
    include_tests: bool,
    todo_proposals: list[dict[str, Any]] | None = None,
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
    for e in top_epics[:12]:
        lines.append(
            f"  {e['key']}|{e['summary'][:60]}|sp={e['sp']}|done={e['done']}|"
            f"ip={e['ip']}|todo={e['todo']}|count={e['count']}"
        )
    if themes:
        lines.append("THEMES")
        for t in themes:
            lines.append(
                f"  {t['name']}|keys={len(t['keys'])}|sp={t['total_sp']}|done={t['done_sp']}|"
                f"pct={round(t['pct'], 1)}"
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
        lines.append(
            f"  completed={deltas['completed_count']} ({deltas['sp_completed']} SP) "
            f"started={deltas['started_count']} "
            f"sent_back={deltas['sent_back_count']} ({deltas['sp_sent_back']} SP) "
            f"regressed={deltas['regressed_count']} ({deltas['sp_regressed']} SP)"
        )
        lines.append(
            f"  scope_added={len(deltas['scope_added'])} "
            f"scope_removed={len(deltas['scope_removed'])}"
        )
        for c in deltas["completed"][:20]:
            lines.append(f"  DONE {c['key']} {c['from']} -> {c['to']}")
        for s in deltas["started"][:20]:
            lines.append(f"  START {s['key']} {s['from']} -> {s['to']}")
        for sb in deltas.get("sent_back", [])[:20]:
            lines.append(f"  SENTBACK {sb['key']} {sb['from']} -> {sb['to']}")
        for r in deltas["regressed"][:20]:
            lines.append(f"  REGRESS {r['key']} {r['from']} -> {r['to']}")
    if todo_proposals:
        lines.append("TODO_REESTIMATES")
        for p in todo_proposals:
            lines.append(
                f"  {p['key']}|{p['current_sp']}->{p['suggested_sp']}|"
                f"epic={p['epic']}|ratio={p['epic_median_ratio']}|{p['confidence']}"
            )
    return "\n".join(lines)


def print_summary_line(result: dict[str, Any], out_path: Path | None) -> None:
    m = result["metrics"]
    d = result.get("deltas") or {}
    b = result.get("bottleneck") or {}
    parts = [
        f"issues={m['issue_count']}",
        f"done_sp={m['done_sp']}/{m['total_sp']}",
        f"aging={len(result.get('aging', []))}",
        f"deltas_done={d.get('completed_count', 0)}",
    ]
    if b:
        parts.append(
            "bottleneck=dev{}/review{}/qa{}".format(
                (b.get("in_progress_dev") or {}).get("count", 0),
                (b.get("in_review") or {}).get("count", 0),
                (b.get("qa") or {}).get("count", 0),
            )
        )
    if out_path:
        print(f"WROTE {out_path}")
    print("SUMMARY " + " ".join(parts))


def build_result(
    all_issues: list[dict[str, Any]],
    changelogs: dict[str, dict[str, Any]],
    start: date,
    end: date,
    today: date,
    *,
    as_of: str | None = None,
    sprint_id: int | None = None,
    sprint_name: str | None = None,
    sprint_state: str | None = None,
    cutoff: datetime | None = None,
    cutoff_end: datetime | None = None,
    theme_defs: list[tuple[str, list[str]]] | None = None,
    include_tests: bool = False,
    extra_test_issues: list[dict[str, Any]] | None = None,
    todo_reestimates: bool = False,
    epic_peer_issues: list[dict[str, Any]] | None = None,
    peer_changelogs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clear_caches()
    precompute_changelogs(changelogs)

    scoped, tests_from_main = filter_scope(all_issues, include_tests)
    if extra_test_issues and not include_tests:
        test_keys = {i["key"] for i in tests_from_main}
        for t in extra_test_issues:
            if t["key"] not in test_keys:
                tests_from_main.append(t)

    as_of_meta: dict[str, Any] | None = None
    if as_of:
        as_of_dt = datetime.combine(today, time(23, 59, 59), tzinfo=timezone.utc)
        sid = int(sprint_id)  # type: ignore[arg-type]
        snapshots: dict[str, IssueSnapshot] = {}
        gated: list[dict[str, Any]] = []
        candidates = len(scoped)
        excluded = 0
        for issue in scoped:
            cl = changelogs.get(issue["key"], {})
            snap = snapshot_at(issue, cl, as_of_dt)
            snapshots[issue["key"]] = snap
            if sid in snap.sprint_ids:
                gated.append(issue)
            else:
                excluded += 1
        set_snapshots(snapshots)
        scoped = gated
        as_of_meta = {
            "date": today.isoformat(),
            "sprint_id": sid,
            "sprint_name": sprint_name or "",
            "sprint_state": sprint_state or "",
            "candidates": candidates,
            "included": len(gated),
            "excluded": excluded,
            "membership_note": (
                "Membership replayed from changelog Sprint field. "
                "Tickets manually removed from sprint to backlog after the as-of date "
                "are not returned by sprint= JQL and cannot be recovered."
            ),
        }
    else:
        set_snapshots(None)

    precompute_derived(scoped)

    test_summary = summarize_tests(tests_from_main if not include_tests else [])
    metrics = compute_metrics(scoped, start, end, today)
    epics = epic_rollup(scoped)
    top_epics = epics[:12]
    themes = theme_rollup(scoped, theme_defs or []) if theme_defs else []

    if cutoff is None:
        cutoff = datetime.combine(today, time(0, 0), tzinfo=timezone.utc) - timedelta(days=1)
    if cutoff_end is None and as_of:
        cutoff_end = datetime.combine(today, time(23, 59, 59), tzinfo=timezone.utc)

    scoped_by_key = {i["key"]: i for i in scoped}
    scoped_keys = set(scoped_by_key)
    now = datetime.combine(today, time(12, 0), tzinfo=timezone.utc)
    aging = aging_flags(scoped, changelogs, now)
    bottleneck = bottleneck_breakdown(scoped, changelogs, now)
    deltas = changelog_deltas(scoped_keys, scoped_by_key, changelogs, cutoff, cutoff_end)

    todo_proposals: list[dict[str, Any]] = []
    epic_medians: dict[str, dict[str, Any]] = {}
    if todo_reestimates and epic_peer_issues:
        peer_cls = peer_changelogs or {}
        for key, cl in peer_cls.items():
            if key not in _PARSED_CL:
                _PARSED_CL[key] = parse_changelog_entry(cl)
        epic_medians = compute_epic_median_ratios(epic_peer_issues, peer_cls)
        todo_proposals = todo_reestimate_proposals(scoped, epic_medians)

    result: dict[str, Any] = {
        "scope": "include_tests" if include_tests else "exclude_tests",
        "test_summary": test_summary,
        "metrics": metrics,
        "top_epics": top_epics,
        "themes": themes,
        "aging": aging,
        "bottleneck": bottleneck,
        "deltas": deltas,
    }
    if as_of_meta:
        result["as_of"] = as_of_meta
    if todo_proposals:
        result["todo_reestimates"] = todo_proposals
        result["epic_median_ratios"] = epic_medians
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprint Health metrics from MCP JSON dumps")
    parser.add_argument("issue_files", nargs="+", type=Path, help="searchJiraIssuesUsingJql JSON dump(s)")
    parser.add_argument("--tests", type=Path, default=None, help="Optional separate Test-only issue dump")
    parser.add_argument(
        "--changelogs",
        type=Path,
        required=True,
        help="Changelog JSON map from fetch_changelogs.py (required)",
    )
    parser.add_argument("--start", required=True, help="Sprint start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Sprint end date YYYY-MM-DD")
    parser.add_argument("--today", default=None, help="Report date YYYY-MM-DD (default: UTC today)")
    parser.add_argument("--as-of", dest="as_of", default=None, help="Point-in-time report date YYYY-MM-DD")
    parser.add_argument("--sprint-id", type=int, default=None, help="Sprint id for --as-of membership gate")
    parser.add_argument("--sprint-name", default=None, help="Sprint name for --as-of metadata")
    parser.add_argument("--sprint-state", default=None, help="Sprint state for --as-of metadata")
    parser.add_argument("--cutoff", default=None, help="Day-to-day cutoff ISO datetime (default: yesterday 00:00 UTC)")
    parser.add_argument(
        "--cutoff-end",
        default=None,
        help="Upper bound for deltas ISO datetime (default: end of report day for --as-of)",
    )
    parser.add_argument("--include-tests", action="store_true", help="Include Test issues in metric totals")
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        metavar="LABEL=kw1,kw2",
        help="Goal theme keyword rollup (repeatable)",
    )
    parser.add_argument("--out", type=Path, default=None, help="Write JSON result to file (stdout gets summary only)")
    parser.add_argument("--epic-peers", type=Path, default=None, help="Batched Epic peer issues JSON (5b.3)")
    parser.add_argument("--peer-changelogs", type=Path, default=None, help="Changelogs for Epic peer issues")
    parser.add_argument(
        "--todo-reestimates",
        action="store_true",
        help="Compute To Do re-estimate proposals from Epic peer calibration",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--status-mapping",
        type=Path,
        default=Path(".sprint_tmp/jira-status-mapping.json"),
        help="Jira status bucket mapping (from fetch_statuses.py)",
    )
    args = parser.parse_args()

    if not args.status_mapping.is_file():
        print(
            f"error: status mapping not found at {args.status_mapping}. "
            "Run fetch_statuses.py first (chained before sprint_metrics in Step 3).",
            file=sys.stderr,
        )
        return 2
    init_status_mapping(args.status_mapping)

    if args.todo_reestimates and not args.epic_peers:
        print("error: --todo-reestimates requires --epic-peers", file=sys.stderr)
        return 2

    if args.as_of and args.sprint_id is None:
        print("error: --as-of requires --sprint-id", file=sys.stderr)
        return 2

    changelogs = load_changelogs(args.changelogs)
    if not changelogs:
        print(
            f"error: --changelogs {args.changelogs} is missing or empty. "
            "Run fetch_changelogs.py first (requires jira-config.json).",
            file=sys.stderr,
        )
        return 2

    start = parse_date(args.start)
    end = parse_date(args.end)
    if args.as_of:
        today = parse_date(args.as_of)
    else:
        today = parse_date(args.today) if args.today else datetime.now(timezone.utc).date()

    all_issues = load_issues(args.issue_files)
    extra_tests: list[dict[str, Any]] | None = None
    if args.tests:
        all_issues.extend(load_issues([args.tests]))
        if not args.include_tests:
            extra_tests = load_issues([args.tests])

    theme_defs: list[tuple[str, list[str]]] = []
    for raw_theme in args.theme:
        theme_defs.append(parse_theme_arg(raw_theme))

    cutoff = None
    if args.cutoff:
        cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))

    cutoff_end = None
    if args.cutoff_end:
        cutoff_end = datetime.fromisoformat(args.cutoff_end.replace("Z", "+00:00"))

    epic_peer_issues = None
    peer_changelogs = None
    if args.todo_reestimates and args.epic_peers:
        epic_peer_issues = load_issues([args.epic_peers])
        peer_changelogs = load_changelogs(args.peer_changelogs) if args.peer_changelogs else {}

    result = build_result(
        all_issues,
        changelogs,
        start,
        end,
        today,
        as_of=args.as_of,
        sprint_id=args.sprint_id,
        sprint_name=args.sprint_name,
        sprint_state=args.sprint_state,
        cutoff=cutoff,
        cutoff_end=cutoff_end,
        theme_defs=theme_defs,
        include_tests=args.include_tests,
        extra_test_issues=extra_tests,
        todo_reestimates=args.todo_reestimates,
        epic_peer_issues=epic_peer_issues,
        peer_changelogs=peer_changelogs,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print_summary_line(result, args.out)
        return 0

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(
            format_text(
                result["metrics"],
                result["test_summary"],
                result["top_epics"],
                result["aging"],
                result["deltas"],
                result.get("themes") or None,
                args.include_tests,
                result.get("todo_reestimates"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
