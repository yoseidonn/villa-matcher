#!/bin/bash
# Villa Matcher — server setup script
# Run this on the server: bash setup_server.sh

set -e

APP_DIR="/opt/villa-matcher"
SNAPSHOTS_SRC="/root/Resital Villa Scripts/inputs/all_reservations"
REPO_SRC="/root/Resital Villa Scripts"

echo "=== Villa Matcher Setup ==="

# 1. Install dependencies
pip install --break-system-packages pandas openpyxl typer rich readchar fastapi uvicorn 2>/dev/null || \
  pip install pandas openpyxl typer rich readchar fastapi uvicorn

# 2. Copy project
mkdir -p "$APP_DIR"
cp -r /tmp/villa-matcher/* "$APP_DIR/" 2>/dev/null && echo "Project copied" || echo "Project already in place"

# 3. Link snapshots
if [ -d "$SNAPSHOTS_SRC" ]; then
    ln -sf "$SNAPSHOTS_SRC" "$APP_DIR/data/all_reservations"
    echo "Snapshots linked"
fi

# 4. Link report inputs
if [ -d "$REPO_SRC" ]; then
    ln -sf "$REPO_SRC/inputs/caretakers.json" "$APP_DIR/data/" 2>/dev/null
    ln -sf "$REPO_SRC/inputs/korsan_villas.json" "$APP_DIR/data/" 2>/dev/null
    ln -sf "$REPO_SRC/Korsan-Villas-Template.xlsx" "$APP_DIR/data/" 2>/dev/null
    echo "Report inputs linked"
fi

# 5. Install the package
cd "$APP_DIR"
pip install --break-system-packages -e . 2>/dev/null || pip install -e .

echo "=== Setup complete ==="
echo "Run: cd $APP_DIR && villa-matcher serve --port 8080"
