"""Run inside the Open WebUI container; JSON configuration arrives via stdin."""
import asyncio
import json
from pathlib import Path
import sys
import os
sys.path.insert(0, '/app/backend')
if not os.environ.get('WEBUI_SECRET_KEY') and not os.environ.get('WEBUI_JWT_SECRET_KEY'):
    secret_file = Path(os.environ.get('WEBUI_SECRET_KEY_FILE', '/app/backend/.webui_secret_key'))
    if secret_file.is_file():
        os.environ['WEBUI_SECRET_KEY'] = secret_file.read_text().strip()
from sqlalchemy import select
from open_webui.internal.db import get_async_db_context
from open_webui.models.users import User
from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
from open_webui.models.groups import Groups, GroupForm
from open_webui.models.models import Models, ModelForm, ModelParams, ModelMeta


async def main():
    options = json.load(sys.stdin)
    key = options['api_key']
    if not isinstance(key, str) or not key:
        raise RuntimeError('API_SERVER_KEY ausente')
    from verify_hermes_integration import verify
    api = await verify(options.get('base_url', 'http://host.docker.internal:8643/v1'), key)
    profiles = json.loads(Path('/tmp/hermes-specialists.json').read_text())
    source = Path('/tmp/hermes-openwebui-pipe.py').read_text().replace(
        'PROFILES = {}  # HERMES_PROFILE_CATALOGUE', 'PROFILES = ' + repr(profiles))
    compile(source, 'hermes-openwebui-pipe.py', 'exec')
    async with get_async_db_context() as db:
        admins = (await db.execute(select(User.id).where(User.role == 'admin').order_by(User.created_at))).scalars().all()
    if not admins:
        raise RuntimeError('Crie primeiro a conta administrativa no Open WebUI')
    for profile_id, profile in profiles.items():
        function_id = 'hermes_chromium_pool3' if profile_id == 'admin' else 'hermes_' + profile_id
        existing = await Functions.get_function_by_id(function_id)
        model = await Models.get_model_by_id(function_id)
        if (existing and 'Hermes' not in existing.name) or (model and 'Hermes' not in model.name):
            raise RuntimeError('ID ocupado por outra integracao: ' + function_id)
        group_ids = []
        for name in profile['groups']:
            group = await Groups.get_group_by_name(name)
            if not group:
                group = await Groups.insert_new_group(admins[0], GroupForm(name=name,
                    description='Acesso aos especialistas Hermes deste setor.', permissions={},
                    data={'config': {'share': False}}))
            if not group: raise RuntimeError('Falha ao criar grupo: ' + name)
            group_ids.append(group.id)
        if existing:
            updated = await Functions.update_function_by_id(function_id, dict(content=source,
                name=existing.name, is_active=existing.is_active))
            if not updated: raise RuntimeError('Falha ao atualizar funcao: ' + function_id)
        else:
            form = FunctionForm(id=function_id, name=profile['name'], content=source,
                meta=FunctionMeta(description='Especialista Hermes com acesso por grupo, arquivos e Chromium.'))
            if not await Functions.insert_new_function(admins[0], 'pipe', form):
                raise RuntimeError('Falha ao criar funcao Hermes')
            await Functions.update_function_by_id(function_id, dict(is_active=True))
        valves = dict(
            HERMES_BASE_URL=options.get('base_url', 'http://host.docker.internal:8643/v1'),
            HERMES_API_KEY=key, HERMES_MODEL='hermes-agent', REQUEST_TIMEOUT_SECONDS=3600,
            HERMES_PROFILE=profile_id, HERMES_GROUP_IDS=group_ids)
        if existing:
            valves.update(await Functions.get_function_valves_by_id(function_id) or {})
        # Transport comes from this installation; stale credentials/URLs break even plain text.
        # Administrative permissions, activation, timeout and model preferences remain intact.
        valves.update(HERMES_BASE_URL=options.get('base_url', 'http://host.docker.internal:8643/v1'),
                      HERMES_API_KEY=key, HERMES_MODEL=api['model_alias'])
        result = await Functions.update_function_valves_by_id(function_id, valves)
        if not result: raise RuntimeError('Falha ao configurar Valves Hermes')
        # Override the built-in Pipe model with a native private workspace model.
        form = ModelForm(id=function_id, base_model_id=None, name=profile['name'],
            params=ModelParams(), meta=ModelMeta(description=profile['prompt'],
                capabilities={'vision': True, 'file_upload': True, 'web_search': False},
                suggestion_prompts=profile['suggestions']),
            access_grants=[{'principal_type': 'group', 'principal_id': group_id, 'permission': 'read'} for group_id in group_ids])
        # Model visibility, capabilities, parameters and prompts remain administrator-managed.
        if model:
            form = ModelForm(**model.model_dump())
        saved = await Models.update_model_by_id(function_id, form) if model else await Models.insert_new_model(form, admins[0])
        if not saved: raise RuntimeError('Falha ao configurar acesso do modelo: ' + function_id)
        print('Configurado: ' + profile['name'] + ' | grupos: ' + (', '.join(profile['groups']) or 'administradores'))
    from configure_openwebui_access import configure
    await configure()
    await configure_portuguese(profiles)
    print('Nenhum usuario foi associado automaticamente. Defina membros em Administracao > Grupos.')


async def configure_portuguese(profiles):
    from open_webui.models.config import Config
    from open_webui.models.users import Users
    locale_marker = Path('/app/backend/data/hermes-portuguese.initialized')
    if not locale_marker.exists():
        await Config.upsert({'ui.prompt_suggestions': profiles['admin']['suggestions'],
                            'ui.prompt_suggestions_i18n': {}})
        locale_marker.touch(mode=0o600)
    async with get_async_db_context() as db:
        users = (await db.execute(select(User))).scalars().all()
    for user in users:
        if not (user.settings or {}).get('ui', {}).get('language'):
            await Users.update_user_settings_by_id(user.id, {'ui': {'language': 'pt-BR'}})
    # Existing containers may predate DEFAULT_LOCALE in our Compose file.
    config_file = Path('/app/backend/open_webui/config.py')
    content = config_file.read_text()
    updated = content.replace("DEFAULT_LOCALE = os.getenv('DEFAULT_LOCALE', '')",
                              "DEFAULT_LOCALE = os.getenv('DEFAULT_LOCALE', 'pt-BR')")
    if updated != content:
        config_file.write_text(updated)
        Path('/tmp/hermes-webui-locale-restart').touch()
    print('Sugestoes de todos os perfis e idioma padrao configurados em portugues do Brasil.')
    print('Conexoes, chaves, ativacao de modelos e permissoes existentes preservadas; administradores gerenciam bloqueios e liberacoes.')


asyncio.run(main())
