"""Authenticated, bounded report export from per-request output directories."""
from pathlib import Path
import mimetypes
import uuid
from urllib.parse import quote
from aiohttp import web
from hermes_constants import get_hermes_home

LIMIT = 25 * 1024 * 1024
EXTENSIONS = {'.html', '.htm', '.pdf', '.docx', '.xlsx', '.pptx', '.csv', '.txt',
              '.md', '.json', '.xml', '.zip', '.png', '.jpg', '.jpeg', '.svg', '.webp',
              '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.cc', '.h', '.hpp',
              '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.kts', '.dart', '.r',
              '.sql', '.sh', '.ps1', '.bat', '.cmd', '.yaml', '.yml', '.toml', '.ini',
              '.css', '.scss', '.sass', '.less', '.vue', '.svelte', '.ipynb', '.lua', '.pl'}


class ExportMixin:
    def _authorized_export_scope(self, request):
        try:
            from tools.hermes_workspace import decode_scope
            scope = decode_scope(request.headers.get('X-Hermes-Scope', ''))
            if scope['session'] != request.match_info['session'] or scope['run'] != request.match_info['run']:
                raise ValueError('Scope mismatch')
            return scope
        except (ValueError, KeyError, TypeError):
            raise web.HTTPForbidden()

    async def _handle_integration_health(self, request):
        error = self._check_auth(request)
        if error is not None:
            return error
        try:
            from tools.hermes_workspace import decode_scope, PROFILES
            scope = decode_scope(request.headers.get('X-Hermes-Scope', ''))
            if scope['session'] != request.headers.get('X-Hermes-Session-Id'):
                raise ValueError('Scope mismatch')
            return web.json_response({'service': 'hermes-openwebui', 'protocol': 1,
                'model_alias': getattr(self, '_model_name', 'hermes-agent'),
                'scoped_chat': True, 'file_upload': True, 'file_download': True,
                'profiles': list(PROFILES)})
        except (ValueError, KeyError, TypeError):
            return web.Response(status=403)

    async def _handle_input_upload(self, request):
        error = self._check_auth(request)
        if error is not None:
            return error
        try:
            self._authorized_export_scope(request)
            root = self._export_directory(request) / 'inputs'
            name = request.match_info['name']
            if Path(name).name != name or name.startswith('.') or Path(name).suffix.lower() not in EXTENSIONS:
                raise ValueError('Unsupported attachment')
            if root.is_symlink(): raise ValueError('Unsafe input directory')
            root.mkdir(parents=True, exist_ok=True)
            if len(list(root.iterdir())) >= 20: raise ValueError('Too many attachments')
            data = bytearray()
            async for chunk in request.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > LIMIT: return web.Response(status=413)
            if not data: raise ValueError('Empty attachment')
            path = root / name
            # Exclusive create prevents overwriting originals and following symlinks.
            with path.open('xb') as target:
                target.write(data)
            return web.json_response({'name': 'inputs/' + name}, status=201)
        except (ValueError, OSError, KeyError):
            return web.Response(status=400)

    def _export_directory(self, request):
        session = str(uuid.UUID(request.match_info['session']))
        run = str(uuid.UUID(request.match_info['run']))
        root = (get_hermes_home() / 'exports').resolve()
        path = root / session / run
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('Invalid export path')
        return path

    async def _handle_export_list(self, request):
        error = self._check_auth(request)
        if error is not None:
            return error
        if not self._expected_api_key():
            return web.Response(status=403)
        try:
            self._authorized_export_scope(request)
            path = self._export_directory(request)
            path.mkdir(parents=True, exist_ok=True)
            files = []
            for file in sorted(path.iterdir()):
                if (file.is_file() and not file.is_symlink() and file.suffix.lower() in EXTENSIONS
                        and 0 < file.stat().st_size <= LIMIT):
                    files.append(dict(name=file.name, size=file.stat().st_size,
                                      content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'))
            return web.json_response({'files': files[:20]})
        except (ValueError, OSError):
            return web.Response(status=400)

    async def _handle_export_download(self, request):
        error = self._check_auth(request)
        if error is not None:
            return error
        if not self._expected_api_key():
            return web.Response(status=403)
        try:
            self._authorized_export_scope(request)
            root = self._export_directory(request)
            name = request.match_info['name']
            file = root / name
            if (Path(name).name != name or file.is_symlink() or not file.resolve().is_relative_to(root.resolve())
                    or file.suffix.lower() not in EXTENSIONS or not file.is_file()
                    or not 0 < file.stat().st_size <= LIMIT):
                return web.Response(status=404)
            return web.FileResponse(file, headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name),
                'X-Content-Type-Options': 'nosniff'})
        except (ValueError, OSError):
            return web.Response(status=404)
