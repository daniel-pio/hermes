"""Pinned-image integration for signed, scoped specialist requests."""
from pathlib import Path
import ast

root = Path('/opt/hermes')
def patch(name, before, after):
    path = root / name
    text = path.read_text()
    if text.count(before) != 1: raise RuntimeError('Unsupported specialist integration: ' + name)
    text = text.replace(before, after)
    ast.parse(text)
    path.write_text(text)

patch('gateway/platforms/api_server_openai_routes.py',
    '        messages = body.get("messages")\n',
    '        from tools.hermes_workspace import decode_scope, PROFILES\n'
    '        signed_scope = request.headers.get("X-Hermes-Scope", "")\n'
    '        try:\n'
    '            specialist_scope = decode_scope(signed_scope)\n'
    '            if specialist_scope["session"] != request.headers.get("X-Hermes-Session-Id"):\n'
    '                raise ValueError("Scope/session mismatch")\n'
    '        except Exception:\n'
    '            return _error_response("Signed specialist scope required; use the authorized Open WebUI integration", 403)\n'
    '        messages = body.get("messages")\n')
patch('gateway/platforms/api_server_openai_routes.py',
    '        completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"\n',
    '        system_prompt = "HERMES_SCOPE:" + signed_scope + "\\n" + (system_prompt or "")\n'
    '        completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"\n')
patch('gateway/platforms/api_server_openai_routes.py',
    '            session_history_delivery=("1" if provided_session_id else ""))',
    '            session_history_delivery="")  # Scoped requests use synchronous children only.\n')
patch('gateway/platforms/api_server.py',
    '        agent = AIAgent(**agent_kwargs)\n',
    '        from tools.hermes_workspace import decode_scope, PROFILES, LANGUAGE_POLICY\n'
    '        specialist_scope = None\n'
    '        if (ephemeral_system_prompt or "").startswith("HERMES_SCOPE:"):\n'
    '            signed, _, prompt = ephemeral_system_prompt.partition("\\n")\n'
    '            specialist_scope = decode_scope(signed[len("HERMES_SCOPE:"):])\n'
    '            specialist = PROFILES[specialist_scope["profile"]]\n'
    '            agent_kwargs.update(enabled_toolsets=specialist["tools"], skip_context_files=True, skip_memory=True,\n'
    '                max_iterations=60, ephemeral_system_prompt=specialist["prompt"] + "\\n" + LANGUAGE_POLICY + "\\n" + prompt +\n'
    '                "\\nUse workspace_file e workspace_pdf; caminhos relativos a pasta da tarefa. "\n'
    '                "Todas as pesquisas devem usar browser_* no Chromium local. "\n'
    '                "Delegue no maximo tres atividades independentes dentro deste perfil; aguarde e valide os resultados. "\n'
    '                "Nenhum subagente pode ampliar permissoes ou acessar outro setor.")\n'
    '        agent = AIAgent(**agent_kwargs)\n'
    '        agent._hermes_scope = specialist_scope\n')
patch('gateway/platforms/api_server_openai_routes.py',
    '            def _on_pool_progress(event_type, name, preview, args, **kwargs):\n',
    '            def _on_pool_progress(event_type, name=None, preview=None, args=None, **kwargs):\n'
    '                if str(event_type).startswith("subagent") and name != "browser_queue" and event_type not in ("subagent.text", "subagent.thinking"):\n'
    '                    failed = kwargs.get("status") in ("failed", "error", "timeout")\n'
    '                    label = ("Subagente falhou; coordenador avaliando o resultado." if failed else\n'
    '                        "Subagente concluiu a atividade; consolidando resultados." if event_type == "subagent.complete" else\n'
    '                        "Subagente iniciou uma atividade especializada." if event_type == "subagent.start" else\n'
    '                        "Subagente processando a atividade especializada.")\n'
    '                    index = int(kwargs.get("task_index", 0)) + 1\n'
    '                    profile_name = PROFILES[specialist_scope["profile"]]["name"]\n'
    '                    label = label.replace("Subagente", f"Subagente {index} do perfil {profile_name}", 1)\n'
    '                    _stream_q.put_threadsafe(("__tool_progress__", {"tool": "delegate_task",\n'
    '                        "toolCallId": kwargs.get("subagent_id", "hermes-delegation"), "label": label,\n'
    '                        "status": "completed" if event_type == "subagent.complete" else "running"}))\n')
patch('tools/delegate_tool.py',
    '    parent_sid = getattr(parent_agent, "session_id", None)\n',
    '    scope = getattr(parent_agent, "_hermes_scope", None)\n'
    '    if scope:\n'
    '        from tools.hermes_workspace import PROFILES, LANGUAGE_POLICY\n'
    '        child_prompt = (PROFILES[scope["profile"]]["prompt"] + "\\n" + LANGUAGE_POLICY + "\\n" + goal + "\\n" + (context or "") +\n'
    '            "\\nUse workspace_file/workspace_pdf com caminhos relativos. "\n'
    '            "Toda pesquisa deve usar browser_* no Chromium local. Nao amplie o escopo do setor.")\n'
    '        max_iterations = min(max_iterations, 60)\n'
    '    parent_sid = getattr(parent_agent, "session_id", None)\n')
patch('tools/delegate_tool.py',
    '    child._print_fn = getattr(parent_agent, "_print_fn", None)\n',
    '    child._hermes_scope = getattr(parent_agent, "_hermes_scope", None)\n'
    '    child._print_fn = getattr(parent_agent, "_print_fn", None)\n')
patch('agent/conversation_loop.py',
    '    browser_pool_client.register(task_id, agent)\n',
    '    browser_pool_client.register(task_id, agent)\n'
    '    from tools.hermes_workspace import bind\n'
    '    bind(task_id, getattr(agent, "_hermes_scope", None))\n')
patch('agent/conversation_loop.py',
    '                browser_pool_client.unregister(task_id)',
    '                browser_pool_client.unregister(task_id)\n'
    '                from tools.hermes_workspace import unbind\n'
    '                unbind(task_id)')
patch('agent/vision_message_prep.py',
    '            "Describe everything visible in this image in thorough detail. "',
    '            "Responda em portugues do Brasil. Descreva somente o que esta visivel, sem inventar detalhes. "\n'
    '            "Describe everything visible in this image in thorough detail. "')
