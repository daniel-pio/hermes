"""Check all three services without exposing dashboard credentials."""
import base64
import os
import urllib.request

for url in ("http://127.0.0.1:6079/health",):
    with urllib.request.urlopen(url, timeout=3) as response:
        assert response.status == 200
credentials = os.environ["HERMES_DASHBOARD_BASIC_AUTH_USERNAME"] + ":" + os.environ["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"]
request = urllib.request.Request("http://127.0.0.1:9119/api/status")
request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
with urllib.request.urlopen(request, timeout=3) as response:
    assert response.status == 200

request = urllib.request.Request('http://127.0.0.1:6080/vnc.html')
request.add_header('Authorization', 'Basic ' + base64.b64encode(credentials.encode()).decode())
with urllib.request.urlopen(request, timeout=3) as response:
    assert response.status == 200
