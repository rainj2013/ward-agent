#!/bin/bash
screen -S ward -X quit 2>/dev/null
sleep 1
screen -dmS ward bash -c 'WARD_PUBLIC_MODE=1 /root/.venv/bin/ward'
echo "Ward restarted"
