"""
title: Hermes Agent - Chromium e fila
description: Sessao por usuario/chat e feedback de pesquisas no Hermes local.
version: 2.2.0
"""
import json
import uuid
import io
import base64
import hashlib
import hmac
import time
import copy
from pathlib import Path
from urllib.parse import quote
from typing import AsyncGenerator
import aiohttp
from pydantic import BaseModel, Field

# Replaced by the installer with the secret-free specialist catalogue.
PROFILES = {}  # HERMES_PROFILE_CATALOGUE

IMAGE_MIMES = {'image/png', 'image/jpeg', 'image/webp'}
IMAGE_EXTENSIONS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def connection_error(status, operation):
    if status in (401, 403):
        return 'Hermes recusou a autenticacao ou o escopo da tarefa (HTTP ' + str(status) + '). Execute o instalador completo na pasta original para sincronizar a conexao, preservando seu .env.'
    if status in (404, 405):
        return 'O endpoint de ' + operation + ' nao existe nesta API Hermes (HTTP ' + str(status) + '). Execute o instalador completo para atualizar o container e conferir o endereco da API.'
    if status == 413:
        return 'A solicitacao excede o tamanho aceito pelo Hermes. Divida o texto ou os anexos em solicitacoes menores.'
    return 'Hermes retornou HTTP ' + str(status) + ' ao ' + operation + '. Confira a disponibilidade dos servicos e execute o diagnostico da integracao.'


def validate_image_url(url):
    """Only inline image bytes: never fetch arbitrary remote URLs or local paths."""
    if not isinstance(url, str) or not url.startswith('data:') or len(url) > 14 * 1024 * 1024:
        raise ValueError('Envie a imagem como anexo PNG, JPEG ou WebP de ate 10 MB; URLs externas nao sao aceitas.')
    header, _, encoded = url.partition(',')
    mime = header[5:].split(';')[0]
    if mime not in IMAGE_MIMES or not header.endswith(';base64'):
        raise ValueError('Formato de imagem nao suportado. Use PNG, JPEG ou WebP.')
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > 10 * 1024 * 1024:
            raise ValueError('Imagem maior que 10 MB.')
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 40_000_000 or Image.MIME.get(image.format) != mime:
                raise ValueError('Imagem excede 40 megapixels ou tem formato inconsistente.')
            image.verify()
    except Exception as exc:
        raise ValueError('Imagem invalida ou muito grande. Use PNG, JPEG ou WebP de ate 10 MB e 40 megapixels.') from exc
    return hashlib.sha256(data).hexdigest()


