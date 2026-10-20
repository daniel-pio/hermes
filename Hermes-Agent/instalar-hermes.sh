#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
install_dir="$(pwd -P)"
install_docker=false
prepare_only=false
timeout=180
username=admin
die() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' 'Uso: bash instalar-hermes.sh [--instalar-docker] [--preparar-somente] [--usuario NOME] [--timeout SEGUNDOS]'
    printf '%s\n' '--instalar-docker: instala Docker Engine/Compose no Ubuntu ou Debian, se ausentes.'
}
while (($#)); do
    case "$1" in
        --instalar-docker) install_docker=true; shift ;;
        --preparar-somente) prepare_only=true; shift ;;
        --usuario) (($# >= 2)) || die 'Falta o nome do usuario.'; username="$2"; shift 2 ;;
        --timeout) (($# >= 2)) || die 'Falta o timeout.'; timeout="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Opcao desconhecida: $1" ;;
    esac
done
[[ "$username" =~ ^[A-Za-z0-9_-]+$ ]] || die 'Usuario deve conter apenas letras, numeros, _ ou -.'
[[ "$timeout" =~ ^[0-9]{2,4}$ ]] && ((10#$timeout >= 60 && 10#$timeout <= 1800)) || die 'Timeout deve estar entre 60 e 1800 segundos.'
for file in Dockerfile docker-compose.yml browser-stack.sh browser-s6-run configure-browser.py configure-browser-init verify-health.py .dockerignore hermes-exports.py hermes-workspace.py hermes-specialists.json patch-specialists.py; do
    [[ -f "$file" ]] || die "Arquivo ausente: $file. Extraia todo o pacote."
done
secret() { od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'; }
[[ ! -L .env ]] || die '.env e um link simbolico. Use um arquivo local regular.'
if [[ ! -e .env ]]; then
    (
        set -o noclobber
        printf '%s\n' "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=$username" \
            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=$(secret 16)" \
            "HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(secret 32)" \
            "API_SERVER_KEY=$(secret 32)" \
            "HERMES_BIND_ADDRESS=0.0.0.0" \
            'NVIDIA_API_KEY=' > .env
    )
    printf '%s\n' 'Novas credenciais locais geradas no .env (acesso somente do dono). Chave NVIDIA vazia.'
else
    [[ -f .env ]] || die '.env nao e um arquivo regular.'
    printf '%s\n' '.env existente preservado.'
fi
if "$prepare_only"; then
    printf '%s\n' 'Preparacao concluida. Nenhum container foi alterado.'
    exit 0
fi
admin=()
if ((EUID != 0)) && command -v sudo >/dev/null; then
    admin=(sudo)
fi
install_engine() {
    ((EUID == 0 || ${#admin[@]} > 0)) || die 'sudo necessario para instalar Docker.'
    [[ -r /etc/os-release ]] || die 'Nao foi possivel identificar a distribuicao Linux.'
    # shellcheck disable=SC1091
    . /etc/os-release
    case "$ID" in
        ubuntu) distro=ubuntu; codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}" ;;
        debian) distro=debian; codename="${VERSION_CODENAME:-}" ;;
        *) die 'Instalacao automatica do Docker disponivel para Ubuntu/Debian. Nas demais distribuicoes instale Docker Engine e Compose primeiro.' ;;
    esac
    [[ -n "$codename" ]] || die 'Distribuicao sem codinome de versao.'
    for pkg in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
        if [[ "$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)" == 'install ok installed' ]]; then
            die "Pacote conflitante instalado: $pkg. Resolva conforme a documentacao oficial do Docker; este script nao remove pacotes existentes."
        fi
    done
    printf '%s\n' "Instalando Docker pelo repositorio oficial para $distro/$codename."
    "${admin[@]}" apt-get update
    "${admin[@]}" apt-get install -y ca-certificates curl
    "${admin[@]}" install -m 0755 -d /etc/apt/keyrings
    "${admin[@]}" curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
    "${admin[@]}" chmod a+r /etc/apt/keyrings/docker.asc
    arch="$(dpkg --print-architecture)"
    printf '%s\n' 'Types: deb' "URIs: https://download.docker.com/linux/$distro" \
        "Suites: $codename" 'Components: stable' "Architectures: $arch" \
        'Signed-By: /etc/apt/keyrings/docker.asc' | "${admin[@]}" tee /etc/apt/sources.list.d/docker.sources >/dev/null
    "${admin[@]}" apt-get update
    "${admin[@]}" apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    if command -v systemctl >/dev/null; then
        "${admin[@]}" systemctl enable --now docker
    else
        die 'Docker instalado. Inicie o daemon pelo gerenciador de servicos e execute novamente.'
    fi
}
if ! command -v docker >/dev/null; then
    "$install_docker" || die 'Docker ausente. Use --instalar-docker (Ubuntu/Debian) ou instale Docker Engine e Compose.'
    install_engine
fi
docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then
    if ((${#admin[@]})) && sudo docker info >/dev/null 2>&1; then
        docker_cmd=(sudo docker)
    else
        die 'Daemon Docker indisponivel. Inicie o servico e confira sua permissao de acesso.'
    fi
fi
[[ "$("${docker_cmd[@]}" info --format '{{.OSType}}')" == linux ]] || die 'Docker precisa executar containers Linux.'
"${docker_cmd[@]}" compose version
"${docker_cmd[@]}" compose config --quiet
container_name=hermes-agent-v2026-9-11
if [[ -n "$("${docker_cmd[@]}" ps -a --filter "name=^/$container_name$" --format '{{.ID}}')" ]]; then
    owner="$("${docker_cmd[@]}" inspect "$container_name" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')"
    [[ "$owner" == "$install_dir" ]] || die "Ja existe $container_name de outra pasta. Execute o instalador na pasta original."
fi
printf '%s\n' 'Construindo e iniciando Hermes + dashboard + Chromium. O primeiro download pode demorar.'
"${docker_cmd[@]}" compose up -d --build --wait --wait-timeout "$timeout"
"${docker_cmd[@]}" compose exec -T hermes python /usr/local/lib/verify-health.py
"${docker_cmd[@]}" compose ps
printf '%s\n' 'Instalacao concluida.' 'Dashboard local: http://127.0.0.1:9120/' \
    'Chromium local: http://127.0.0.1:6080/' 'Usuario/senha: consulte o .env nesta pasta.' \
    'Vincule NVIDIA_API_KEY em http://127.0.0.1:9120/env' \
    'Modelo: nvidia/nemotron-3-super-120b-a12b'
lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true)"
if [[ -n "$lan_ip" ]]; then
    printf '%s\n' "Dashboard LAN: http://$lan_ip:9120/" "Chromium LAN: http://$lan_ip:6080/" "API LAN: http://$lan_ip:8643/"
fi
printf '%s\n' 'Se o acesso LAN for bloqueado, libere TCP 9120, 6080 e 8643 no firewall apenas para a rede local.'
