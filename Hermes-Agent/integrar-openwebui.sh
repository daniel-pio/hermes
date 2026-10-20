#!/bin/bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
container="${1:-open-webui}"
base_url="${2:-http://host.docker.internal:8643/v1}"
docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then docker_cmd=(sudo docker); fi
[[ -f .env ]] || { echo 'Instale o Hermes primeiro para gerar .env.' >&2; exit 1; }
"${docker_cmd[@]}" cp openwebui-hermes-pipe.py "$container:/tmp/hermes-openwebui-pipe.py"
"${docker_cmd[@]}" cp install-openwebui-pipe.py "$container:/tmp/install-hermes-pipe.py"
"${docker_cmd[@]}" cp hermes-specialists.json "$container:/tmp/hermes-specialists.json"
"${docker_cmd[@]}" cp configure-openwebui-access.py "$container:/tmp/configure_openwebui_access.py"
"${docker_cmd[@]}" cp verify-hermes-integration.py "$container:/tmp/verify_hermes_integration.py"
api_line=''
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in API_SERVER_KEY=*) api_line="$line"; break ;; esac
done < .env
[[ -n "$api_line" ]] || { echo 'API_SERVER_KEY ausente no .env' >&2; exit 1; }
# Only the local Hermes API key arrives on stdin; it is never a shell argument.
printf '%s\n' "$api_line" | "${docker_cmd[@]}" exec -i "$container" python -c '
import json,sys,subprocess
lines=sys.stdin.read().splitlines()
key=next((line.split("=",1)[1].strip().strip("\"\x27") for line in lines if line.startswith("API_SERVER_KEY=")), "")
if not key: raise SystemExit("API_SERVER_KEY ausente no .env")
result=subprocess.run(["python","/tmp/install-hermes-pipe.py"],input=json.dumps({"api_key":key,"base_url":sys.argv[1]}).encode())
raise SystemExit(result.returncode)
' "$base_url"
restart_code=0
"${docker_cmd[@]}" exec "$container" python -c 'from pathlib import Path; p=Path("/tmp/hermes-webui-locale-restart"); needed=p.exists(); p.unlink(missing_ok=True); raise SystemExit(10 if needed else 0)' || restart_code=$?
if [[ "$restart_code" == 10 ]]; then
  echo 'Reiniciando Open WebUI para aplicar o idioma padrao. Dados e usuarios preservados.'
  "${docker_cmd[@]}" restart "$container"
  "${docker_cmd[@]}" cp verify-openwebui.py "$container:/tmp/verify-openwebui.py"
  "${docker_cmd[@]}" exec "$container" python /tmp/verify-openwebui.py
elif [[ "$restart_code" != 0 ]]; then
  echo 'Falha ao verificar idioma do Open WebUI.' >&2; exit "$restart_code"
fi
echo 'Atualize o Open WebUI. Configure os membros em Administracao > Grupos e selecione o especialista Hermes.'
