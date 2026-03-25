#!/usr/bin/env bash
set -euo pipefail

cd /Users/joshuakao/anacare_03.20

# Preflight
command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI not on PATH"; exit 1; }
[ -f PRD.md ]       || { echo "ERROR: PRD.md missing"; exit 1; }
[ -f prd.json ]     || { echo "ERROR: prd.json missing"; exit 1; }

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

MAX_ITERATIONS=$1

# Create dated log file in logs/
mkdir -p logs
LOG_FILE="logs/$(date '+%Y-%m-%d_%H%M')_progress.txt"
touch "$LOG_FILE"

source tools/slack_iteration.sh

echo "AFK Ralph starting — max $MAX_ITERATIONS iterations"
echo "Logging to: $LOG_FILE"
echo "--- AFK Ralph: $(date '+%Y-%m-%d %H:%M:%S') — $MAX_ITERATIONS iterations ---" >> "$LOG_FILE"

for ((i=1; i<=$MAX_ITERATIONS; i++)); do
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Iteration $i of $MAX_ITERATIONS"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  result=$(claude --permission-mode acceptEdits -p \
    "@PRD.md @prd.json \

    CONTEXT:
    Read PRD.md before doing anything.
    prd.json contains the structured list of tasks and stories.

    YOUR JOB:
    1. Read prd.json. 1. Find the highest-priority feature to work on and work only on that feature.
   This should be the one YOU decide has the highest priority — not necessarily the first in the list. Implement that story.
       (PRD.md for high-level context)
    2. Implement it — one logical change, keep it focused
    3. Run feedback loops:
       - Tests: python -m pytest tests/ -v
       - Type checks: cd frontend && npx tsc --noEmit 2>&1; cd ..
       - Lint: cd frontend && npx next lint 2>&1; cd ..
       Do NOT commit if any check fails. Fix first.
       If a check is not applicable, skip it and note SKIP.
    4. Update prd.json to set passes: true on the completed story. Do NOT modify PRD.md.
    5. Append to $LOG_FILE in exactly this format:

       --- Iteration $i ---
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
    - If all stories in prd.json have passes: true, output exactly: <promise>COMPLETE</promise>")

  echo "$result"

  # Post this iteration to Slack
  slack_post_last "$LOG_FILE" "$i"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "✅ Complete after $i iterations." | tee -a "$LOG_FILE"
    exit 0
  fi

done

echo "⚠️ Reached max iterations ($MAX_ITERATIONS). Check prd.json for remaining stories." | tee -a "$LOG_FILE"
exit 0
