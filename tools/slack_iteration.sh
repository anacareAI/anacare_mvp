#!/usr/bin/env bash
# Post the last iteration block from a log file to Slack.
# Usage: source tools/slack_iteration.sh && slack_post_last "$LOG_FILE" "$ITERATION"

slack_post_last() {
  local log_file="$1"
  local iteration="${2:-}"

  # Extract fields from the last iteration block
  local story status quality notes
  story=$(grep -o 'Story: .*' "$log_file" | tail -1 | sed 's/Story: //')
  status=$(grep -o 'Status: .*' "$log_file" | tail -1 | sed 's/Status: //')
  quality=$(grep -o 'Quality Score: .*' "$log_file" | tail -1 | sed 's/Quality Score: //')
  notes=$(grep -o 'Notes: .*' "$log_file" | tail -1 | sed 's/Notes: //')

  if [ -n "$story" ] && [ -n "$status" ]; then
    python3 tools/slack_notify.py \
      --story "$story" \
      --status "$status" \
      --quality "${quality:-?}" \
      --notes "${notes:-}" \
      --iteration "${iteration:-}" 2>/dev/null || true
  fi
}
