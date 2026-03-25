#!/usr/bin/env bash
set -euo pipefail

cd /Users/joshuakao/anacare_03.20

# Preflight
command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI not on PATH"; exit 1; }
[ -f PRD.md ]       || { echo "ERROR: PRD.md missing"; exit 1; }
[ -f prd.json ]     || { echo "ERROR: prd.json missing"; exit 1; }

# Create dated log file in logs/
mkdir -p logs
LOG_FILE="logs/$(date '+%Y-%m-%d_%H%M')_progress.txt"
touch "$LOG_FILE"

source tools/slack_iteration.sh

echo "--- Ralph: Single Iteration — $(date '+%Y-%m-%d %H:%M:%S') ---"
echo "Logging to: $LOG_FILE"

claude --permission-mode acceptEdits -p \
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
     If a check is not applicable (e.g. no frontend changes), skip it and note SKIP.
  4. Update prd.json to set passes: true on the completed story.
  5. Append to $LOG_FILE in exactly this format:

     --- Iteration 1 ---
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
  - Keep changes small and focused."

# Post to Slack
slack_post_last "$LOG_FILE" "1"
