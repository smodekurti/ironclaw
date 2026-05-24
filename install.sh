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
echo -e "${YELLOW}[1/4] Checking dependencies...${NC}"
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: Git is not installed. Please install Git and try again.${NC}"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is not installed. Please install Python 3.10+ and try again.${NC}"
    exit 1
fi

# 2. Clone or update repository
echo -e "\n${YELLOW}[2/4] Cloning IronClaw repository...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo "Directory $INSTALL_DIR already exists. Updating..."
    cd "$INSTALL_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. Setup Virtual Environment and Install
echo -e "\n${YELLOW}[3/4] Setting up isolated Python environment...${NC}"
python3 -m venv "$VENV_DIR"

echo "Installing IronClaw core dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

# 4. Create executable symlink
echo -e "\n${YELLOW}[4/4] Creating executable link...${NC}"
mkdir -p "$BIN_DIR"
cat << 'EOF' > "$BIN_DIR/ironclaw"
#!/usr/bin/env bash
# IronClaw executable wrapper
exec "$HOME/.ironclaw/venv/bin/ironclaw" "$@"
EOF
chmod +x "$BIN_DIR/ironclaw"

echo -e "\n${GREEN}=======================================${NC}"
echo -e "${GREEN}      IronClaw installed successfully! ${NC}"
echo -e "${GREEN}=======================================${NC}"
echo -e "\n${YELLOW}Note: The executable 'ironclaw' has been installed to ${BIN_DIR}${NC}"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n${RED}WARNING: $BIN_DIR is not in your PATH!${NC}"
    echo -e "Please add the following line to your shell profile (~/.bashrc, ~/.zshrc, or ~/.profile):"
    echo -e "\n    ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
    echo -e "Then run 'source ~/.zshrc' (or restart your terminal) to apply the changes."
fi

echo -e "\nTo get started, simply run:"
echo -e "  ${BLUE}ironclaw --help${NC}\n"
