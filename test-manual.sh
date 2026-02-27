#!/usr/bin/env bash
# aside manual test script — run inside the VM
# Each test exercises multiple features. Mark pass/fail/skip after each.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
PASS=0; FAIL=0; SKIP=0; RESULTS=()

pause() {
    echo ""
    echo -e "${CYAN}>>> [y/n/s] ${NC}"
    read -r -n1 ans; echo ""
    case "$ans" in
        y|Y) PASS=$((PASS+1)); RESULTS+=("${GREEN}PASS${NC}: $1") ;;
        n|N) FAIL=$((FAIL+1)); RESULTS+=("${RED}FAIL${NC}: $1") ;;
        *)   SKIP=$((SKIP+1)); RESULTS+=("${YELLOW}SKIP${NC}: $1") ;;
    esac
}

header() {
    echo ""
    echo -e "${BOLD}${YELLOW}═══ $1 ═══${NC}"
    echo ""
}

# --- Preflight ---
echo -e "${BOLD}Preflight checks...${NC}"
ok=true
pgrep -f "aside.daemon" >/dev/null 2>&1 && echo -e "${GREEN}✓${NC} daemon" || { echo -e "${RED}✗${NC} daemon not running"; ok=false; }
pgrep -f "aside-overlay" >/dev/null 2>&1 && echo -e "${GREEN}✓${NC} overlay" || echo -e "${YELLOW}!${NC} overlay not detected"
[ -n "${ANTHROPIC_API_KEY:-}" ] && echo -e "${GREEN}✓${NC} API key" || { echo -e "${RED}✗${NC} no ANTHROPIC_API_KEY"; ok=false; }
$ok || { echo "Fix prerequisites first."; exit 1; }
echo -e "\n${CYAN}Press any key to start...${NC}"; read -r -n1; echo ""

# ─────────────────────────────────────────────────────────────────────
header "1. Tool use + overlay streaming + linger + conversation continuity"
echo "Query asks for shell tool use, produces multi-line output."
echo -e "${YELLOW}Watch for:${NC}"
echo "  - Overlay appears, streams text"
echo "  - Shell tool is invoked (brief 'thinking' pause, then result)"
echo "  - After streaming ends, overlay LINGERS ~3s before fading"
echo "  - Hover mouse over overlay to pause the fade"
echo ""
aside query "Use the shell tool to run 'uname -a' and tell me about this system."
echo "Waiting for response + linger + fade..."
sleep 20
echo ""
echo "Now testing conversation continuity (follow-up within 60s):"
aside query "What distro was that again?"
sleep 15
pause "1. Tool use + streaming + linger + hover + continuity"

# ─────────────────────────────────────────────────────────────────────
header "2. Memory save + recall across conversations"
echo "Saving to memory, then recalling in a NEW conversation."
echo -e "${YELLOW}Watch for:${NC}"
echo "  - First query: LLM uses memory tool to save"
echo "  - Second query (--new): LLM searches memory, finds 'purple'"
echo ""
aside query "Remember that my favorite color is purple. Save this to memory."
sleep 12
aside query "What's my favorite color? Check your memory." --new
sleep 12
pause "2. Memory save + recall across conversations"

# ─────────────────────────────────────────────────────────────────────
header "3. Cancel + rapid-fire"
echo "Tests cancel mid-stream, then rapid-fire query replacement."
echo -e "${YELLOW}Watch for:${NC}"
echo "  - Cancel: overlay dismissed mid-stream"
echo "  - Rapid-fire: only the LAST query's answer shows"
echo ""
echo "Sending long query, cancelling after 2s..."
aside query "Count slowly from 1 to 100, one number per line." --new &
sleep 2
aside cancel
sleep 3

echo "Rapid-fire: 3 queries in quick succession..."
aside query "Say only: FIRST" --new &
sleep 0.3
aside query "Say only: SECOND" --new &
sleep 0.3
aside query "Say only: THIRD" --new
sleep 12
pause "3. Cancel + rapid-fire"

# ─────────────────────────────────────────────────────────────────────
header "4. Overlay interactions (scroll, click dismiss, right-click cancel)"
echo "Long response to test scrolling and mouse interactions."
echo -e "${YELLOW}Watch for:${NC}"
echo "  - Scroll UP with mouse wheel while streaming (pauses auto-scroll)"
echo "  - Scrolling cancels the linger/fade (overlay stays visible)"
echo "  - LEFT-CLICK dismisses instantly"
echo "  - (Next query) RIGHT-CLICK cancels the query + dismisses"
echo ""
aside query "Write a 12-line poem about mountains. Number each line." --new
echo "Try scrolling, then left-click to dismiss when ready."
sleep 25

aside query "Count from 1 to 50, one per line." --new
echo "RIGHT-CLICK the overlay to cancel mid-stream."
sleep 15
pause "4. Scroll + left-click dismiss + right-click cancel"

# ─────────────────────────────────────────────────────────────────────
header "5. Shell tool edge cases"
echo "More shell tool exercises."
echo -e "${YELLOW}Watch for:${NC}"
echo "  - LLM runs a command and reports output"
echo "  - Unicode/special chars render correctly in overlay"
echo ""
aside query "Use the shell tool to list files in /tmp and tell me how many there are." --new
sleep 15
aside query "List 3 animals with emoji. Use actual emoji characters." --new
sleep 12
pause "5. Shell tool + unicode rendering"

# ─────────────────────────────────────────────────────────────────────
header "6. Status + persistence + edge cases"
echo "Non-interactive checks + edge cases."
echo ""

echo -e "${BOLD}aside status:${NC}"
aside status 2>&1 || echo "(returned non-zero)"
echo ""

CONV_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/aside/conversations"
USAGE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/aside/usage.jsonl"
[ -d "$CONV_DIR" ] && echo "Conversations: $(ls "$CONV_DIR"/*.json 2>/dev/null | wc -l) files" || echo "No conversations dir"
[ -f "$USAGE_FILE" ] && echo "Usage log: $(wc -l < "$USAGE_FILE") entries" || echo "No usage log"
echo ""

echo "Edge cases:"
echo "  Empty query..."
aside query "" 2>&1 || true
sleep 2
echo "  Special characters..."
aside query "What do & | > < mean in bash? Also test: \"quotes\" and 'apostrophes'." --new
sleep 12
echo "  Unicode/emoji..."
aside query "List 3 animals with emoji. Use actual emoji characters." --new
sleep 12
pause "6. Status + persistence + edge cases"

# ─────────────────────────────────────────────────────────────────────
header "RESULTS"
echo ""
for r in "${RESULTS[@]}"; do echo -e "  $r"; done
echo ""
echo -e "  ${GREEN}PASS: $PASS${NC}  ${RED}FAIL: $FAIL${NC}  ${YELLOW}SKIP: $SKIP${NC}  Total: $((PASS+FAIL+SKIP))"
echo ""
[ "$FAIL" -gt 0 ] && echo -e "${RED}Failures detected — report what broke!${NC}" || echo -e "${GREEN}All passed!${NC}"
