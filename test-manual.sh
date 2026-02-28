#!/usr/bin/env bash
# aside manual test — run inside the VM
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

echo -e "${BOLD}Preflight...${NC}"
pgrep -f "aside.daemon" >/dev/null 2>&1 && echo -e "${GREEN}✓${NC} daemon" || { echo -e "${RED}✗${NC} daemon not running"; exit 1; }
pgrep -f "aside-overlay" >/dev/null 2>&1 && echo -e "${GREEN}✓${NC} overlay" || echo -e "${YELLOW}!${NC} overlay not detected"
[ -n "${ANTHROPIC_API_KEY:-}" ] && echo -e "${GREEN}✓${NC} API key" || { echo -e "${RED}✗${NC} no ANTHROPIC_API_KEY"; exit 1; }

echo ""
echo -e "${BOLD}${YELLOW}═══ Query + buttons + CLI ═══${NC}"
echo ""
echo "Sending a query. Watch for:"
echo "  1. Overlay streams text"
echo "  2. After done, 3 buttons appear: [mic] [open] [reply]"
echo "  3. Click 'reply' to open the text input box"
echo "  4. Type a follow-up and press Enter"
echo ""
echo -e "${CYAN}Press any key to start...${NC}"; read -r -n1; echo ""

aside query "What's 2+2? Answer in one sentence."
echo ""
echo "Waiting for response + linger..."
sleep 8

echo ""
echo -e "${BOLD}Now check the CLI:${NC}"
echo ""
aside ls
echo ""
echo -e "${CYAN}Done! Try 'aside show <id>' or 'aside reply <id> \"your text\"' to continue.${NC}"
