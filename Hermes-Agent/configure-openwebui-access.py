"""Apply a reproducible restricted interface using native Open WebUI permissions."""
import asyncio
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, '/app/backend')
if not os.environ.get('WEBUI_SECRET_KEY'):
    os.environ['WEBUI_SECRET_KEY'] = Path('/app/backend/.webui_secret_key').read_text().strip()
from sqlalchemy import select, update
from open_webui.internal.db import get_async_db_context
from open_webui.models.users import User
from open_webui.models.groups import Groups, GroupUpdateForm
from open_webui.models.functions import Functions
from open_webui.models.tools import Tool
from open_webui.models.skills import Skill
from open_webui.models.access_grants import AccessGrants
from open_webui.models.config import Config
from open_webui.utils.auth import create_token
from open_webui.utils.access_control import get_permissions

DENIED = {
    'chat': ['controls', 'valves', 'system_prompt', 'params', 'temporary', 'temporary_enforced', 'multiple_models', 'web_upload'],
    'workspace': ['models', 'knowledge', 'prompts', 'tools', 'skills', 'models_import', 'models_export', 'prompts_import', 'prompts_export', 'tools_import', 'tools_export', 'skills_import', 'skills_export'],
    'features': ['api_keys', 'direct_tool_servers', 'web_search', 'image_generation', 'code_interpreter', 'memories', 'automations', 'webhooks'],
}

def restrict(permissions):
    result = copy.deepcopy(permissions or {})
    for section, keys in DENIED.items():
        for key in keys:
            result.setdefault(section, {})[key] = False
    result.setdefault('chat', {})['file_upload'] = True
    return result

async def configure():
    backup_dir = Path('/app/backend/data/hermes-access-backups')
    marker = backup_dir / '.initialized'
    if marker.exists() or (backup_dir.exists() and any(backup_dir.glob('access-*.json'))):
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker.touch(mode=0o600, exist_ok=True)
        print('Permissoes ja inicializadas: escolhas atuais do administrador preservadas.')
        return
    async with get_async_db_context() as db:
        users = list((await db.execute(select(User))).scalars())
        admins = sorted((u for u in users if u.role == 'admin'), key=lambda u: u.created_at)
        tools = list((await db.execute(select(Tool))).scalars())
        skills = list((await db.execute(select(Skill))).scalars())
    if not admins: raise RuntimeError('Conta administrativa necessaria')
    admin = admins[0]
    token = create_token({'id': admin.id}, expires_delta=timedelta(minutes=5))
    def api(method, payload=None):
        request = urllib.request.Request('http://127.0.0.1:8080/api/v1/users/default/permissions',
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    defaults = await asyncio.to_thread(api, 'GET')
    groups = await Groups.get_all_groups()
    functions = [f for f in await Functions.get_functions() if f.type in ('filter', 'action')]
    connections = await Config.get('tool_server.connections', []) or []
    # Backup only access settings, inside the persistent container. No tool code or credentials.
    snapshot = {'default_permissions': defaults,
        'groups': [{'id':g.id, 'permissions':g.permissions} for g in groups],
        'functions': [{'id':f.id, 'is_active':f.is_active} for f in functions],
        'resources': [],
        'tool_servers': [{'index':i, 'access_grants':c.get('config', {}).get('access_grants'),
                          'access_control':c.get('config', {}).get('access_control')} for i,c in enumerate(connections)]}
    for kind, items in [('tool', tools), ('skill', skills)]:
        for item in items:
            grants = await AccessGrants.get_grants_by_resource(kind, item.id)
            snapshot['resources'].append({'type':kind, 'id':item.id, 'owner':item.user_id,
                'grants':[g.model_dump() for g in grants]})
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Separate new backups from legacy ones: an interrupted first setup must retry.
    backup = backup_dir / ('initial-access-' + str(time.time_ns()) + '.json')
    backup.write_text(json.dumps(snapshot, ensure_ascii=False))
    backup.chmod(0o600)
    await asyncio.to_thread(api, 'POST', restrict(defaults))
    for group in groups:
        result = await Groups.update_group_by_id(group.id, GroupUpdateForm(name=group.name,
            description=group.description, permissions=restrict(group.permissions), data=group.data))
        if not result: raise RuntimeError('Falha ao restringir grupo')
    # Filters/actions are optional WebUI functions. Keep every Hermes Pipe active.
    for function in functions:
        if function.is_active:
            if not await Functions.update_function_by_id(function.id, {'is_active': False}):
                raise RuntimeError('Falha ao desativar funcao opcional')
    for kind, items, model in [('tool', tools, Tool), ('skill', skills, Skill)]:
        for item in items:
            await AccessGrants.set_access_grants(kind, item.id, [])
            # Native owners bypass grants; retain management with the administrator.
            async with get_async_db_context() as db:
                await db.execute(update(model).where(model.id == item.id).values(user_id=admin.id))
                await db.commit()
    updated_connections = copy.deepcopy(connections)
    for connection in updated_connections:
        settings = connection.setdefault('config', {})
        settings.pop('access_control', None)
        settings['access_grants'] = []
    if connections:
        await Config.upsert({'tool_server.connections': updated_connections})
    actual = await asyncio.to_thread(api, 'GET')
    for user_id in [u.id for u in users if u.role != 'admin'] + ['hermes-permissions-probe']:
        permissions = await get_permissions(user_id, actual)
        assert all(permissions[section][key] is False for section,keys in DENIED.items() for key in keys)
        assert permissions['chat']['file_upload'] is True
    assert all(not f.is_active for f in await Functions.get_functions() if f.type in ('filter','action'))
    marker.touch(mode=0o600)
    print('PASS: controles, parametros, prompt, chat temporario e integracoes opcionais bloqueados para usuarios comuns.')
    print('Anexos, downloads e Pipes Hermes preservados. Administradores mantem controles nativos.')
    print('Backup de permissoes salvo dentro do volume Open WebUI (hermes-access-backups).')

if __name__ == '__main__':
    asyncio.run(configure())
