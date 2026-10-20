#!/bin/bash
set -Eeuo pipefail
umask 077
printf 'slot1: 127.0.0.1:5901\nslot2: 127.0.0.1:5902\nslot3: 127.0.0.1:5903\n' > /tmp/browser-pool-tokens
printf '%s:%s\n' "$HERMES_DASHBOARD_BASIC_AUTH_USERNAME" "$HERMES_DASHBOARD_BASIC_AUTH_PASSWORD" > /tmp/browser-pool-auth
python /usr/local/lib/browser-pool.py &
manager=$!
PYTHONPATH=/usr/local/lib websockify --web=/usr/share/novnc --web-auth --auth-plugin browser_pool_auth.FileAuth --auth-source /tmp/browser-pool-auth --token-plugin TokenFile --token-source /tmp/browser-pool-tokens 0.0.0.0:6080 &
viewer=$!
cleanup() {
  trap - EXIT TERM INT
  kill "$viewer" "$manager" 2>/dev/null || true
  wait "$manager" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
wait -n "$manager" "$viewer"
