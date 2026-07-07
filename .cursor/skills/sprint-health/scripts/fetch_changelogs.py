#!/usr/bin/env python3
"""Bulk-fetch Jira changelogs via REST API for sprint-health.

Usage:
  python fetch_changelogs.py issues_page1.json \\
    --config ../jira-config.json \\
    --output .sprint_tmp/changelogs.json

Requires a Jira API token (Basic auth). See jira-config.example.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_SITE = "inhabitiq.atlassian.net"
DEFAULT_FIELD_IDS = ["status", "Story Points", "Sprint", "Flagged"]
BULKFETCH_PATH = "/rest/api/3/changelog/bulkfetch"


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


def load_issue_keys(issue_files: list[Path]) -> tuple[list[str], dict[str, str]]:
    keys: list[str] = []
    id_to_key: dict[str, str] = {}
    seen: set[str] = set()
    for path in issue_files:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        for issue in data.get("issues", []):
            key = issue.get("key")
            issue_id = str(issue.get("id", ""))
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
            if key and issue_id:
                id_to_key[issue_id] = key
    return keys, id_to_key


def bulkfetch_changelogs(
    site: str,
    email: str,
    api_token: str,
    issue_keys: list[str],
    field_ids: list[str] | None,
    id_to_key: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    if not issue_keys:
        return {}

    url = f"https://{site}{BULKFETCH_PATH}"
    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth}",
    }

    result: dict[str, dict[str, Any]] = {}
    next_token: str | None = None

    while True:
        body: dict[str, Any] = {
            "issueIdsOrKeys": issue_keys,
            "maxResults": 1000,
        }
        if field_ids is not None:
            body["fieldIds"] = field_ids
        if next_token:
            body["nextPageToken"] = next_token

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"bulkfetch failed HTTP {exc.code}: {err_body[:500]}"
            ) from exc

        for entry in payload.get("issueChangeLogs", []):
            issue_id = str(entry.get("issueId", ""))
            issue_key = entry.get("issueKey") or (id_to_key or {}).get(issue_id) or issue_id
            histories = entry.get("changeHistories") or entry.get("histories") or []
            if issue_key:
                result[issue_key] = {"histories": histories}

        next_token = payload.get("nextPageToken")
        if not next_token:
            break

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-fetch Jira changelogs for sprint-health")
    parser.add_argument("issue_files", nargs="+", type=Path, help="Main sprint issue JSON dump(s)")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "jira-config.json",
        help="Path to jira-config.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".sprint_tmp/changelogs.json"),
        help="Output path for changelog map",
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        dest="field_ids",
        help="Changelog field filter (repeatable; default: status, Story Points, Sprint, Flagged)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Fetch all changelog fields (omit fieldIds filter; required for --as-of replay)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    keys, id_to_key = load_issue_keys(args.issue_files)
    if not keys:
        print("No issue keys found in input files.", file=sys.stderr)
        return 1

    field_ids = None if args.full else (args.field_ids or list(DEFAULT_FIELD_IDS))
    changelogs = bulkfetch_changelogs(
        cfg["site"], cfg["email"], cfg["apiToken"], keys, field_ids, id_to_key
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(changelogs, f, ensure_ascii=False, indent=2)

    print(f"Fetched changelogs for {len(changelogs)} issue(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
