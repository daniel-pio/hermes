#!/bin/bash
set -Eeuo pipefail
export HOME=/home/browser
export DISPLAY=:$((100 + BROWSER_SLOT))
profile="$BROWSER_PROFILE"
Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH:-1600}x${SCREEN_HEIGHT:-900}x24" -ac -nolisten tcp &
for _ in $(seq 1 80); do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then break; fi
  sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null 2>&1
openbox-session &
x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport "$((5900 + BROWSER_SLOT))" -listen 127.0.0.1 -noxdamage -quiet &
chromium --display="$DISPLAY" --no-sandbox --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$((9221 + BROWSER_SLOT))" --remote-allow-origins='*' \
  --user-data-dir="$profile" --no-first-run --no-default-browser-check \
  --disable-gpu --disable-background-networking --disable-component-update \
  --password-store=basic --disable-session-crashed-bubble --disable-dev-shm-usage \
  --window-size="${SCREEN_WIDTH:-1600},${SCREEN_HEIGHT:-900}" about:blank &
wait $!
