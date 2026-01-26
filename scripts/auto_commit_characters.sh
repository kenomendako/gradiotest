#!/bin/bash

# Configuration
PROJECT_DIR="/home/baken/nexus_ark"
CHAR_DIR="${PROJECT_DIR}/characters"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$(date)] Starting daily characters auto-commit..."

# Navigate to characters directory
cd "$CHAR_DIR" || { echo "Error: Could not enter ${CHAR_DIR}"; exit 1; }

# Stage all changes
git add .

# Check if there are changes to commit
if git diff --cached --quiet; then
    echo "[${TIMESTAMP}] No changes to commit in characters."
else
    # Commit changes
    git commit -m "Daily Character Backup: ${TIMESTAMP}"
    echo "[${TIMESTAMP}] Successfully committed changes to characters."
fi

echo "[$(date)] Auto-commit process finished."
