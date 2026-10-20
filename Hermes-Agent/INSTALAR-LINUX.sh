#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
prepare=false
webui_port=3000
webui_container=''
hermes_args=(--instalar-docker --timeout 1200)
while (($#)); do
  case "$1" in
    --preparar-somente) prepare=true; shift ;;
    --porta) webui_port="${2:?Informe a porta}"; shift 2 ;;
    --container) webui_container="${2:?Informe o container}"; shift 2 ;;
    -h|--help) printf '%s\n' 'Uso: bash INSTALAR-LINUX.sh [--preparar-somente] [--porta 3000] [--container NOME]'; exit 0 ;;
    *) printf 'Opcao desconhecida: %s\n' "$1" >&2; exit 1 ;;
  esac
done
[[ "$webui_port" =~ ^[0-9]+$ ]] && ((10#$webui_port >= 1024 && 10#$webui_port <= 65535)) || { echo 'Porta invalida' >&2; exit 1; }
[[ -z "$webui_container" || "$webui_container" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Nome de container invalido' >&2; exit 1; }
bash instalar-hermes.sh --preparar-somente
secret() { od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'; }
[[ ! -L .env.openwebui ]] || { echo '.env.openwebui nao pode ser link simbolico' >&2; exit 1; }
if [[ ! -e .env.openwebui ]]; then
  (set -o noclobber; printf '%s\n' "OPEN_WEBUI_CONTAINER=${webui_container:-hermes-open-webui}" \
    "OPEN_WEBUI_PORT=$webui_port" 'OPEN_WEBUI_BIND_ADDRESS=0.0.0.0' 'WEBUI_ADMIN_EMAIL=admin@hermes.local' \
    "WEBUI_ADMIN_PASSWORD=$(secret 16)" "WEBUI_SECRET_KEY=$(secret 32)" > .env.openwebui)
  echo 'Credenciais novas do Open WebUI geradas em .env.openwebui (permissao 600).'
else
  [[ -f .env.openwebui ]] || { echo '.env.openwebui deve ser arquivo regular' >&2; exit 1; }
  echo '.env.openwebui existente preservado.'
fi
if "$prepare"; then echo 'Preparacao concluida; nenhum container alterado.'; exit 0; fi
bash instalar-hermes.sh "${hermes_args[@]}"
docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then docker_cmd=(sudo docker); fi
env_value() {
  local name="$1" line
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in "$name="*) printf '%s' "${line#*=}"; return ;; esac
  done < .env.openwebui
  echo "Campo ausente em .env.openwebui: $name" >&2; return 1
}
target="${webui_container:-$(env_value OPEN_WEBUI_CONTAINER)}"
[[ "$target" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Nome de container invalido' >&2; exit 1; }
existing="$("${docker_cmd[@]}" ps -a --filter "name=^/$target$" --format '{{.ID}}')"
if [[ -z "$existing" && -z "$webui_container" ]]; then
  old="$("${docker_cmd[@]}" ps -a --filter 'name=^/open-webui$' --format '{{.ID}}')"
  if [[ -n "$old" ]]; then target=open-webui; existing="$old"; fi
fi
if [[ -n "$existing" ]]; then
  echo "Integrando Open WebUI existente: $target. Dados e credenciais existentes preservados."
  "${docker_cmd[@]}" start "$target"
  "${docker_cmd[@]}" cp verify-openwebui.py "$target:/tmp/verify-openwebui.py"
  "${docker_cmd[@]}" exec "$target" python /tmp/verify-openwebui.py
else
  [[ "$target" == "$(env_value OPEN_WEBUI_CONTAINER)" ]] || { echo 'Ajuste OPEN_WEBUI_CONTAINER em .env.openwebui' >&2; exit 1; }
  "${docker_cmd[@]}" compose --project-name hermes-openwebui --env-file .env.openwebui -f docker-compose.openwebui.yml up -d --wait --wait-timeout 1200
fi
bash integrar-openwebui.sh "$target"
printf '%s\n' 'Instalacao completa: Hermes + Open WebUI integrados.' \
  "Open WebUI novo: http://localhost:$(env_value OPEN_WEBUI_PORT)/ (tambem pelo IP LAN)." \
  'Instalacao nova: login/senha em .env.openwebui. Reutilizada: mantenha o login/endereco atuais.' \
  'Vincule somente a chave NVIDIA em http://localhost:9120/env.' \
  'Cadastre funcionarios e associe-os aos grupos em Administracao > Grupos.'
