#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

screen -S ward -X quit 2>/dev/null
sleep 1
cd "$SCRIPT_DIR"
screen -dmS ward "$SCRIPT_DIR/.venv/bin/ward"
echo "Ward restarted"
