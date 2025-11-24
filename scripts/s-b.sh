#!/usr/bin/env bash
set -euo pipefail

# Lightweight installer/manager for the "support-bot" project
# Features:
# - install/update script into /usr/local/bin/s-b
# - clone/update repository
# - create .env from .env.example with optional overrides
# - install Docker (Ubuntu-friendly) or fallback to get.docker.com
# - docker compose up/down/restart/logs/ps
# - self-update from raw UPDATE_URL
#
# Этот скрипт основан на образце и упрощён под репозиторий:
# https://github.com/nikitasryvkov/bot

APP_NAME="support-bot"
BIN_NAME="s-b"
DEFAULT_INSTALL_DIR="/opt/${APP_NAME}"
INSTALL_DIR="${INSTALL_DIR:-${DEFAULT_INSTALL_DIR}}"
REPO_URL="https://github.com/nikitasryvkov/support-bot.git"

# raw URL used for self-update (точный путь к raw должен существовать в репозитории)
UPDATE_URL="https://raw.githubusercontent.com/nikitasryvkov/support-bot/refs/heads/main/scripts/s-b.sh"

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
ACTUAL_PATH=""
if [[ -n "${SCRIPT_SOURCE}" && "${SCRIPT_SOURCE}" != "bash" && -e "${SCRIPT_SOURCE}" ]]; then
  ACTUAL_PATH="$(realpath "${SCRIPT_SOURCE}" 2>/dev/null || true)"
fi

# derived paths
update_paths() {
  INSTALL_DIR="${INSTALL_DIR%/}"
  [[ -z "${INSTALL_DIR}" ]] && INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
  ENV_FILE="${INSTALL_DIR}/.env"
  EXAMPLE_FILE="${INSTALL_DIR}/.env.example"
  COMPOSE_DIR="${INSTALL_DIR}"
}
update_paths

# helpers
log()  { printf "\033[1;34m[INFO]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[OK]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[ERR]\033[0m %s\n" "$*" >&2; }

run_with_check() {
  log "Running: $*"
  if ! "$@"; then
    err "Command failed: $*"
    return 1
  fi
  return 0
}

need_sudo() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      echo sudo
    else
      err "Нужны права root или sudo."
      exit 1
    fi
  fi
}
SUDO="$(need_sudo || true)"

# utilities
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    err "Нет sha256sum/shasum в системе"
    return 1
  fi
}

generate_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(24))'
  else
    head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48
  fi
}

