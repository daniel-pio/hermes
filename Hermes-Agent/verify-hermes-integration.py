"""Check the real signed API from inside Open WebUI. No model call or printed key."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlsplit
import aiohttp


async def verify(base_url, key):
    base = base_url.rstrip('/')
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.endswith('/v1'):
        raise RuntimeError('Endereco da API invalido: use http://HOST:8643/v1, sem credenciais na URL.')
    session_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    scope = {'user': 'installer-check', 'profile': 'admin', 'session': session_id,
             'run': run_id, 'issued': time.time()}
    encoded = base64.urlsafe_b64encode(json.dumps(scope, separators=(',', ':')).encode()).decode().rstrip('=')
    signed = encoded + '.' + hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    headers = {'Authorization': 'Bearer ' + key, 'X-Hermes-Session-Id': session_id, 'X-Hermes-Scope': signed}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
            async with client.get(base + '/integration/health', headers=headers, allow_redirects=False) as response:
                if response.status in (401, 403):
                    raise RuntimeError('Integracao recusada (HTTP ' + str(response.status) + '): a API_SERVER_KEY do .env nao corresponde ao Hermes em execucao ou o escopo foi recusado. Reexecute o instalador completo com o .env original.')
                if response.status in (404, 405):
                    raise RuntimeError('API Hermes desatualizada ou endereco incorreto (HTTP ' + str(response.status) + '). Reexecute INSTALAR.cmd ou bash INSTALAR-LINUX.sh na pasta original para reconstruir Hermes antes de integrar o WebUI.')
                if response.status != 200:
                    raise RuntimeError('A verificacao da integracao retornou HTTP ' + str(response.status) + '. Confira os servicos.')
                result = await response.json()
                if result.get('service') != 'hermes-openwebui' or result.get('protocol') != 1 or not all(result.get(k) is True for k in ('scoped_chat', 'file_upload', 'file_download')):
                    raise RuntimeError('A API respondeu, mas nao suporta a integracao completa de texto e arquivos. Atualize o Hermes.')
                if not isinstance(result.get('model_alias'), str) or not result['model_alias']:
                    raise RuntimeError('A API Hermes nao informou o identificador da conversa. Atualize o Hermes.')
            exports_url = base + '/exports/' + session_id + '/' + run_id
            async with client.get(exports_url, headers=headers, allow_redirects=False) as response:
                if response.status != 200 or not isinstance((await response.json()).get('files'), list):
                    raise RuntimeError('A API de arquivos nao esta pronta. Confira o container Hermes e sua pasta de dados.')
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise RuntimeError('Nao foi possivel acessar Hermes a partir do Open WebUI. Confira Docker, host.docker.internal, a porta 8643 e o firewall.') from exc
    print('PASS: Open WebUI acessa a API correta; chave local, escopo assinado, conversa e entrega de arquivos compativeis.')
    return result


if __name__ == '__main__':
    import sys
    options = json.load(sys.stdin)
    asyncio.run(verify(options['base_url'], options['api_key']))
