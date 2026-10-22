#!/bin/sh
# start.sh [PORT] — run mini-tools on TCP (default 8082)
cd "$(dirname "$0")"
PORT="${1:-${PORT:-8082}}" exec python3 server.py
