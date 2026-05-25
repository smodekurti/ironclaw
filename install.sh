#!/usr/bin/env bash
set -e

# IronClaw Framework Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/smodekurti/ironclaw/main/install.sh | bash

REPO_URL="https://github.com/smodekurti/ironclaw.git"
INSTALL_DIR="$HOME/.ironclaw"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$INSTALL_DIR/venv"

# Colors for terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=======================================${NC}"
echo -e "${BLUE}       Installing IronClaw Framework   ${NC}"
echo -e "${BLUE}=======================================${NC}\n"

# 1. Check dependencies
echo -e "${YELLOW}[1/5] Checking dependencies...${NC}"

if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: Git is not installed. Please install Git and try again.${NC}"
    exit 1
fi

# Check for Node.js/npm (needed for dashboard build)
HAS_NODE=false
if command -v npm &> /dev/null; then
    HAS_NODE=true
    NODE_VERSION=$(node --version 2>/dev/null || echo "unknown")
    echo -e "  Node.js $NODE_VERSION ✓"
else
    echo -e "  ${YELLOW}Warning: npm not found — dashboard will not be built.${NC}"
    echo -e "  Install Node.js from https://nodejs.org to enable the web UI."
fi

# Find Python 3.10+ — check versioned binaries first, then fall back to python3.
# macOS ships python3 = 3.9; Homebrew/pyenv installs land as python3.12, python3.11, etc.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &> /dev/null; then
        _major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        _minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$_major" -eq 3 ] && [ "$_minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}Error: Python 3.10+ is required but was not found.${NC}"
    echo -e ""
    echo -e "Install Python 3.12 via Homebrew (recommended on macOS):"
    echo -e "  ${BLUE}brew install python@3.12${NC}"
    echo -e ""
    echo -e "Or download from: ${BLUE}https://www.python.org/downloads/${NC}"
    echo -e ""
    echo -e "After installing, re-run:"
    echo -e "  ${BLUE}curl -fsSL https://raw.githubusercontent.com/smodekurti/ironclaw/main/install.sh | bash${NC}"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo -e "  Python $PY_VERSION ($PYTHON) ✓"

# 2. Clone or update repository
echo -e "\n${YELLOW}[2/5] Cloning IronClaw repository...${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Directory $INSTALL_DIR already exists — updating..."
    cd "$INSTALL_DIR"
    git fetch origin main
    git pull --ff-only origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. Setup Virtual Environment and Install
echo -e "\n${YELLOW}[3/5] Setting up isolated Python environment...${NC}"
echo "  Using $PYTHON to create virtualenv at $VENV_DIR"
"$PYTHON" -m venv "$VENV_DIR"

echo "  Installing IronClaw and dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR[all]" --quiet

# 4. Build dashboard
echo -e "\n${YELLOW}[4/5] Building web dashboard...${NC}"
DASHBOARD_DIR="$INSTALL_DIR/ironclaw/web/dashboard"
if [ "$HAS_NODE" = true ] && [ -d "$DASHBOARD_DIR" ]; then
    echo "  Running npm install..."
    npm install --prefix "$DASHBOARD_DIR" --silent
    echo "  Running npm run build..."
    npm run build --prefix "$DASHBOARD_DIR" --silent
    echo -e "  Dashboard built ✓"
else
    echo -e "  ${YELLOW}Skipped (npm not available)${NC}"
fi

# 5. Create executable wrapper
echo -e "\n${YELLOW}[5/5] Creating executable link...${NC}"
mkdir -p "$BIN_DIR"
cat << 'EOF' > "$BIN_DIR/ironclaw"
#!/usr/bin/env bash
# IronClaw executable wrapper
exec "$HOME/.ironclaw/venv/bin/ironclaw" "$@"
EOF
chmod +x "$BIN_DIR/ironclaw"
echo "  Installed to $BIN_DIR/ironclaw"

echo -e "\n${GREEN}=======================================${NC}"
echo -e "${GREEN}      IronClaw installed successfully! ${NC}"
echo -e "${GREEN}=======================================${NC}"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n${YELLOW}⚠  $BIN_DIR is not in your PATH.${NC}"
    echo -e "Add this line to your shell profile (~/.zshrc or ~/.bashrc):"
    echo -e "\n    ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
    echo -e "Then reload it:"
    echo -e "    ${BLUE}source ~/.zshrc${NC}"
fi

echo -e "\nTo get started:"
echo -e "  ${BLUE}ironclaw --help${NC}\n"
