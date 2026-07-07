#!/bin/bash
# Ward 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

screen -S ward -X quit 2>/dev/null
sleep 1

cd "$SCRIPT_DIR"
screen -dmS ward "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/run.py"
echo "Ward started"
