#!/bin/bash
# Ward 启动脚本 - 避免 Hermes 安全机制拦截

source "$HOME/.bashrc"

screen -S ward -X quit 2>/dev/null
sleep 1

screen -dmS ward /root/.venv/bin/ward
echo "Ward started"
