#!/usr/bin/env bash
# aside manual test script — run inside the VM
# Usage: bash test-manual.sh
# Each test pauses for you to observe the result.

set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

PASS=0
FAIL=0
SKIP=0
RESULTS=()

pause() {
    echo ""
    echo -e "${CYAN}>>> Did it work? [y/n/s(kip)] ${NC}"
    read -r -n1 ans
    echo ""
    case "$ans" in
        y|Y) PASS=$((PASS+1)); RESULTS+=("${GREEN}PASS${NC}: $1") ;;
        n|N) FAIL=$((FAIL+1)); RESULTS+=("${RED}FAIL${NC}: $1") ;;
        *)   SKIP=$((SKIP+1)); RESULTS+=("${YELLOW}SKIP${NC}: $1") ;;
    esac
}

header() {
    echo ""
    echo -e "${BOLD}${YELLOW}════════════════════════════════════════${NC}"
    echo -e "${BOLD}${YELLOW}  $1${NC}"
    echo -e "${BOLD}${YELLOW}════════════════════════════════════════${NC}"
    echo ""
}

section() {
    echo ""
    echo -e "${BOLD}${CYAN}── $1 ──${NC}"
    echo ""
}

# ═══════════════════════════════════════════
header "ASIDE MANUAL TEST SUITE"
echo "This script walks through every aside feature."
echo "After each test, mark it pass/fail/skip."
echo ""
echo -e "${YELLOW}Prerequisites:${NC}"
echo "  - aside daemon running"
echo "  - aside-overlay running (in Wayland session)"
echo "  - ANTHROPIC_API_KEY set"
echo ""

# Check prereqs
section "Checking prerequisites"

if pgrep -f "aside.daemon" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Daemon is running"
else
    echo -e "${RED}✗${NC} Daemon NOT running. Start with: nohup python3 -m aside.daemon &"
    echo "  Aborting."
    exit 1
fi

if pgrep -f "aside-overlay" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Overlay is running"
else
    echo -e "${YELLOW}!${NC} Overlay not detected (may be running under different name)"
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo -e "${GREEN}✓${NC} ANTHROPIC_API_KEY is set"
else
    echo -e "${RED}✗${NC} ANTHROPIC_API_KEY not set. Source ~/.bashrc first."
    exit 1
fi

echo ""
echo -e "${CYAN}Ready? Press any key to start...${NC}"
read -r -n1
echo ""

# ═══════════════════════════════════════════
header "1. BASIC QUERY"
# ═══════════════════════════════════════════

section "1a. Simple query"
echo "Sending: aside query \"What is 2+2? One word answer.\""
echo -e "${YELLOW}Expected: Overlay appears at top of screen, streams short answer, fades out${NC}"
aside query "What is 2+2? One word answer."
sleep 8
pause "1a. Simple query — overlay appeared, streamed text, faded out"

section "1b. Longer query"
echo "Sending: aside query \"List 5 fun facts about penguins. Keep each fact to one sentence.\""
echo -e "${YELLOW}Expected: Overlay streams multiple lines of text${NC}"
aside query "List 5 fun facts about penguins. Keep each fact to one sentence."
sleep 15
pause "1b. Longer query — overlay showed multi-line streamed response"

section "1c. Conversation continuity (auto)"
echo "Sending a follow-up within 60s..."
echo "Sending: aside query \"Now tell me about their diet.\""
echo -e "${YELLOW}Expected: Response references penguins (knows context)${NC}"
aside query "Now tell me about their diet."
sleep 12
pause "1c. Conversation continuity — response referenced penguins"

section "1d. Force new conversation"
echo "Sending: aside query \"What color is the sky?\" --new"
echo -e "${YELLOW}Expected: Response about sky (no penguin context)${NC}"
aside query "What color is the sky?" --new
sleep 8
pause "1d. Force new conversation — no penguin context"

# ═══════════════════════════════════════════
header "2. OVERLAY INTERACTIONS"
# ═══════════════════════════════════════════

section "2a. Scroll during streaming"
echo "Sending a long query. TRY SCROLLING with mouse wheel while it streams."
aside query "Write a short poem about the ocean, 8 lines."
echo -e "${YELLOW}Expected: Mouse wheel scrolls text. Auto-scroll pauses when you scroll up.${NC}"
sleep 15
pause "2a. Scroll during streaming — mouse wheel worked"

section "2b. Left-click dismiss"
echo "Sending a query. LEFT-CLICK the overlay to dismiss it."
aside query "Say hello and nothing else."
echo -e "${YELLOW}Expected: Left click instantly dismisses the overlay${NC}"
sleep 5
pause "2b. Left-click dismiss — overlay dismissed on click"

section "2c. Right-click cancel"
echo "Sending a long query. RIGHT-CLICK to cancel mid-stream."
aside query "Count from 1 to 100, one number per line."
echo -e "${YELLOW}Expected: Right click stops streaming and dismisses overlay${NC}"
sleep 3
echo "(Right-click now if you haven't yet)"
sleep 5
pause "2c. Right-click cancel — query was cancelled"

