#!/usr/bin/env python3
"""Fetch Jira workflow statuses for SCL and build sprint-health bucket mapping.

Usage:
  python fetch_statuses.py \\
    --config ../jira-config.json \\
    --output .sprint_tmp/jira-status-mapping.json \\
    [--project SCL] [--max-age-days 7] [--force]

Requires a Jira API token (Basic auth). See jira-config.example.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_SITE = "inhabitiq.atlassian.net"
REVIEW_QA_KEYWORDS = ("review", "qa", "test", "uat", "verify", "validation")


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


def jira_get(site: str, email: str, api_token: str, path: str) -> Any:
    url = f"https://{site}{path}"
    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {"Accept": "application/json", "Authorization": f"Basic {auth}"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jira GET {path} failed HTTP {exc.code}: {err_body[:500]}") from exc


def sprint_health_bucket(name: str, status_category: str) -> str:
    lower = name.lower()
    if status_category == "Done":
        return "done"
    if status_category == "To Do":
        return "todo"
    if any(k in lower for k in REVIEW_QA_KEYWORDS):
        return "review_qa"
    if status_category == "In Progress":
        return "in_progress"
    return "other"


def build_mapping(project_statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for issue_type in project_statuses:
        type_name = issue_type.get("name", "")
        for status in issue_type.get("statuses", []):
            name = status["name"]
            cat = (status.get("statusCategory") or {}).get("name", "")
            entry = by_name.setdefault(
                name,
                {
                    "name": name,
                    "id": status.get("id"),
                    "statusCategory": cat,
                    "issueTypes": [],
                },
            )
            entry["issueTypes"].append(type_name)

    mapping: list[dict[str, Any]] = []
    for name, info in sorted(by_name.items(), key=lambda x: x[0].lower()):
        cat = info["statusCategory"]
        mapping.append(
            {
                "name": name,
                "id": info["id"],
                "statusCategory": cat,
                "sprintHealthBucket": sprint_health_bucket(name, cat),
                "issueTypes": sorted(set(info["issueTypes"])),
            }
        )
    return mapping


def fetch_mapping(cfg: dict[str, str], project: str = "SCL") -> dict[str, Any]:
    project_statuses = jira_get(
        cfg["site"],
        cfg["email"],
        cfg["apiToken"],
        f"/rest/api/3/project/{project}/statuses",
    )
    statuses = build_mapping(project_statuses)
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "site": cfg["site"],
        "statuses": statuses,
    }


def _mapping_is_fresh(path: Path, max_age_days: int) -> bool:
    if max_age_days <= 0 or not path.is_file():
        return False
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = data.get("fetchedAt")
        if not fetched_at:
            return False
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - fetched
        return age <= timedelta(days=max_age_days)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def load_or_fetch_mapping(
    cfg: dict[str, str],
    output: Path,
    project: str = "SCL",
    max_age_days: int = 0,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Return (payload, fetched_from_api). Uses cache when fresh and force=False."""
    if not force and _mapping_is_fresh(output, max_age_days):
        with output.open(encoding="utf-8") as f:
            return json.load(f), False
    return fetch_mapping(cfg, project), True


def write_mapping(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def print_mapping_summary(payload: dict[str, Any], output: Path, from_api: bool) -> None:
    statuses = payload.get("statuses", [])
    buckets: dict[str, int] = {}
    for row in statuses:
        buckets[row["sprintHealthBucket"]] = buckets.get(row["sprintHealthBucket"], 0) + 1
    source = "fetched" if from_api else "cached"
    print(f"{source.capitalize()} {len(statuses)} unique status(es) for {payload.get('project', 'SCL')} -> {output}")
    for bucket, count in sorted(buckets.items()):
        print(f"  {bucket}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Jira statuses and build sprint-health mapping")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "jira-config.json",
        help="Path to jira-config.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".sprint_tmp/jira-status-mapping.json"),
        help="Output path for status mapping JSON",
    )
    parser.add_argument("--project", default="SCL", help="Jira project key")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=0,
        help="Reuse existing mapping if younger than N days (0 = always fetch)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache and fetch from Jira",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    payload, from_api = load_or_fetch_mapping(
        cfg, args.output, args.project, args.max_age_days, args.force
    )
    if from_api:
        write_mapping(payload, args.output)
    print_mapping_summary(payload, args.output, from_api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
