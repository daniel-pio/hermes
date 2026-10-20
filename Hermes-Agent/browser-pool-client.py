"""Internal adapter for Hermes' per-task browser lifecycle."""
import json
import os
import threading
import time
import logging
import urllib.request

_leases = {}
_lock = threading.RLock()
_agents = {}


def register(task_id, agent):
    with _lock:
        _agents[str(task_id)] = agent


def notify(task_id, text, event='tool.started'):
    with _lock:
        agent = _agents.get(str(task_id).removesuffix('::local'))
    callback = getattr(agent, 'tool_progress_callback', None)
    if callback:
        try:
            callback(event, 'browser_queue', text, {'status': text})
        except Exception:
            logging.getLogger(__name__).debug('Browser queue progress unavailable', exc_info=True)


def unregister(task_id):
    with _lock:
        _agents.pop(str(task_id), None)


def call(action, data):
    request = urllib.request.Request(
        'http://127.0.0.1:6079/' + action,
        data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=135) as response:
        result = json.load(response)
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result


def acquire(task_id):
    import psutil
    data = dict(task=str(task_id), pid=os.getpid(), started=psutil.Process().create_time())
    began = time.monotonic()
    previous = None
    was_queued = False
    while True:
        with _lock:
            agent = _agents.get(str(task_id).removesuffix('::local'))
        if getattr(agent, '_interrupt_requested', False):
            call('cancel', data)
            raise RuntimeError('Pesquisa cancelada enquanto aguardava na fila.')
        result = call('acquire', data)
        if not result.get('queued'):
            break
        was_queued = True
        position = result['position']
        eta = result['estimated_seconds']
        estimate = ('previsao ainda indisponivel (sem historico suficiente)' if eta is None
                    else f'previsao aproximada: {max(1, round(eta / 60))} min')
        # Refresh on position changes and every 30 seconds while waiting.
        state = (position, int((time.monotonic() - began) / 30))
        if state != previous:
            notify(task_id, f'Pesquisa na fila: posicao {position}; {estimate}. Tres vagas de Chromium.')
            previous = state
        if time.monotonic() - began >= result['queue_timeout_seconds']:
            call('cancel', data)
            raise RuntimeError('Tempo limite de espera na fila atingido. Tente novamente.')
        time.sleep(2)
    if was_queued:
        notify(task_id, f'Pesquisa saiu da fila. Chromium {result["slot"]} reservado.', 'tool.completed')
    notify(task_id, f'Pesquisa em execucao no Chromium {result["slot"]}, disponivel na porta 6080.')
    with _lock:
        _leases[str(task_id)] = result['lease']
    return dict(session_name='cdp_' + result['lease'][:10], bb_session_id=None,
                cdp_url=result['cdp_url'], features={'cdp_override': True},
                pool_lease=result['lease'])


def touch(info):
    if info.get('pool_lease'):
        call('touch', {'lease': info['pool_lease']})


def release(info):
    if info.get('pool_lease'):
        call('release', {'lease': info['pool_lease']})


def release_task(task_id):
    import psutil
    for key in (str(task_id), str(task_id) + '::local'):
        with _lock:
            lease = _leases.pop(key, None)
        if lease:
            call('release', {'lease': lease})
        call('cancel', dict(task=key, pid=os.getpid(), started=psutil.Process().create_time()))