# dependency checks (simple)
check_dependencies() {
  local deps=(git curl realpath)
  local miss=()
  for d in "${deps[@]}"; do
    if ! command -v "$d" >/dev/null 2>&1; then
      miss+=("$d")
    fi
  done
  if [[ ${#miss[@]} -gt 0 ]]; then
    err "Отсутствуют зависимости: ${miss[*]}. Установите их и повторите."
    exit 1
  fi
}

# self-install into /usr/local/bin
self_install() {
  local target="/usr/local/bin/${BIN_NAME}"
  local src="${ACTUAL_PATH:-${SCRIPT_SOURCE}}"

  if [[ -z "${src}" ]]; then
    warn "Не могу определить путь к скрипту — пропускаю установку."
    return 0
  fi

  if [[ "${src}" == "${target}" ]]; then
    ok "Скрипт уже установлен в ${target}"
    return 0
  fi

  log "Устанавливаю ${BIN_NAME} -> ${target}"
  if [[ -e "${src}" ]]; then
    $SUDO install -m 0755 -D "${src}" "${target}"
  else
    # попытка скачать по UPDATE_URL
    local tmp
    tmp="$(mktemp)"
    trap 'rm -f "${tmp}"' RETURN
    run_with_check curl -fsSL "${UPDATE_URL}" -o "${tmp}"
    $SUDO install -m 0755 -D "${tmp}" "${target}"
    rm -f "${tmp}"
  fi
  ok "Установлено: ${BIN_NAME}"
}

# simple ubuntu detection for Docker repository install
detect_ubuntu_like() {
  [[ -r /etc/os-release ]] || return 1
  . /etc/os-release
  case "${ID,,}" in
    ubuntu|linuxmint|pop|zorin) return 0 ;;
  esac
  if [[ -n "${ID_LIKE:-}" && "${ID_LIKE}" == *ubuntu* ]]; then
    return 0
  fi
  return 1
}

docker_is_installed() {
  if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

install_docker_if_needed() {
  if docker_is_installed; then
    ok "Docker установлен и работает"
    return 0
  fi

  log "Устанавливаю Docker..."
  if detect_ubuntu_like; then
    # apt install flow (best-effort)
    $SUDO apt-get update -y
    $SUDO apt-get install -y ca-certificates curl gnupg lsb-release
    $SUDO install -m0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
    ARCH="$(dpkg --print-architecture || true)"
    CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    if [[ -z "${CODENAME}" ]]; then
      warn "Не удалось определить CODENAME. Попробую fallback установщик."
      run_with_check $SUDO sh -c "curl -fsSL https://get.docker.com | sh"
    else
      echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
      $SUDO apt-get update -y
      $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
  else
    run_with_check $SUDO sh -c "curl -fsSL https://get.docker.com | sh"
  fi

  if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable --now docker || true
  fi

  # add current user to docker group
  local user="${SUDO_USER:-$USER}"
  if ! getent group docker >/dev/null 2>&1; then
    $SUDO groupadd docker || true
  fi
  if ! id -nG "${user}" | grep -qw docker; then
    $SUDO usermod -aG docker "${user}" || true
    warn "Пользователь ${user} добавлен в группу docker. Выполните 'newgrp docker' или перелогиньтесь."
  fi

  ok "Docker установлен (проверьте, возможно нужен relogin пользователя)."
}

decide_docker_prefix() {
  if id -nG "${SUDO_USER:-$USER}" 2>/dev/null | grep -qw docker; then
    DOCKER_PREFIX=""
  else
    DOCKER_PREFIX="$SUDO"
  fi
}

# repository management
ensure_install_dir() {
  if [[ ! -d "${INSTALL_DIR}" ]]; then
    $SUDO mkdir -p "${INSTALL_DIR}"
    $SUDO chown -R "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "${INSTALL_DIR}"
  fi
}

clone_or_update_repo() {
  ensure_install_dir
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "Обновляю репозиторий в ${INSTALL_DIR}..."
    (cd "${INSTALL_DIR}" && git pull --ff-only) || warn "git pull не удался — пропускаю."
  else
    run_with_check git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi
  update_paths
}

prompt_install_dir() {
  update_paths
  echo
  read -r -p "Каталог установки [${INSTALL_DIR}]: " in_dir || true
  if [[ -n "${in_dir}" ]]; then
    INSTALL_DIR="${in_dir%/}"
  fi
  update_paths
  ok "Каталог: ${INSTALL_DIR}"
}

# .env management
prompt_overrides() {
  echo
  echo "Укажите значения для ключевых параметров (пусто — оставить как в .env.example):"
  read -r -p "BOT_TOKEN: " OV_BOT_TOKEN || true
  read -r -p "BOT_DEV_ID: " OV_DEV_ID || true
  read -r -p "BOT_GROUP_ID: " OV_GROUP_ID || true
  read -r -p "DEFAULT_LANG (ru/en): " OV_DEFAULT_LANG || true
  read -r -p "REDIS_PASSWORD (Enter — сгенерировать): " OV_REDIS_PASSWORD || true

  if [[ -z "${OV_REDIS_PASSWORD}" ]]; then
    OV_REDIS_PASSWORD="$(generate_password)"
    log "Сгенерирован REDIS_PASSWORD"
  fi
}

safe_replace() {
  local key="$1"; local val="$2"; local file="$3"
  local esc
  esc="$(printf '%s' "$val" | sed -e 's/[\/&]/\\&/g')"
  if grep -qE "^${key}=" "$file"; then
    sed -i -E "s|^${key}=.*$|${key}=${esc}|" "$file"
  else
    printf "%s=%s\n" "$key" "$val" >> "$file"
  fi
}

write_env_from_example() {
  if [[ ! -f "${EXAMPLE_FILE}" ]]; then
    err ".env.example не найден в ${INSTALL_DIR}"
    return 1
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    cp "${ENV_FILE}" "${ENV_FILE}.bak_$(date +%Y%m%d%H%M%S)" || true
  fi
  cp "${EXAMPLE_FILE}" "${ENV_FILE}"
  [[ -n "${OV_BOT_TOKEN:-}" ]] && safe_replace "BOT_TOKEN" "${OV_BOT_TOKEN}" "${ENV_FILE}"
  [[ -n "${OV_DEV_ID:-}" ]]    && safe_replace "BOT_DEV_ID" "${OV_DEV_ID}" "${ENV_FILE}"
  [[ -n "${OV_GROUP_ID:-}" ]]  && safe_replace "BOT_GROUP_ID" "${OV_GROUP_ID}" "${ENV_FILE}"
  [[ -n "${OV_DEFAULT_LANG:-}" ]] && safe_replace "DEFAULT_LANG" "${OV_DEFAULT_LANG}" "${ENV_FILE}"
  [[ -n "${OV_REDIS_PASSWORD:-}" ]] && safe_replace "REDIS_PASSWORD" "${OV_REDIS_PASSWORD}" "${ENV_FILE}"
  ok ".env создан/обновлён: ${ENV_FILE}"
}

# docker compose wrappers
compose_up() {
  update_paths
  if [[ ! -f "${COMPOSE_DIR}/docker-compose.yml" && ! -f "${COMPOSE_DIR}/compose.yml" ]]; then
    err "docker-compose.yml не найден в ${COMPOSE_DIR}"
    return 1
  fi
  decide_docker_prefix
  (cd "${COMPOSE_DIR}" && ${DOCKER_PREFIX} docker compose up -d --build)
  ok "Контейнеры подняты"
}

compose_down() {
  update_paths
  decide_docker_prefix
  (cd "${COMPOSE_DIR}" && ${DOCKER_PREFIX} docker compose down)
  ok "Контейнеры остановлены"
}

compose_restart() {
  update_paths
  decide_docker_prefix
  (cd "${COMPOSE_DIR}" && ${DOCKER_PREFIX} docker compose restart)
  ok "Контейнеры перезапущены"
}

compose_logs() {
  update_paths
  decide_docker_prefix
  (cd "${COMPOSE_DIR}" && ${DOCKER_PREFIX} docker compose logs -f)
}

compose_ps() {
  update_paths
  decide_docker_prefix
  (cd "${COMPOSE_DIR}" && ${DOCKER_PREFIX} docker compose ps)
}

status_summary() {
  echo "==== STATUS ===="
  if docker_is_installed; then
    docker --version || true
  else
    echo "Docker: not installed"
  fi
  echo "Install dir: ${INSTALL_DIR}"
  if [[ -f "${ENV_FILE}" ]]; then
    echo ".env: present ($(wc -l < "${ENV_FILE}") lines)"
  else
    echo ".env: missing"
  fi
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    (cd "${INSTALL_DIR}" && git rev-parse --short HEAD 2>/dev/null) || true
  fi
  compose_ps || true
  echo "================"
}

# self-update
self_update_check() {
  if [[ -z "${UPDATE_URL}" ]]; then
    warn "UPDATE_URL не задан."
    return 1
  fi
  local tmp; tmp="$(mktemp)"
  trap 'rm -f "${tmp}"' RETURN
  run_with_check curl -fsSL "${UPDATE_URL}" -o "${tmp}"
  local cur
  cur="$(command -v "${BIN_NAME}" || true)"
  if [[ -z "${cur}" || ! -f "${cur}" ]]; then
    warn "Установленная копия ${BIN_NAME} не найдена."
    return 2
  fi
  local hcur hnew
  hcur="$(sha256 "${cur}" || true)"
  hnew="$(sha256 "${tmp}" || true)"
  if [[ "${hcur}" == "${hnew}" ]]; then
    ok "Нет доступных обновлений"
    return 0
  fi
  warn "Доступно обновление: ${hcur:0:7} -> ${hnew:0:7}"
  read -r -p "Обновить сейчас? (yes/NO): " yn
  if [[ "${yn}" == "yes" ]]; then
    $SUDO install -m 0755 -D "${tmp}" "${cur}"
    ok "${BIN_NAME} обновлён"
  else
    warn "Отмена обновления"
  fi
}

self_update_now() {
  if [[ -z "${UPDATE_URL}" ]]; then
    warn "UPDATE_URL не задан."
    return 1
  fi
  local tmp; tmp="$(mktemp)"
  trap 'rm -f "${tmp}"' RETURN
  run_with_check curl -fsSL "${UPDATE_URL}" -o "${tmp}"
  local cur; cur="$(command -v "${BIN_NAME}" || "/usr/local/bin/${BIN_NAME}")"
  $SUDO install -m 0755 -D "${tmp}" "${cur}"
  ok "${BIN_NAME} обновлён"
}

uninstall_bot() {
  compose_down || true
  read -r -p "Удалить каталог ${INSTALL_DIR}? (yes/NO): " yn
  if [[ "${yn}" == "yes" ]]; then
    $SUDO rm -rf "${INSTALL_DIR}"
    ok "Каталог удалён"
  else
    warn "Удаление отменено"
  fi
}

print_menu() {
  cat <<EOF
======== ${APP_NAME} installer/manager ========
Текущий каталог: ${INSTALL_DIR}
1) Быстрая установка (Docker + клонирование + .env + up)
2) Установить Docker (если нужно)
3) Клонировать/обновить репозиторий
4) Создать .env из .env.example (с вопросами)
5) docker compose up -d --build
6) Перезапустить контейнеры
7) Остановить контейнеры (down)
8) Просмотр логов
9) Обновить бот (git pull + up)
10) Статус
11) Проверить обновление скрипта (self-check)
12) Самообновление скрипта (install latest)
13) Удалить бота (compose down + rm dir)
0) Выход
=============================================
EOF
}

quick_install() {
  install_docker_if_needed
  clone_or_update_repo
  prompt_overrides
  write_env_from_example
  compose_up
}

menu_loop() {
  while true; do
    print_menu
    read -r -p "Выберите пункт: " choice
    case "${choice}" in
      1) quick_install ;;
      2) install_docker_if_needed ;;
      3) clone_or_update_repo ;;
      4) prompt_overrides; write_env_from_example ;;
      5) install_docker_if_needed; compose_up ;;
      6) compose_restart ;;
      7) compose_down ;;
      8) compose_logs ;;
      9) clone_or_update_repo; compose_up ;;
      10) status_summary ;;
      11) self_update_check ;;
      12) self_update_now ;;
      13) uninstall_bot ;;
      0) exit 0 ;;
      *) warn "Неизвестный выбор" ;;
    esac
    echo
  done
}

main() {
  check_dependencies
  prompt_install_dir
  self_install
  menu_loop
}

main "$@"