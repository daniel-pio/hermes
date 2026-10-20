FROM nousresearch/hermes-agent:v2026.9.11@sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1

USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       chromium \
       curl \
       dbus-x11 \
       fonts-dejavu-core \
       fonts-liberation \
       novnc \
       openbox \
       procps \
       websockify \
       x11-utils \
       x11vnc \
       xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && if ! id browser >/dev/null 2>&1; then useradd --create-home --uid 10001 --shell /bin/bash browser; fi \
    && mkdir -p /browser-data \
    && chown -R browser:browser /browser-data \
    && printf '%s\n' \
       '<!doctype html>' \
       '<html><head><meta charset="utf-8"><title>Hermes Browser</title>' \
       '<meta http-equiv="refresh" content="0; url=/vnc.html?autoconnect=true&amp;resize=scale&amp;view_only=true">' \
       '</head><body>Connecting to Hermes Chromium...</body></html>' \
       > /usr/share/novnc/index.html

COPY --chmod=0755 browser-stack.sh /usr/local/bin/browser-stack.sh
COPY --chmod=0755 browser-s6-run /etc/s6-overlay/s6-rc.d/browser-visible/run
COPY configure-browser.py verify-health.py /usr/local/lib/
COPY --chmod=0755 configure-browser-init /etc/cont-init.d/90-visible-browser

# Windows checkouts may use CRLF; Linux entrypoints require LF.
RUN sed -i 's/\r$//' /usr/local/bin/browser-stack.sh \
    /etc/s6-overlay/s6-rc.d/browser-visible/run \
    /etc/cont-init.d/90-visible-browser

RUN printf 'longrun\n' > /etc/s6-overlay/s6-rc.d/browser-visible/type \
    && mkdir -p /etc/s6-overlay/s6-rc.d/browser-visible/dependencies.d \
                /etc/s6-overlay/s6-rc.d/user/contents.d \
    && touch /etc/s6-overlay/s6-rc.d/browser-visible/dependencies.d/base \
             /etc/s6-overlay/s6-rc.d/user/contents.d/browser-visible

# IMPORTANT: intentionally do NOT replace ENTRYPOINT/CMD.
# The upstream image keeps /init (s6-overlay) as PID 1, which supervises
# Hermes gateway/dashboard and our browser-visible service together.

COPY browser-pool.py /usr/local/lib/browser-pool.py
COPY browser-pool-client.py /opt/hermes/tools/browser_pool_client.py
COPY patch-browser-pool.py /usr/local/lib/patch-browser-pool.py
COPY --chmod=0755 browser-session.sh /usr/local/bin/browser-session.sh
COPY browser-pool.html /usr/share/novnc/index.html
COPY browser-pool-auth.py /usr/local/lib/browser_pool_auth.py
COPY hermes-exports.py /opt/hermes/gateway/hermes_exports.py
RUN sed -i 's/\r$//' /usr/local/bin/browser-session.sh && python /usr/local/lib/patch-browser-pool.py

COPY hermes-specialists.json /opt/hermes/hermes-specialists.json
COPY hermes-workspace.py /opt/hermes/tools/hermes_workspace.py
RUN uv pip install --python /opt/hermes/.venv/bin/python pypdf==6.1.1 python-docx==1.2.0 openpyxl==3.1.5
COPY patch-specialists.py /usr/local/lib/patch-specialists.py
RUN python /usr/local/lib/patch-specialists.py
