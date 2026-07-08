#!/usr/bin/env python3
"""Wrap an agent-authored roast body fragment in the shared styled HTML shell.

Purely presentational: substitutes the title/subtitle tokens and injects the
body fragment into the template. No metrics parsing happens here so the roast
styling stays consistent with assets/roast-template.html.

Usage:
  python render_roast.py \\
    --title "\U0001f525 THE A TEAM ROAST \u2014 Sprint 56 \U0001f525" \\
    --subtitle "Roast Friday edition \u00b7 2026-07-08 \u00b7 Day 4 of 10 \u00b7 real data, zero mercy" \\
    --body .sprint_tmp/roast_body.html \\
    --out sprint-health_ROAST_SCL_Sprint-56_2026-07-08.html \\
    [--template .cursor/skills/sprint-health/assets/roast-template.html]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BODY_MARKER = "<!-- ROAST_BODY -->"
DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "assets" / "roast-template.html"
)


def render(template: str, title: str, subtitle: str, body: str) -> str:
    if BODY_MARKER not in template:
        raise ValueError(f"Template is missing the {BODY_MARKER} marker.")
    html = template.replace("{{TITLE}}", title).replace("{{SUBTITLE}}", subtitle)
    return html.replace(BODY_MARKER, body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Document + h1 heading text")
    parser.add_argument("--subtitle", required=True, help="Sub-line under the heading")
    parser.add_argument(
        "--body",
        required=True,
        help="Path to the agent-authored HTML body fragment",
    )
    parser.add_argument("--out", required=True, help="Path to write the roast HTML")
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE),
        help="Path to the HTML shell template (default: assets/roast-template.html)",
    )
    args = parser.parse_args()

    template_path = Path(args.template)
    body_path = Path(args.body)
    out_path = Path(args.out)

    if not template_path.is_file():
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 1
    if not body_path.is_file():
        print(f"ERROR: body fragment not found: {body_path}", file=sys.stderr)
        return 1

    template = template_path.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")

    try:
        html = render(template, args.title, args.subtitle, body)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"WROTE {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