section "2d. Cancel via CLI"
echo "Sending a long query, then cancelling via CLI after 3s..."
aside query "Tell me a very long story about a wizard." &
sleep 3
aside cancel
echo -e "${YELLOW}Expected: Overlay dismissed after cancel command${NC}"
sleep 3
pause "2d. CLI cancel — overlay dismissed after 'aside cancel'"

# ═══════════════════════════════════════════
header "3. OVERLAY SOCKET PROTOCOL (direct)"
# ═══════════════════════════════════════════

OVERLAY_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/aside-overlay.sock"

section "3a. Direct open + text + done"
echo "Sending raw commands to overlay socket..."
echo -e "${YELLOW}Expected: Overlay opens, shows 'Hello from socket!', then fades out${NC}"
echo '{"cmd":"open"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 0.5
echo '{"cmd":"text","data":"Hello from socket!"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 2
echo '{"cmd":"done"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 3
pause "3a. Direct socket — overlay opened, showed text, faded out"

section "3b. Replace command"
echo "Opening overlay, sending text, then replacing it..."
echo -e "${YELLOW}Expected: Shows 'First text', then replaced with 'Replaced!'${NC}"
echo '{"cmd":"open"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 0.5
echo '{"cmd":"text","data":"First text..."}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 2
echo '{"cmd":"replace","data":"Replaced! This is new text."}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 2
echo '{"cmd":"done"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 3
pause "3b. Replace command — text was replaced"

section "3c. Clear (instant dismiss)"
echo "Opening overlay, then clearing immediately..."
echo -e "${YELLOW}Expected: Overlay appears briefly then vanishes (no fade)${NC}"
echo '{"cmd":"open"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 0.5
echo '{"cmd":"text","data":"This will vanish instantly"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 1.5
echo '{"cmd":"clear"}' | socat - UNIX-CONNECT:"$OVERLAY_SOCK" 2>/dev/null || true
sleep 2
pause "3c. Clear command — overlay vanished instantly (no fade)"

# ═══════════════════════════════════════════
header "4. BUILT-IN TOOLS"
# ═══════════════════════════════════════════

section "4a. Shell tool"
echo "Sending: aside query \"What Linux kernel version is running? Use the shell tool to check.\""
echo -e "${YELLOW}Expected: LLM uses shell tool (uname -r or similar), overlay shows kernel version${NC}"
aside query "What Linux kernel version is running? Use the shell tool to check."
sleep 15
pause "4a. Shell tool — LLM ran a command and reported result"

section "4b. Clipboard tool"
echo "Sending: aside query \"Copy the text 'hello clipboard test' to my clipboard using the clipboard tool.\""
echo -e "${YELLOW}Expected: LLM uses clipboard tool. Then paste (Ctrl+V) somewhere to verify.${NC}"
aside query "Copy the text 'hello clipboard test' to my clipboard using the clipboard tool."
sleep 10
echo ""
echo "Try pasting (Ctrl+V) in a terminal to verify clipboard contents."
pause "4b. Clipboard tool — text was copied to clipboard"

section "4c. Memory tool — save"
echo "Sending: aside query \"Remember that my favorite color is purple. Save this to your memory.\""
echo -e "${YELLOW}Expected: LLM uses memory tool to save${NC}"
aside query "Remember that my favorite color is purple. Save this to your memory."
sleep 10
pause "4c. Memory save — confirmed it saved"

section "4d. Memory tool — recall"
echo "Sending (new conversation): aside query \"What's my favorite color? Check your memory.\" --new"
echo -e "${YELLOW}Expected: LLM searches memory and finds 'purple'${NC}"
aside query "What's my favorite color? Check your memory." --new
sleep 10
pause "4d. Memory recall — found 'purple' from memory"

# ═══════════════════════════════════════════
header "5. PLUGINS"
# ═══════════════════════════════════════════

section "5a. Screenshot (full)"
echo "Sending: aside query \"Take a screenshot of my screen.\""
echo -e "${YELLOW}Expected: LLM uses screenshot tool, then describes what it sees${NC}"
aside query "Take a screenshot of my screen."
sleep 15
pause "5a. Screenshot (full) — screenshot taken and described"

section "5b. Web search"
echo "Sending: aside query \"Search the web for 'Arch Linux latest news' and summarize.\""
echo -e "${YELLOW}Expected: LLM uses web_search tool, shows search results summary${NC}"
aside query "Search the web for 'Arch Linux latest news' and summarize."
sleep 20
pause "5b. Web search — search results returned and summarized"

section "5c. Fetch URL"
echo "Sending: aside query \"Fetch https://example.com and tell me what it says.\""
echo -e "${YELLOW}Expected: LLM fetches URL and summarizes content${NC}"
aside query "Fetch https://example.com and tell me what it says."
sleep 15
pause "5c. Fetch URL — page content fetched and described"

# ═══════════════════════════════════════════
header "6. STATUS & MONITORING"
# ═══════════════════════════════════════════

section "6a. Status command"
echo "Running: aside status"
echo -e "${YELLOW}Expected: JSON output with status, model, usage info${NC}"
aside status 2>&1 || echo "(command returned non-zero)"
pause "6a. Status — JSON output shown"

