"""Wait for Open WebUI without depending on host Python or shell quoting."""
import sys
import time
import urllib.request

deadline = time.monotonic() + (int(sys.argv[1]) if len(sys.argv) > 1 else 180)
while time.monotonic() < deadline:
    try:
        urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)
        print('Open WebUI pronto.')
        break
    except Exception:
        time.sleep(3)
else:
    raise SystemExit('Open WebUI nao ficou pronto no prazo. Confira os logs do container.')
