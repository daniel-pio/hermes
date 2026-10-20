"""Apply the visible-browser policy after upstream seeds the durable config."""
import os
from pathlib import Path
import shutil

import yaml

home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
path = home / "config.yaml"
config = yaml.safe_load(path.read_text()) if path.exists() else {}
config = config or {}
if path.exists() and not (home / "config.before-visible-browser.yaml").exists():
    shutil.copy2(path, home / "config.before-visible-browser.yaml")

model = config.setdefault("model", {})
model.update(default="nvidia/nemotron-3-super-120b-a12b", provider="nvidia")
model.pop("base_url", None)
config.setdefault('auxiliary', {}).setdefault('vision', {}).update(
    provider='nvidia', model='meta/llama-3.2-90b-vision-instruct')

browser = config.setdefault("browser", {})
browser.update(backend="off", cloud_provider="local", inactivity_timeout=300)
browser.pop('cdp_url', None)
# These toolsets call search/extraction APIs instead of the visible browser.
agent = config.setdefault("agent", {})
disabled = agent.get("disabled_toolsets", []) or []
config.pop("disabled_toolsets", None)
disabled = [item for item in disabled if item != "browser"]
agent["disabled_toolsets"] = list(dict.fromkeys([*disabled, "web", "search"]))
for selected in (config.get("platform_toolsets", {}) or {}).values():
    if isinstance(selected, list) and "browser" not in selected:
        selected.append("browser")
selected = config.get("toolsets")
if isinstance(selected, list) and "browser" not in selected:
    selected.append("browser")
config.setdefault('delegation', {}).update(max_concurrent_children=3, max_spawn_depth=1,
    orchestrator_enabled=False, child_timeout_seconds=900, inherit_mcp_toolsets=False)
path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))

instructions = home / "AGENTS.md"
start = "<!-- visible-browser-policy:start -->"
end = "<!-- visible-browser-policy:end -->"
policy = f"""{start}
## Pesquisa e navegacao web
Todas as pesquisas, consultas a sites e navegacao web devem usar as ferramentas
browser_* conectadas ao Chromium isolado da tarefa (pool local de 3 vagas).
O usuario acompanha esse navegador em http://HOST:6080, nas telas 1, 2 ou 3.
Para pesquisar, abra um buscador no Chromium, leia os resultados com
browser_snapshot e navegue pelos links. Use esse navegador tambem para ler sites.
Nao use web_search, web_extract, APIs de busca, curl, requests, navegadores
headless separados ou provedores de navegador na nuvem para pesquisas web.
Se o Chromium estiver indisponivel, informe a falha; nao troque de navegador.
{end}"""
content = instructions.read_text() if instructions.exists() else ""
if start in content and end in content:
    before, remaining = content.split(start, 1)
    _, after = remaining.split(end, 1)
    content = before + policy + after
else:
    content = content.rstrip() + "\n\n" + policy + "\n"
instructions.write_text(content)
print("[visible-browser] CDP configured; browser tools enabled; external web tools disabled")

# SOUL.md is loaded independently of the active chat's working directory.
# Keep the same policy when a session switches to a different project folder.
soul = home / "SOUL.md"
soul_content = soul.read_text() if soul.exists() else ""
if start in soul_content and end in soul_content:
    before, remaining = soul_content.split(start, 1)
    _, after = remaining.split(end, 1)
    soul_content = before + policy + after
else:
    soul_content = soul_content.rstrip() + "\n\n" + policy + "\n"
soul.write_text(soul_content)
