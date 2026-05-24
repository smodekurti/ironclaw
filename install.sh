#!/usr/bin/env bash
# IronClaw one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/your-org/ironclaw/main/install.sh | bash
# or locally: bash install.sh

set -euo pipefail

IRONCLAW_DIR="${IRONCLAW_DIR:-$HOME/.ironclaw}"
VENV_DIR="$IRONCLAW_DIR/venv"
REPO_URL="${IRONCLAW_REPO:-https://github.com/your-org/ironclaw}"

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
info() { echo -e "${CYAN}•${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗  Error: $*${RESET}" >&2; exit 1; }
header() { echo; echo -e "${BOLD}$*${RESET}"; echo "────────────────────────────────"; }

# ── Check requirements ───────────────────────────────────────────────────────
header "IronClaw Installer"

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.9+ first."

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    die "Python 3.9+ required (found $PY_VERSION)"
fi
ok "Python $PY_VERSION"

command -v pip3 >/dev/null 2>&1 || die "pip3 not found."
ok "pip3 found"

# ── Create install directory ──────────────────────────────────────────────────
mkdir -p "$IRONCLAW_DIR"
info "Install directory: $IRONCLAW_DIR"

# ── Create virtual environment ────────────────────────────────────────────────
header "Setting up virtual environment"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
else
    ok "Virtual environment already exists"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

"$PIP" install --upgrade pip --quiet

# ── Install IronClaw ──────────────────────────────────────────────────────────
header "Installing IronClaw"

# If a local ironclaw directory exists (dev install), use it
if [ -d "$(pwd)/ironclaw" ] && [ -f "$(pwd)/ironclaw/pyproject.toml" ]; then
    info "Found local ironclaw package — installing in editable mode"
    "$PIP" install -e "$(pwd)/ironclaw[all]" --quiet
else
    info "Installing from PyPI: ironclaw[all]"
    "$PIP" install "ironclaw[all]" --quiet
fi

ok "IronClaw installed"

# ── Shell integration ─────────────────────────────────────────────────────────
header "Shell integration"

IRONCLAW_BIN="$VENV_DIR/bin/ironclaw"
SHELL_RC=""
case "$SHELL" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    *)      SHELL_RC="$HOME/.profile" ;;
esac

ALIAS_LINE="alias ironclaw='$IRONCLAW_BIN'"
if ! grep -qF "$ALIAS_LINE" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# IronClaw" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    ok "Added ironclaw alias to $SHELL_RC"
else
    ok "ironclaw alias already in $SHELL_RC"
fi

# Also symlink to /usr/local/bin if writable (optional, best-effort)
if [ -w /usr/local/bin ] && [ ! -f /usr/local/bin/ironclaw ]; then
    ln -sf "$IRONCLAW_BIN" /usr/local/bin/ironclaw 2>/dev/null && ok "Symlinked to /usr/local/bin/ironclaw"
fi

# ── Run setup wizard ──────────────────────────────────────────────────────────
header "Setup"
echo ""
echo -e "${BOLD}IronClaw is installed!${RESET}"
echo ""
echo "Next steps:"
echo "  1. Reload your shell:  source $SHELL_RC"
echo "  2. Run the wizard:     ironclaw setup"
echo "  3. Start the server:   ironclaw serve"
echo "  4. Open the UI:        http://localhost:7432"
echo ""
echo -e "Run the wizard now? (y/N) \c"
read -r RUN_SETUP </dev/tty || RUN_SETUP="n"

if [[ "$RUN_SETUP" =~ ^[Yy]$ ]]; then
    "$IRONCLAW_BIN" setup
fi
