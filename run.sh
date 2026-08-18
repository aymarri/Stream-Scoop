#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Stream Scoop launcher — run.sh
#
#  Works on macOS and Linux.
#    Creates a virtualenv on first run, installs deps, then launches.
# ─────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── Colours ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

echo ""
echo -e "${CYAN} ===================================================${RESET}"
echo -e "${CYAN}  Stream Scoop — Starting up...${RESET}"
echo -e "${CYAN} ===================================================${RESET}"
echo ""

# ── Find Python ──────────────────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" --version 2>&1 | awk '{print $2}')
        MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}[ERROR] Python 3.9+ not found!${RESET}"
    echo ""
    echo "  Install Python 3.9+:"
    echo "    macOS:  brew install python"
    echo "    Ubuntu: sudo apt install python3 python3-venv python3-pip"
    echo "    Arch:   sudo pacman -S python"
    echo ""
    exit 1
fi

echo -e "${GREEN}[OK] Python: $PYTHON ($PY_VER)${RESET}"

# ── Create venv if missing ────────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo ""
    echo -e "${YELLOW}[SETUP] Creating virtual environment...${RESET}"
    "$PYTHON" -m venv "$VENV_DIR"
    echo -e "${GREEN}[OK] Virtual environment created.${RESET}"

    echo ""
    echo -e "${YELLOW}[SETUP] Installing dependencies...${RESET}"
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
    echo -e "${GREEN}[OK] Dependencies installed.${RESET}"
else
    echo -e "${GREEN}[OK] Virtual environment found.${RESET}"
fi

# ── FFmpeg check ──────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
    echo -e "${GREEN}[OK] FFmpeg found.${RESET}"
else
    echo -e "${YELLOW}[WARN] FFmpeg not found!${RESET}"
    echo "       Install it:"
    echo "         macOS:  brew install ffmpeg"
    echo "         Ubuntu: sudo apt install ffmpeg"
    echo "         Arch:   sudo pacman -S ffmpeg"
    echo ""
    read -r -p "  Press ENTER to continue anyway..."
fi

# ── aria2c check (optional) ───────────────────────────────────────
if command -v aria2c &>/dev/null; then
    echo -e "${GREEN}[OK] aria2c found (faster downloads enabled).${RESET}"
else
    echo -e "${CYAN}[INFO] aria2c not found (optional — install for faster downloads).${RESET}"
fi

echo ""
echo -e "${CYAN} ===================================================${RESET}"
echo -e "${CYAN}  Launching Stream Scoop...${RESET}"
echo -e "${CYAN} ===================================================${RESET}"
echo ""

# ── Run ───────────────────────────────────────────────────────────
cd "$SCRIPT_DIR"
"$VENV_DIR/bin/python" main.py
