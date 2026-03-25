#!/usr/bin/env bash
set -euo pipefail
#
# Run Ralph for a fixed time window (default 3 hours).
# Each iteration takes ~5-10 minutes, so 3 hours ≈ 18-36 iterations.
#
# Usage:
#   ./ralph-nightly.sh              # runs for 3 hours
#   ./ralph-nightly.sh 4            # runs for 4 hours
#   RALPH_HOURS=2 ./ralph-nightly.sh
#
# Designed to be triggered by launchd/cron every night.

cd /Users/joshuakao/anacare_03.20

HOURS="${1:-${RALPH_HOURS:-3}}"
SECONDS_LIMIT=$((HOURS * 3600))
START_TIME=$SECONDS

mkdir -p logs
LOG_FILE="logs/$(date '+%Y-%m-%d_%H%M')_nightly.txt"

source tools/slack_iteration.sh

echo "🌙 Ralph nightly starting at $(date '+%Y-%m-%d %H:%M:%S')" | tee "$LOG_FILE"
echo "   Time limit: ${HOURS}h (${SECONDS_LIMIT}s)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

ITERATION=0

while true; do
  ELAPSED=$((SECONDS - START_TIME))
  REMAINING=$((SECONDS_LIMIT - ELAPSED))

  if [ "$REMAINING" -le 300 ]; then
    echo "⏰ Less than 5 minutes remaining. Stopping." | tee -a "$LOG_FILE"
    break
  fi

  ITERATION=$((ITERATION + 1))
  echo "" | tee -a "$LOG_FILE"
  echo "━━━ Iteration $ITERATION ($(( ELAPSED / 60 ))m elapsed, $(( REMAINING / 60 ))m remaining) ━━━" | tee -a "$LOG_FILE"

  result=$(claude --permission-mode acceptEdits -p \
    "@PRD.md @prd.json \

    CONTEXT:
    Read PRD.md before doing anything.
    prd.json contains the structured list of tasks and stories.

    YOUR JOB:
    1. Read prd.json. Find the first task with a story where passes is false. Implement that story.
       (PRD.md for high-level context)
    2. Implement it — one logical change, keep it focused
    3. Run feedback loops:
       - Tests: python -m pytest tests/ -v
       - Type checks: cd frontend && npx tsc --noEmit 2>&1; cd ..
       - Lint: cd frontend && npx next lint 2>&1; cd ..
       Do NOT commit if any check fails. Fix first.
       If a check is not applicable, skip it and note SKIP.
    4. Update prd.json to set passes: true on the completed story.
    5. Append to $LOG_FILE in exactly this format:

       --- Iteration $ITERATION ---
       Story: [task title]
       Status: PASSED / FAILED
       Tests: PASS / FAIL — [X passed, Y failed]
       Type Check: PASS / FAIL / SKIP
       Lint: PASS / FAIL / SKIP
       Quality Score: [1-10]
       Notes: [what you did, any blockers, what the next iteration should know]
       ---

    6. Commit: git add -A && git commit -m 'feat: [short description of change]'

    RULES:
    - ONLY DO ONE STORY. Stop after committing.
    - If you cannot complete the story, set Status: FAILED and explain in Notes.
    - Do not modify PRD.md.
    - Keep changes small and focused.
    - If all stories in prd.json have passes: true, output exactly: <promise>COMPLETE</promise>" 2>&1) || true

  echo "$result" >> "$LOG_FILE"

  # Post this iteration to Slack
  slack_post_last "$LOG_FILE" "$ITERATION"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "✅ All stories complete after $ITERATION iterations." | tee -a "$LOG_FILE"
    break
  fi

done

TOTAL_ELAPSED=$(( (SECONDS - START_TIME) / 60 ))
echo "" | tee -a "$LOG_FILE"
echo "🌙 Ralph nightly finished at $(date '+%Y-%m-%d %H:%M:%S') — $ITERATION iterations in ${TOTAL_ELAPSED}m" | tee -a "$LOG_FILE"

# Send summary to Slack
if [ -f tools/slack_notify.py ]; then
  echo "Sending Slack notification..."
  python3 tools/slack_notify.py "$LOG_FILE" 2>&1 || echo "⚠️ Slack notification failed"
fi
