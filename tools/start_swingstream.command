#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Navigiere ins Repository-Root, damit .venv_vr und tools/swingstream_dashboard.py gefunden werden.
cd "$REPO_ROOT"

echo "============================================="
echo "  SwingStream Live Dashboard wird gestartet  "
echo "============================================="

# Bevorzuge .venv_vr (enthält numpy/scikit-learn/joblib für optionale Live-Schlagerkennung).
if [ -d ".venv_vr" ] && [ -f ".venv_vr/bin/python3" ]; then
    PYTHON_BIN=".venv_vr/bin/python3"
elif [ -d ".venv" ] && [ -f ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
elif [ -d ".venv311" ] && [ -f ".venv311/bin/python3" ]; then
    PYTHON_BIN=".venv311/bin/python3"
else
    PYTHON_BIN="python3"
fi

echo "Verwende Python: $PYTHON_BIN"

# Lokale IP fürs iPhone anzeigen (das iPhone postet an http://<diese-ip>:8788/api/ingest).
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
if [ -n "$LAN_IP" ]; then
    echo "iPhone-Bridge Ziel: http://$LAN_IP:8788/api/ingest"
fi

# Öffne Safari nach kurzer Verzögerung, damit der Server Zeit zum Starten hat.
if [ "${SWINGSTREAM_OPEN_BROWSER:-1}" != "0" ]; then
    (sleep 1.5 && open -a Safari "http://127.0.0.1:8788") &
fi

# Starte das Dashboard (0.0.0.0 = im LAN erreichbar fürs iPhone).
"$PYTHON_BIN" tools/swingstream_dashboard.py --host 0.0.0.0 --port 8788
