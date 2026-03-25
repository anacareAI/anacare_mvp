#!/usr/bin/env python3
"""Send Ralph updates to Slack via incoming webhook.

Usage:
    # Post a single iteration result
    python tools/slack_notify.py --story "Add CPT lookup endpoint" --status PASSED --quality 8 --notes "Created /cpt endpoint"

    # Post a full log summary
    python tools/slack_notify.py --summary logs/2026-03-25_0200_nightly.txt

    # Dry run (print without sending)
    python tools/slack_notify.py --story "Test" --status PASSED --dry-run

Requires SLACK_WEBHOOK_URL in .env or environment.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def send_to_slack(payload: dict) -> bool:
    if not WEBHOOK_URL:
        return False

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Slack send failed: {e}", file=sys.stderr)
        return False


def post_iteration(story: str, status: str, quality: str = "?",
                   notes: str = "", iteration: str = "") -> dict:
    """Post a single iteration result to Slack."""
    icon = ":white_check_mark:" if "PASS" in status.upper() else ":x:"
    iter_label = f"Iteration {iteration} — " if iteration else ""

    text = f"{icon} *{iter_label}{story}*\nStatus: {status} | Quality: {quality}/10"
    if notes:
        text += f"\n_{notes}_"

    return {"text": text}


def post_summary(log_path: Path) -> dict:
    """Parse a full log file and post a summary."""
    text = log_path.read_text()
    iterations = re.findall(
        r"--- Iteration (\d+) ---\n(.*?)---",
        text,
        re.DOTALL,
    )

    stories = []
    for num, body in iterations:
        story = {"iteration": int(num)}
        for line in body.strip().split("\n"):
            line = line.strip()
            if line.startswith("Story:"):
                story["story"] = line.split(":", 1)[1].strip()
            elif line.startswith("Status:"):
                story["status"] = line.split(":", 1)[1].strip()
            elif line.startswith("Quality Score:"):
                story["quality"] = line.split(":", 1)[1].strip()
            elif line.startswith("Notes:"):
                story["notes"] = line.split(":", 1)[1].strip()
        stories.append(story)

    passed = sum(1 for s in stories if "PASSED" in s.get("status", ""))
    failed = sum(1 for s in stories if "FAILED" in s.get("status", ""))

    lines = [f"*Ralph Report — {log_path.name}*"]
    lines.append(f":white_check_mark: {passed} passed | :x: {failed} failed | :bar_chart: {len(stories)} total\n")

    for s in stories:
        icon = ":white_check_mark:" if "PASSED" in s.get("status", "") else ":x:"
        lines.append(f"{icon}  {s.get('story', '?')}  (quality: {s.get('quality', '?')}/10)")

    failures = [s for s in stories if "FAILED" in s.get("status", "")]
    if failures:
        lines.append("\n:warning: *Failures:*")
        for s in failures:
            lines.append(f"• *{s.get('story', '?')}*: {s.get('notes', 'no notes')}")

    return {"text": "\n".join(lines)}


def main():
    parser = argparse.ArgumentParser(description="Send Ralph updates to Slack")
    parser.add_argument("--story", help="Story title (for per-iteration mode)")
    parser.add_argument("--status", help="PASSED or FAILED")
    parser.add_argument("--quality", default="?", help="Quality score 1-10")
    parser.add_argument("--notes", default="", help="Notes from iteration")
    parser.add_argument("--iteration", default="", help="Iteration number")
    parser.add_argument("--summary", help="Path to log file for full summary")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    args = parser.parse_args()

    if args.summary:
        payload = post_summary(Path(args.summary))
    elif args.story and args.status:
        payload = post_iteration(
            args.story, args.status, args.quality, args.notes, args.iteration
        )
    else:
        parser.error("Use --story + --status for per-iteration, or --summary for full log")

    if args.dry_run:
        print(json.dumps(payload, indent=2))
    else:
        ok = send_to_slack(payload)
        if ok:
            print("Slack notification sent.")
        elif not WEBHOOK_URL:
            pass  # silently skip if no webhook configured
        else:
            print("Slack notification failed.", file=sys.stderr)


if __name__ == "__main__":
    main()
