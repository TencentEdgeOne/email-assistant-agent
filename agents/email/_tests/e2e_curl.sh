"""End-to-end smoke test for the run → review HITL flow.

Runs against a local pnpm dev server. Skip this if you don't have one
running — the unit tests already validate the mechanics offline.

Usage:
    cd agents/email-assistant
    pnpm dev &                     # start the local Pages dev server
    bash agents/email/tests/e2e_curl.sh

Expected:
    Step 1: SSE stream pauses with event:human_review_required
    Step 2: review POST returns next pause OR final done event
"""
set -euo pipefail

BASE_URL=${BASE_URL:-http://localhost:8788}
CONV=${CONV:-conv-$(date +%s)-$$}

echo "═══════════════════════════════════════════════════════════════════════════"
echo "Step 1: POST /email/run — start daily_digest task"
echo "═══════════════════════════════════════════════════════════════════════════"
echo "BASE_URL=$BASE_URL  CONV=$CONV"
echo ""

curl -N -sS -X POST "$BASE_URL/email/run" \
  -H "Content-Type: application/json" \
  -H "X-Conversation-Id: $CONV" \
  -d '{"task":"daily_digest"}' \
  | tee /tmp/email-sse-1.log

echo ""
echo ""

if grep -q "human_review_required" /tmp/email-sse-1.log; then
    echo "✓ Step 1 paused at human_review_required as expected"
else
    echo "✗ Step 1 did not pause — check the SSE log above" >&2
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "Step 2: POST /email/review — approve the first draft"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

curl -N -sS -X POST "$BASE_URL/email/review" \
  -H "Content-Type: application/json" \
  -H "X-Conversation-Id: $CONV" \
  -d '{"decision":"approve"}' \
  | tee /tmp/email-sse-2.log

echo ""
echo ""

if grep -q -e 'human_review_required' -e '\[DONE\]' /tmp/email-sse-2.log; then
    echo "✓ Step 2 either paused on next email or completed"
    echo ""
    echo "To approve the next email, repeat Step 2."
    echo "To inspect the final summary:"
    echo "    grep '\"summary\"' /tmp/email-sse-2.log"
else
    echo "✗ Step 2 unexpected output" >&2
    exit 1
fi
