#!/bin/bash
# ─────────────────────────────────────────
#  VIDCOMP — Start Script
# ─────────────────────────────────────────

echo ""
echo "  ██╗   ██╗██╗██████╗  ██████╗ ██████╗ ███╗   ███╗██████╗ "
echo "  ██║   ██║██║██╔══██╗██╔════╝██╔═══██╗████╗ ████║██╔══██╗"
echo "  ██║   ██║██║██║  ██║██║     ██║   ██║██╔████╔██║██████╔╝"
echo "  ╚██╗ ██╔╝██║██║  ██║██║     ██║   ██║██║╚██╔╝██║██╔═══╝ "
echo "   ╚████╔╝ ██║██████╔╝╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     "
echo "    ╚═══╝  ╚═╝╚═════╝  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     "
echo ""
echo "  Custom Video Compression Codec v2.4.1"
echo "  ────────────────────────────────────────"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "  [ERROR] Python 3 not found."
  exit 1
fi

# Install deps if needed
if ! python3 -c "import flask" &>/dev/null; then
  echo "  Installing dependencies..."
  pip install -r requirements.txt --quiet
fi

echo "  Starting backend server..."
echo "  Open: http://localhost:5000"
echo "  Press Ctrl+C to stop."
echo ""

cd backend && python3 app.py
