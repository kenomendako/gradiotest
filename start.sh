#!/bin/bash

# Configuration
VENV_DIR="venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
REQUIREMENTS="requirements.txt"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}---------------------------------------------------${NC}"
echo -e "${GREEN} Nexus Ark Launching (WSL/Linux)${NC}"
echo -e "${GREEN}---------------------------------------------------${NC}"

# Ensure we are in the script's directory
cd "$(dirname "$0")" || exit 1


# Check for virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}[INFO] Virtual environment not found. Creating one...${NC}"
    
    # Try to create venv
    if python3 -m venv "$VENV_DIR"; then
        echo -e "${GREEN}[SUCCESS] Virtual environment created in ./$VENV_DIR${NC}"
    else
        echo -e "${RED}[ERROR] Failed to create virtual environment.${NC}"
        echo -e "Please ensure python3-venv is installed: ${YELLOW}sudo apt install python3-venv${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}[INFO] Virtual environment found.${NC}"
fi

# Install dependencies (Always check)
echo -e "${YELLOW}[INFO] Installing/Verifying dependencies from $REQUIREMENTS...${NC}"
if "$PIP_BIN" install -r "$REQUIREMENTS"; then
     echo -e "${GREEN}[SUCCESS] Dependencies check passed.${NC}"
else
     echo -e "${RED}[ERROR] Failed to install dependencies.${NC}"
     exit 1
fi

# Launch Application
echo -e "${GREEN}[INFO] Starting Nexus Ark...${NC}"
echo -e "${YELLOW}Access URL: http://0.0.0.0:7860 (Local)${NC}"
echo -e "${YELLOW}Remote Access: http://<Tailscale-IP>:7860${NC}"
echo -e "${GREEN}---------------------------------------------------${NC}"

"$PYTHON_BIN" nexus_ark.py

# Check exit code
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Nexus Ark exited with error.${NC}"
fi

echo -e "${GREEN}---------------------------------------------------${NC}"
echo -e "Application Closed."
