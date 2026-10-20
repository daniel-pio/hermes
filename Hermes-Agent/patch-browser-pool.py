"""Fail closed if the pinned upstream integration points change."""
from pathlib import Path
import ast

root = Path('/opt/hermes')


def patch(file, before, after):
    path = root / file
    source = path.read_text()
    if source.count(before) != 1:
        raise RuntimeError(f'Unsupported Hermes integration point: {file}')
    source = source.replace(before, after, 1)
    ast.parse(source)
    path.write_text(source)


patch('gateway/platforms/api_server.py',
      'class APIServerAdapter(OpenAICompatRoutesMixin, BasePlatformAdapter):',
      'from gateway.hermes_exports import ExportMixin\n\n'
      'class APIServerAdapter(ExportMixin, OpenAICompatRoutesMixin, BasePlatformAdapter):')
patch('gateway/platforms/api_server.py',
      '            ("GET", "/health", self._handle_health),',
      '            ("GET", "/v1/integration/health", self._handle_integration_health),\n'
      '            ("GET", "/v1/exports/{session}/{run}", self._handle_export_list),\n'
      '            ("GET", "/v1/exports/{session}/{run}/{name}", self._handle_export_download),\n'
      '            ("POST", "/v1/exports/{session}/{run}/inputs/{name}", self._handle_input_upload),\n'
      '            ("GET", "/health", self._handle_health),')


patch('tools/browser_tool_session.py',
      '    cdp_override = _cdp._get_cdp_override()\n',
      '    from tools import browser_pool_client\n'
      '    return browser_pool_client.acquire(task_id)\n'
      '    cdp_override = _cdp._get_cdp_override()\n')
patch('tools/browser_tool_session.py',
      '    # Cleanup stops the supervisor before closing the backend;',
      '    from tools import browser_pool_client\n'
      '    if command != "close":\n'
      '        browser_pool_client.touch(session_info)\n'
      '    # Cleanup stops the supervisor before closing the backend;')
patch('tools/browser_tool_lifecycle.py',
      '    bb_session_id = session_info.get("bb_session_id", "unknown")\n',
      '    from tools import browser_pool_client\n'
      '    _best_effort("Release visible Chromium", lambda: browser_pool_client.release(session_info))\n'
      '    bb_session_id = session_info.get("bb_session_id", "unknown")\n')
patch('agent/chat_completion_helpers.py',
      '("browser", lambda _tid: _headed(),',
      '("browser", lambda _tid: False,')

path = root / 'agent/conversation_loop.py'
source = path.read_text()
start = source.index('    result = _run_conversation_turn(\n', source.index('\ndef run_conversation('))
end = source.index('\n\n\n__all__', start)
body = source[start:end]
replacement = ('    task_id = task_id or str(__import__("uuid").uuid4())\n'
               '    from tools import browser_pool_client\n'
               '    browser_pool_client.register(task_id, agent)\n'
               '    try:\n' + ''.join('    ' + line + '\n' for line in body.splitlines()) +
               '    finally:\n'
               '        from tools import browser_pool_client\n'
               '        try:\n'
               '            from tools.browser_tool_lifecycle import cleanup_browser\n'
               '            cleanup_browser(task_id)\n'
               '        finally:\n'
               '            try:\n'
               '                browser_pool_client.release_task(task_id)\n'
               '            except Exception:\n'
               '                logger.warning("Browser pool final cleanup failed", exc_info=True)\n'
               '            finally:\n'
               '                browser_pool_client.unregister(task_id)')
source = source[:start] + replacement + source[end:]
ast.parse(source)
path.write_text(source)

patch('gateway/platforms/api_server_openai_routes.py',
      '            # tool_progress_callback deliberately NOT wired: it would duplicate the structured\n'
      '            # start/complete callbacks (which carry the tool_call id).\n',
      '            def _on_pool_progress(event_type, name, preview, args, **kwargs):\n'
      '                if name == "browser_queue":\n'
      '                    _stream_q.put_threadsafe(("__tool_progress__", {\n'
      '                        "tool": name, "toolCallId": "hermes-browser-queue",\n'
      '                        "label": preview, "status": "completed" if event_type == "tool.completed" else "running"}))\n')
patch('gateway/platforms/api_server_openai_routes.py',
      '                _stream_q, tool_start_callback=_on_tool_start,\n',
      '                _stream_q, tool_progress_callback=_on_pool_progress, tool_start_callback=_on_tool_start,\n')
