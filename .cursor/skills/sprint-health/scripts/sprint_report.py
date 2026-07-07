#!/usr/bin/env python3
"""Single-process sprint-health runner: parallel I/O + metrics in one invocation.

Usage:
  python sprint_report.py issues_page1.json [issues_page2.json ...] \\
    --start 2026-06-18 --end 2026-07-02 \\
    [--as-of 2026-06-25 --sprint-id 14379 --sprint-name "SCL Sprint 55"] \\
    [--full] \\
    --out .sprint_tmp/metrics.json \\
    [--theme "VRBO=vrbo,SCL-12933"] \\
    [--tests tests.json] [--include-tests]

Replaces the chained fetch_statuses && fetch_changelogs && sprint_metrics workflow.
Issues must already be fetched via MCP (searchJiraIssuesUsingJql JSON dumps).
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from fetch_changelogs import bulkfetch_changelogs, load_config, load_issue_keys
from fetch_statuses import load_or_fetch_mapping, write_mapping, print_mapping_summary
from sprint_metrics import (
    build_result,
    init_status_mapping,
    load_issues,
    parse_date,
    parse_theme_arg,
    print_summary_line,
)


def _fetch_statuses_task(
    cfg: dict[str, str],
    output: Path,
    project: str,
    max_age_days: int,
    force: bool,
) -> tuple[dict[str, Any], bool]:
    payload, from_api = load_or_fetch_mapping(cfg, output, project, max_age_days, force)
    if from_api:
        write_mapping(payload, output)
    return payload, from_api


def _fetch_changelogs_task(
    cfg: dict[str, str],
    issue_files: list[Path],
    full: bool,
) -> dict[str, dict[str, Any]]:
    keys, id_to_key = load_issue_keys(issue_files)
    if not keys:
        raise RuntimeError("No issue keys found in input files.")
    field_ids = None if full else ["status", "Story Points", "Sprint", "Flagged"]
    return bulkfetch_changelogs(
        cfg["site"], cfg["email"], cfg["apiToken"], keys, field_ids, id_to_key
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint-health runner: parallel status/changelog fetch + metrics"
    )
    parser.add_argument("issue_files", nargs="+", type=Path, help="MCP issue JSON dump(s)")
    parser.add_argument("--config", type=Path, default=_SCRIPT_DIR.parent / "jira-config.json")
    parser.add_argument("--start", required=True, help="Sprint start YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Sprint end YYYY-MM-DD")
    parser.add_argument("--today", default=None, help="Report date YYYY-MM-DD (default: UTC today or --as-of)")
    parser.add_argument("--as-of", dest="as_of", default=None, help="Point-in-time report date")
    parser.add_argument("--sprint-id", type=int, default=None)
    parser.add_argument("--sprint-name", default=None)
    parser.add_argument("--sprint-state", default=None)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Fetch all changelog fields (required for --as-of replay)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".sprint_tmp/metrics.json"),
        help="Output metrics JSON path",
    )
    parser.add_argument(
        "--status-out",
        type=Path,
        default=Path(".sprint_tmp/jira-status-mapping.json"),
    )
    parser.add_argument(
        "--changelogs-out",
        type=Path,
        default=Path(".sprint_tmp/changelogs.json"),
    )
    parser.add_argument(
        "--status-max-age-days",
        type=int,
        default=7,
        help="Reuse cached status mapping if younger than N days (default: 7)",
    )
    parser.add_argument("--force-status", action="store_true", help="Ignore status cache")
    parser.add_argument("--tests", type=Path, default=None)
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        metavar="LABEL=kw1,kw2",
    )
    parser.add_argument("--project", default="SCL", help="Jira project for status mapping")
    args = parser.parse_args()

    if args.as_of and args.sprint_id is None:
        print("error: --as-of requires --sprint-id", file=sys.stderr)
        return 2
    if args.as_of and not args.full:
        print("note: --as-of implies --full changelog fetch", file=sys.stderr)
        args.full = True

    cfg = load_config(args.config)
    args.status_out.parent.mkdir(parents=True, exist_ok=True)
    args.changelogs_out.parent.mkdir(parents=True, exist_ok=True)

    status_from_api = False
    changelogs: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=2) as pool:
        status_future = pool.submit(
            _fetch_statuses_task,
            cfg,
            args.status_out,
            args.project,
            args.status_max_age_days,
            args.force_status,
        )
        changelog_future = pool.submit(
            _fetch_changelogs_task,
            cfg,
            args.issue_files,
            args.full,
        )
        for future in as_completed([status_future, changelog_future]):
            exc = future.exception()
            if exc is not None:
                raise exc
        status_payload, status_from_api = status_future.result()
        changelogs = changelog_future.result()

    print_mapping_summary(status_payload, args.status_out, status_from_api)
    with args.changelogs_out.open("w", encoding="utf-8") as f:
        json.dump(changelogs, f, ensure_ascii=False, indent=2)
    print(f"Fetched changelogs for {len(changelogs)} issue(s) -> {args.changelogs_out}")

    init_status_mapping(args.status_out)

    start = parse_date(args.start)
    end = parse_date(args.end)
    if args.as_of:
        today = parse_date(args.as_of)
    else:
        from datetime import datetime, timezone

        today = parse_date(args.today) if args.today else datetime.now(timezone.utc).date()

    all_issues = load_issues(args.issue_files)
    extra_tests: list[dict[str, Any]] | None = None
    if args.tests:
        all_issues.extend(load_issues([args.tests]))
        if not args.include_tests:
            extra_tests = load_issues([args.tests])

    theme_defs = [parse_theme_arg(t) for t in args.theme]

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
        theme_defs=theme_defs,
        include_tests=args.include_tests,
        extra_test_issues=extra_tests,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print_summary_line(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
