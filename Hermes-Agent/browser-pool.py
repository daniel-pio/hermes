"""Three visible Chromium leases; one process group and profile per task."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid
import heapq
import statistics
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import psutil

condition = threading.Condition()
slots = {}
queue = {}
durations = deque(maxlen=30)
stopping = False
ROOT = Path('/browser-data/pool')
ROOT.mkdir(parents=True, exist_ok=True)
IDLE = int(os.environ.get('BROWSER_POOL_IDLE_SECONDS', '300'))
MAX_AGE = int(os.environ.get('BROWSER_POOL_MAX_SECONDS', '1800'))
QUEUE_WAIT = int(os.environ.get('BROWSER_POOL_QUEUE_SECONDS', '600'))


def reap_previous_manager():
    # s6 may restart this manager after SIGKILL; task-owned process groups
    # must not survive that restart. Only our random pool profile dirs qualify.
    for profile in ROOT.iterdir():
        if not profile.is_dir() or len(profile.name) != 32:
            continue
        try:
            int(profile.name, 16)
        except ValueError:
            continue
        for proc in psutil.process_iter(['cmdline']):
            if any(str(profile) in arg for arg in (proc.info['cmdline'] or [])):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        shutil.rmtree(profile, ignore_errors=True)
    for slot in range(1, 4):
        Path(f'/tmp/.X{100 + slot}-lock').unlink(missing_ok=True)
        Path(f'/tmp/.X11-unix/X{100 + slot}').unlink(missing_ok=True)


def stop(entry):
    # Slot is not released until its entire process group has been terminated.
    pgid = entry['proc'].pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            time.sleep(0.5)
    entry['proc'].wait(timeout=5)
    # Chromium crash handlers may detach from the original process group.
    # Their random, per-task profile path is an unambiguous ownership marker.
    detached = []
    for proc in psutil.process_iter(['cmdline']):
        if any(str(entry['profile']) in arg for arg in (proc.info['cmdline'] or [])):
            try:
                proc.kill()
                detached.append(proc)
            except psutil.Error:
                pass
    psutil.wait_procs(detached, timeout=3)
    entry['log'].close()
    shutil.rmtree(entry['profile'], ignore_errors=True)
    for path in (Path(f"/tmp/.X{100 + entry['slot']}-lock"),
                 Path(f"/tmp/.X11-unix/X{100 + entry['slot']}")):
        path.unlink(missing_ok=True)


def remove(slot, completed=False):
    entry = slots[slot]
    if completed:
        durations.append(time.monotonic() - entry['born'])
    stop(entry)
    del slots[slot]
    condition.notify_all()


def queue_status(key):
    position = list(queue).index(key) + 1
    eta = None
    if len(durations) >= 3:
        typical = statistics.median(durations)
        now = time.monotonic()
        availability = [max(1, typical - (now - e['born'])) for e in slots.values()]
        availability += [0] * (3 - len(slots))
        heapq.heapify(availability)
        for _ in range(position):
            eta = heapq.heappop(availability)
            heapq.heappush(availability, eta + typical)
        eta = round(eta)
    return dict(queued=True, position=position, estimated_seconds=eta,
                queue_timeout_seconds=QUEUE_WAIT)


def acquire(data):
    task, pid, started = str(data['task']), int(data['pid']), float(data['started'])
    if psutil.Process(pid).create_time() != started:
        raise RuntimeError('Task owner is no longer alive')
    key = (task, pid, started)
    with condition:
        if stopping:
            raise RuntimeError('Browser pool is stopping')
        for entry in slots.values():
            if (entry['task'], entry['pid'], entry['started']) == key:
                entry['touch'] = time.monotonic()
                return public(entry)
        free = next((s for s in range(1, 4) if s not in slots), None)
        if key not in queue:
            queue[key] = time.monotonic()
        if time.monotonic() - queue[key] > QUEUE_WAIT:
            del queue[key]
            raise RuntimeError('Tempo limite de espera na fila atingido. Tente novamente.')
        if free is None or next(iter(queue)) != key:
            return queue_status(key)
        del queue[key]
        lease = uuid.uuid4().hex
        profile = ROOT / lease
        profile.mkdir(mode=0o700)
        log = open(profile / 'session.log', 'wb')
        env = dict(os.environ, BROWSER_SLOT=str(free), BROWSER_PROFILE=str(profile))
        proc = subprocess.Popen(['/usr/local/bin/browser-session.sh'], env=env,
                                stdout=log, stderr=log, start_new_session=True)
        now = time.monotonic()
        entry = dict(slot=free, task=task, pid=pid, started=started, lease=lease,
                     proc=proc, profile=profile, log=log, born=now, touch=now)
        slots[free] = entry
        try:
            for _ in range(120):
                if proc.poll() is not None:
                    raise RuntimeError('Chromium failed to start')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{9221 + free}/json/version', timeout=0.5) as response:
                        if response.status == 200:
                            return public(entry)
                except OSError:
                    time.sleep(0.25)
            raise RuntimeError('Chromium startup timeout')
        except BaseException:
            remove(free)
            raise


def public(entry):
    return dict(slot=entry['slot'], lease=entry['lease'],
                cdp_url=f"http://127.0.0.1:{9221 + entry['slot']}")


def janitor():
    while not stopping:
        time.sleep(2)
        with condition:
            for key, born in list(queue.items()):
                try:
                    alive = psutil.Process(key[1]).create_time() == key[2]
                except psutil.Error:
                    alive = False
                if not alive or time.monotonic() - born > QUEUE_WAIT:
                    del queue[key]
            for slot, entry in list(slots.items()):
                try:
                    alive = psutil.Process(entry['pid']).create_time() == entry['started']
                except psutil.Error:
                    alive = False
                now = time.monotonic()
                if (not alive or entry['proc'].poll() is not None or
                        now - entry['touch'] > IDLE or now - entry['born'] > MAX_AGE):
                    remove(slot)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with condition:
            self.respond(dict(capacity=3, active=[public(e) for e in slots.values()]))

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if self.path == '/acquire':
                result = acquire(data)
            elif self.path == '/cancel':
                with condition:
                    queue.pop((str(data['task']), int(data['pid']), float(data['started'])), None)
                result = {'ok': True}
            elif self.path in ('/touch', '/release'):
                with condition:
                    slot = next((s for s, e in slots.items() if e['lease'] == data['lease']), None)
                    if slot is not None:
                        if self.path == '/release':
                            remove(slot, completed=True)
                        else:
                            slots[slot]['touch'] = time.monotonic()
                    elif self.path == '/touch':
                        raise RuntimeError('Browser session expired; start a new task')
                result = {'ok': True}
            else:
                raise ValueError('Unknown action')
            self.respond(result)
        except Exception as exc:
            self.respond({'error': str(exc)})


def shutdown(*_):
    global stopping
    stopping = True
    with condition:
        condition.notify_all()
        for slot in list(slots):
            remove(slot)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
reap_previous_manager()
threading.Thread(target=janitor, daemon=True).start()
ThreadingHTTPServer(('127.0.0.1', 6079), Handler).serve_forever()
