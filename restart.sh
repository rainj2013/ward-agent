#!/bin/bash
source "$HOME/.bashrc"

screen -S ward -X quit 2>/dev/null
sleep 1
screen -dmS ward /root/.venv/bin/ward
echo "Ward restarted"