class Pipe:
    class Valves(BaseModel):
        HERMES_BASE_URL: str = Field(default='http://host.docker.internal:8643/v1')
        HERMES_API_KEY: str = Field(default='', description='API_SERVER_KEY do Hermes; nao e a chave NVIDIA.')
        HERMES_MODEL: str = Field(default='hermes-agent')
        HERMES_PROFILE: str = Field(default='admin', description='Perfil fixo; somente administrador altera.')
        HERMES_GROUP_IDS: list[str] = Field(default_factory=list, description='Grupos autorizados deste perfil.')
        REQUEST_TIMEOUT_SECONDS: int = Field(default=3600, ge=60, le=7200)

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: dict = None, __metadata__: dict = None,
                   __chat_id__: str = None, __task__: str = None,
                   __event_emitter__=None, __request__=None, __task_body__: dict = None,
                   __files__: list = None) -> AsyncGenerator[str, None]:
        async def status(text, done=False):
            if __event_emitter__:
                await __event_emitter__({'type': 'status', 'data': {'description': text, 'done': done}})

        from open_webui.models.users import Users
        from open_webui.models.groups import Groups
        user_id = str((__user__ or {}).get('id', ''))
        user = await Users.get_user_by_id(user_id) if user_id else None
        profile = PROFILES.get(self.valves.HERMES_PROFILE)
        groups = await Groups.get_groups_by_member_id(user_id) if user else []
        if not user or not profile or (user.role != 'admin' and not set(self.valves.HERMES_GROUP_IDS).intersection(g.id for g in groups)):
            await status('Acesso negado: seu usuario nao pertence a um grupo autorizado para este assistente.', True)
            yield 'Acesso negado. Solicite ao administrador a associacao ao grupo do setor.'
            return
        messages = body.get('messages', [])
        if __task__:
            # Open WebUI housekeeping must not create extra agent/browser tasks.
            original_messages = (__task_body__ or {}).get('messages', messages)
            first = next((m.get('content', '') for m in original_messages if m.get('role') == 'user'), '')
            title = first[:60] if isinstance(first, str) else 'Conversa com Hermes'
            yield json.dumps({'title': title, 'tags': [], 'follow_ups': [], 'queries': []}, ensure_ascii=False)
            return
        if not self.valves.HERMES_API_KEY:
            await status('Configure HERMES_API_KEY nas Valves da funcao Hermes.', True)
            yield 'A conexao Hermes ainda precisa de API_SERVER_KEY nas Valves do Open WebUI.'
            return
        metadata = __metadata__ or {}
        chat_id = __chat_id__ or metadata.get('chat_id') or body.get('chat_id')
        if not chat_id:
            chat_id = str(uuid.uuid4())
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'hermes-openwebui:{user_id}:{chat_id}:{self.valves.HERMES_PROFILE}'))
        run_id = str(uuid.uuid4())
        output_dir = f'/opt/data/exports/{session_id}/{run_id}'
        messages = copy.deepcopy(messages)
        messages.insert(0, {'role': 'system', 'content':
            f'Entrega de arquivos: salve TODOS os relatorios e arquivos finais desta solicitacao em {output_dir}/. '
            'As ferramentas criam a pasta automaticamente. Use nomes simples e extensao correta. Esses arquivos serao entregues ao usuario '
            'com links para baixar no Open WebUI. Nao diga apenas que salvou um arquivo em outro caminho. '
            'Codigo de programacao extenso deve ser entregue como arquivo completo com a extensao da linguagem; '
            'para projetos com varios arquivos ou subpastas, entregue tambem um ZIP com a estrutura completa. '
            'Crie efetivamente o arquivo antes de afirmar que o relatorio esta pronto.'})
        messages[0]['content'] += ' Use workspace_file/workspace_pdf com nomes relativos (ex.: relatorio.html), nunca caminhos absolutos.'
        messages[0]['content'] += (' Responda sempre em português do Brasil, inclusive relatórios e resumos dos subagentes, '
            'salvo pedido explícito em outra língua. Preserve referências, nomes próprios, código e SQL no idioma original '
            'quando necessário, explicando em português. Ao delegar, inclua esta regra no contexto de cada subagente.')
        headers = {'Authorization': 'Bearer ' + self.valves.HERMES_API_KEY,
                   'X-Hermes-Session-Id': session_id, 'Content-Type': 'application/json'}
        scope = {'user': user_id, 'profile': self.valves.HERMES_PROFILE, 'session': session_id,
                 'run': run_id, 'issued': time.time()}
        encoded = base64.urlsafe_b64encode(json.dumps(scope, separators=(',', ':')).encode()).decode().rstrip('=')
        signature = hmac.new(self.valves.HERMES_API_KEY.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        headers['X-Hermes-Scope'] = encoded + '.' + signature
        payload = {'model': self.valves.HERMES_MODEL, 'messages': messages, 'stream': True}
        await status('Processando a solicitação. Aguarde...')
        try:
            image_hashes = set()
            image_count = 0
            for message in messages:
                if isinstance(message.get('content'), list):
                    for part in message['content']:
                        if part.get('type') == 'image_url':
                            image_count += 1
                            image_hashes.add(validate_image_url(part.get('image_url', {}).get('url')))
                        elif part.get('type') in ('input_image', 'video_url', 'input_audio'):
                            raise ValueError('Use anexos de imagem PNG, JPEG ou WebP; audio e video nao estao habilitados.')
            if image_count > 20:
                raise ValueError('Limite de 20 imagens no contexto da solicitacao.')
            if image_count:
                await status('Analisando as imagens anexadas. Aguarde...')
            timeout = aiohttp.ClientTimeout(total=self.valves.REQUEST_TIMEOUT_SECONDS, sock_read=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                export_url = self.valves.HERMES_BASE_URL.rstrip('/') + f'/exports/{session_id}/{run_id}'
                # Resolve IDs through native storage; never trust a client-supplied path/URL.
                from open_webui.models.files import Files
                from open_webui.storage.provider import Storage
                import asyncio
                attachments = __files__ or metadata.get('files') or body.get('files') or []
                if not isinstance(attachments, list) or any(not isinstance(item, dict) for item in attachments):
                    raise ValueError('Lista de anexos invalida. Envie os arquivos pelo botao de anexar do Open WebUI.')
                if len(attachments) > 20:
                    raise RuntimeError('Limite de 20 anexos por solicitacao.')
                if attachments:
                    await status('Recebendo documentos autorizados para esta tarefa.')
                input_names = []
                for item in attachments:
                    file_id = item.get('id') or (item.get('file') or {}).get('id')
                    if not file_id and item.get('type') == 'image':
                        if not image_count:
                            raise ValueError('Imagem sem conteudo. Anexe a imagem novamente.')
                        continue  # Inline images already validated above.
                    saved_file = await Files.get_file_by_id(file_id) if file_id else None
                    # Strict ownership. Shared knowledge is handled by Open WebUI RAG, not arbitrary file IDs.
                    if not saved_file or saved_file.user_id != user_id:
                        raise RuntimeError('Anexo indisponivel ou pertencente a outro usuario.')
                    local_path = await asyncio.to_thread(Storage.get_file, saved_file.path)
                    path = Path(local_path)
                    if path.stat().st_size > 25 * 1024 * 1024:
                        raise RuntimeError('Anexo maior que 25 MB.')
                    name = str(uuid.UUID(file_id)) + '_' + Path(saved_file.filename).name
                    data = await asyncio.to_thread(path.read_bytes)
                    mime = IMAGE_EXTENSIONS.get(Path(saved_file.filename).suffix.lower())
                    if mime:
                        image_url = 'data:' + mime + ';base64,' + base64.b64encode(data).decode()
                        digest = validate_image_url(image_url)
                        if digest not in image_hashes:
                            image_count += 1
                            if image_count > 20:
                                raise ValueError('Limite de 20 imagens no contexto da solicitacao.')
                            image_hashes.add(digest)
                            latest = next(m for m in reversed(messages) if m.get('role') == 'user')
                            if not isinstance(latest.get('content'), list):
                                latest['content'] = [{'type': 'text', 'text': latest.get('content', '')}]
                            latest['content'].append({'type': 'image_url', 'image_url': {'url': image_url}})
                            await status('Analisando as imagens anexadas. Aguarde...')
                    async with session.post(export_url + '/inputs/' + quote(name, safe=''), headers=headers, data=io.BytesIO(data)) as uploaded:
                        if uploaded.status != 201:
                            raise RuntimeError(connection_error(uploaded.status, 'receber o anexo') if uploaded.status != 400 else 'Hermes recusou o anexo: confira formato, tamanho e nome do arquivo.')
                    input_names.append('inputs/' + name)
                if input_names:
                    messages.insert(1, {'role': 'system', 'content': 'Anexos desta tarefa (use workspace_file para ler): ' + ', '.join(input_names)})
                async with session.post(self.valves.HERMES_BASE_URL.rstrip('/') + '/chat/completions',
                                        headers=headers, json=payload) as response:
                    if response.status != 200:
                        raise RuntimeError(connection_error(response.status, 'processar a conversa'))
                    event = ''
                    data_lines = []
                    finished = False
                    async for raw in response.content:
                        line = raw.decode('utf-8').rstrip('\r\n')
                        if line.startswith('event:'):
                            event = line[6:].strip()
                        elif line.startswith('data:'):
                            data_lines.append(line[5:].lstrip())
                        elif not line and data_lines:
                            data = '\n'.join(data_lines)
                            data_lines = []
                            if data == '[DONE]':
                                finished = True
                                break
                            item = json.loads(data)
                            if item.get('error'):
                                raise RuntimeError('Hermes interrompeu a execucao. Confira no dashboard a chave do provedor, o modelo e a disponibilidade da API.')
                            if event == 'hermes.tool.progress':
                                if item.get('label'):
                                    labels = {'workspace_file': 'Processando documentos e arquivos', 'workspace_pdf': 'Organizando e conferindo paginas PDF', 'delegate_task': 'Coordenando subagentes especializados'}
                                    tool = item.get('tool')
                                    if tool == 'delegate_task':
                                        text = item['label'] if item['label'].startswith('Subagente') else 'Distribuindo atividades entre subagentes do perfil ' + profile['name'] + '.'
                                    elif tool == 'browser_queue':
                                        text = item['label']
                                    else:
                                        text = labels.get(tool, 'Executando uma etapa da tarefa. Aguarde...')
                                    await status(text)
                            elif item.get('choices'):
                                if item['choices'][0].get('finish_reason') == 'error':
                                    raise RuntimeError('Hermes interrompeu a execucao. Confira no dashboard a chave do provedor e a disponibilidade do modelo.')
                                delta = item['choices'][0].get('delta', {})
                                text = delta.get('content')
                                if text:
                                    yield text
                            event = ''
                    if not finished:
                        raise RuntimeError('Conexao com Hermes encerrada antes da conclusao.')
                async with session.get(export_url, headers=headers) as listing:
                    if listing.status in (404, 405):
                        await status('Resposta de texto recebida. A API conectada precisa ser atualizada para entregar arquivos.', True)
                        yield '\n\nAviso: a resposta de texto foi recebida, mas os downloads nao estao disponiveis nesta API. Execute o instalador completo para atualizar a integracao.'
                        return
                    if listing.status != 200:
                        raise RuntimeError(connection_error(listing.status, 'consultar arquivos gerados'))
                    exports = (await listing.json()).get('files', [])
                if exports:
                    await status('Preparando os arquivos para baixar no Open WebUI.')
                    from fastapi import UploadFile
                    from starlette.datastructures import Headers
                    from open_webui.models.users import Users
                    from open_webui.routers.files import upload_file_handler
                    user = await Users.get_user_by_id(user_id)
                    if not user:
                        raise RuntimeError('Usuario do chat nao encontrado para entregar os arquivos.')
                    links = []
                    for export in exports:
                        name = export['name']
                        async with session.get(export_url + '/' + quote(name, safe=''), headers=headers) as download:
                            if download.status != 200:
                                raise RuntimeError('Nao foi possivel transferir o arquivo gerado.')
                            data = bytearray()
                            async for chunk in download.content.iter_chunked(65536):
                                data.extend(chunk)
                                if len(data) > 25 * 1024 * 1024:
                                    raise RuntimeError('Arquivo maior que o limite de 25 MB.')
                        upload = UploadFile(file=io.BytesIO(data), filename=name,
                                            headers=Headers({'content-type': export['content_type']}))
                        saved = await upload_file_handler(request=__request__, file=upload,
                            metadata={'chat_id': str(chat_id), 'source': 'hermes'}, process=False,
                            process_in_background=False, user=user, background_tasks=None)
                        label = name.replace('[', '').replace(']', '').replace('\n', '')
                        links.append(f'- [Baixar {label}](/api/v1/files/{saved.id}/content?attachment=true)')
                    yield '\n\nArquivos para baixar:\n\n' + '\n'.join(links) + '\n'
            await status('Hermes concluiu a tarefa. Chromium da pesquisa encerrado.', True)
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                message = 'O tempo de atendimento foi excedido. Tente novamente ou divida a tarefa.'
            elif isinstance(exc, aiohttp.ClientError):
                message = 'Falha na conexao com o Hermes. Confira se o servico esta disponivel e tente novamente.'
            else:
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Nao foi possivel concluir a solicitacao. Confira os servicos e tente novamente.'
            await status(message, True)
            yield '\n\n' + message