section "6b. Status during query"
echo "Sending a query and checking status while it runs..."
aside query "Explain quantum entanglement in 3 sentences." &
sleep 2
echo "Status while query is running:"
aside status 2>&1 || true
sleep 10
pause "6b. Status during query — showed 'thinking' status"

# ═══════════════════════════════════════════
header "7. CONVERSATION PERSISTENCE"
# ═══════════════════════════════════════════

section "7a. Conversation files"
CONV_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/aside/conversations"
echo "Checking conversation directory: $CONV_DIR"
if [ -d "$CONV_DIR" ]; then
    count=$(ls "$CONV_DIR"/*.json 2>/dev/null | wc -l)
    echo "Found $count conversation file(s)"
    ls -lt "$CONV_DIR"/*.json 2>/dev/null | head -5
else
    echo "Directory does not exist yet"
fi
pause "7a. Conversation files — files exist on disk"

section "7b. Usage log"
USAGE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/aside/usage.jsonl"
echo "Checking usage log: $USAGE_FILE"
if [ -f "$USAGE_FILE" ]; then
    lines=$(wc -l < "$USAGE_FILE")
    echo "Found $lines usage entries"
    echo "Last 3 entries:"
    tail -3 "$USAGE_FILE"
else
    echo "Usage file does not exist yet"
fi
pause "7b. Usage log — entries being recorded"

# ═══════════════════════════════════════════
header "8. OVERLAY CONFIGURATION"
# ═══════════════════════════════════════════

section "8a. Overlay config file"
OVERLAY_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/aside/overlay.conf"
echo "Checking: $OVERLAY_CONF"
if [ -f "$OVERLAY_CONF" ]; then
    echo "Contents:"
    cat "$OVERLAY_CONF"
else
    echo "File not found"
fi
pause "8a. Overlay config — file exists with expected settings"

section "8b. Daemon config"
DAEMON_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/aside/config.toml"
echo "Checking: $DAEMON_CONF"
if [ -f "$DAEMON_CONF" ]; then
    echo "Contents:"
    cat "$DAEMON_CONF"
else
    echo "No config.toml (using defaults)"
fi
pause "8b. Daemon config — config present or defaults OK"

# ═══════════════════════════════════════════
header "9. INPUT WINDOW (if GTK4 available)"
# ═══════════════════════════════════════════

section "9a. aside-input"
if command -v aside-input &>/dev/null; then
    echo "Launching aside-input..."
    echo -e "${YELLOW}Expected: GTK4 popup with conversation list and text entry${NC}"
    echo -e "${YELLOW}  - Select a conversation or 'New conversation'${NC}"
    echo -e "${YELLOW}  - Type a message, press Ctrl+Enter to send${NC}"
    echo -e "${YELLOW}  - Press Escape to close${NC}"
    aside-input &
    sleep 1
    pause "9a. aside-input — popup appeared with conversation list"
else
    echo "aside-input not available (GTK4 deps not installed)"
    SKIP=$((SKIP+1))
    RESULTS+=("${YELLOW}SKIP${NC}: 9a. aside-input — not installed")
fi

# ═══════════════════════════════════════════
header "10. EDGE CASES"
# ═══════════════════════════════════════════

section "10a. Empty query"
echo "Sending empty query..."
aside query "" 2>&1 || echo "(returned error)"
sleep 3
pause "10a. Empty query — handled gracefully"

section "10b. Very long query"
echo "Sending a long query string..."
LONG_Q="Repeat the word 'test' exactly 5 times. "
aside query "$LONG_Q"
sleep 10
pause "10b. Long query — handled OK"

section "10c. Special characters"
echo "Sending query with special chars..."
aside query "What does the symbol & mean in bash? What about | and > and < ?"
sleep 10
pause "10c. Special characters — rendered correctly in overlay"

section "10d. Rapid-fire queries"
echo "Sending 3 queries rapidly (each should cancel the previous)..."
aside query "Say 'first'" &
sleep 0.5
aside query "Say 'second'" &
sleep 0.5
aside query "Say 'third'"
sleep 10
pause "10d. Rapid-fire — last query won, previous cancelled"

section "10e. Unicode/emoji in response"
echo "Sending: aside query \"List 3 animals with their emoji.\""
echo -e "${YELLOW}Expected: Unicode renders correctly in overlay${NC}"
aside query "List 3 animals with their emoji."
sleep 10
pause "10e. Unicode/emoji — rendered correctly"

# ═══════════════════════════════════════════
header "RESULTS SUMMARY"
# ═══════════════════════════════════════════

echo ""
echo -e "${BOLD}Test Results:${NC}"
echo ""
for r in "${RESULTS[@]}"; do
    echo -e "  $r"
done
echo ""
echo -e "${BOLD}────────────────────────${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}"
echo -e "  ${RED}FAIL: $FAIL${NC}"
echo -e "  ${YELLOW}SKIP: $SKIP${NC}"
echo -e "  Total: $((PASS + FAIL + SKIP))"
echo -e "${BOLD}────────────────────────${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Some tests failed. Note the failures and report them!${NC}"
else
    echo -e "${GREEN}All tested features passed!${NC}"
fi
