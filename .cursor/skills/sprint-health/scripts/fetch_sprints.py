#!/usr/bin/env python3
"""Fetch board sprints via Jira Agile REST API for sprint-health.

Usage:
  python fetch_sprints.py --as-of 2026-07-05
  python fetch_sprints.py --as-of 2026-07-05 --output .sprint_tmp/sprint.json
  python fetch_sprints.py --list --output .sprint_tmp/sprints.json

Requires a Jira API token (Basic auth). See jira-config.example.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_SITE = "inhabitiq.atlassian.net"
DEFAULT_BOARD = 231
SPRINTS_PATH = "/rest/agile/1.0/board/{board_id}/sprint"


def load_config(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    email = (data.get("email") or "").strip()
    token = (data.get("apiToken") or "").strip()
    site = (data.get("site") or DEFAULT_SITE).strip()
    if not email or not token or "YOUR-" in email or "YOUR-" in token:
        raise ValueError(
            f"Missing email or apiToken in {path}. "
            "Copy jira-config.example.json to jira-config.json and add your credentials."
        )
    return {"email": email, "apiToken": token, "site": site}


def parse_date(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_board_sprints(
    site: str,
    email: str,
    api_token: str,
    board_id: int = DEFAULT_BOARD,
) -> list[dict[str, Any]]:
    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {auth}",
    }

    sprints: list[dict[str, Any]] = []
    start_at = 0
    max_results = 50

    while True:
        url = (
            f"https://{site}{SPRINTS_PATH.format(board_id=board_id)}"
            f"?state=active,closed,future&startAt={start_at}&maxResults={max_results}"
        )
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"sprint fetch failed HTTP {exc.code}: {err_body[:500]}"
            ) from exc

        values = payload.get("values", [])
        sprints.extend(values)
        if payload.get("isLast", True) or not values:
            break
        start_at += len(values)

    return sprints


def sprint_end(sprint: dict[str, Any]) -> datetime | None:
    return parse_iso_datetime(sprint.get("completeDate")) or parse_iso_datetime(
        sprint.get("endDate")
    )


def sprint_contains_date(sprint: dict[str, Any], target: date) -> bool:
    start = parse_iso_datetime(sprint.get("startDate"))
    end = sprint_end(sprint)
    if not start or not end:
        return False
    start_d = start.date()
    end_d = end.date()
    return start_d <= target <= end_d


def select_sprint_for_date(
    sprints: list[dict[str, Any]], target: date, board_id: int = DEFAULT_BOARD
) -> dict[str, Any] | None:
    candidates = [
        s
        for s in sprints
        if sprint_contains_date(s, target) and s.get("boardId", board_id) == board_id
    ]
    if not candidates:
        return None
    # Prefer active, then most recently started
    candidates.sort(
        key=lambda s: (
            0 if s.get("state") == "active" else 1,
            -(parse_iso_datetime(s.get("startDate")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
        )
    )
    return candidates[0]


def normalize_sprint(sprint: dict[str, Any]) -> dict[str, Any]:
    start = parse_iso_datetime(sprint.get("startDate"))
    end = sprint_end(sprint)
    return {
        "id": sprint.get("id"),
        "name": sprint.get("name", ""),
        "state": sprint.get("state", ""),
        "boardId": sprint.get("boardId"),
        "goal": sprint.get("goal", ""),
        "startDate": sprint.get("startDate"),
        "endDate": sprint.get("endDate"),
        "completeDate": sprint.get("completeDate"),
        "start": start.date().isoformat() if start else None,
        "end": end.date().isoformat() if end else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Jira board sprints for sprint-health")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "jira-config.json",
        help="Path to jira-config.json",
    )
    parser.add_argument(
        "--board",
        type=int,
        default=DEFAULT_BOARD,
        help=f"Agile board id (default: {DEFAULT_BOARD})",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        help="Select sprint active on this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all sprints instead of selecting one",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON result to file",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    sprints = fetch_board_sprints(cfg["site"], cfg["email"], cfg["apiToken"], args.board)

    if args.list:
        result: dict[str, Any] = {
            "boardId": args.board,
            "count": len(sprints),
            "sprints": [normalize_sprint(s) for s in sprints],
        }
    elif args.as_of:
        target = parse_date(args.as_of)
        selected = select_sprint_for_date(sprints, target, args.board)
        if not selected:
            print(
                f"No sprint found for board {args.board} on {target.isoformat()}.",
                file=sys.stderr,
            )
            return 1
        norm = normalize_sprint(selected)
        result = {
            "asOf": target.isoformat(),
            "boardId": args.board,
            "sprint": norm,
            "jql": f"project = SCL AND sprint = {norm['id']} AND issuetype != Test",
        }
        print(f"SPRINT_ID {norm['id']}")
        print(f"SPRINT_NAME {norm['name']}")
        print(f"SPRINT_STATE {norm['state']}")
        print(f"START {norm['start']}")
        print(f"END {norm['end']}")
        print(f"GOAL {norm['goal']}")
        print(f"JQL {result['jql']}")
    else:
        print("error: specify --as-of YYYY-MM-DD or --list", file=sys.stderr)
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
